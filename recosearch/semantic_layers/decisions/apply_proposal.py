from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.propose import ProposalError, load_trust_prior_proposal
from recosearch.semantic_layers.decisions.types import TrustPriorProposal

TRUST_OVERRIDES_FILENAME = "_trust_overrides.yaml"


def _trust_overrides_path(context_dir: Path | str) -> Path:
    return Path(context_dir) / TRUST_OVERRIDES_FILENAME


def load_trust_overrides(context_dir: Path | str) -> dict[str, Any]:
    path = _trust_overrides_path(context_dir)
    if not path.exists():
        return {"version": 1, "overrides": []}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    return raw


def trust_overrides_to_dict(raw: dict[str, Any]) -> dict[str, Any]:
    overrides = raw.get("overrides") or []
    cleaned = []
    for item in overrides:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "term_id": str(item["term_id"]),
                "ares_confidence_interval": list(item["ares_confidence_interval"]),
                "source_proposal_id": str(item.get("source_proposal_id", "")),
                "operator": str(item.get("operator", "")),
                "applied_at": str(item.get("applied_at", "")),
            }
        )
    return {"version": int(raw.get("version", 1)), "overrides": cleaned}


def approve_trust_prior_proposal(
    proposal_id: str,
    *,
    context_dir: Path | str,
    operator: str,
) -> Path:
    proposal = load_trust_prior_proposal(proposal_id)
    if proposal is None:
        raise ProposalError(f"missing trust prior proposal: {proposal_id}")
    if proposal.status != "pending":
        raise ProposalError(f"proposal {proposal_id} is not pending (status={proposal.status})")

    path = _trust_overrides_path(context_dir)
    raw = load_trust_overrides(context_dir)
    overrides = [dict(item) for item in raw.get("overrides") or [] if isinstance(item, dict)]
    applied_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry = {
        "term_id": proposal.term_id,
        "ares_confidence_interval": list(proposal.proposed_ci),
        "source_proposal_id": proposal.proposal_id,
        "operator": operator,
        "applied_at": applied_at,
    }
    replaced = False
    for index, item in enumerate(overrides):
        if str(item.get("term_id", "")) == proposal.term_id:
            overrides[index] = entry
            replaced = True
            break
    if not replaced:
        overrides.append(entry)

    payload = {"version": 1, "overrides": overrides}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    updated = TrustPriorProposal(
        proposal_id=proposal.proposal_id,
        term_id=proposal.term_id,
        trigger_report_id=proposal.trigger_report_id,
        current_ci=proposal.current_ci,
        proposed_ci=proposal.proposed_ci,
        proposed_trust_delta=proposal.proposed_trust_delta,
        rationale=proposal.rationale,
        status="approved",
    )
    ledger.record(
        "trust_prior_proposal",
        source_id=proposal.proposal_id,
        payload=updated.to_dict(),
        contract_hash="",
    )
    return path


def reject_trust_prior_proposal(proposal_id: str, *, operator: str) -> TrustPriorProposal:
    proposal = load_trust_prior_proposal(proposal_id)
    if proposal is None:
        raise ProposalError(f"missing trust prior proposal: {proposal_id}")
    if proposal.status != "pending":
        raise ProposalError(f"proposal {proposal_id} is not pending (status={proposal.status})")

    updated = TrustPriorProposal(
        proposal_id=proposal.proposal_id,
        term_id=proposal.term_id,
        trigger_report_id=proposal.trigger_report_id,
        current_ci=proposal.current_ci,
        proposed_ci=proposal.proposed_ci,
        proposed_trust_delta=proposal.proposed_trust_delta,
        rationale=f"{proposal.rationale}; rejected by {operator}",
        status="rejected",
    )
    ledger.record(
        "trust_prior_proposal",
        source_id=proposal.proposal_id,
        payload=updated.to_dict(),
        contract_hash="",
    )
    return updated
