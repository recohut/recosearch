from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.mcp_tools import handle_describe_metric, handle_list_metrics, handle_metric_query

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
    from recosearch.semantic_layers.contract import compile_contract

    return compile_contract()


def test_handle_metric_query_returns_governed_answer(contract):
    payload = handle_metric_query(
        {"term": "order revenue", "tenant": "novashop", "reference_date": "2026-01-31"},
        contract=contract,
    )
    assert payload["decision"] == "answer"
    assert payload["result"][0]["metric_value"] == 109.97
    assert payload["metric_resolution"]["resolved_metric_id"] == "metric:novashop:order_revenue"


def test_handle_metric_query_guest_denied(contract):
    payload = handle_metric_query(
        {"term": "order revenue", "tenant": "novashop"},
        contract=contract,
        actor=identity.resolve(role="guest"),
    )
    assert payload["decision"] == "refuse"
    assert payload["reason_code"] == "POLICY_METRIC_ACCESS_DENIED"


def test_handle_metric_query_unknown_clarifies(contract):
    payload = handle_metric_query(
        {"term": "nonexistent metric", "tenant": "novashop"},
        contract=contract,
    )
    assert payload["decision"] == "clarify"
    assert "unknown metric" in payload["reason"]


def test_handle_list_metrics(contract):
    payload = handle_list_metrics(contract=contract)
    metric_ids = {item["metric_id"] for item in payload["metrics"]}
    assert "metric:novashop:net_revenue" in metric_ids
    assert "metric:novashop:revenue_per_customer" in metric_ids


def test_handle_describe_metric(contract):
    payload = handle_describe_metric("metric:novashop:net_revenue", contract=contract)
    assert payload["kind"] == "derived"
    assert payload["formula"]
    assert payload["certification"]["definition_hash"]
