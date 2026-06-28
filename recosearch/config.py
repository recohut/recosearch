from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from .errors import SEVERITY_ERROR, SEVERITY_WARNING, BoundaryError, ContractIssue
from .settings import ROOT, SOURCE_CONFIG_PATH

# Schemas for source types that have no adapter module yet.
# Adapter-backed types carry their own config_schema inside their SourceAdapter;
# they are pulled in lazily via _source_type_registry() below to avoid a
# config<->adapters circular import. Add a type here only while its adapter does
# not yet exist — the adapter schema takes precedence via the merge order below.
# (duckdb graduated to a real adapter: recosearch/adapters/duckdb.py.)
_PLACEHOLDER_SCHEMAS: dict[str, dict[str, list[str]]] = {}


def _source_type_registry() -> dict[str, dict]:
    """Return the merged source-type registry: adapter schemas + placeholder schemas.

    The adapter import is done lazily inside this function to avoid a circular
    import (adapters/ imports config.py at module load time; a top-level import
    here would form a cycle).
    """
    from .adapters import all_config_schemas  # noqa: PLC0415 — intentional lazy import
    # Placeholders lose to adapter-declared schemas when both exist for a type.
    return {**_PLACEHOLDER_SCHEMAS, **all_config_schemas()}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


def _is_secret_ref(value: Any) -> bool:
    text = str(value or "")
    return text.startswith("${") and text.endswith("}")


def registered_source_types() -> set[str]:
    return set(_source_type_registry())


def identifiers_for(source_type: str) -> list[str]:
    """Declared location-identifier keys for a source type (e.g. ``database`` /
    ``index`` / ``collection``), read from the merged adapter + placeholder config
    schemas. Data-driven so a new source type surfaces its identifiers without code
    edits elsewhere (mirrors how ``config_schema`` already drives validation)."""
    return list(_source_type_registry().get(source_type, {}).get("identifiers", []))


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    source_type: str
    config_key: str
    config: Mapping[str, Any]


def _load_yaml_detecting_duplicates(text: str) -> tuple[Any, list[str]]:
    """Parse YAML, collecting any duplicate mapping keys instead of silently
    overwriting them (PyYAML's default). ``source_config.yaml`` is the connection
    authority, so a duplicate key is a governance error, not a last-wins merge."""
    duplicates: list[str] = []

    class _Loader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=True)
            if key in mapping:
                duplicates.append(str(key))
            mapping[key] = loader.construct_object(value_node, deep=True)
        return mapping

    _Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
    data = yaml.load(text, Loader=_Loader)  # noqa: S506 - custom SafeLoader subclass
    return data, duplicates


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_env_refs(body: Mapping[str, Any]) -> dict[str, Any]:
    """Replace ``${VAR}`` config values with the environment variable's value, so
    secrets stay out of source_config.yaml. An unset variable is left as the
    literal ref (the connection then fails loudly rather than silently using a
    blank secret)."""
    resolved: dict[str, Any] = {}
    for key, value in body.items():
        if isinstance(value, str):
            match = _ENV_REF_RE.match(value.strip())
            if match:
                resolved[key] = os.environ.get(match.group(1), value)
                continue
        resolved[key] = value
    return resolved


def _resolve_env_path(path: str) -> Path | None:
    """Resolve an ``env:`` file path. Tries (in order): absolute path as given,
    repo-root-relative, source_config-dir-relative, and tolerates a leading
    ``/<repo-name>/`` prefix. Returns the first that exists, else None."""
    if not isinstance(path, str) or not path.strip():
        return None
    p = Path(path).expanduser()
    rel = path.strip().lstrip("/")
    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
    candidates += [ROOT / rel, SOURCE_CONFIG_PATH.parent / rel]
    parts = Path(rel).parts
    if parts and parts[0] == ROOT.name:  # tolerate a leading /<repo-name>/ prefix
        candidates.append(ROOT / Path(*parts[1:]))
    return next((c for c in candidates if c.exists()), None)


def _load_env_file(path: Any) -> dict[str, str]:
    """Parse a KEY=VALUE env file into a dict (original-case keys). Tolerates
    blank lines, ``#`` comments, ``export`` prefixes, and quoted values. Returns
    {} if the path is empty or the file cannot be found/read."""
    resolved = _resolve_env_path(path) if isinstance(path, str) else None
    if resolved is None:
        return {}
    out: dict[str, str] = {}
    try:
        for line in resolved.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:  # pragma: no cover - unreadable file -> treat as empty
        return {}
    return out


