"""Adapter capability registry.

Capabilities are STORAGE capabilities intrinsic to the adapter type — never
business roles. Mapping adapter type -> capability is allowed; inferring business
meaning from adapter type is not.

This package auto-builds ADAPTER_CAPABILITIES from registered ADAPTER objects
so registering an adapter automatically grants its capabilities.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys

from .base import SourceAdapter

# Package internals that are never adapter modules. Any module whose name starts
# with "_" (e.g. "_template", "__init__") is also skipped.
_NON_ADAPTER_MODULES = {"base"}


def _discover_adapters() -> dict[str, SourceAdapter]:
    """Auto-discover adapters: import every module in this package that defines a
    module-level ``ADAPTER`` (a :class:`SourceAdapter`) and key it by source_type.

    Each module is imported defensively — a module that fails to import (e.g. an
    uninstalled optional driver) is skipped with a stderr warning rather than
    breaking the whole package. Discovery is deterministic (modules are visited in
    sorted name order). Dropping a new ``<type>.py`` adapter file into this package
    registers it automatically; no edit here is needed.
    """
    discovered: dict[str, SourceAdapter] = {}
    for module_info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        name = module_info.name
        if name in _NON_ADAPTER_MODULES or name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except Exception as exc:  # pragma: no cover - depends on optional drivers
            print(f"[adapters] skipped {name!r}: import failed ({exc!r})", file=sys.stderr)
            continue
        adapter = getattr(module, "ADAPTER", None)
        if isinstance(adapter, SourceAdapter):
            discovered[adapter.source_type] = adapter
    return discovered


# Auto-registry: keyed by source_type, built by discovery over this package.
ADAPTERS: dict[str, SourceAdapter] = _discover_adapters()

# Derived from registered adapters — no hand-maintenance needed.
# An adapter that is not currently available (available=False) contributes NO
# usable capabilities; this prevents placeholder adapters from colliding with
# real sources in capability-based resolution.
ADAPTER_CAPABILITIES: dict[str, set[str]] = {
    t: set(a.capabilities) for t, a in ADAPTERS.items() if a.available
}
# NOTE: a source type gains a capability only when its adapter is implemented
# AND available=True. A declared type with no adapter (e.g. duckdb) stays
# capability-less here. Because governance keys off capability (not source type),
# implementing an adapter + setting available=True is all that is needed to bring
# a source under SQL guards/metrics/etc.

# Capability -> (clarification id, accepted request keys). Capability-level only.
CAPABILITY_CLARIFICATION: dict[str, tuple[str, tuple[str, ...]]] = {
    "text_search": ("text_search_focus", ("text_query", "query", "search_query", "review_filters", "filters", "allow_broad_text_search")),
    "vector_search": ("vector_query_focus", ("vector_query", "query", "policy_query", "policy_focus", "evidence_queries", "allow_broad_vector_search")),
    "document_query": ("document_query_focus", ("filter", "projection", "query", "allow_broad_document_scan")),
}

# Capability -> generic tools (suggestions derived from capability, not source type).
CAPABILITY_TOOLS: dict[str, list[str]] = {
    "structured_query": ["execute_postgres_semantic_query", "run_guarded_postgres_sql"],
    "text_search": ["search_text"],
    "vector_search": ["search_vector"],
    "document_query": ["query_documents"],
}


def capabilities_for(source_type: str) -> set[str]:
    return ADAPTER_CAPABILITIES.get(source_type, set())


def suggested_tools_for(source_type: str) -> list[str]:
    tools: list[str] = []
    for capability in sorted(capabilities_for(source_type)):
        tools.extend(CAPABILITY_TOOLS.get(capability, []))
    return tools


def adapter_for_type(source_type: str) -> SourceAdapter | None:
    """Return the adapter object for source_type, regardless of availability.

    The adapter object always exists once registered; availability only gates
    whether its capabilities appear in ADAPTER_CAPABILITIES.
    """
    return ADAPTERS.get(source_type)


def config_schema_for(source_type: str) -> dict | None:
    """Return the per-adapter connection-key schema, or None if not declared."""
    adapter = ADAPTERS.get(source_type)
    return adapter.config_schema if adapter is not None else None


def all_config_schemas() -> dict[str, dict]:
    """Return {source_type: config_schema} for every adapter that declares a schema."""
    return {t: a.config_schema for t, a in ADAPTERS.items() if a.config_schema is not None}
