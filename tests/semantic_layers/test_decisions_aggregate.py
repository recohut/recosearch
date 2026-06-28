from __future__ import annotations

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration, breach_trust_prior_trigger
from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.stats import match_rate_interval, miss_rate_ci_low, wilson_interval
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim


def test_wilson_interval_known_values():
    rate, lo, hi = wilson_interval(8, 10)
    assert rate == pytest.approx(0.8)
    assert lo < rate < hi
    assert lo >= 0.0
    assert hi <= 1.0


def test_wilson_zero_total():
    rate, lo, hi = wilson_interval(0, 0)
    assert (rate, lo, hi) == (0.0, 0.0, 0.0)


def test_match_rate_interval():
    match_rate, ci_low, ci_high, miss_rate = match_rate_interval(2, 4)
    assert match_rate == pytest.approx(0.5)
    assert miss_rate == pytest.approx(0.5)
    assert ci_low <= match_rate <= ci_high


def test_miss_rate_ci_low_single_miss():
    assert miss_rate_ci_low(0, 1) > 0.15


def test_miss_rate_ci_low_all_match():
    assert miss_rate_ci_low(3, 3) == pytest.approx(0.0)


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


def _record_miss_signal(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "defer_revenue_recognition"},
        expected_outcome={"status": "recognized", "period": "2026-Q2", "amount": 1.0},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
    )
    record_outcome(
        decision.decision_id,
        actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 2.0},
        contract_hash=str(compile_contract.get("contract_hash", "")),
    )
    return generate_calibration_signal(decision.decision_id, contract=compile_contract)


class TestAggregateCalibration:
    def setup_method(self):
        ledger.clear()

    def test_aggregate_empty(self, compile_contract):
        report = aggregate_calibration(contract=compile_contract)
        assert report.n == 0
        assert report.method == "wilson"

    def test_aggregate_after_miss_signal(self, compile_contract):
        signal = _record_miss_signal(compile_contract)
        report = aggregate_calibration(contract=compile_contract)
        assert report.n == 1
        assert signal.signal_id in report.signal_ids
        assert report.miss_rate == pytest.approx(1.0)
        assert report.match_rate == pytest.approx(0.0)
        assert 0.0 <= report.ci_low <= report.ci_high <= 1.0

    def test_breach_on_miss(self, compile_contract):
        _record_miss_signal(compile_contract)
        report = aggregate_calibration(contract=compile_contract)
        assert breach_trust_prior_trigger(report, contract=compile_contract) is True