def _resolve_source_config(body: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a source's effective config. Per field, precedence is:
    inline value in source_config.yaml  >  value from the linked ``env:`` file
    >  ``${ENV}`` resolution. The ``env:`` meta-key (a path to a KEY=VALUE file)
    is consumed here and dropped. A field given neither inline nor by the env
    file (nor a resolvable ${ENV}) is simply absent — the source is then
    undeclared/unusable per the required-key validation."""
    body = dict(body)
    env_path = body.pop("env", None)
    env_vars = _load_env_file(env_path)  # {} when no env: link or file missing
    env_lower = {k.lower(): v for k, v in env_vars.items()}

    def _interp(value: Any) -> Any:
        if isinstance(value, str):
            match = _ENV_REF_RE.match(value.strip())
            if match:
                var = match.group(1)
                # ${VAR} resolves from the env file first, then the process env.
                return env_vars.get(var) or env_lower.get(var.lower()) or os.environ.get(var, value)
        return value

    # 1. Inline fields win (with ${ENV} interpolation applied).
    resolved: dict[str, Any] = {key: _interp(value) for key, value in body.items()}
    # 2. The env file fills only fields not given (or blank) inline.
    for key_lower, value in env_lower.items():
        if key_lower not in resolved or resolved.get(key_lower) in (None, ""):
            resolved[key_lower] = value
    return resolved


def _source_refs() -> dict[str, SourceRef]:
    config = _read_yaml(SOURCE_CONFIG_PATH)
    sources = config.get("sources")
    if not isinstance(sources, dict):
        raise BoundaryError("source_config.yaml must contain a sources object")

    refs: dict[str, SourceRef] = {}
    for source_type, body in sources.items():
        if not isinstance(body, dict):
            raise BoundaryError(f"source {source_type!r} must be an object")
        # Resolve credentials (inline > env: file > ${ENV}) BEFORE reading id, so a
        # source whose id is supplied via its linked env: file resolves correctly.
        resolved = _resolve_source_config(body)
        source_id = str(resolved.get("id") or "").strip()
        if not source_id:
            raise BoundaryError(f"source {source_type!r} is missing id")
        refs[source_id] = SourceRef(
            source_id=source_id,
            source_type=str(source_type),
            config_key=str(source_type),
            config=resolved,  # inline > env: file > ${ENV}, at load time
        )
    return refs


def validate_source_config(text: str | None = None) -> list[ContractIssue]:
    """Validate source_config.yaml directly (connection authority hardening).

    Non-raising: returns structured issues. ``text`` may be injected for offline
    tests; otherwise the declared file is read.
    """
    if text is None:
        text = SOURCE_CONFIG_PATH.read_text(encoding="utf-8")
    loc = "source_config.yaml"
    issues: list[ContractIssue] = []

    data, duplicates = _load_yaml_detecting_duplicates(text)
    for key in duplicates:
        issues.append(
            ContractIssue("config_duplicate_yaml_key", SEVERITY_ERROR, loc, f"duplicate key {key!r} in source_config.yaml")
        )

    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, dict) or not sources:
        issues.append(ContractIssue("config_no_sources", SEVERITY_ERROR, loc, "source_config.yaml must contain a non-empty sources object"))
        return issues

    seen_ids: set[str] = set()
    for source_type, body in sources.items():
        type_loc = f"{loc}:{source_type}"
        if not isinstance(body, dict):
            issues.append(ContractIssue("config_source_not_object", SEVERITY_ERROR, type_loc, f"source {source_type!r} must be an object"))
            continue

        # Resolve env: / ${ENV} before reading id, so a source whose id is supplied
        # via its linked env file is recognized (consistent with _source_refs).
        effective = _resolve_source_config(body)
        source_id = str(effective.get("id") or "").strip()
        id_loc = f"{loc}:{source_id or source_type}"
        if not source_id:
            issues.append(ContractIssue("config_empty_source_id", SEVERITY_ERROR, type_loc, f"source {source_type!r} is missing a non-empty id"))
        elif source_id in seen_ids:
            issues.append(ContractIssue("config_duplicate_source_id", SEVERITY_ERROR, id_loc, f"source id {source_id!r} is declared more than once"))
        else:
            seen_ids.add(source_id)

        _registry = _source_type_registry()
        spec = _registry.get(str(source_type))
        if spec is None:
            issues.append(
                ContractIssue(
                    "config_unknown_source_type",
                    SEVERITY_ERROR,
                    id_loc,
                    f"source type {source_type!r} is not in the adapter registry {sorted(_registry)}",
                )
            )
            continue

        # A source may supply credentials via a linked ``env:`` file instead of
        # inline; resolve the effective config (inline > env-file > ${ENV}) before
        # the required-key check. A field given by neither is genuinely missing,
        # which makes the source undeclared/unusable.
        if "env" in body and _resolve_env_path(body.get("env")) is None:
            issues.append(ContractIssue("config_env_file_missing", SEVERITY_WARNING, id_loc, f"env file {body.get('env')!r} for {source_type} was not found"))
        effective = _resolve_source_config(body)
        for key in spec["required"]:
            if key not in effective or effective.get(key) in (None, ""):
                issues.append(ContractIssue("config_missing_required_key", SEVERITY_ERROR, id_loc, f"{source_type} source is missing required key {key!r}"))

        if "port" in body and not _is_secret_ref(body.get("port")):
            port = body.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
                issues.append(ContractIssue("config_malformed_port", SEVERITY_ERROR, id_loc, f"port {port!r} must be an integer in 1..65535"))

        if "url" in body and not _is_secret_ref(body.get("url")):
            parsed = urlparse(str(body.get("url")))
            if not parsed.scheme or not parsed.netloc:
                issues.append(ContractIssue("config_malformed_url", SEVERITY_ERROR, id_loc, f"url {body.get('url')!r} must include scheme and host"))

        for ident_key in spec["identifiers"]:
            value = body.get(ident_key)
            if value is not None and not _is_secret_ref(value) and not _IDENTIFIER_RE.match(str(value)):
                issues.append(ContractIssue("config_malformed_identifier", SEVERITY_ERROR, id_loc, f"{ident_key} {value!r} is not a valid identifier"))

        # Migration policy: credentials should be ${ENV_VAR} secret refs; flag plaintext.
        for cred_key in ("password", "token", "secret", "api_key"):
            value = body.get(cred_key)
            if value not in (None, "") and not _is_secret_ref(value):
                issues.append(ContractIssue("config_plaintext_secret", SEVERITY_WARNING, id_loc, f"{cred_key} for {source_type} is plaintext; prefer a ${{ENV_VAR}} secret reference"))

        unexpected = [key for key in body if key not in spec["allowed"] and key != "env"]
        for key in unexpected:
            issues.append(ContractIssue("config_unexpected_credential_shape", SEVERITY_WARNING, id_loc, f"unexpected key {key!r} for {source_type} source"))

    return issues


def _assert_source_allowed(source_id: str, source_refs: Mapping[str, SourceRef] | None = None) -> None:
    refs = source_refs or _source_refs()
    if source_id not in refs:
        raise BoundaryError(f"source {source_id!r} is not declared in source_config.yaml")


def _redact_source_config(ref: SourceRef) -> dict[str, Any]:
    redacted = dict(ref.config)
    for key in ("password", "token", "secret", "api_key"):
        if key in redacted:
            redacted[key] = "***REDACTED***"
    redacted["type"] = ref.source_type
    return redacted


def _source_ref_by_type(source_type: str) -> SourceRef:
    refs = _source_refs()
    matches = [ref for ref in refs.values() if ref.source_type == source_type]
    if not matches:
        raise BoundaryError(f"no {source_type} source is declared in source_config.yaml")
    if len(matches) > 1:
        ids = sorted(ref.source_id for ref in matches)
        raise BoundaryError(f"multiple {source_type} sources are declared; specify one of {ids}")
    return matches[0]


def sources_with_capability(capability: str) -> list[SourceRef]:
    from .adapters import capabilities_for

    return [ref for ref in _source_refs().values() if capability in capabilities_for(ref.source_type)]


def resolve_source_id(capability: str, source_id: str | None = None) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve which source provides a capability. Returns (source_id, None) or
    (None, refusal). Defaults only when exactly one source matches; otherwise
    requires an explicit source_id."""
    candidates = sources_with_capability(capability)
    ids = [ref.source_id for ref in candidates]
    if source_id is not None:
        if source_id in ids:
            return source_id, None
        return None, {"status": "refused", "reason_code": "source_not_found_for_capability",
                      "capability": capability, "requested": source_id, "candidates": ids, "rows": [], "row_count": 0}
    if len(candidates) == 1:
        return candidates[0].source_id, None
    if not candidates:
        return None, {"status": "refused", "reason_code": "no_source_for_capability",
                      "capability": capability, "rows": [], "row_count": 0}
    return None, {"status": "refused", "reason_code": "source_selection_required",
                  "capability": capability, "candidates": ids, "rows": [], "row_count": 0}


def _ref_by_id(source_id: str) -> SourceRef:
    refs = _source_refs()
    if source_id not in refs:
        raise BoundaryError(f"source {source_id!r} is not declared in source_config.yaml")
    return refs[source_id]


def _opensearch_ref() -> SourceRef:
    return _source_ref_by_type("opensearch")


def _postgres_ref() -> SourceRef:
    return _source_ref_by_type("postgres")


def _qdrant_ref() -> SourceRef:
    return _source_ref_by_type("qdrant")
