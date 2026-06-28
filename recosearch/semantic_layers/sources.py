from __future__ import annotations

from pathlib import Path
from typing import Any

from recosearch.semantic_layers import capabilities as cap
from recosearch.semantic_layers.adapters import adapter_for


def normalize_sources(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each source entry gets source_id + type for routing."""
    out: dict[str, dict[str, Any]] = {}
    for key, cfg in (raw or {}).items():
        if not isinstance(cfg, dict):
            continue
        entry = dict(cfg)
        entry.setdefault("source_id", entry.get("id", key))
        if "type" not in entry:
            raise ValueError(f"source {key!r} missing type:")
        adapter = adapter_for(entry["type"])
        if adapter is not None:
            entry.setdefault("mode", adapter.source_mode)
            entry.setdefault("operations", sorted(adapter.capabilities))
            entry.setdefault("masking", {"supported": adapter.masking_supported})
            entry.setdefault("cost_controls", adapter.cost_controls)
            entry.setdefault("citation_kinds", sorted(adapter.citation_kinds))
            entry.setdefault("connector_version", adapter.connector_version)
        out[key] = entry
    return out


def resolve_source(source_key: str, contract: dict[str, Any]) -> tuple[Any, Any, dict[str, Any]]:
    sources = normalize_sources(contract.get("sources", {}))
    if source_key not in sources:
        raise KeyError(f"unknown source: {source_key}")
    cfg = sources[source_key]
    adapter = adapter_for(cfg["type"])
    if adapter is None or not adapter.available:
        raise RuntimeError(f"no adapter for type: {cfg['type']}")
    operations = set(cfg.get("operations", []))
    if cap.STRUCTURED_QUERY not in operations:
        raise RuntimeError(f"source {source_key} does not support structured_query")
    connection = adapter.connect(_with_root(cfg))
    return adapter, connection, cfg


def _with_root(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    path = out.get("path")
    if path and not Path(path).is_absolute():
        root = Path(__file__).resolve().parent
        out["path"] = str(root / path)
    return out
