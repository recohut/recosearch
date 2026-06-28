from __future__ import annotations

from typing import Any

from recosearch.semantic_layers import policy
from recosearch.semantic_layers.context.events import EventBus, get_event_bus
from recosearch.semantic_layers.context.hash import compute_trust_id
from recosearch.semantic_layers.context.types import (
    EVIDENCE_TIER_LABELS,
    ClaimScope,
    ContextCard,
    ContextCertification,
    ContextKernel,
    TermBinding,
    TrustSignal,
)
from recosearch.semantic_layers.envelope import Answer
from recosearch.semantic_layers.metrics.loader import MetricKernel


def _metric_refs(binding: TermBinding) -> list[str]:
    return [ref for ref in binding.primary_refs if ref.startswith("metric:")]


def _source_refs(binding: TermBinding, metric_kernel: MetricKernel) -> list[str]:
    sources: set[str] = set()
    for ref in binding.primary_refs:
        if ref.startswith("metric:") and ref in metric_kernel.metrics:
            metric = metric_kernel.metrics[ref]
            if metric.measure_id and metric.measure_id in metric_kernel.measures:
                entity_id = metric_kernel.measures[metric.measure_id].entity_id
                if entity_id in metric_kernel.entities:
                    sources.add(metric_kernel.entities[entity_id].source_id)
        elif ref.startswith("entity:") and ref in metric_kernel.entities:
            sources.add(metric_kernel.entities[ref].source_id)
        elif ":" not in ref:
            sources.add(ref)
    return sorted(sources)


def _lineage_for_refs(metric_kernel: MetricKernel, refs: tuple[str, ...]) -> list[Any]:
    from recosearch.semantic_layers.metrics.lineage import filter_lineage_for_refs

    return filter_lineage_for_refs(metric_kernel, refs)


def _map_evidence_tier(
    metric_kernel: MetricKernel,
    metric_ids: list[str],
    *,
    answer: Answer | None = None,
    context_cert: ContextCertification | None = None,
) -> tuple[int, str, tuple[str, ...]]:
    labels: list[str] = []
    tier = 1
    if answer and answer.evidence_tier:
        label = answer.evidence_tier
        labels.append(label)
        tier_map = {v: k for k, v in EVIDENCE_TIER_LABELS.items()}
        tier = tier_map.get(label, 2)
        if (
            context_cert is not None
            and context_cert.certified
            and context_cert.golden_passed
            and context_cert.evidence_tier is not None
        ):
            tier = max(tier, context_cert.evidence_tier)
            labels.append(EVIDENCE_TIER_LABELS.get(context_cert.evidence_tier, "fixture-backed"))
            label = EVIDENCE_TIER_LABELS.get(tier, label)
        return tier, label, tuple(labels)

    if context_cert is not None and context_cert.evidence_tier is not None:
        tier = max(tier, context_cert.evidence_tier)
        if context_cert.certified and context_cert.golden_passed:
            labels.append(EVIDENCE_TIER_LABELS.get(tier, "fixture-backed"))
        elif context_cert.golden_passed:
            labels.append(EVIDENCE_TIER_LABELS.get(tier, "fixture-backed"))
        else:
            labels.append("contract-only")

    for metric_id in metric_ids:
        cert = metric_kernel.certifications.get(metric_id)
        metric = metric_kernel.metrics.get(metric_id)
        if cert is None or metric is None:
            if not labels:
                labels.append("contract-only")
            continue
        if cert.certified and cert.golden_passed:
            labels.append("fixture-backed")
            tier = max(tier, 2)
        elif cert.golden_passed:
            labels.append("fixture-backed")
            tier = max(tier, 2)
        else:
            labels.append("contract-only")

    if not labels:
        labels.append("contract-only")
    label = EVIDENCE_TIER_LABELS.get(tier, "contract-only")
    return tier, label, tuple(labels)


