from __future__ import annotations

from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.types import ClarifyRequest, Collection, Metric, MetricQuery, ResolvedMetric


class MetricResolver:
    _TENANT_PRIORITY = 100

    def __init__(self, kernel: MetricKernel) -> None:
        self._kernel = kernel
        self._metrics_by_collection: dict[str, list[Metric]] = {}
        for metric in kernel.metrics.values():
            self._metrics_by_collection.setdefault(metric.collection_id, []).append(metric)

    def resolve(self, query: MetricQuery) -> ResolvedMetric | ClarifyRequest:
        if query.term in self._kernel.metrics:
            return self._resolved(self._kernel.metrics[query.term])

        normalized = query.term.strip().casefold()
        for collection in self._applicable_collections(query):
            matches = [
                metric
                for metric in self._metrics_by_collection.get(collection.collection_id, [])
                if self._is_match(normalized, metric)
            ]
            if not matches:
                continue
            if len(matches) == 1:
                return self._resolved(matches[0])
            candidates = tuple(sorted((m.metric_id, m.display_name) for m in matches))
            return ClarifyRequest(
                reason="ambiguous metric",
                requested_term=query.term,
                candidates=candidates,
            )

        available = tuple(sorted(self._kernel.metrics))
        return ClarifyRequest(
            reason="unknown metric",
            requested_term=query.term,
            available_metrics=available,
        )

    def _applicable_collections(self, query: MetricQuery) -> list[Collection]:
        applicable: list[Collection] = []
        for collection in self._kernel.collections.values():
            scope = dict(collection.scope)
            if not scope:
                applicable.append(collection)
                continue
            if scope.get("tenant") == query.tenant:
                applicable.append(collection)
                continue
            if query.industry and scope.get("industry") == query.industry:
                applicable.append(collection)
        applicable.sort(key=lambda c: (-c.priority, c.collection_id))
        return applicable

    def _resolved(self, metric: Metric) -> ResolvedMetric:
        collection = self._kernel.collections[metric.collection_id]
        fallback_used = collection.priority < self._TENANT_PRIORITY
        caveat_codes: list[str] = []
        if fallback_used:
            caveat_codes.append("fallback_metric")
        if metric.deprecated:
            caveat_codes.append("deprecated_metric")

        effective_status = metric.status
        cert = self._kernel.certifications.get(metric.metric_id)
        if cert is not None:
            if cert.definition_hash != metric.definition_hash:
                effective_status = "uncertified"
                caveat_codes.append("stale_certification")
            elif cert.golden_passed is False:
                effective_status = "uncertified"
                caveat_codes.append("failed_certification")
            elif cert.certified is False:
                effective_status = "uncertified"
                caveat_codes.append("failed_certification")

        measure_id = metric.measure_id
        if metric.kind == "derived" and not measure_id:
            for ref in metric.formula_refs:
                if ref.startswith("measure:"):
                    measure_id = ref
                    break
                if ref.startswith("metric:"):
                    ref_metric = self._kernel.metrics[ref]
                    if ref_metric.measure_id:
                        measure_id = ref_metric.measure_id
                        break

        return ResolvedMetric(
            metric_id=metric.metric_id,
            display_name=metric.display_name,
            collection=collection,
            fallback_used=fallback_used,
            measure_id=measure_id,
            grain=metric.grain,
            filter_rules=metric.filter_rules,
            allowed_dimension_ids=metric.allowed_dimension_ids,
            caveat_codes=tuple(caveat_codes),
            version=metric.version,
            definition_hash=metric.definition_hash,
            status=effective_status,
            kind=metric.kind,
            formula=metric.formula,
            formula_refs=metric.formula_refs,
        )

    def _is_match(self, normalized_term: str, metric: Metric) -> bool:
        if metric.display_name.strip().casefold() == normalized_term:
            return True
        return any(synonym.strip().casefold() == normalized_term for synonym in metric.synonyms)
