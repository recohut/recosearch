"""L5 composition-wedge governed learning loop integration."""

from __future__ import annotations

import shutil
from pathlib import Path

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.context.loader import ContextKernelLoader
from recosearch.semantic_layers.contract import SEMANTIC_DIR, compile_contract as compile_semantic_contract
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration
from recosearch.semantic_layers.decisions.apply_proposal import approve_trust_prior_proposal
from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.replay import counterfactual_replay
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


class TestL5WorldSotaGovernedLearning:
    def setup_method(self):
        ledger.clear()

    def test_aggregate_propose_approve_l2_contract_version_bump(self, compile_contract, tmp_path):
        pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
        decision = record_decision(
            pack.pack_id,
            actor="controller",
            decision_payload={"action": "defer_revenue_recognition"},
            expected_outcome={"status": "recognized", "period": "2026-Q2", "amount": 500.0},
            outcome_due_date="2026-07-01",
            contract=compile_contract,
        )
        record_outcome(
            decision.decision_id,
            actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 600.0},
            contract_hash=str(compile_contract.get("contract_hash", "")),
        )
        generate_calibration_signal(decision.decision_id, contract=compile_contract)

        report = aggregate_calibration(contract=compile_contract)
        assert report.n == 1
        assert report.method == "wilson"

        proposal = propose_trust_prior_from_ledger(contract=compile_contract)
        assert proposal is not None
        assert proposal.status == "pending"

        semantic = tmp_path / "semantic"
        shutil.copytree(SEMANTIC_DIR, semantic)
        context_dir = semantic / "context"
        before = compile_semantic_contract(semantic)
        approve_trust_prior_proposal(
            proposal.proposal_id,
            context_dir=context_dir,
            operator="cert-operator",
        )
        after = compile_semantic_contract(semantic)
        assert after["contract_hash"] != before["contract_hash"]

        kernel = ContextKernelLoader.from_contract(after)
        cert = kernel.certifications[proposal.term_id]
        assert cert.ares_confidence_interval == proposal.proposed_ci

    def test_counterfactual_sensitivity_in_loop(self, compile_contract):
        pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
        decision = record_decision(
            pack.pack_id,
            actor="controller",
            decision_payload={"action": "approve_board_pack"},
            expected_outcome={"status": "recognized"},
            outcome_due_date="2026-04-15",
            contract=compile_contract,
        )
        overlay = compile_contract["counterfactuals_config"]["scenarios"]["raise_tier_bar_to_local_live"]["overlay"]
        cf = counterfactual_replay(
            decision.decision_id,
            contract=compile_contract,
            overrides=overlay,
            scenario_label="raise_tier_bar_to_local_live",
        )
        assert cf.changed is True
        assert cf.baseline_decision == "answer"
        assert cf.counterfactual_decision == "review_required"
