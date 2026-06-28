from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Mapping

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.metrics.types import MetricQuery
from recosearch.semantic_layers.ontology.hash import compute_claim_hash
from recosearch.semantic_layers.ontology.types import OntologyKernel

NS_BASE = "https://recosearch.example/ontology/ns#"


def _ns(kernel: OntologyKernel) -> Namespace:
    return Namespace(kernel.namespace or NS_BASE)


def _qualifier_map(claim_qualifiers: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {str(k): str(v) for k, v in claim_qualifiers}


def _revenue_iri(ns: Namespace, revenue_type: str) -> URIRef:
    return URIRef(ns[revenue_type])


def build_claim_graph(
    binding: TermBinding,
    metric_id: str,
    kernel: OntologyKernel,
    *,
    claim_qualifiers: tuple[tuple[str, str], ...] = (),
    reference_date: date | None = None,
) -> tuple[Graph, str]:
    mapping = kernel.mappings.get(binding.term_id)
    if mapping is None:
        raise ValueError(f"no ontology mapping for term: {binding.term_id}")

    ns = _ns(kernel)
    qualifiers = _qualifier_map(claim_qualifiers)
    period = qualifiers.get("period")
    if not period and reference_date is not None:
        period = reference_date.strftime("%Y-%m")

    payload = {
        "term_id": binding.term_id,
        "metric_id": metric_id,
        "revenue_type": mapping.revenue_type,
        "period": period or "",
        "refund_treatment": qualifiers.get("refund_treatment", ""),
        "recognition_status": qualifiers.get("recognition_status", ""),
        "reported_as": qualifiers.get("reported_as", ""),
    }
    claim_hash = compute_claim_hash(payload)
    claim_uri = URIRef(f"{ns}claim/{claim_hash}")

    graph = Graph()
    graph.bind("ns", ns)
    graph.add((claim_uri, RDF.type, ns[mapping.claim_class]))
    graph.add((claim_uri, ns.revenueType, _revenue_iri(ns, mapping.revenue_type)))
    graph.add((claim_uri, ns.termRef, Literal(binding.term_id)))
    graph.add((claim_uri, ns.metricRef, Literal(metric_id)))

    if period:
        graph.add((claim_uri, ns.period, Literal(period)))
    refund_treatment = qualifiers.get("refund_treatment")
    if refund_treatment:
        graph.add((claim_uri, ns.refundTreatment, Literal(refund_treatment)))
    recognition_status = qualifiers.get("recognition_status")
    if recognition_status:
        graph.add((claim_uri, ns.recognitionStatus, Literal(recognition_status)))
    reported_as = qualifiers.get("reported_as")
    if reported_as:
        graph.add((claim_uri, ns.reportedAs, _revenue_iri(ns, reported_as)))

    return graph, claim_hash


def claim_payload_for_cache(
    binding: TermBinding,
    metric_id: str,
    kernel: OntologyKernel,
    *,
    claim_qualifiers: tuple[tuple[str, str], ...] = (),
    reference_date: date | None = None,
) -> dict[str, Any]:
    mapping = kernel.mappings[binding.term_id]
    qualifiers = _qualifier_map(claim_qualifiers)
    period = qualifiers.get("period")
    if not period and reference_date is not None:
        period = reference_date.strftime("%Y-%m")
    return {
        "term_id": binding.term_id,
        "metric_id": metric_id,
        "revenue_type": mapping.revenue_type,
        "period": period or "",
        "refund_treatment": qualifiers.get("refund_treatment", ""),
        "recognition_status": qualifiers.get("recognition_status", ""),
        "reported_as": qualifiers.get("reported_as", ""),
        "ontology_hash": kernel.ontology_hash,
        "reasoner_mode": kernel.reasoner_mode,
    }
