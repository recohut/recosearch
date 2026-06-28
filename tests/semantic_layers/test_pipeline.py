from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.compiler import QuerySpec
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.pipeline import execute_query_spec, execute_structured_query

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


def test_pipeline_answer_and_ledger(contract):
    answer = execute_query_spec(
        QuerySpec(
            source_key="novashop",
            table="orders",
            columns=["order_id"],
            filters={"status": "delivered"},
            scoped_question="delivered orders",
        ),
        contract=contract,
    )
    assert answer.decision == "answer"
    assert len(answer.result) == 2
    assert answer.citations[0]["kind"] == "query_hash"
    assert answer.evidence_tier == "fixture-backed"
    assert answer.answer_id.startswith("ans-")
    assert answer.plan_ref.startswith("plan-")
    assert answer.replay_refs
    assert answer.source_role_matrix[0]["role"] == "analyst"
    assert answer.scoped_question == "delivered orders"
    assert answer.reason_code == "POLICY_DEFAULT_ALLOW"
    assert answer.policy_trace[0]["rule_id"] == "default"
    artifact_ids = [e["artifact_id"] for e in ledger.events()]
    assert all(aid.startswith("art-") for aid in artifact_ids)
    assert len({aid for aid in artifact_ids}) == len(artifact_ids)
    policy_decisions = [
        e["payload"]["policy_decision"]
        for e in ledger.events()
        if e["artifact_type"] == "decision" and "policy_decision" in e["payload"]
    ]
    assert policy_decisions[0]["decision"] == "answer"
    assert policy_decisions[0]["reason_code"] == "POLICY_DEFAULT_ALLOW"
    assert policy_decisions[0]["policy_trace"][0]["matched"] is True
    lineage_kinds = {edge.kind for edge in ledger.lineage_edges()}
    assert {"selects_source", "decides_plan", "executes_plan", "reads_source"} <= lineage_kinds


def test_pipeline_policy_denies_role_source_operation(contract):
    answer = execute_query_spec(
        QuerySpec(
            source_key="novashop",
            table="orders",
            columns=["order_id"],
            filters={"status": "delivered"},
            scoped_question="delivered orders",
        ),
        contract=contract,
        actor=identity.resolve(role="guest"),
    )
    assert answer.decision == "refuse"
    assert answer.result is None
    assert answer.reason_code == "POLICY_ROLE_SOURCE_OPERATION_DENIED"
    assert answer.policy_trace[0]["rule_id"] == "deny_guest_structured_query_novashop"
    assert not any(e["artifact_type"] == "query" for e in ledger.events())

    policy_decisions = [
        e["payload"]["policy_decision"]
        for e in ledger.events()
        if e["artifact_type"] == "decision" and "policy_decision" in e["payload"]
    ]
    assert policy_decisions[0]["decision"] == "refuse"
    assert policy_decisions[0]["reason_code"] == "POLICY_ROLE_SOURCE_OPERATION_DENIED"
    assert policy_decisions[0]["policy_trace"][0]["matched"] is True
    lineage_kinds = {edge.kind for edge in ledger.lineage_edges()}
    assert "decides_plan" in lineage_kinds
    assert "executes_plan" not in lineage_kinds


def test_pipeline_refuse_records_ledger(contract):
    answer = execute_structured_query(
        "DELETE FROM orders",
        source_key="novashop",
        contract=contract,
    )
    assert answer.decision == "refuse"
    assert any(e["artifact_type"] == "refusal" for e in ledger.events())


def test_pipeline_unknown_source_refused(contract):
    answer = execute_structured_query(
        "SELECT 1",
        source_key="nonexistent",
        contract=contract,
    )
    assert answer.decision == "refuse"
    assert "unknown source" in answer.reason


def test_pipeline_bad_spec_refused(contract):
    answer = execute_query_spec(
        QuerySpec(source_key="novashop", table="orders; DROP TABLE orders", columns=["order_id"]),
        contract=contract,
    )
    assert answer.decision == "refuse"
    assert "invalid table" in answer.reason
