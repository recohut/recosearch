"""L1–L5 CFO board-close decision loop — governed evidence to decision to outcome."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import recosearch.semantic_layers.policy as policy_module

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.context.events import get_event_bus
from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.replay import replay_decision
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers.ontology.validate import clear_validation_cache

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
JANUARY_REFERENCE = "2026-01-31"
CLOSE_GROUP = "january_close_totals"


def _revenue_subclaim(**overrides) -> Subclaim:
    defaults = dict(
        term="revenue",
        tenant="novashop",
        actor_role="analyst",
        reference_date=JANUARY_REFERENCE,
        comparable_group=CLOSE_GROUP,
        time_period="2026-01",
        scoped_question="What was Novashop recognized revenue for January 2026 close?",
    )
    defaults.update(overrides)
    return Subclaim(**defaults)


def _deferred_exposure_subclaim(**overrides) -> Subclaim:
    defaults = dict(
        term="deferred revenue",
        tenant="novashop",
        actor_role="analyst",
        reference_date=JANUARY_REFERENCE,
        comparable_group=CLOSE_GROUP,
        time_period="2026-01",
        scoped_question="What is Novashop deferred revenue exposure for January 2026 close?",
    )
    defaults.update(overrides)
    return Subclaim(**defaults)


class TestCfoDecisionLoopL5:
    def setup_method(self):
        get_event_bus().clear()
        ledger.clear()
        clear_validation_cache()

    def teardown_method(self):
        get_event_bus().clear()
        ledger.clear()
        clear_validation_cache()

    def test_l5_cfo_close_decision_replay_calibration_loop(self, compile_contract, monkeypatch):
        claim_set = ClaimSet(
            subclaims=(_revenue_subclaim(), _deferred_exposure_subclaim()),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "review_required"
        assert answer.decision == "review_required"

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
            claim_set_snapshot=claim_set.to_dict(),
        )
        assert decision.original_pack_decision == "review_required"
        assert decision.pack_id == pack.pack_id

        outcome = record_outcome(
            decision.decision_id,
            actual_outcome={
                "status": "deferred",
                "period": "2026-Q3",
                "amount": 999.0,
            },
            contract_hash=compile_contract["contract_hash"],
        )
        assert outcome.decision_id == decision.decision_id

        monkeypatch.setattr(policy_module, "compute_policy_hash", lambda: "deadbeef00000000")
        replay = replay_decision(decision.decision_id, contract=compile_contract)
        assert replay.drift is True
        assert "policy_hash_changed" in replay.drift_reasons

        signal = generate_calibration_signal(decision.decision_id, contract=compile_contract)
        assert signal.calibration_delta == "miss"
        assert "term:novashop:deferred_revenue" in signal.advisory_targets

        decision_events = [e for e in ledger.events() if e["artifact_type"] == "decision_record"]
        outcome_events = [e for e in ledger.events() if e["artifact_type"] == "outcome_record"]
        signal_events = [e for e in ledger.events() if e["artifact_type"] == "calibration_signal"]
        assert decision_events and outcome_events and signal_events
