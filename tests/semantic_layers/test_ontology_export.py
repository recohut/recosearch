from __future__ import annotations

from pathlib import Path

from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.export import export_validation_report, write_ontology_export
from recosearch.semantic_layers.ontology.loader import load_ontology_kernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_export_validation_report(tmp_path):
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    ontology_kernel = load_ontology_kernel(SEMANTIC, context_kernel=context_kernel)
    binding = context_kernel.terms["term:novashop:revenue"]
    payload = export_validation_report(
        binding,
        "metric:novashop:order_revenue",
        ontology_kernel,
        claim_qualifiers=(("period", "2026-01"),),
    )
    assert payload["claim_hash"].startswith("claim-")
    assert "turtle" in payload
    assert "json_ld" in payload
    out = write_ontology_export(tmp_path / "report.ttl", payload)
    assert out.exists()
    assert "@prefix" in out.read_text(encoding="utf-8")
