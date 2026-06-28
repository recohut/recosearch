from pathlib import Path

from recosearch.semantic_layers.context.export import export_context_cards, validate_osi_export
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


def test_osi_export_round_trip():
    metric_kernel = MetricKernel.from_dir(ROOT / "semantic" / "metrics")
    context_kernel = load_context_kernel(ROOT / "semantic", metric_kernel=metric_kernel)
    payload = export_context_cards(context_kernel, metric_kernel, contract_hash="abc123")
    assert validate_osi_export(payload) == []
    assert len(payload["glossary"]) >= 6
    assert payload["context_cards"][0]["openlineage_facets"]["schema"] is not None
    revenue_cards = [c for c in payload["context_cards"] if c["term_id"] == "term:novashop:revenue"]
    assert revenue_cards
    assert revenue_cards[0]["semantic"].get("why_provenance") is not None
    facets = revenue_cards[0]["openlineage_facets"]
    assert facets["policyDecision"] is not None
    assert facets["whyProvenance"] is not None
