"""SourceAdapter dataclass — the plugin contract for adapter modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class SourceAdapter:
    source_type: str               # 'postgres', 'opensearch', 'qdrant', 'snowflake'
    capabilities: frozenset        # storage capabilities, e.g. frozenset({'structured_query'})
    run_query: Callable            # the capability executor for this adapter
    sql_dialect: str | None = None # sqlglot dialect for structured_query adapters ('postgres'/'snowflake')
    health_check: Callable | None = None
    available: bool = True         # capabilities are advertised ONLY when available=True; set False for
                                   # placeholder adapters (missing driver, no live creds, etc.)
    config_schema: dict | None = None  # per-adapter connection-key schema:
                                       # {'required':[...],'identifiers':[...],'allowed':[...]}
