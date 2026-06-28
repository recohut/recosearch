from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.ontology.eval import (
    DEFAULT_LATENCY_BUDGET_MS,
    assert_latency_budget,
    golden_constraint_suite,
    pass_k,
)
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_pass_k_constraint_suite(contract):
    score = pass_k(golden_constraint_suite(), contract, k=2)
    assert score == 1.0


def test_latency_budget_default_gate(contract):
    runner = lambda: execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
        reference_date=date(2026, 1, 31),
    )
    for _ in range(3):
        duration_ms = assert_latency_budget(
            runner,
            budget_ms=DEFAULT_LATENCY_BUDGET_MS,
        )
        assert duration_ms <= DEFAULT_LATENCY_BUDGET_MS
