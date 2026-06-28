from __future__ import annotations

from typing import Any

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.context.loader import ContextKernelLoader
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration, breach_trust_prior_trigger
from recosearch.semantic_layers.decisions.hash import compute_proposal_id
from recosearch.semantic_layers.decisions.loader import load_decisions_config_from_contract
from recosearch.semantic_layers.decisions.types import CalibrationReport, TrustPriorProposal
from recosearch.semantic_layers.ledger import LineageEdge


class ProposalError(ValueError):
    pass


def _resolve_primary_term_id(report: CalibrationReport, *, contract: dict[str, Any]) -> str:
    if report.term_id:
        return report.term_id
    for event in ledger.events():
        if event.get("artifact_type") != "calibration_signal":
            continue
        payload = dict(event.get("payload") or {})
        if str(payload.get("signal_id", "")) not in report.signal_ids:
            continue
        targets = payload.get("advisory_targets") or []
        if targets:
            target = str(targets[0])
            if target.startswith("term:"):
                return target
    context = contract.get("context_kernel") or {}
    certs = context.get("certifications") or []
    if certs:
        return str(certs[0].get("term_id", ""))
    return ""


def _current_ci_for_term(term_id: str, *, contract: dict[str, Any]) -> tuple[float, float]:
    kernel = ContextKernelLoader.from_contract(contract)
    cert = kernel.certifications.get(term_id)
    if cert is not None and cert.ares_confidence_interval is not None:
        return cert.ares_confidence_interval
    return (0.0, 1.0)


def propose_trust_prior(
    report: CalibrationReport,
    *,
    contract: dict[str, Any],
) -> TrustPriorProposal | None:
    if not breach_trust_prior_trigger(report, contract=contract):
        return None

    term_id = _resolve_primary_term_id(report, contract=contract)
    if not term_id:
        return None

    current_ci = _current_ci_for_term(term_id, contract=contract)
    proposed_ci = (report.ci_low, report.ci_high)
    proposed_trust_delta = proposed_ci[0] - current_ci[0]
    rationale = (
        f"miss-rate CI lower bound {report.miss_ci_low:.4f} exceeds configured threshold "
        f"over n={report.n} calibration outcomes; propose outcome-grounded PPI interval "
        f"{list(proposed_ci)} for {term_id}"
    )
    proposal_id = compute_proposal_id(
        term_id=term_id,
        trigger_report_id=report.report_id,
        proposed_ci=proposed_ci,
    )
    proposal = TrustPriorProposal(
        proposal_id=proposal_id,
        term_id=term_id,
        trigger_report_id=report.report_id,
        current_ci=current_ci,
        proposed_ci=proposed_ci,
        proposed_trust_delta=proposed_trust_delta,
        rationale=rationale,
        status="pending",
    )

    contract_hash = str(contract.get("contract_hash", ""))
    ledger.record(
        "trust_prior_proposal",
        source_id=proposal_id,
        payload=proposal.to_dict(),
        contract_hash=contract_hash,
        lineage_edges=[
            LineageEdge(from_id=proposal_id, to_id=report.report_id, kind="triggered_by"),
        ],
    )
    return proposal


def propose_trust_prior_from_ledger(
    *,
    contract: dict[str, Any],
    decision_class: str | None = None,
    term: str | None = None,
) -> TrustPriorProposal | None:
    report = aggregate_calibration(contract=contract, decision_class=decision_class, term=term)
    return propose_trust_prior(report, contract=contract)


def load_trust_prior_proposal(proposal_id: str) -> TrustPriorProposal | None:
    latest: TrustPriorProposal | None = None
    latest_at = -1.0
    for event in ledger.events():
        if event.get("artifact_type") != "trust_prior_proposal":
            continue
        payload = dict(event.get("payload") or {})
        if str(payload.get("proposal_id", "")) != proposal_id:
            continue
        recorded_at = float(event.get("recorded_at", 0.0))
        if recorded_at >= latest_at:
            latest_at = recorded_at
            latest = _proposal_from_payload(payload)
    return latest


def _proposal_from_payload(payload: dict[str, Any]) -> TrustPriorProposal:
    current = payload.get("current_ci") or [0.0, 1.0]
    proposed = payload.get("proposed_ci") or [0.0, 1.0]
    return TrustPriorProposal(
        proposal_id=str(payload["proposal_id"]),
        term_id=str(payload["term_id"]),
        trigger_report_id=str(payload["trigger_report_id"]),
        current_ci=(float(current[0]), float(current[1])),
        proposed_ci=(float(proposed[0]), float(proposed[1])),
        proposed_trust_delta=float(payload.get("proposed_trust_delta", 0.0)),
        rationale=str(payload.get("rationale", "")),
        status=str(payload.get("status", "pending")),
    )
