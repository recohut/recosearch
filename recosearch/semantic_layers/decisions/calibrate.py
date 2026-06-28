from __future__ import annotations

import fnmatch
from typing import Any

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.loader import load_decisions_config_from_contract
from recosearch.semantic_layers.decisions.outcomes import find_outcome_for_decision
from recosearch.semantic_layers.decisions.record import load_decision_record
from recosearch.semantic_layers.decisions.types import DecisionKernel
from recosearch.semantic_layers.decisions.hash import compute_signal_id
from recosearch.semantic_layers.decisions.types import CalibrationSignal


class CalibrationError(ValueError):
    pass


def _field_value(payload: dict[str, Any], field: str) -> Any:
    if field in payload:
        return payload[field]
    parts = field.split(".")
    current: Any = payload
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _values_match(expected: Any, actual: Any, *, mode: str) -> bool:
    if mode == "numeric_tolerance":
        try:
            return abs(float(expected) - float(actual)) <= 0.01
        except (TypeError, ValueError):
            return False
    return expected == actual


def classify_calibration_delta(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    kernel: DecisionKernel,
) -> str:
    if not kernel.calibration_match_rules:
        return "match" if expected == actual else "miss"

    matched = 0
    total = len(kernel.calibration_match_rules)

    for rule in kernel.calibration_match_rules:
        exp_val = _field_value(expected, rule.field)
        act_val = _field_value(actual, rule.field)
        if _values_match(exp_val, act_val, mode=rule.match_mode):
            matched += 1

    if matched == total:
        return "match"
    if matched > 0:
        return "partial"
    return "miss"


def resolve_advisory_targets(
    decision_payload: dict[str, Any],
    claim_set_snapshot: dict[str, Any],
    *,
    kernel: DecisionKernel,
) -> tuple[str, ...]:
    targets: set[str] = set()
    terms = [str(item.get("term", "")) for item in claim_set_snapshot.get("subclaims", []) or []]
    action = str(decision_payload.get("action", ""))
    for rule in kernel.advisory_target_rules:
        for term in terms:
            if fnmatch.fnmatchcase(term, rule.pattern) or fnmatch.fnmatchcase(action, rule.pattern):
                targets.add(rule.target)
        if fnmatch.fnmatchcase(action, rule.pattern):
            targets.add(rule.target)
    return tuple(sorted(targets))


def generate_calibration_signal(
    decision_id: str,
    *,
    contract: dict[str, Any],
) -> CalibrationSignal:
    decision = load_decision_record(decision_id)
    if decision is None:
        raise CalibrationError(f"missing decision record: {decision_id}")

    outcome = find_outcome_for_decision(decision_id)
    if outcome is None:
        raise CalibrationError(f"missing outcome for decision: {decision_id}")

    kernel = load_decisions_config_from_contract(contract)
    calibration_delta = classify_calibration_delta(
        decision.expected_outcome,
        outcome.actual_outcome,
        kernel=kernel,
    )
    advisory_targets = resolve_advisory_targets(
        decision.decision_payload,
        decision.claim_set_snapshot,
        kernel=kernel,
    )

    signal_id = compute_signal_id(
        decision_id=decision_id,
        outcome_id=outcome.outcome_id,
        calibration_delta=calibration_delta,
    )
    signal = CalibrationSignal(
        signal_id=signal_id,
        decision_id=decision_id,
        outcome_id=outcome.outcome_id,
        expected_outcome=dict(decision.expected_outcome),
        actual_outcome=dict(outcome.actual_outcome),
        calibration_delta=calibration_delta,
        advisory_targets=advisory_targets,
    )

    from recosearch.semantic_layers.ledger import LineageEdge

    contract_hash = str(contract.get("contract_hash", ""))
    ledger.record(
        "calibration_signal",
        source_id=decision_id,
        payload=signal.to_dict(),
        contract_hash=contract_hash,
        lineage_edges=[
            LineageEdge(from_id=signal_id, to_id=decision_id, kind="calibrates"),
            LineageEdge(from_id=signal_id, to_id=outcome.outcome_id, kind="compares"),
        ],
    )
    return signal
