from __future__ import annotations

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.hash import compute_decision_id, compute_outcome_id, compute_signal_id
from recosearch.semantic_layers.decisions.record import (
    DecisionRecordError,
    claim_set_from_snapshot,
    load_decision_record,
    record_decision,
)
from recosearch.semantic_layers.decisions.types import DecisionRecord
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim


def _revenue_claim_set() -> ClaimSet:
    return ClaimSet(
        subclaims=(
            Subclaim(
                term="revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date="2026-01-31",
                comparable_group="january_close_totals",
                time_period="2026-01",
            ),
        ),
        pack_label="board_pack",
    )


def test_compute_decision_id_stable():
    first = compute_decision_id(
        pack_id="pack-abc",
        actor="controller",
        decision_payload={"action": "defer"},
        contract_hash="hash1",
        policy_hash="pol1",
    )
    second = compute_decision_id(
        pack_id="pack-abc",
        actor="controller",
        decision_payload={"action": "defer"},
        contract_hash="hash1",
        policy_hash="pol1",
    )
    assert first == second
    assert first.startswith("decision-")


def test_record_decision_binds_pack(compile_contract):
    pack, _ = compose_evidence_pack(_revenue_claim_set(), contract=compile_contract)
    record = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "defer_revenue_recognition"},
        expected_outcome={"status": "recognized", "period": "2026-Q2"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_revenue_claim_set().to_dict(),
    )
    assert record.decision_id.startswith("decision-")
    assert record.pack_id == pack.pack_id
    assert record.contract_hash == compile_contract["contract_hash"]
    assert record.original_pack_decision == "answer"
    loaded = load_decision_record(record.decision_id)
    assert loaded is not None
    assert loaded.decision_id == record.decision_id
    decision_events = [e for e in ledger.events() if e["artifact_type"] == "decision_record"]
    assert decision_events
    assert decision_events[0]["lineage_edges"][0]["to_id"] == pack.pack_id


def test_record_decision_missing_pack(compile_contract):
    with pytest.raises(DecisionRecordError, match="missing evidence pack"):
        record_decision(
            "pack-missing",
            actor="controller",
            decision_payload={"action": "defer"},
            expected_outcome={"status": "recognized"},
            outcome_due_date="2026-07-01",
            contract=compile_contract,
        )


def test_record_decision_wrong_artifact_type(compile_contract):
    artifact_id = ledger.record("answer", payload={"answer_id": "a1"})
    with pytest.raises(DecisionRecordError, match="not an evidence pack"):
        record_decision(
            artifact_id,
            actor="controller",
            decision_payload={"action": "defer"},
            expected_outcome={"status": "recognized"},
            outcome_due_date="2026-07-01",
            contract=compile_contract,
        )


def test_record_decision_expired_pack(compile_contract):
    pack, _ = compose_evidence_pack(_revenue_claim_set(), contract=compile_contract)
    stale = dict(compile_contract)
    stale["contract_hash"] = "stale000000000001"
    with pytest.raises(DecisionRecordError, match="expired or contract drift"):
        record_decision(
            pack.pack_id,
            actor="controller",
            decision_payload={"action": "defer"},
            expected_outcome={"status": "recognized"},
            outcome_due_date="2026-07-01",
            contract=stale,
        )


def test_claim_set_from_snapshot():
    claim_set = claim_set_from_snapshot(_revenue_claim_set().to_dict())
    assert claim_set.pack_label == "board_pack"
    assert claim_set.subclaims[0].term == "revenue"


def test_decision_record_to_dict():
    record = DecisionRecord(
        decision_id="decision-abc",
        pack_id="pack-abc",
        actor="controller",
        decision_payload={"action": "defer"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract_hash="hash1",
        policy_hash="pol1",
        recorded_at=1.0,
        claim_set_snapshot={"subclaims": []},
    )
    data = record.to_dict()
    assert data["decision_id"] == "decision-abc"
    assert data["decision_payload"]["action"] == "defer"


def test_compute_outcome_and_signal_ids():
    outcome_id = compute_outcome_id(decision_id="decision-1", actual_outcome={"status": "ok"})
    signal_id = compute_signal_id(
        decision_id="decision-1",
        outcome_id=outcome_id,
        calibration_delta="match",
    )
    assert outcome_id.startswith("outcome-")
    assert signal_id.startswith("signal-")
