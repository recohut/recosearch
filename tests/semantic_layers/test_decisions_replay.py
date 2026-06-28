from __future__ import annotations

import recosearch.semantic_layers.policy as policy_module

from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.replay import persist_replay_result, replay_decision
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
                comparable_group="january_close_totals",
                time_period="2026-01",
            ),
        ),
        pack_label="board_pack",
    )


def test_replay_no_drift(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )
    replay = replay_decision(decision.decision_id, contract=compile_contract)
    assert replay.drift is False
    assert replay.original_decision == "answer"
    assert replay.replayed_decision == "answer"
    assert replay.drift_reasons == ()


def test_replay_contract_drift(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )
    replay = replay_decision(
        decision.decision_id,
        contract=compile_contract,
        target_contract_hash="stale000000000001",
    )
    assert replay.drift is True
    assert "contract_hash_changed" in replay.drift_reasons


def test_replay_policy_drift(compile_contract, monkeypatch):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )
    monkeypatch.setattr(policy_module, "compute_policy_hash", lambda: "deadbeef00000000")
    replay = replay_decision(decision.decision_id, contract=compile_contract)
    assert replay.drift is True
    assert "policy_hash_changed" in replay.drift_reasons


def test_persist_replay_result(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )
    replay = replay_decision(decision.decision_id, contract=compile_contract)
    artifact_id = persist_replay_result(replay, contract_hash=compile_contract["contract_hash"])
    assert artifact_id.startswith("art-")
