from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from recosearch.semantic_layers import capabilities as cap
from recosearch.semantic_layers.adapters import base
from recosearch.semantic_layers.adapters.base import SourceAdapter

_CONFIG = {
    "required": ["path"],
    "identifiers": ["id"],
    "allowed": [
        "path",
        "id",
        "type",
        "mode",
        "operations",
        "source_role",
        "grain",
        "masking",
        "cost_controls",
    ],
}


def connect(config: dict[str, Any]):
    path = Path(config["path"])
    if not path.is_absolute():
        root = Path(__file__).resolve().parents[1]
        path = root / path
    if not path.exists():
        raise FileNotFoundError(f"duckdb file not found: {path}")
    return duckdb.connect(str(path), read_only=True)


def run_structured_query(
    connection,
    sql: str,
    *,
    row_limit: int = 100,
    actor=None,
) -> list[dict[str, Any]]:
    limited = sql.strip()
    if "limit" not in limited.lower():
        limited = f"{limited} LIMIT {row_limit}"
    cur = connection.execute(limited)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def health_check(config: dict[str, Any]) -> bool:
    try:
        con = connect(config)
        con.execute("SELECT 1").fetchone()
        con.close()
        return True
    except Exception:
        return False


ADAPTER = SourceAdapter(
    source_type="duckdb",
    capabilities=frozenset({cap.STRUCTURED_QUERY}),
    connect=connect,
    run_structured_query=run_structured_query,
    health_check=health_check,
    sql_dialect="duckdb",
    source_mode=base.MODE_RUNTIME,
    masking_supported=False,
    citation_kinds=frozenset({"query_hash"}),
    config_schema=_CONFIG,
)
