from __future__ import annotations

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.loader import load_counterfactuals_from_contract
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


class TestCounterfactualReplay:
    def setup_method(self):
        ledger.clear()

    def test_counterfactual_flip_tier_bar(self, compile_contract):
        pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
        assert pack.decision == "answer"
        decision = record_decision(
            pack.pack_id,
            actor="controller",
            decision_payload={"action": "approve_board_pack"},
            expected_outcome={"status": "recognized"},
            outcome_due_date="2026-04-15",
            contract=compile_contract,
        )
        scenarios = load_counterfactuals_from_contract(compile_contract)
        scenario = scenarios["raise_tier_bar_to_local_live"]
        result = counterfactual_replay(
            decision.decision_id,
            contract=compile_contract,
            overrides=scenario.overlay,
            scenario_label=scenario.label,
        )
        assert result.baseline_decision == "answer"
        assert result.counterfactual_decision == "review_required"
        assert result.changed is True
        assert result.baseline_contract_hash != result.counterfactual_contract_hash
