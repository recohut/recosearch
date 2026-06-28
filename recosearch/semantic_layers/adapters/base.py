"""One contract for every connector (Snowflake RBAC-at-source, Cube Meta API, Lyft per-source health)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

MODE_RUNTIME = "runtime"
MODE_ORIGIN_ONLY = "origin_only"
MODE_PLANNED = "planned"


@dataclass(frozen=True)
class SourceAdapter:
    source_type: str
    capabilities: frozenset[str]
    connect: Callable[[dict[str, Any]], Any]
    run_structured_query: Callable[..., list[dict[str, Any]]]
    health_check: Callable[[dict[str, Any]], bool]
    sql_dialect: str | None = None
    available: bool = True
    source_mode: str = MODE_RUNTIME
    masking_supported: bool = False
    cost_controls: dict[str, Any] = field(default_factory=lambda: {"max_rows": 100, "timeout_s": 30})
    citation_kinds: frozenset[str] = field(default_factory=lambda: frozenset({"query_hash"}))
    connector_version: str = "0.1.0"
    config_schema: dict[str, Any] | None = None
