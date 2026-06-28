from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.context.loader import ContextKernel
from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.metrics.loader import MetricKernel

OSI_EXPORT_VERSION = "1.0.0"


def export_context_cards(
    context_kernel: ContextKernel,
    metric_kernel: MetricKernel,
    *,
    contract_hash: str = "",
) -> dict[str, Any]:
    """Open interchange export: glossary + OpenLineage facets + trust."""
    cards: list[dict[str, Any]] = []
    for binding in sorted(context_kernel.terms.values(), key=lambda t: t.term_id):
        card = build_context_card(
            binding,
            context_kernel,
            metric_kernel,
            contract_hash=contract_hash,
        )
        entry = card.to_dict()
        entry["osi_version"] = OSI_EXPORT_VERSION
        entry["openlineage_facets"] = {
            "schema": card.technical.get("schema", []),
            "columnLineage": card.technical.get("column_lineage", []),
            "ownership": card.operational.get("owners", []),
            "dataSource": card.technical.get("data_source", []),
            "semanticMetric": card.semantic.get("semantic_metric"),
            "policyDecision": card.technical.get("policy_decision"),
            "certificationTier": card.operational.get("certification"),
            "whyProvenance": card.semantic.get("why_provenance", []),
        }
        cards.append(entry)

    return {
        "osi_version": OSI_EXPORT_VERSION,
        "contract_hash": contract_hash,
        "glossary": [
            {
                "term_id": t.term_id,
                "display_name": t.display_name,
                "definition": t.definition,
                "aliases": list(t.aliases),
            }
            for t in sorted(context_kernel.terms.values(), key=lambda t: t.term_id)
        ],
        "context_cards": cards,
    }


def write_osi_export(
    path: Path | str,
    payload: dict[str, Any],
) -> Path:
    out = Path(path)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out


def validate_osi_export(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("osi_version") != OSI_EXPORT_VERSION:
        errors.append("invalid osi_version")
    if "glossary" not in payload or "context_cards" not in payload:
        errors.append("missing glossary or context_cards")
    return errors
