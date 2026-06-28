from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rdflib import Graph
from pyshacl import validate as pyshacl_validate

from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.ontology.claim import build_claim_graph
from recosearch.semantic_layers.ontology.types import OntologyKernel


def export_validation_report(
    binding: TermBinding,
    metric_id: str,
    kernel: OntologyKernel,
    *,
    claim_qualifiers: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    data_graph, claim_hash = build_claim_graph(
        binding,
        metric_id,
        kernel,
        claim_qualifiers=claim_qualifiers,
    )
    ontology_graph = Graph()
    ontology_graph.parse(data=kernel.ontology_ttl, format="turtle")
    shapes_graph = Graph()
    shapes_graph.parse(data=kernel.shapes_ttl, format="turtle")

    conforms, results_graph, results_text = pyshacl_validate(
        data_graph,
        shacl_graph=shapes_graph,
        ont_graph=ontology_graph,
        inference=kernel.reasoner_mode,
        advanced=True,
        allow_warnings=True,
    )

    merged = Graph()
    for graph in (ontology_graph, shapes_graph, data_graph):
        for triple in graph:
            merged.add(triple)
    if results_graph:
        for triple in results_graph:
            merged.add(triple)

    return {
        "claim_hash": claim_hash,
        "conforms": conforms,
        "ontology_hash": kernel.ontology_hash,
        "reasoner_mode": kernel.reasoner_mode,
        "validation_report_text": results_text or "",
        "turtle": merged.serialize(format="turtle"),
        "json_ld": merged.serialize(format="json-ld"),
    }


def write_ontology_export(out_path: Path | str, payload: dict[str, Any]) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".ttl":
        path.write_text(str(payload.get("turtle", "")), encoding="utf-8")
    elif path.suffix == ".jsonld":
        path.write_text(str(payload.get("json_ld", "")), encoding="utf-8")
    else:
        serializable = {k: v for k, v in payload.items() if k not in ("turtle", "json_ld")}
        path.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")
    return path
