from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics import ClarifyRequest, MetricKernel, MetricQuery, MetricResolver

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(scope="module")
def resolver() -> MetricResolver:
    return MetricResolver(MetricKernel.from_dir(METRICS_DIR))


def test_resolve_exact_metric_id(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    assert result.metric_id == "metric:novashop:order_revenue"
    assert result.fallback_used is False
    assert result.caveat_codes == ()


def test_resolve_display_name_case_insensitive(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="Order Revenue", tenant="novashop"))
    assert result.metric_id == "metric:novashop:order_revenue"
    assert result.fallback_used is False


def test_resolve_synonym_in_tenant_collection(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="order income", tenant="novashop"))
    assert result.metric_id == "metric:novashop:order_revenue"


def test_resolve_industry_fallback_when_tenant_has_no_match(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="revenue", tenant="other_shop", industry="retail"))
    assert result.metric_id == "metric:retail:generic_revenue"
    assert result.collection.collection_id == "retail_industry"
    assert result.fallback_used is True
    assert result.caveat_codes == ("fallback_metric",)


def test_resolve_global_fallback(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="revenue", tenant="other_shop"))
    assert result.metric_id == "metric:global:revenue"
    assert result.collection.collection_id == "global"
    assert result.fallback_used is True
    assert result.caveat_codes == ("fallback_metric",)


def test_resolve_unknown_term_returns_clarify(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="churn rate", tenant="novashop"))
    assert isinstance(result, ClarifyRequest)
    assert result.reason == "unknown metric"
    assert result.requested_term == "churn rate"
    assert "metric:novashop:order_revenue" in result.available_metrics


def test_resolve_ambiguous_same_collection(tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    (metrics_dir / "ambiguous.yaml").write_text(
        """
metrics:
  - id: metric:novashop:alt_sales
    display_name: alt sales
    synonyms:
      - sales
    collection_id: novashop_custom
    measure_id: measure:novashop:total_amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
        encoding="utf-8",
    )
    resolver = MetricResolver(MetricKernel.from_dir(metrics_dir))
    result = resolver.resolve(MetricQuery(term="sales", tenant="novashop"))
    assert isinstance(result, ClarifyRequest)
    assert result.reason == "ambiguous metric"
    assert len(result.candidates) == 2


def test_resolve_tenant_beats_industry_no_ambiguity(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="revenue", tenant="novashop"))
    assert result.metric_id == "metric:novashop:order_revenue"
    assert result.fallback_used is False


def test_resolve_surfaces_governance_fields(resolver: MetricResolver):
    result = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    assert result.version == "1.0.0"
    assert result.definition_hash == "0e66426cb4be77f6"
    assert result.status == "certified"
