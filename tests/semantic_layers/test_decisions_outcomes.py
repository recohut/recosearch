from __future__ import annotations

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.outcomes import (
    OutcomeRecordError,
    find_outcome_for_decision,
    load_outcome_record,
    record_outcome,
)
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.types import OutcomeRecord
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim


def _claim_set() -> ClaimSet:
    return ClaimSet(
        subclaims=(
            Subclaim(
                term="revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date="2026-01-31",
                time_period="2026-01",
            ),
        ),
        pack_label="board_pack",
    )


def _decision(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    return record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "defer"},
        expected_outcome={"status": "recognized", "period": "2026-Q2"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )


def test_record_outcome(compile_contract):
    decision = _decision(compile_contract)
    outcome = record_outcome(
        decision.decision_id,
        actual_outcome={"status": "recognized", "period": "2026-Q2"},
        contract_hash=compile_contract["contract_hash"],
    )
    assert outcome.outcome_id.startswith("outcome-")
    loaded = load_outcome_record(outcome.outcome_id)
    assert loaded is not None
    assert loaded.decision_id == decision.decision_id
    found = find_outcome_for_decision(decision.decision_id)
    assert found is not None
    assert found.outcome_id == outcome.outcome_id
    outcome_events = [e for e in ledger.events() if e["artifact_type"] == "outcome_record"]
    assert outcome_events[0]["lineage_edges"][0]["to_id"] == decision.decision_id


def test_record_outcome_missing_decision(compile_contract):
    with pytest.raises(OutcomeRecordError, match="missing decision record"):
        record_outcome("decision-missing", actual_outcome={"status": "ok"})


def test_load_outcome_record_missing():
    assert load_outcome_record("outcome-missing") is None


def test_outcome_record_to_dict():
    record = OutcomeRecord(
        outcome_id="outcome-abc",
        decision_id="decision-abc",
        actual_outcome={"status": "recognized"},
        recorded_at=1.0,
    )
    assert record.to_dict()["outcome_id"] == "outcome-abc"
