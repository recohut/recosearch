from __future__ import annotations

from recosearch.semantic_layers.context.types import ContextKernel, ContextQuery, ContextResolution, TermBinding
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.types import Collection


class ContextResolver:
    _TENANT_PRIORITY = 100

    def __init__(self, context_kernel: ContextKernel, metric_kernel: MetricKernel) -> None:
        self._context = context_kernel
        self._metric = metric_kernel
        self._terms_by_collection: dict[str, list[TermBinding]] = {}
        for term in context_kernel.terms.values():
            self._terms_by_collection.setdefault(term.collection_id, []).append(term)

    def resolve(self, query: ContextQuery) -> ContextResolution:
        if query.term in self._context.terms:
            binding = self._context.terms[query.term]
            return ContextResolution(
                decision="resolved",
                term_id=binding.term_id,
                reason="exact term id",
                binding=binding,
            )

        normalized = query.term.strip().casefold()
        for collection in self._applicable_collections(query):
            matches = [
                term
                for term in self._terms_by_collection.get(collection.collection_id, [])
                if self._is_match(normalized, term)
            ]
            if not matches:
                continue
            if len(matches) == 1:
                binding = matches[0]
                return ContextResolution(
                    decision="resolved",
                    term_id=binding.term_id,
                    reason="matched term",
                    binding=binding,
                )
            candidates = tuple(sorted((t.term_id, t.display_name) for t in matches))
            return ContextResolution(
                decision="clarify",
                term_id="",
                reason="ambiguous term",
                candidates=candidates,
            )

        return ContextResolution(
            decision="unknown",
            term_id="",
            reason="unknown term",
        )

    def _applicable_collections(self, query: ContextQuery) -> list[Collection]:
        applicable: list[Collection] = []
        for collection in self._metric.collections.values():
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

    def _is_match(self, normalized: str, term: TermBinding) -> bool:
        if term.display_name.strip().casefold() == normalized:
            return True
        return any(alias.strip().casefold() == normalized for alias in term.aliases)
