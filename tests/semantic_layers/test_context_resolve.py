from pathlib import Path

from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.context.resolve import ContextResolver
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def _resolver() -> ContextResolver:
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    return ContextResolver(context_kernel, metric_kernel)


def test_resolve_exact_term_id():
    resolution = _resolver().resolve(
        ContextQuery(term="term:novashop:revenue", tenant="novashop")
    )
    assert resolution.decision == "resolved"
    assert resolution.term_id == "term:novashop:revenue"


def test_resolve_alias_revenue():
    resolution = _resolver().resolve(ContextQuery(term="sales", tenant="novashop"))
    assert resolution.decision == "resolved"
    assert resolution.term_id == "term:novashop:revenue"


def test_resolve_unknown_term():
    resolution = _resolver().resolve(ContextQuery(term="widget flux", tenant="novashop"))
    assert resolution.decision == "unknown"


def test_tenant_beats_global_for_revenue():
    resolution = _resolver().resolve(ContextQuery(term="revenue", tenant="novashop"))
    assert resolution.decision == "resolved"
    assert resolution.term_id == "term:novashop:revenue"


def test_ambiguous_same_scope(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "dup.yaml").write_text(
        """
terms:
  - id: term:novashop:rev_a
    display_name: revenue
    definition: a
    collection_id: novashop_custom
    primary_refs: [metric:novashop:order_revenue]
  - id: term:novashop:rev_b
    display_name: revenue
    definition: b
    collection_id: novashop_custom
    primary_refs: [metric:novashop:gross_revenue]
guidance:
  - term_id: term:novashop:rev_a
    when_to_use: u
    when_to_clarify: c
    when_to_refuse: r
  - term_id: term:novashop:rev_b
    when_to_use: u
    when_to_clarify: c
    when_to_refuse: r
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(tmp_path, metric_kernel=metric_kernel)
    resolver = ContextResolver(context_kernel, metric_kernel)
    resolution = resolver.resolve(ContextQuery(term="revenue", tenant="novashop"))
    assert resolution.decision == "clarify"
    assert len(resolution.candidates) == 2
