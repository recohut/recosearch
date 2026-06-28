from __future__ import annotations

from collections import defaultdict

from recosearch.semantic_layers.envelope import DECISION_REFUSE, DECISION_REVIEW
from recosearch.semantic_layers.evidence.loader import pattern_matches
from recosearch.semantic_layers.evidence.review import create_review_ticket
from recosearch.semantic_layers.evidence.types import (
    ClaimSet,
    ConsistencyReport,
    EvidenceGateKernel,
    EvidencePack,
    SubclaimResult,
    TIER_LABEL_TO_RANK,
)
from recosearch.semantic_layers.evidence.hash import compute_pack_id


def _tier_rank(label: str) -> int:
    return TIER_LABEL_TO_RANK.get(label, 1)


def _require_known_tier_label(label: str) -> int:
    if label not in TIER_LABEL_TO_RANK:
        raise ValueError(f"unknown evidence tier label: {label}")
    return TIER_LABEL_TO_RANK[label]


def _resolve_term_id(result: SubclaimResult) -> str:
    ctx = dict(result.answer.context_resolution or ())
    return str(ctx.get("term_id", result.subclaim.term))


def _min_tier_label(results: tuple[SubclaimResult, ...]) -> str:
    ranks = [_tier_rank(r.answer.evidence_tier or "contract-only") for r in results]
    if not ranks:
        return "contract-only"
    min_rank = min(ranks)
    for label, rank in TIER_LABEL_TO_RANK.items():
        if rank == min_rank:
            return label
    return "contract-only"


def _required_tier_rank(
    kernel: EvidenceGateKernel,
    *,
    pack_label: str,
    claim_min_label: str,
) -> tuple[int, str]:
    if claim_min_label:
        return _require_known_tier_label(claim_min_label), claim_min_label
    for bar in kernel.tier_bars.values():
        if pattern_matches(bar.pattern, pack_label):
            return bar.min_tier_rank, bar.min_tier_label
    return kernel.default_min_tier_rank, kernel.default_min_tier_label


_PASSING_SUBCLAIM_DECISIONS = frozenset({"answer", "answer_with_caveats"})


def check_comparable_consistency(
    results: tuple[SubclaimResult, ...],
    *,
    kernel: EvidenceGateKernel,
) -> ConsistencyReport:
    grouped: dict[str, list[SubclaimResult]] = defaultdict(list)
    reasons: list[str] = []

    for result in results:
        group = result.subclaim.comparable_group.strip()
        if not group:
            continue
        if group not in kernel.comparable_groups:
            reasons.append(f"unknown_comparable_group:{group}")
        grouped[group].append(result)

    for group_id, members in sorted(grouped.items()):
        if group_id not in kernel.comparable_groups:
            continue
        incomplete = False
        for member in members:
            if member.answer.decision not in _PASSING_SUBCLAIM_DECISIONS:
                incomplete = True
                break
            if not member.grain or not member.period:
                incomplete = True
                break
        if incomplete:
            reasons.append(f"comparable_group_incomplete:{group_id}")
            continue
        grains = {m.grain for m in members}
        periods = {m.period for m in members}
        if len(grains) > 1:
            reasons.append(f"comparable_group {group_id}: grain mismatch {sorted(grains)}")
        if len(periods) > 1:
            reasons.append(f"comparable_group {group_id}: period mismatch {sorted(periods)}")

    if reasons:
        return ConsistencyReport(ok=False, reasons=tuple(sorted(set(reasons))))
    return ConsistencyReport(ok=True)


def _review_triggers_for_results(
    kernel: EvidenceGateKernel,
    results: tuple[SubclaimResult, ...],
) -> tuple[str, ...]:
    triggers: list[str] = []
    for result in results:
        term_id = _resolve_term_id(result)
        for trigger in kernel.review_triggers.values():
            if pattern_matches(trigger.pattern, term_id) or pattern_matches(
                trigger.pattern, result.subclaim.term
            ):
                triggers.append(f"review_trigger:{trigger.pattern}")
    return tuple(sorted(set(triggers)))


def apply_composite_gate(
    claim_set: ClaimSet,
    results: tuple[SubclaimResult, ...],
    *,
    kernel: EvidenceGateKernel,
    contract_hash: str,
) -> EvidencePack:
    pack_id = compute_pack_id(claim_set_payload=claim_set.to_dict(), contract_hash=contract_hash)
    consistency = check_comparable_consistency(results, kernel=kernel)
    tier_min = _min_tier_label(results)
    required_rank, required_label = _required_tier_rank(
        kernel,
        pack_label=claim_set.pack_label,
        claim_min_label=claim_set.min_tier_label,
    )
    actual_rank = _tier_rank(tier_min)
    composite_reasons: list[str] = []

    refuse_reasons: list[str] = []
    for result in results:
        if result.answer.decision == DECISION_REFUSE:
            refuse_reasons.append(
                f"subclaim_refuse:{_resolve_term_id(result)}:{result.answer.reason_code or result.answer.reason}"
            )
    if refuse_reasons:
        return EvidencePack(
            pack_id=pack_id,
            decision=DECISION_REFUSE,
            contract_hash=contract_hash,
            subclaim_results=results,
            composite_reasons=tuple(refuse_reasons),
            evidence_tier_min=tier_min,
            consistency_report=consistency,
            replay_refs=_collect_replay_refs(results),
        )

    for result in results:
        if result.answer.decision == "clarify":
            composite_reasons.append(f"subclaim_clarify:{_resolve_term_id(result)}")
        elif result.answer.decision not in _PASSING_SUBCLAIM_DECISIONS:
            composite_reasons.append(
                f"subclaim_unexpected_decision:{_resolve_term_id(result)}:{result.answer.decision}"
            )

    review_triggers = _review_triggers_for_results(kernel, results)
    if review_triggers:
        composite_reasons.extend(review_triggers)

    if actual_rank < required_rank:
        composite_reasons.append(
            f"evidence_tier_below_bar:actual={tier_min}:required={required_label}"
        )

    if not consistency.ok:
        composite_reasons.extend(list(consistency.reasons))

    if composite_reasons:
        required_role = "controller"
        for trigger in kernel.review_triggers.values():
            if any(pattern_matches(trigger.pattern, t.split(":", 1)[-1]) for t in review_triggers):
                required_role = trigger.required_role
                break
        ticket = create_review_ticket(
            pack_id=pack_id,
            triggers=tuple(composite_reasons),
            required_role=required_role,
        )
        return EvidencePack(
            pack_id=pack_id,
            decision=DECISION_REVIEW,
            contract_hash=contract_hash,
            subclaim_results=results,
            composite_reasons=tuple(composite_reasons),
            evidence_tier_min=tier_min,
            consistency_report=consistency,
            review_ticket=ticket,
            replay_refs=_collect_replay_refs(results),
        )

    return EvidencePack(
        pack_id=pack_id,
        decision="answer",
        contract_hash=contract_hash,
        subclaim_results=results,
        composite_reasons=(),
        evidence_tier_min=tier_min,
        consistency_report=consistency,
        replay_refs=_collect_replay_refs(results),
    )


def _collect_replay_refs(results: tuple[SubclaimResult, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for result in results:
        refs.extend(result.answer.replay_refs)
    return tuple(sorted(set(refs)))
