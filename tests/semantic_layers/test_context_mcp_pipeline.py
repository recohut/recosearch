from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.mcp_tools import handle_describe_context, handle_list_terms, handle_resolve_context
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
    from recosearch.semantic_layers.contract import compile_contract

    return compile_contract()


def test_handle_describe_context_revenue(contract):
    payload = handle_describe_context("revenue", tenant="novashop", contract=contract)
    assert payload["decision"] == "resolved"
    assert payload["card"]["term_id"] == "term:novashop:revenue"
    assert payload["card"]["trust"]["evidence_tier"] >= 1


def test_handle_resolve_context_guest_trust(contract):
    payload = handle_resolve_context(
        {"term": "revenue", "tenant": "novashop"},
        contract=contract,
        actor=identity.resolve(role="guest"),
    )
    assert payload["card"]["trust"]["status"] == "not_usable"


def test_handle_resolve_context_unknown(contract):
    payload = handle_resolve_context(
        {"term": "nonexistent term", "tenant": "novashop"},
        contract=contract,
    )
    assert payload["decision"] == "unknown"


def test_handle_list_terms(contract):
    payload = handle_list_terms(tenant="novashop", contract=contract)
    term_ids = {item["term_id"] for item in payload["terms"]}
    assert "term:novashop:revenue" in term_ids


def test_execute_context_query_revenue(contract):
    answer = execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
        reference_date=__import__("datetime").date(2026, 1, 31),
    )
    assert answer.decision == "answer"
    assert answer.context_resolution
    assert dict(answer.context_resolution)["term_id"] == "term:novashop:revenue"


def test_execute_context_query_guest_refuse(contract):
    answer = execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
        actor=identity.resolve(role="guest"),
    )
    assert answer.decision == "refuse"
    assert answer.reason_code == "POLICY"


def test_execute_context_query_customer_clarify(contract):
    answer = execute_context_query(
        ContextQuery(term="customer", tenant="novashop"),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert answer.context_resolution
