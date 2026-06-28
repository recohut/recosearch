from __future__ import annotations

from recosearch.semantic_layers.context.facets import build_provenance_facets, discover_join_path_refs
from recosearch.semantic_layers.context.hash import compute_card_id
from recosearch.semantic_layers.context.loader import ContextKernel
from recosearch.semantic_layers.context.trust import build_trust_signal
from recosearch.semantic_layers.context.types import ContextCard, TermBinding
from recosearch.semantic_layers.metrics.loader import MetricKernel


def build_context_card(
    binding: TermBinding,
    context_kernel: ContextKernel,
    metric_kernel: MetricKernel,
    *,
    actor_role: str = "",
    contract_hash: str = "",
) -> ContextCard:
    facets = build_provenance_facets(
        binding,
        metric_kernel,
        actor_role=actor_role,
        contract_hash=contract_hash,
    )
    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role=actor_role,
        context_kernel=context_kernel,
    )

    authored_refs = tuple(
        sorted(
            {
                edge.to_id
                for edge in context_kernel.relationships
                if edge.from_id == binding.term_id
            }
        )
    )
    join_refs = discover_join_path_refs(binding, metric_kernel, context_kernel.relationships)
    related_refs = tuple(sorted(set((*authored_refs, *join_refs))))

    guidance = context_kernel.guidance.get(binding.term_id)
    client_guidance = {
        "when_to_use": guidance.when_to_use if guidance else "",
        "when_to_clarify": guidance.when_to_clarify if guidance else "",
        "when_to_refuse": guidance.when_to_refuse if guidance else "",
    }

    technical = {
        "schema": list(facets.schema),
        "data_source": list(facets.data_source),
        "column_lineage": [list(item) for item in facets.column_lineage],
        "policy_decision": facets.policy_decision,
    }
    semantic = {
        "definition": binding.definition,
        "primary_refs": list(binding.primary_refs),
        "semantic_metric": facets.semantic_metric,
        "why_provenance": list(facets.why_provenance),
    }
    operational = {
        "owners": _owners_for_context(binding, context_kernel, facets.ownership),
        "certification": facets.certification_tier,
        "freshness_sla": _freshness_for_refs(binding, metric_kernel),
    }
    relationships = {
        "related_refs": list(related_refs),
        "authored_edges": [
            {"to_id": edge.to_id, "kind": edge.kind}
            for edge in context_kernel.relationships
            if edge.from_id == binding.term_id
        ],
        "join_path_refs": list(join_refs),
    }

    caveats: list[str] = []
    if trust.status == "usable_with_caveats":
        caveats.append("trust_caveat")
    if trust.drift_status != "current":
        caveats.extend(trust.expiry_reasons)

    card_dict = {
        "term_id": binding.term_id,
        "display_name": binding.display_name,
        "definition": binding.definition,
        "primary_refs": list(binding.primary_refs),
        "related_refs": list(related_refs),
        "trust": {
            "status": trust.status,
            "evidence_tier": trust.evidence_tier,
            "drift_status": trust.drift_status,
            "expiry_reasons": list(trust.expiry_reasons),
            "claim_scope": {
                "sources": list(trust.claim_scope.sources),
                "roles": list(trust.claim_scope.roles),
                "metrics": list(trust.claim_scope.metrics),
            },
        },
    }
    card_id = compute_card_id(card_dict)

    return ContextCard(
        card_id=card_id,
        term_id=binding.term_id,
        display_name=binding.display_name,
        definition=binding.definition,
        primary_refs=binding.primary_refs,
        related_refs=related_refs,
        technical=technical,
        semantic=semantic,
        operational=operational,
        relationships=relationships,
        trust=trust,
        client_guidance=client_guidance,
        caveats=tuple(caveats),
    )


def _freshness_for_refs(binding: TermBinding, metric_kernel: MetricKernel) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for ref in binding.primary_refs:
        if not ref.startswith("metric:") or ref not in metric_kernel.metrics:
            continue
        metric = metric_kernel.metrics[ref]
        if metric.freshness_sla is None:
            continue
        out.append(
            {
                "metric_id": ref,
                "max_age_days": metric.freshness_sla.max_age_days,
                "hard_sla": metric.freshness_sla.hard_sla,
            }
        )
    return out


def _owners_for_context(
    binding: TermBinding,
    context_kernel: ContextKernel,
    facet_owners: tuple[str, ...],
) -> list[str]:
    owners = set(facet_owners)
    for edge in context_kernel.relationships:
        if edge.from_id == binding.term_id and edge.to_id.startswith("owner:"):
            owners.add(edge.to_id.removeprefix("owner:"))
    return sorted(owners)
