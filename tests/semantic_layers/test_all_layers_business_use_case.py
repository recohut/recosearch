"""Whole-system Novashop CFO board-close pack across L1–L5 (one business use case)."""

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
from recosearch.semantic_layers.ontology.validate import clear_validation_cache

JANUARY_REFERENCE = "2026-01-31"
CLOSE_GROUP = "january_close_totals"


def _board_close_claim_set() -> ClaimSet:
    return ClaimSet(
        subclaims=(
            Subclaim(
                term="revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date=JANUARY_REFERENCE,
                comparable_group=CLOSE_GROUP,
                time_period="2026-01",
                scoped_question="What was Novashop recognized revenue for January 2026 close?",
            ),
            Subclaim(
                term="deferred revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date=JANUARY_REFERENCE,
                comparable_group=CLOSE_GROUP,
                time_period="2026-01",
                scoped_question="What is Novashop deferred revenue exposure for January 2026 close?",
            ),
        ),
        pack_label="board_pack",
    )


class TestNovashopCfoBoardCloseAllLayers:
    def setup_method(self):
        ledger.clear()
        clear_validation_cache()

    def teardown_method(self):
        ledger.clear()
        clear_validation_cache()

    def test_novashop_cfo_close_pack_l1_through_l5(self, compile_contract, tmp_path):
        # L1–L4: governed board-close pack (review_required for deferred exposure)
        pack, answer = compose_evidence_pack(_board_close_claim_set(), contract=compile_contract)
        assert pack.decision == "review_required"
        assert answer.decision == "review_required"

        # L5: controller decision and outcome mismatch
        decision = record_decision(
            pack.pack_id,
            actor="controller",
            decision_payload={
                "action": "defer_revenue_recognition",
                "note": "Defer Q1 rev rec; release pending Q2 review",
            },
            expected_outcome={
                "status": "recognized",
                "period": "2026-Q2",
                "amount": 125000.0,
            },
            outcome_due_date="2026-07-01",
            contract=compile_contract,
            claim_set_snapshot=_board_close_claim_set().to_dict(),
        )
        record_outcome(
            decision.decision_id,
            actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 999.0},
            contract_hash=compile_contract["contract_hash"],
        )

        signal = generate_calibration_signal(decision.decision_id, contract=compile_contract)
        assert signal.calibration_delta == "miss"
        assert "term:novashop:deferred_revenue" in signal.advisory_targets

        report = aggregate_calibration(contract=compile_contract)
        assert report.n == 1
        assert report.method == "wilson"

        proposal = propose_trust_prior_from_ledger(contract=compile_contract)
        assert proposal is not None
        assert proposal.status == "pending"

        semantic = tmp_path / "semantic"
        shutil.copytree(SEMANTIC_DIR, semantic)
        context_dir = semantic / "context"
        before_hash = compile_semantic_contract(semantic)["contract_hash"]
        approve_trust_prior_proposal(
            proposal.proposal_id,
            context_dir=context_dir,
            operator="cert-operator",
        )
        after = compile_semantic_contract(semantic)
        assert after["contract_hash"] != before_hash

        kernel = ContextKernelLoader.from_contract(after)
        cert = kernel.certifications[proposal.term_id]
        assert cert.ares_confidence_interval == proposal.proposed_ci

        # Counterfactual on the same multi-claim board-close decision: baseline is
        # already review_required; overlay must still recompute contract_hash and
        # keep the pack governed (decision need not flip).
        overlay = after["counterfactuals_config"]["scenarios"]["raise_tier_bar_to_local_live"]["overlay"]
        cf = counterfactual_replay(
            decision.decision_id,
            contract=after,
            overrides=overlay,
            scenario_label="raise_tier_bar_to_local_live",
        )
        assert cf.baseline_decision == "review_required"
        assert cf.counterfactual_decision == "review_required"
        assert cf.baseline_contract_hash != cf.counterfactual_contract_hash
        assert "contract_hash_changed" in cf.deltas
