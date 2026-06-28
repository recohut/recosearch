from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from recosearch.semantic_layers.context.types import ContextKernel, RelationshipEdge


class IngestAdapter(Protocol):
    def load(self) -> dict[str, Any]: ...
    def merge_related_refs(self, term_id: str, authored_refs: tuple[str, ...]) -> tuple[str, ...]: ...


@dataclass
class FileCatalogAdapter:
    """Read-only catalog ingest from DataHub/OpenMetadata JSON export."""

    path: Path
    conflicts: list[str] = field(default_factory=list)

    def load(self) -> dict[str, Any]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"entities": raw}

    def merge_related_refs(
        self,
        term_id: str,
        authored_refs: tuple[str, ...],
    ) -> tuple[str, ...]:
        catalog = self.load()
        extra: set[str] = set(authored_refs)
        for entity in catalog.get("entities", []):
            if not isinstance(entity, dict):
                continue
            urn = str(entity.get("urn", ""))
            glossary_term = str(entity.get("glossaryTerm", ""))
            if glossary_term and glossary_term == term_id:
                for related in entity.get("related", []):
                    ref = str(related)
                    if ref in authored_refs:
                        self.conflicts.append(f"{term_id}: conflict on {ref}")
                        continue
                    extra.add(ref)
                owner = entity.get("owner")
                if owner:
                    extra.add(f"owner:{owner}")
        return tuple(sorted(extra))


def apply_catalog_ingest(context_kernel: ContextKernel, adapter: IngestAdapter) -> ContextKernel:
    """Return a kernel enriched with read-only catalog relationships."""
    existing = {
        (edge.from_id, edge.to_id, edge.kind)
        for edge in context_kernel.relationships
    }
    relationships = list(context_kernel.relationships)
    for term_id in context_kernel.terms:
        authored = tuple(edge.to_id for edge in relationships if edge.from_id == term_id)
        enriched_refs = adapter.merge_related_refs(term_id, authored)
        for ref in enriched_refs:
            if ref in authored:
                continue
            edge = (term_id, ref, "catalog_related")
            existing.add(edge)
            relationships.append(RelationshipEdge(from_id=term_id, to_id=ref, kind="catalog_related"))

    return ContextKernel(
        terms=context_kernel.terms,
        guidance=context_kernel.guidance,
        relationships=tuple(relationships),
        alias_index=context_kernel.alias_index,
        certifications=context_kernel.certifications,
        persisted_certification_results=context_kernel.persisted_certification_results,
    )
