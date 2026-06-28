from pathlib import Path

from recosearch.semantic_layers.context.facets import build_provenance_facets, discover_join_path_refs
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_provenance_facets_shape():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    binding = context_kernel.terms["term:novashop:revenue"]
    facets = build_provenance_facets(binding, metric_kernel, actor_role="analyst")
    assert facets.schema
    assert facets.data_source
    assert facets.semantic_metric is not None
    assert facets.certification_tier is not None
    assert facets.policy_decision is not None
    assert facets.policy_decision["allowed"] is True


def test_join_path_discovery_revenue_to_customer():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    binding = context_kernel.terms["term:novashop:revenue"]
    refs = discover_join_path_refs(binding, metric_kernel, context_kernel.relationships)
    assert "entity:novashop:customer" in refs or "relation:novashop:order_customer" in refs
