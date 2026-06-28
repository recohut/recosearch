from __future__ import annotations

from typing import Any

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.hash import compute_report_id
from recosearch.semantic_layers.decisions.loader import load_decisions_config_from_contract
from recosearch.semantic_layers.decisions.stats import match_rate_interval, wilson_interval
from recosearch.semantic_layers.decisions.types import CalibrationReport
from recosearch.semantic_layers.ledger import LineageEdge


class AggregateError(ValueError):
    pass


def _signal_matches_filters(
    payload: dict[str, Any],
    *,
    decision_class: str | None,
    term: str | None,
) -> bool:
    if decision_class and str(payload.get("calibration_delta", "")) != decision_class:
        return False
    if term:
        targets = payload.get("advisory_targets") or []
        if not any(term in str(target) for target in targets):
            return False
    return True


def aggregate_calibration(
    *,
    contract: dict[str, Any],
    decision_class: str | None = None,
    term: str | None = None,
) -> CalibrationReport:
    kernel = load_decisions_config_from_contract(contract)
    method = kernel.confidence_method

    matched_signals: list[dict[str, Any]] = []
    for event in ledger.events():
        if event.get("artifact_type") != "calibration_signal":
            continue
        payload = dict(event.get("payload") or {})
        if not _signal_matches_filters(payload, decision_class=decision_class, term=term):
            continue
        matched_signals.append(payload)

    n = len(matched_signals)
    matches = sum(1 for payload in matched_signals if payload.get("calibration_delta") == "match")
    match_rate, ci_low, ci_high, miss_rate = match_rate_interval(matches, n, method=method)
    _, miss_ci_low, _ = wilson_interval(n - matches, n) if n > 0 else (0.0, 0.0, 0.0)

    report_id = compute_report_id(
        n=n,
        matches=matches,
        decision_class=decision_class or "",
        term_id=term or "",
        method=method,
    )
    report = CalibrationReport(
        report_id=report_id,
        n=n,
        match_rate=match_rate,
        ci_low=ci_low,
        ci_high=ci_high,
        miss_rate=miss_rate,
        miss_ci_low=miss_ci_low,
        method=method,
        decision_class=decision_class or "",
        term_id=term or "",
        signal_ids=tuple(str(p.get("signal_id", "")) for p in matched_signals),
    )

    contract_hash = str(contract.get("contract_hash", ""))
    ledger.record(
        "calibration_report",
        source_id=report_id,
        payload=report.to_dict(),
        contract_hash=contract_hash,
        lineage_edges=[
            LineageEdge(from_id=report_id, to_id=signal_id, kind="aggregates")
            for signal_id in report.signal_ids
            if signal_id
        ],
    )
    return report


def breach_trust_prior_trigger(report: CalibrationReport, *, contract: dict[str, Any]) -> bool:
    kernel = load_decisions_config_from_contract(contract)
    trigger = kernel.trust_prior_trigger
    if trigger is None:
        return False
    if report.n < trigger.min_n:
        return False
    return report.miss_ci_low > trigger.miss_rate_ci_low_threshold
