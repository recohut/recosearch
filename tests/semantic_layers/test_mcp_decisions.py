from __future__ import annotations

from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers.mcp_tools import (
    handle_aggregate_calibration,
    handle_approve_trust_prior_proposal,
    handle_counterfactual_replay,
    handle_generate_calibration_signal,
    handle_propose_trust_prior,
    handle_record_decision,
    handle_record_outcome,
    handle_reject_trust_prior_proposal,
    handle_replay_decision,
)


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


def test_mcp_record_replay_outcome_calibrate(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    recorded = handle_record_decision(
        {
            "pack_id": pack.pack_id,
            "actor": "controller",
            "decision_payload": {"action": "defer_revenue_recognition"},
            "expected_outcome": {"status": "recognized", "period": "2026-Q2", "amount": 1.0},
            "outcome_due_date": "2026-07-01",
        },
        contract=compile_contract,
    )
    decision_id = recorded["decision"]["decision_id"]
    replay = handle_replay_decision({"decision_id": decision_id}, contract=compile_contract)
    assert replay["replay"]["drift"] is False
    handle_record_outcome(
        {
            "decision_id": decision_id,
            "actual_outcome": {"status": "recognized", "period": "2026-Q2", "amount": 1.0},
        },
        contract=compile_contract,
    )
    signal = handle_generate_calibration_signal({"decision_id": decision_id}, contract=compile_contract)
    assert signal["calibration_signal"]["calibration_delta"] == "match"


def test_mcp_world_sota_handlers(compile_contract, tmp_path):
    from recosearch.semantic_layers import ledger
    from recosearch.semantic_layers.decisions.outcomes import record_outcome

    ledger.clear()
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    recorded = handle_record_decision(
        {
            "pack_id": pack.pack_id,
            "actor": "controller",
            "decision_payload": {"action": "defer_revenue_recognition"},
            "expected_outcome": {"status": "recognized", "period": "2026-Q2", "amount": 1.0},
            "outcome_due_date": "2026-07-01",
        },
        contract=compile_contract,
    )
    decision_id = recorded["decision"]["decision_id"]
    record_outcome(
        decision_id,
        actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 2.0},
        contract_hash=str(compile_contract.get("contract_hash", "")),
    )
    handle_generate_calibration_signal({"decision_id": decision_id}, contract=compile_contract)
    report = handle_aggregate_calibration({}, contract=compile_contract)
    assert report["calibration_report"]["n"] == 1
    cf = handle_counterfactual_replay(
        {"decision_id": decision_id, "scenario": "raise_tier_bar_to_local_live"},
        contract=compile_contract,
    )
    assert cf["counterfactual_result"]["changed"] is True
    proposal = handle_propose_trust_prior({}, contract=compile_contract)
    assert proposal["trust_prior_proposal"] is not None
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    approved = handle_approve_trust_prior_proposal(
        {"proposal_id": proposal["trust_prior_proposal"]["proposal_id"], "context_dir": str(context_dir)},
        contract=compile_contract,
    )
    assert approved["trust_overrides_path"]

    ledger.clear()
    pack2, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    recorded2 = handle_record_decision(
        {
            "pack_id": pack2.pack_id,
            "actor": "controller",
            "decision_payload": {"action": "defer_revenue_recognition"},
            "expected_outcome": {"status": "recognized", "period": "2026-Q2", "amount": 1.0},
            "outcome_due_date": "2026-07-01",
        },
        contract=compile_contract,
    )
    decision_id2 = recorded2["decision"]["decision_id"]
    record_outcome(
        decision_id2,
        actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 2.0},
        contract_hash=str(compile_contract.get("contract_hash", "")),
    )
    handle_generate_calibration_signal({"decision_id": decision_id2}, contract=compile_contract)
    proposal2 = handle_propose_trust_prior({}, contract=compile_contract)
    rejected = handle_reject_trust_prior_proposal(
        {"proposal_id": proposal2["trust_prior_proposal"]["proposal_id"]}
    )
    assert rejected["trust_prior_proposal"]["status"] == "rejected"
