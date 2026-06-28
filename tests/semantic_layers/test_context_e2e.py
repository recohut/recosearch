from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


@pytest.fixture(autouse=True)
def _clear_ledger():
    ledger.clear()
    yield
    ledger.clear()


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_missing_context_kernel_clarifies():
    contract = {"contract_hash": "deadbeef"}
    answer = execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert "context kernel not loaded" in answer.reason


def test_no_metric_ref_clarifies_with_card(contract):
    answer = execute_context_query(
        ContextQuery(term="customer", tenant="novashop"),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert answer.context_resolution
    ctx = dict(answer.context_resolution)
    assert ctx["term_id"] == "term:novashop:customer"
    assert "card_id" in ctx


def test_e2e_revenue_context_metric_ledger(contract):
    answer = execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
        reference_date=date(2026, 1, 31),
    )
    assert answer.decision == "answer"
    assert answer.context_resolution
    ctx = dict(answer.context_resolution)
    assert ctx["term_id"] == "term:novashop:revenue"
    assert ctx["trust_status"] in ("trusted", "usable_with_caveats")
    assert ctx["evidence_tier"] >= 1
    assert answer.result
    events = ledger.events()
    context_events = [e for e in events if e["artifact_type"] == "context"]
    assert context_events
    edges = context_events[0]["lineage_edges"]
    assert {"from_id": "term:novashop:revenue", "to_id": "metric:novashop:order_revenue", "kind": "context_ref"} in edges
    assert {"from_id": "term:novashop:revenue", "to_id": "novashop", "kind": "context_ref"} in edges
