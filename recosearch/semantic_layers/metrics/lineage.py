from __future__ import annotations

from typing import Any

from recosearch.semantic_layers.ledger import LineageEdge
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.types import ResolvedMetric


def _relation_column_edges(kernel: MetricKernel, relation_id: str) -> list[LineageEdge]:
    relation = kernel.relations[relation_id]
    from_entity = kernel.entities[relation.from_entity_id]
    to_entity = kernel.entities[relation.to_entity_id]
    from_col = f"{from_entity.source_id}.{from_entity.table}.{relation.join_key}"
    to_col = f"{to_entity.source_id}.{to_entity.table}.{relation.join_key}"
    return [
        LineageEdge(from_id=relation_id, to_id=from_col, kind="reads_column"),
        LineageEdge(from_id=relation_id, to_id=to_col, kind="reads_column"),
    ]


def _join_plan_relation_edges(
    kernel: MetricKernel,
    join_plan: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[LineageEdge]:
    edges: list[LineageEdge] = []
    seen: set[str] = set()
    for join in join_plan:
        relation_id = str(join.get("relation_id", ""))
        if not relation_id or relation_id in seen:
            continue
        seen.add(relation_id)
        if relation_id in kernel.relations:
            edges.extend(_relation_column_edges(kernel, relation_id))
    return edges


def _derived_component_edges(kernel: MetricKernel, metric_id: str, formula_refs: tuple[str, ...]) -> list[LineageEdge]:
    edges: list[LineageEdge] = []
    for ref in formula_refs:
        if ref.startswith("measure:"):
            measure = kernel.measures[ref]
            entity = kernel.entities[measure.entity_id]
            column_ref = f"{entity.source_id}.{entity.table}.{measure.field}"
            edges.append(LineageEdge(from_id=metric_id, to_id=ref, kind="uses_measure"))
            edges.append(LineageEdge(from_id=ref, to_id=column_ref, kind="reads_column"))
        elif ref.startswith("metric:"):
            ref_metric = kernel.metrics[ref]
            if ref_metric.measure_id:
                measure = kernel.measures[ref_metric.measure_id]
                entity = kernel.entities[measure.entity_id]
                column_ref = f"{entity.source_id}.{entity.table}.{measure.field}"
                edges.append(
                    LineageEdge(from_id=metric_id, to_id=ref_metric.measure_id, kind="uses_measure")
                )
                edges.append(
                    LineageEdge(from_id=ref_metric.measure_id, to_id=column_ref, kind="reads_column")
                )
    return edges


def project_metric_lineage(
    kernel: MetricKernel,
    resolved: ResolvedMetric,
    column_lineage: tuple[tuple[str, str, str], ...],
    join_plan: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
) -> list[LineageEdge]:
    edges: list[LineageEdge] = []
    metric = kernel.metrics[resolved.metric_id]

    if metric.kind == "derived":
        edges.extend(_derived_component_edges(kernel, resolved.metric_id, metric.formula_refs))
    elif metric.measure_id:
        edges.append(
            LineageEdge(from_id=resolved.metric_id, to_id=metric.measure_id, kind="uses_measure")
        )
        measure = kernel.measures[metric.measure_id]
        entity = kernel.entities[measure.entity_id]
        column_ref = f"{entity.source_id}.{entity.table}.{measure.field}"
        edges.append(
            LineageEdge(from_id=metric.measure_id, to_id=column_ref, kind="reads_column")
        )

    for from_id, _via, column_ref in column_lineage:
        if from_id.startswith("dimension:"):
            edges.append(LineageEdge(from_id=from_id, to_id=column_ref, kind="reads_column"))
        elif from_id == resolved.metric_id and _via not in (metric.measure_id, ""):
            if not _via.startswith("metric:") and not _via.startswith("measure:"):
                edges.append(
                    LineageEdge(
                        from_id=resolved.metric_id,
                        to_id=column_ref,
                        kind="reads_column",
                    )
                )

    if join_plan:
        edges.extend(_join_plan_relation_edges(kernel, join_plan))

    return edges


def filter_lineage_for_refs(
    kernel: MetricKernel,
    refs: tuple[str, ...] | list[str],
) -> list[LineageEdge]:
    ref_set = set(refs)
    expanded: set[str] = set(ref_set)
    column_refs: set[str] = set()

    for ref in ref_set:
        if ref.startswith("metric:") and ref in kernel.metrics:
            metric = kernel.metrics[ref]
            if metric.measure_id:
                expanded.add(metric.measure_id)
            expanded.update(metric.allowed_dimension_ids)
            if metric.measure_id and metric.measure_id in kernel.measures:
                expanded.add(kernel.measures[metric.measure_id].entity_id)
        elif ref.startswith("entity:"):
            expanded.add(ref)
            for relation in kernel.relations.values():
                if relation.from_entity_id == ref or relation.to_entity_id == ref:
                    expanded.add(relation.relation_id)

    for ref in expanded:
        if ref.startswith("measure:") and ref in kernel.measures:
            measure = kernel.measures[ref]
            entity = kernel.entities[measure.entity_id]
            column_refs.add(f"{entity.source_id}.{entity.table}.{measure.field}")
        elif ref.startswith("dimension:") and ref in kernel.dimensions:
            dimension = kernel.dimensions[ref]
            entity = kernel.entities[dimension.entity_id]
            column_refs.add(f"{entity.source_id}.{entity.table}.{dimension.field}")
        elif ref.startswith("entity:") and ref in kernel.entities:
            entity = kernel.entities[ref]
            column_refs.add(f"{entity.source_id}.{entity.table}.{entity.primary_key}")

    edges = project_kernel_lineage(kernel)
    return [
        edge
        for edge in edges
        if edge.from_id in expanded
        or edge.to_id in expanded
        or edge.to_id in column_refs
        or edge.from_id in ref_set
    ]


def project_kernel_lineage(kernel: MetricKernel) -> list[LineageEdge]:
    edges: list[LineageEdge] = []
    for metric in kernel.metrics.values():
        if metric.kind == "derived":
            edges.extend(_derived_component_edges(kernel, metric.metric_id, metric.formula_refs))
        elif metric.measure_id and metric.measure_id in kernel.measures:
            measure = kernel.measures[metric.measure_id]
            entity = kernel.entities[measure.entity_id]
            column_ref = f"{entity.source_id}.{entity.table}.{measure.field}"
            edges.append(LineageEdge(from_id=metric.metric_id, to_id=metric.measure_id, kind="uses_measure"))
            edges.append(LineageEdge(from_id=metric.measure_id, to_id=column_ref, kind="reads_column"))
        for dimension_id in metric.allowed_dimension_ids:
            if dimension_id in kernel.dimensions:
                dimension = kernel.dimensions[dimension_id]
                entity = kernel.entities[dimension.entity_id]
                column_ref = f"{entity.source_id}.{entity.table}.{dimension.field}"
                edges.append(LineageEdge(from_id=metric.metric_id, to_id=dimension_id, kind="allows_dimension"))
                edges.append(LineageEdge(from_id=dimension_id, to_id=column_ref, kind="reads_column"))
    for relation in kernel.relations.values():
        edges.extend(_relation_column_edges(kernel, relation.relation_id))
    return edges