def _event_bus_drift_reasons(
    event_bus: EventBus,
    term_id: str,
    metric_ids: list[str],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(event_bus.drift_reasons(term_id))
    for metric_id in metric_ids:
        reasons.extend(event_bus.drift_reasons(metric_id))
    return reasons


def _assess_drift(
    metric_kernel: MetricKernel,
    metric_ids: list[str],
    lineage_edges: list[Any],
    *,
    term_binding: TermBinding | None = None,
    context_cert: ContextCertification | None = None,
    event_bus: EventBus | None = None,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    if term_binding is not None and context_cert is not None:
        if context_cert.definition_hash != term_binding.definition_hash:
            reasons.append("definition_hash_mismatch")
        if context_cert.policy_hash and context_cert.policy_hash != policy.compute_policy_hash():
            reasons.append("policy_changed")
        if context_cert.golden_passed is False:
            reasons.append("failed_certification")
        if context_cert.certified is False:
            reasons.append("failed_certification")

    for metric_id in metric_ids:
        metric = metric_kernel.metrics.get(metric_id)
        cert = metric_kernel.certifications.get(metric_id)
        if metric is None:
            continue
        if cert is not None and cert.definition_hash != metric.definition_hash:
            reasons.append("definition_hash_mismatch")
        if cert is not None and cert.golden_passed is False:
            reasons.append("failed_certification")
        if cert is not None and cert.certified is False:
            reasons.append("failed_certification")
        if metric.status == "certified" and cert is None:
            reasons.append("missing_certification")
        if metric.freshness_sla is None and metric.status == "certified":
            reasons.append("missing_freshness_sla")
        if metric.status == "certified":
            metric_lineage = [e for e in lineage_edges if e.from_id == metric_id or e.to_id == metric_id]
            if not metric_lineage:
                reasons.append("missing_lineage")

    if event_bus is not None and term_binding is not None:
        reasons.extend(
            _event_bus_drift_reasons(event_bus, term_binding.term_id, metric_ids)
        )

    if not reasons:
        return "current", ()
    expired_reasons = (
        "definition_hash_mismatch",
        "failed_certification",
        "missing_lineage",
        "policy_changed",
        "schema_changed",
    )
    if any(r in expired_reasons for r in reasons):
        return "expired", tuple(sorted(set(reasons)))
    return "at_risk", tuple(sorted(set(reasons)))


def build_trust_signal(
    binding: TermBinding,
    metric_kernel: MetricKernel,
    *,
    actor_role: str = "",
    answer: Answer | None = None,
    context_kernel: ContextKernel | None = None,
    event_bus: EventBus | None = None,
) -> TrustSignal:
    if event_bus is None:
        event_bus = get_event_bus()
    metric_ids = _metric_refs(binding)
    sources = _source_refs(binding, metric_kernel)
    lineage_edges = _lineage_for_refs(metric_kernel, binding.primary_refs)
    context_cert = (
        context_kernel.certifications.get(binding.term_id) if context_kernel is not None else None
    )

    policy_traces: list[dict[str, Any]] = []
    policy_denied = False
    for metric_id in metric_ids or [""]:
        for source_id in sources or [""]:
            allowed, reason_code, trace = policy.project_access(
                actor_role,
                metric_id=metric_id,
                source_id=source_id,
            )
            policy_traces.append(trace)
            if not allowed:
                policy_denied = True

    evidence_tier, evidence_label, no_overclaim = _map_evidence_tier(
        metric_kernel,
        metric_ids,
        answer=answer,
        context_cert=context_cert,
    )
    drift_status, expiry_reasons = _assess_drift(
        metric_kernel,
        metric_ids,
        lineage_edges,
        term_binding=binding,
        context_cert=context_cert,
        event_bus=event_bus,
    )

    if answer is not None:
        runtime_reasons = list(expiry_reasons)
        for caveat in answer.caveats:
            if caveat in ("stale_data", "stale_certification", "failed_certification"):
                runtime_reasons.append(caveat)
        if answer.decision == "refuse":
            runtime_reasons.append("policy_refuse")
        expiry_reasons = tuple(sorted(set(runtime_reasons)))
        if runtime_reasons and drift_status != "expired":
            drift_status = "expired" if "policy_refuse" in runtime_reasons else "at_risk"

    reasons: list[str] = []
    status = "trusted"

    if policy_denied:
        status = "not_usable"
        reasons.append("policy_denied")
    elif drift_status == "expired":
        status = "not_usable"
        reasons.append("drift_expired")
    elif drift_status == "at_risk":
        status = "usable_with_caveats"
        reasons.append("drift_at_risk")
    elif evidence_tier < 2:
        status = "usable_with_caveats"
        reasons.append("low_evidence_tier")
        no_overclaim = (*no_overclaim, "contracts_parse_only")

    if tier3_no_cloud_claim(evidence_tier):
        no_overclaim = (*no_overclaim, "not_cloud_proven")
    if context_cert is not None and context_cert.ares_confidence_interval is not None:
        lo, hi = context_cert.ares_confidence_interval
        no_overclaim = (*no_overclaim, f"ares_ci={lo:.2f}-{hi:.2f}")

    if metric_ids:
        for metric_id in metric_ids:
            metric = metric_kernel.metrics.get(metric_id)
            if metric and metric.deprecated:
                status = "usable_with_caveats"
                reasons.append("deprecated_metric")

    claim_scope = ClaimScope(
        sources=tuple(sources),
        roles=(actor_role,) if actor_role else ("*",),
        metrics=tuple(metric_ids),
    )

    trust_dict = {
        "status": status,
        "evidence_tier": evidence_tier,
        "drift_status": drift_status,
        "expiry_reasons": list(expiry_reasons),
        "claim_scope": {
            "sources": list(claim_scope.sources),
            "roles": list(claim_scope.roles),
            "metrics": list(claim_scope.metrics),
        },
    }
    signal_id = compute_trust_id(trust_dict)

    return TrustSignal(
        signal_id=signal_id,
        status=status,
        evidence_tier=evidence_tier,
        evidence_label=evidence_label,
        claim_scope=claim_scope,
        drift_status=drift_status,
        expiry_reasons=expiry_reasons,
        no_overclaim_labels=no_overclaim,
        reasons=tuple(reasons),
    )


def tier3_no_cloud_claim(evidence_tier: int) -> bool:
    return evidence_tier == 3


def apply_runtime_trust(
    card: ContextCard,
    answer: Answer,
    metric_kernel: MetricKernel,
    *,
    context_kernel: ContextKernel | None = None,
    event_bus: EventBus | None = None,
) -> ContextCard:
    if context_kernel is not None and card.term_id in context_kernel.terms:
        binding = context_kernel.terms[card.term_id]
    else:
        binding = TermBinding(
            term_id=card.term_id,
            display_name=card.display_name,
            definition=card.definition,
            aliases=(),
            collection_id="",
            primary_refs=card.primary_refs,
        )
    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role=answer.actor_role,
        answer=answer,
        context_kernel=context_kernel,
        event_bus=event_bus,
    )
    return ContextCard(
        card_id=card.card_id,
        term_id=card.term_id,
        display_name=card.display_name,
        definition=card.definition,
        primary_refs=card.primary_refs,
        related_refs=card.related_refs,
        technical=card.technical,
        semantic=card.semantic,
        operational=card.operational,
        relationships=card.relationships,
        trust=trust,
        client_guidance=card.client_guidance,
        caveats=tuple(sorted(set((*card.caveats, *answer.caveats)))),
    )
