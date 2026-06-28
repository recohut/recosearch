from __future__ import annotations

from datetime import date
from typing import Any

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.envelope import (
    DECISION_REVIEW,
    Answer,
)
from recosearch.semantic_layers.evidence.gate import apply_composite_gate
from recosearch.semantic_layers.evidence.loader import load_evidence_gates_from_contract
from recosearch.semantic_layers.evidence.types import ClaimSet, EvidencePack, Subclaim, SubclaimResult
from recosearch.semantic_layers.pipeline import execute_context_query


def _parse_reference_date(value: str) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _extract_grain_period(answer: Answer) -> tuple[str, str]:
    metric = dict(answer.metric_resolution or ())
    grain = str(metric.get("grain", ""))
    period = str(metric.get("time_period", ""))
    return grain, period


def execute_subclaim(
    subclaim: Subclaim,
    *,
    contract: dict[str, Any],
) -> SubclaimResult:
    actor = identity.Actor(role=subclaim.actor_role)
    query = ContextQuery(
        term=subclaim.term,
        tenant=subclaim.tenant,
        industry=subclaim.industry,
        actor_role=subclaim.actor_role,
        claim_qualifiers=subclaim.claim_qualifiers,
    )
    answer = execute_context_query(
        query,
        contract=contract,
        actor=actor,
        scoped_question=subclaim.scoped_question or subclaim.term,
        reference_date=_parse_reference_date(subclaim.reference_date),
    )
    grain, period = _extract_grain_period(answer)
    if subclaim.time_period and not period:
        period = subclaim.time_period
    return SubclaimResult(subclaim=subclaim, answer=answer, grain=grain, period=period)


def compose_evidence_pack(
    claim_set: ClaimSet,
    *,
    contract: dict[str, Any],
) -> tuple[EvidencePack, Answer]:
    from recosearch.semantic_layers.evidence.types import EvidencePack

    contract_hash = contract.get("contract_hash", "")
    kernel = load_evidence_gates_from_contract(contract)
    results = tuple(
        execute_subclaim(subclaim, contract=contract) for subclaim in claim_set.subclaims
    )
    pack = apply_composite_gate(
        claim_set,
        results,
        kernel=kernel,
        contract_hash=contract_hash,
    )
    pack = _persist_pack(pack, claim_set=claim_set)
    answer = pack_to_answer(pack, claim_set=claim_set, contract_hash=contract_hash)
    return pack, answer


def _persist_pack(pack: EvidencePack, *, claim_set: ClaimSet | None = None) -> EvidencePack:
    from recosearch.semantic_layers.evidence.types import EvidencePack as EP

    payload = pack.to_dict()
    if claim_set is not None:
        payload["claim_set"] = claim_set.to_dict()
    artifact_id = ledger.record(
        "evidence_pack",
        evidence_tier=pack.evidence_tier_min,
        payload=payload,
        contract_hash=pack.contract_hash,
    )
    ticket_id = ""
    if pack.review_ticket is not None:
        ticket_id = ledger.record(
            "review_ticket",
            evidence_tier=pack.evidence_tier_min,
            payload=pack.review_ticket.to_dict(),
            contract_hash=pack.contract_hash,
        )
    replay_refs = tuple(sorted(set((*pack.replay_refs, artifact_id, *([ticket_id] if ticket_id else [])))))
    return EP(
        pack_id=pack.pack_id,
        decision=pack.decision,
        contract_hash=pack.contract_hash,
        subclaim_results=pack.subclaim_results,
        composite_reasons=pack.composite_reasons,
        evidence_tier_min=pack.evidence_tier_min,
        consistency_report=pack.consistency_report,
        review_ticket=pack.review_ticket,
        replay_refs=replay_refs,
        expired=pack.expired,
    )


def pack_to_answer(
    pack: EvidencePack,
    *,
    claim_set: ClaimSet,
    contract_hash: str,
) -> Answer:
    results_rows: list[dict[str, Any]] = []
    for result in pack.subclaim_results:
        row: dict[str, Any] = {
            "term": result.subclaim.term,
            "decision": result.answer.decision,
        }
        if result.answer.result:
            row["values"] = result.answer.result
        results_rows.append(row)

    reason = ""
    reason_code = ""
    if pack.decision == DECISION_REVIEW:
        reason = "; ".join(pack.composite_reasons) or "evidence pack requires review"
        reason_code = "EVIDENCE_REVIEW_REQUIRED"
    elif pack.decision == "refuse":
        reason = "; ".join(pack.composite_reasons) or "evidence pack refused"
        reason_code = "EVIDENCE_PACK_REFUSED"

    answer = Answer(
        decision=pack.decision,
        result=results_rows if pack.decision == "answer" else results_rows or None,
        contract_version=contract_hash,
        answer_id=pack.pack_id,
        evidence_tier=pack.evidence_tier_min,
        actor_role=claim_set.subclaims[0].actor_role if claim_set.subclaims else "",
        scoped_question=claim_set.pack_label,
        plan_ref=pack.pack_id,
        reason=reason,
        reason_code=reason_code,
        replay_refs=list(pack.replay_refs),
        evidence_pack=pack.to_tuple(),
        caveats=list(pack.composite_reasons),
    )
    return answer
