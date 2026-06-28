"""Field-level access control (basic ACL): role-based masking of sensitive (PII)
columns in tool results — and, because masking runs *inside* tracing, in the
spans too, so PII stops leaking into Phoenix for restricted roles.

Declared in the scenario file's ``access`` block (data, not code):

    access:
      sensitive_fields: [source.table.column, ...]   # the column is what gets masked
      unmasked_roles:   [admin]                       # roles that see clear values
      mask: "***MASKED***"

Masking is OPT-IN, consistent with RBAC: with ``RECOSEARCH_ROLE`` unset there is
no masking. With a role set, sensitive columns are masked unless the role is in
``unmasked_roles``. No ``sensitive_fields`` declared -> no masking at all.

:func:`mask_result` wraps each tool at the dispatch chokepoint, *inside*
``traced_tool``, so the recorded span sees the masked rows.
"""
from __future__ import annotations

import functools
import os
import typing
from typing import Any, Callable

import yaml

from .settings import SCENARIO_PATH

_DEFAULT_MASK = "***MASKED***"
_cache: dict[str, Any] = {}


def _load() -> dict[str, Any]:
    if not _cache:
        try:
            full = yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8")) or {}
            data = full.get("access") or {}  # no `access` block -> no masking
        except FileNotFoundError:
            data = {}
        except Exception:  # pragma: no cover - malformed config -> no masking
            data = {}
        fields = [str(f) for f in (data.get("sensitive_fields") or []) if f]
        _cache["columns"] = {f.split(".")[-1] for f in fields}
        _cache["unmasked_roles"] = {str(r) for r in (data.get("unmasked_roles") or [])}
        _cache["mask"] = str(data.get("mask") or _DEFAULT_MASK)
    return _cache


def sensitive_columns() -> set[str]:
    return set(_load()["columns"])


def _active_role() -> str | None:
    value = (os.environ.get("RECOSEARCH_ROLE") or "").strip()
    return value or None


def masking_active() -> bool:
    """Masking applies only when a role is set, sensitive fields are declared, and
    the role is not in unmasked_roles."""
    cfg = _load()
    role = _active_role()
    if role is None or not cfg["columns"]:
        return False
    return role not in cfg["unmasked_roles"]


def _strip_prefix(key: str) -> str:
    for prefix in ("left_", "right_"):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


def mask_rows(rows: list[Any], columns: set[str], token: str) -> list[Any]:
    """Replace sensitive column values with the mask token, in plain rows,
    federated (left_/right_ prefixed) rows, and citation record_refs."""
    out: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        new = dict(row)
        for key in list(new.keys()):
            if key.startswith("_"):
                continue
            if key in columns or _strip_prefix(key) in columns:
                new[key] = token
        citation = new.get("_citation")
        if isinstance(citation, dict) and isinstance(citation.get("record_ref"), dict):
            citation = dict(citation)
            record_ref = dict(citation["record_ref"])
            for key in list(record_ref):
                if key in columns:
                    record_ref[key] = token
            citation["record_ref"] = record_ref
            new["_citation"] = citation
        out.append(new)
    return out


def mask_result(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a tool so sensitive columns in its result rows are masked for the
    active role. Returns ``func`` unchanged when masking doesn't apply (no-op)."""
    if not masking_active():
        return func
    cfg = _load()
    columns, token, role = set(cfg["columns"]), cfg["mask"], _active_role()
    try:
        resolved_hints = typing.get_type_hints(func)
    except Exception:
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        if isinstance(result, dict) and isinstance(result.get("rows"), list) and result["rows"]:
            result = {
                **result,
                "rows": mask_rows(result["rows"], columns, token),
                "masking": {"applied": True, "masked_columns": sorted(columns), "role": role},
            }
        return result

    wrapper.__annotations__ = resolved_hints
    return wrapper
