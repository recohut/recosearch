"""Backward-compatible entry — prefer recosearch.pipeline."""

from __future__ import annotations

from typing import Any

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.envelope import Answer
from recosearch.semantic_layers.pipeline import execute_structured_query


def run_query(
    connection,
    sql: str,
    *,
    source_id: str,
    contract_hash: str,
    row_limit: int = 100,
) -> Answer:
    """Legacy signature — routes through pipeline when source_key is known."""
    contract = compile_contract()
    for key, cfg in contract.get("sources", {}).items():
        sid = cfg.get("id", key)
        if sid == source_id or key == source_id:
            return execute_structured_query(sql, source_key=key, contract=contract, row_limit=row_limit)
    return execute_structured_query(
        sql,
        source_key=next(iter(contract["sources"])),
        contract=contract,
        row_limit=row_limit,
    )
