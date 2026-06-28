from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import MetricQuery
from recosearch.semantic_layers.pipeline import execute_metric_query

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


def test_metric_query_order_revenue(contract):
    answer = execute_metric_query(
        MetricQuery(term="order revenue", tenant="novashop"),
        contract=contract,
        scoped_question="what is order revenue?",
    )
    assert answer.decision == "answer"
    assert answer.result is not None
    assert len(answer.result) == 1
    assert "metric_value" in answer.result[0]
    assert answer.metric_resolution
    resolution = dict(answer.metric_resolution)
    assert resolution["resolved_metric_id"] == "metric:novashop:order_revenue"
    assert resolution["fallback_used"] is False
    assert resolution["collection_id"] == "novashop_custom"
    assert resolution["definition_hash"] == "0e66426cb4be77f6"
    assert resolution["metric_version"] == "1.0.0"
    kinds = {edge.kind for edge in ledger.lineage_edges()}
    assert "defines_plan" in kinds
    assert "executes_plan" in kinds


def test_metric_query_industry_fallback(contract):
    answer = execute_metric_query(
        MetricQuery(term="revenue", tenant="other_shop", industry="retail"),
        contract=contract,
    )
    assert answer.decision == "answer"
    resolution = dict(answer.metric_resolution)
    assert resolution["resolved_metric_id"] == "metric:retail:generic_revenue"
    assert resolution["fallback_used"] is True
    assert "fallback_metric" in answer.caveats


def test_metric_query_unknown_clarifies(contract):
    answer = execute_metric_query(
        MetricQuery(term="nonexistent metric", tenant="novashop"),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert "unknown metric" in answer.reason


def test_metric_query_guest_denied(contract):
    answer = execute_metric_query(
        MetricQuery(term="order revenue", tenant="novashop"),
        contract=contract,
        actor=identity.resolve(role="guest"),
    )
    assert answer.decision == "refuse"
    assert answer.reason_code == "POLICY_METRIC_ACCESS_DENIED"
    assert not any(e["artifact_type"] == "query" for e in ledger.events())
    kinds = {edge.kind for edge in ledger.lineage_edges()}
    assert "attempted_plan" in kinds
