from __future__ import annotations

import pytest

from recosearch.semantic_layers.context.loader import ContextKernelLoader
from recosearch.semantic_layers.decisions.calibrate import (
    CalibrationError,
    classify_calibration_delta,
    generate_calibration_signal,
    resolve_advisory_targets,
)
from recosearch.semantic_layers.decisions.loader import load_decisions_config_from_contract
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.types import CalibrationSignal, DecisionKernel
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim


def _claim_set() -> ClaimSet:
    return ClaimSet(
        subclaims=(
            Subclaim(
                term="deferred revenue",
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
        decision_payload={"action": "defer_revenue_recognition"},
        expected_outcome={"status": "recognized", "period": "2026-Q2", "amount": 500.0},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )


def test_classify_calibration_match(compile_contract):
    kernel = load_decisions_config_from_contract(compile_contract)
    delta = classify_calibration_delta(
        {"status": "recognized", "period": "2026-Q2", "amount": 500.0},
        {"status": "recognized", "period": "2026-Q2", "amount": 500.0},
        kernel=kernel,
    )
    assert delta == "match"


def test_classify_calibration_miss(compile_contract):
    kernel = load_decisions_config_from_contract(compile_contract)
    delta = classify_calibration_delta(
        {"status": "recognized", "period": "2026-Q2", "amount": 500.0},
        {"status": "deferred", "period": "2026-Q3", "amount": 600.0},
        kernel=kernel,
    )
    assert delta == "miss"


def test_classify_calibration_partial(compile_contract):
    kernel = load_decisions_config_from_contract(compile_contract)
    delta = classify_calibration_delta(
        {"status": "recognized", "period": "2026-Q2", "amount": 500.0},
        {"status": "deferred", "period": "2026-Q2", "amount": 500.01},
        kernel=kernel,
    )
    assert delta == "partial"


def test_classify_without_rules():
    kernel = DecisionKernel(calibration_match_rules=(), advisory_target_rules=())
    assert classify_calibration_delta({"a": 1}, {"a": 1}, kernel=kernel) == "match"
    assert classify_calibration_delta({"a": 1}, {"a": 2}, kernel=kernel) == "miss"


def test_resolve_advisory_targets(compile_contract):
    kernel = load_decisions_config_from_contract(compile_contract)
    targets = resolve_advisory_targets(
        {"action": "defer_revenue_recognition"},
        _claim_set().to_dict(),
        kernel=kernel,
    )
    assert "term:novashop:deferred_revenue" in targets


def test_generate_calibration_signal_advisory_only(compile_contract):
    decision = _decision(compile_contract)
    context_before = ContextKernelLoader.from_contract(compile_contract)
    record_outcome(
        decision.decision_id,
        actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 600.0},
        contract_hash=compile_contract["contract_hash"],
    )
    signal = generate_calibration_signal(decision.decision_id, contract=compile_contract)
    assert signal.calibration_delta == "miss"
    assert signal.advisory_targets
    context_after = ContextKernelLoader.from_contract(compile_contract)
    assert context_before.terms == context_after.terms


def test_generate_calibration_missing_outcome(compile_contract):
    decision = _decision(compile_contract)
    with pytest.raises(CalibrationError, match="missing outcome"):
        generate_calibration_signal(decision.decision_id, contract=compile_contract)


def test_calibration_signal_to_dict():
    signal = CalibrationSignal(
        signal_id="signal-abc",
        decision_id="decision-abc",
        outcome_id="outcome-abc",
        expected_outcome={"status": "recognized"},
        actual_outcome={"status": "deferred"},
        calibration_delta="miss",
        advisory_targets=("term:novashop:deferred_revenue",),
    )
    assert signal.to_dict()["calibration_delta"] == "miss"
