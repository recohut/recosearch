"""Tool-level observability for the governed MCP server (Phoenix / OpenTelemetry).

Design constraints (see docs/usage/observability.md):

* Off by default. Activated only when ``RECOSEARCH_TRACING_ENABLED`` is truthy.
  With the flag unset, :func:`traced_tool` returns the original function
  unchanged, so the governed tool surface is byte-for-byte identical to today.
* Fail-open. Missing OTel/Phoenix deps, an unreachable collector, or any setup
  error must never break a tool call — tracing silently no-ops and the tool runs.
* stdout-safe. The MCP server speaks its protocol over stdout; telemetry must
  never write there. OTLP export goes over HTTP, and Phoenix's own setup chatter
  is redirected to stderr during registration.
* Full-payload output. Each span's ``output.value`` carries the complete tool
  response (rows included), so traces may contain PII. Request args still mask
  secret-like keys. This is a deliberate capture choice — dial it back in
  ``_annotate_result`` if a thinner, row-free summary is wanted later.

Only tool-level spans are emitted here (one span per MCP tool call). Sub-spans
into the Postgres/OpenSearch/Qdrant/embedding layers are intentionally out of
scope for this pass.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import json
import os
import sys
import time
import typing
from typing import Any, Callable

from .rbac import active_role
from .session import session_id

# Lazily-populated module state. Nothing OpenTelemetry-related is imported at
# module import time, so importing this module is safe even when the optional
# observability dependencies are absent.
_TRACER: Any = None
_INITIALIZED = False
_OTEL_API: Any = None  # cached (trace, Status, StatusCode)

_TRUTHY = {"1", "true", "yes", "on"}
_SECRET_HINTS = ("password", "token", "secret", "api_key", "apikey", "credential")
_MAX_VALUE_CHARS = 2000
# Output captures the full tool response (rows included), so it needs a much
# larger ceiling than request args. A generous cap remains as a safety net
# against pathologically large payloads breaking span export.
_MAX_OUTPUT_CHARS = 200_000


def _tracing_enabled() -> bool:
    return os.environ.get("RECOSEARCH_TRACING_ENABLED", "").strip().casefold() in _TRUTHY


def _log(message: str) -> None:
    """Diagnostics go to stderr only — stdout carries the MCP protocol."""
    print(f"[observability] {message}", file=sys.stderr)


def init_tracing() -> None:
    """Configure the Phoenix/OTel tracer provider once. Safe to call repeatedly.

    A no-op when tracing is disabled or already initialized. Any failure is
    logged to stderr and swallowed (fail-open): ``_TRACER`` stays ``None`` and
    every traced tool falls back to calling the underlying function directly.
    """
    global _TRACER, _INITIALIZED
    if _INITIALIZED or not _tracing_enabled():
        _INITIALIZED = True
        return
    _INITIALIZED = True
    try:
        from phoenix.otel import register  # type: ignore import-not-found

        base = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or "http://localhost:6006"
        # When endpoint= is passed explicitly, phoenix.otel treats it as the
        # literal OTLP traces URL and does NOT append the path, so spans would
        # POST to the UI root and be dropped. Append /v1/traces ourselves (the
        # HTTP exporter target) unless the caller already included it.
        endpoint = base if base.rstrip("/").endswith("/v1/traces") else base.rstrip("/") + "/v1/traces"
        project = os.environ.get("PHOENIX_PROJECT_NAME", "recosearch-mcp")
        # Phoenix's register() prints setup details to stdout; redirect to stderr
        # so the stdio MCP protocol is never corrupted.
        with contextlib.redirect_stdout(sys.stderr):
            tracer_provider = register(
                project_name=project,
                endpoint=endpoint,
                set_global_tracer_provider=True,
                batch=True,
            )
        _TRACER = tracer_provider.get_tracer("recosearch.tools")
        _log(f"tracing enabled -> {endpoint} (project={project})")
    except Exception as exc:  # pragma: no cover - depends on optional deps/runtime
        _TRACER = None
        _log(f"tracing disabled: setup failed ({exc!r})")


def _get_tracer() -> Any:
    if not _INITIALIZED:
        init_tracing()
    return _TRACER


def _otel_api() -> Any:
    global _OTEL_API
    if _OTEL_API is None:
        from opentelemetry import trace  # type: ignore import-not-found
        from opentelemetry.trace import Status, StatusCode  # type: ignore import-not-found

        _OTEL_API = (trace, Status, StatusCode)
    return _OTEL_API


def _redact_args(func: Callable[..., Any], args: tuple, kwargs: dict) -> dict[str, Any]:
    """Bind call arguments to their parameter names and redact secret-like keys.

    Values are stringified and truncated; secret-like keys are masked. Row
    payloads are never an argument here, so no result data leaks via inputs.
    """
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        raw = dict(bound.arguments)
    except Exception:
        raw = {"args": list(args), "kwargs": dict(kwargs)}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if any(hint in key.casefold() for hint in _SECRET_HINTS):
            out[key] = "***REDACTED***"
            continue
        text = repr(value) if not isinstance(value, (str, int, float, bool, type(None))) else value
        if isinstance(text, str) and len(text) > _MAX_VALUE_CHARS:
            text = text[:_MAX_VALUE_CHARS] + "...<truncated>"
        out[key] = text
    return out


def _safe_json(payload: Any, limit: int = _MAX_VALUE_CHARS) -> str | None:
    try:
        text = json.dumps(payload, default=str, sort_keys=True)
    except Exception:
        return None
    if len(text) > limit:
        text = text[:limit] + "...<truncated>"
    return text


def _annotate_result(span: Any, result: Any, Status: Any, StatusCode: Any) -> None:
    """Record the outcome on the span: flat filterable attributes plus the full
    tool response as ``output.value``. The full payload includes row data, so
    traces may carry PII — this is a deliberate, opted-in capture choice."""
    if not isinstance(result, dict):
        encoded = _safe_json(result, limit=_MAX_OUTPUT_CHARS)
        if encoded is not None:
            span.set_attribute("output.value", encoded)
            span.set_attribute("output.mime_type", "application/json")
        span.set_status(Status(StatusCode.OK))
        return
    provenance = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
    source_ref = provenance.get("source_ref") if isinstance(provenance.get("source_ref"), dict) else {}
    status = result.get("status")
    reason_code = result.get("reason_code")
    # Tools nest source identity differently: top-level source_id, provenance.source,
    # or provenance.source_ref. Check all so the attribute populates everywhere.
    source_id = (
        result.get("source_id")
        or provenance.get("source_id")
        or provenance.get("source")
        or source_ref.get("source_id")
    )
    source_type = provenance.get("source_type") or source_ref.get("source_type")
    source_boundary = result.get("source_boundary") or provenance.get("source") or source_ref.get("boundary")
    row_count = result.get("row_count")

    if status is not None:
        span.set_attribute("tool.status", str(status))
    if reason_code is not None:
        span.set_attribute("tool.reason_code", str(reason_code))
    if source_id is not None:
        span.set_attribute("tool.source_id", str(source_id))
    if source_type is not None:
        span.set_attribute("tool.source_type", str(source_type))
    if source_boundary is not None:
        span.set_attribute("tool.source_boundary", str(source_boundary))
    if isinstance(row_count, int):
        span.set_attribute("tool.row_count", row_count)

    # Full tool response as the span output (rows included).
    encoded = _safe_json(result, limit=_MAX_OUTPUT_CHARS)
    if encoded is not None:
        span.set_attribute("output.value", encoded)
        span.set_attribute("output.mime_type", "application/json")

    # A governed refusal is a normal outcome, not a span error.
    span.set_status(Status(StatusCode.OK))


def traced_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an MCP tool so each call emits one span (request, result, timing).

    Returns ``func`` unchanged when tracing is disabled. When enabled, the
    wrapper preserves the original signature *and* its resolved type hints so
    FastMCP's schema builder (which calls ``get_type_hints``) still works under
    ``from __future__ import annotations``.
    """
    if not _tracing_enabled():
        return func

    try:
        resolved_hints = typing.get_type_hints(func)
    except Exception:
        # Can't safely preserve the schema — skip tracing this tool rather than
        # risk breaking its registration.
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tracer = _get_tracer()
        if tracer is None:
            return func(*args, **kwargs)
        _, Status, StatusCode = _otel_api()
        start = time.perf_counter()
        with tracer.start_as_current_span(func.__name__) as span:
            try:
                span.set_attribute("openinference.span.kind", "TOOL")
                span.set_attribute("tool.name", func.__name__)
                # Audit identity: who asked (role) and which session (trace id).
                span.set_attribute("tool.role", active_role() or "unenforced")
                span.set_attribute("session.id", session_id())
                encoded = _safe_json(_redact_args(func, args, kwargs))
                if encoded is not None:
                    span.set_attribute("input.value", encoded)
                    span.set_attribute("input.mime_type", "application/json")
            except Exception:
                pass
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    span.set_attribute("tool.status", "error")
                    span.set_attribute("tool.duration_ms", (time.perf_counter() - start) * 1000.0)
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
            with contextlib.suppress(Exception):
                span.set_attribute("tool.duration_ms", (time.perf_counter() - start) * 1000.0)
                _annotate_result(span, result, Status, StatusCode)
            return result

    wrapper.__annotations__ = resolved_hints
    return wrapper


def stamp_trace_id(func: Callable[..., Any]) -> Callable[..., Any]:
    """Add a top-level ``trace_id`` (the process session id) to every dict tool
    response, so a final answer can cite it and an auditor can correlate it with
    the spans that share the same ``session.id``.

    Always on (independent of tracing): the trace id is an audit identifier that
    is useful in logs and the answer envelope even when Phoenix is not running.
    Placed on the response envelope, never inside the hashed ``provenance``, so
    deterministic evidence ids are preserved.
    """
    try:
        resolved_hints = typing.get_type_hints(func)
    except Exception:
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        if isinstance(result, dict) and "trace_id" not in result:
            result["trace_id"] = session_id()
        return result

    wrapper.__annotations__ = resolved_hints
    return wrapper
