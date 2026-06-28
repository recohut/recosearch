from __future__ import annotations

from typing import Any

from recosearch.semantic_layers.context.types import ProvenanceFacets, RelationshipEdge, TermBinding
from recosearch.semantic_layers.metrics.lineage import filter_lineage_for_refs
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.relations import plan_relation_path


def _schema_for_refs(metric_kernel: MetricKernel, refs: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    schemas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        entity_id = ""
        if ref.startswith("entity:"):
            entity_id = ref
        elif ref.startswith("metric:") and ref in metric_kernel.metrics:
            metric = metric_kernel.metrics[ref]
            if metric.measure_id and metric.measure_id in metric_kernel.measures:
                entity_id = metric_kernel.measures[metric.measure_id].entity_id
        elif ref.startswith("dimension:") and ref in metric_kernel.dimensions:
            entity_id = metric_kernel.dimensions[ref].entity_id

        if not entity_id or entity_id not in metric_kernel.entities:
            continue
        entity = metric_kernel.entities[entity_id]
        key = f"{entity.source_id}.{entity.table}"
        if key in seen:
            continue
        seen.add(key)
        columns: list[dict[str, str]] = [{"name": entity.primary_key, "role": "primary_key"}]
        if entity.time_field:
            columns.append({"name": entity.time_field, "role": "time_field"})
        if ref.startswith("metric:"):
            metric = metric_kernel.metrics[ref]
            if metric.measure_id and metric.measure_id in metric_kernel.measures:
                measure = metric_kernel.measures[metric.measure_id]
                columns.append({"name": measure.field, "role": "measure"})
        schemas.append(
            {
                "source_id": entity.source_id,
                "table": entity.table,
                "columns": columns,
            }
        )
    return tuple(schemas)


def _data_sources(metric_kernel: MetricKernel, refs: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in refs:
        source_id = ""
        if ref.startswith("entity:") and ref in metric_kernel.entities:
            source_id = metric_kernel.entities[ref].source_id
        elif ref.startswith("metric:") and ref in metric_kernel.metrics:
            metric = metric_kernel.metrics[ref]
            if metric.measure_id and metric.measure_id in metric_kernel.measures:
                entity_id = metric_kernel.measures[metric.measure_id].entity_id
                if entity_id in metric_kernel.entities:
                    source_id = metric_kernel.entities[entity_id].source_id
        elif ":" not in ref:
            source_id = ref
        if source_id and source_id not in seen:
            seen.add(source_id)
            sources.append({"source_id": source_id, "kind": "warehouse"})
    return tuple(sources)


def _owners_for_refs(metric_kernel: MetricKernel, refs: tuple[str, ...]) -> tuple[str, ...]:
    owners: set[str] = set()
    for ref in refs:
        if ref.startswith("metric:") and ref in metric_kernel.metrics:
            owners.update(metric_kernel.metrics[ref].owners)
    return tuple(sorted(owners))


def _semantic_metric_facet(
    metric_kernel: MetricKernel,
    refs: tuple[str, ...],
    *,
    contract_hash: str = "",
) -> dict[str, Any] | None:
    metric_ids = [ref for ref in refs if ref.startswith("metric:")]
    if not metric_ids:
        return None
    metric_id = metric_ids[0]
    metric = metric_kernel.metrics[metric_id]
    return {
        "metric_id": metric.metric_id,
        "display_name": metric.display_name,
        "grain": metric.grain,
        "version": metric.version,
        "definition_hash": metric.definition_hash,
        "contract_hash": contract_hash,
    }


def _certification_tier_facet(metric_kernel: MetricKernel, refs: tuple[str, ...]) -> dict[str, Any] | None:
    metric_ids = [ref for ref in refs if ref.startswith("metric:")]
    if not metric_ids:
        return None
    metric_id = metric_ids[0]
    cert = metric_kernel.certifications.get(metric_id)
    metric = metric_kernel.metrics[metric_id]
    return {
        "metric_id": metric_id,
        "status": metric.status,
        "certification_tier": metric.certification_tier,
        "certified": cert.certified if cert else None,
        "golden_passed": cert.golden_passed if cert else None,
        "definition_hash": cert.definition_hash if cert else "",
    }


def build_provenance_facets(
    binding: TermBinding,
    metric_kernel: MetricKernel,
    *,
    actor_role: str = "",
    contract_hash: str = "",
) -> ProvenanceFacets:
    from recosearch.semantic_layers import policy

    lineage_edges = filter_lineage_for_refs(metric_kernel, binding.primary_refs)
    column_lineage = tuple(
        (edge.from_id, edge.kind, edge.to_id)
        for edge in lineage_edges
        if edge.kind == "reads_column"
    )
    why_provenance = tuple(
        {"from_id": edge.from_id, "kind": edge.kind, "to_id": edge.to_id}
        for edge in lineage_edges
    )

    policy_decision: dict[str, Any] | None = None
    metric_ids = [ref for ref in binding.primary_refs if ref.startswith("metric:")]
    sources = [ref for ref in binding.primary_refs if ":" not in ref]
    if metric_ids or sources:
        allowed, reason_code, trace = policy.project_access(
            actor_role,
            metric_id=metric_ids[0] if metric_ids else "",
            source_id=sources[0] if sources else "",
        )
        policy_decision = {
            "allowed": allowed,
            "reason_code": reason_code,
            "trace": trace,
        }

    return ProvenanceFacets(
        schema=_schema_for_refs(metric_kernel, binding.primary_refs),
        column_lineage=column_lineage,
        ownership=_owners_for_refs(metric_kernel, binding.primary_refs),
        data_source=_data_sources(metric_kernel, binding.primary_refs),
        semantic_metric=_semantic_metric_facet(metric_kernel, binding.primary_refs, contract_hash=contract_hash),
        policy_decision=policy_decision,
        certification_tier=_certification_tier_facet(metric_kernel, binding.primary_refs),
        why_provenance=why_provenance,
    )


def discover_join_path_refs(
    binding: TermBinding,
    metric_kernel: MetricKernel,
    relationships: tuple[RelationshipEdge, ...],
) -> tuple[str, ...]:
    refs: set[str] = set()
    for edge in relationships:
        if edge.from_id == binding.term_id:
            refs.add(edge.to_id)

    entity_ids = [ref for ref in binding.primary_refs if ref.startswith("entity:")]
    metric_entity_ids: list[str] = []
    for ref in binding.primary_refs:
        if ref.startswith("metric:") and ref in metric_kernel.metrics:
            metric = metric_kernel.metrics[ref]
            if metric.measure_id and metric.measure_id in metric_kernel.measures:
                metric_entity_ids.append(metric_kernel.measures[metric.measure_id].entity_id)

    from_entities = entity_ids or metric_entity_ids
    for from_entity in from_entities:
        for entity in metric_kernel.entities.values():
            if entity.entity_id == from_entity:
                continue
            try:
                path = plan_relation_path(metric_kernel.relations, from_entity, entity.entity_id)
            except ValueError:
                continue
            for step in path:
                refs.add(step.relation_id)
                refs.add(step.to_entity_id)
                refs.add(step.from_entity_id)

    return tuple(sorted(refs))
