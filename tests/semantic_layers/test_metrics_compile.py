from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics import (
    DimensionNotAllowed,
    MetricCompiler,
    MetricKernel,
    MetricQuery,
    MetricResolver,
)

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(scope="module")
def kernel() -> MetricKernel:
    return MetricKernel.from_dir(METRICS_DIR)


@pytest.fixture(scope="module")
def compiler(kernel: MetricKernel) -> MetricCompiler:
    return MetricCompiler(kernel)


@pytest.fixture(scope="module")
def order_revenue(kernel: MetricKernel):
    resolver = MetricResolver(kernel)
    return resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))


def test_compile_active_rule_adds_delivered_filter(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(order_revenue, ())
    assert "SUM(t0.total_amount) AS metric_value" in compiled.sql
    assert "FROM orders AS t0" in compiled.sql
    assert "WHERE t0.status = 'delivered'" in compiled.sql
    assert compiled.metric_refs == ("metric:novashop:order_revenue",)
    assert compiled.grain == "order"
    assert compiled.fallback_metric_refs == ()


def test_compile_with_dimension_group_by(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(order_revenue, ("dimension:novashop:order_status",))
    assert "SELECT t0.status, SUM(t0.total_amount) AS metric_value" in compiled.sql
    assert "GROUP BY t0.status" in compiled.sql


def test_compile_denies_disallowed_dimension(compiler: MetricCompiler, order_revenue):
    with pytest.raises(DimensionNotAllowed) as exc:
        compiler.compile(order_revenue, ("dimension:novashop:missing",))
    assert exc.value.metric_id == "metric:novashop:order_revenue"


def test_compile_fallback_metric_refs(compiler: MetricCompiler):
    resolver = MetricResolver(MetricKernel.from_dir(METRICS_DIR))
    resolved = resolver.resolve(MetricQuery(term="revenue", tenant="other_shop", industry="retail"))
    compiled = compiler.compile(resolved, ())
    assert compiled.fallback_metric_refs == ("metric:retail:generic_revenue",)
    assert compiled.plan.sql == compiled.sql


def test_compile_derived_avg_order_value(compiler: MetricCompiler, kernel: MetricKernel):
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="average order value", tenant="novashop"))
    compiled = compiler.compile(resolved, ())
    assert "SUM(t0.total_amount) / NULLIF(COUNT(t0.order_id), 0)" in compiled.sql
    assert "AS metric_value" in compiled.sql


def test_compile_derived_rejects_cycle(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "derived.yaml").write_text(
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
entities:
  - id: entity:x:order
    source_id: novashop
    table: orders
    primary_key: order_id
    time_field: order_date
measures:
  - id: measure:x:a
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
  - id: measure:x:b
    entity_id: entity:x:order
    field: order_id
    aggregation: count
metrics:
  - id: metric:x:a
    display_name: a
    collection_id: global
    kind: derived
    formula: "metric:x:b / measure:x:b"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:b
    display_name: b
    collection_id: global
    kind: derived
    formula: "metric:x:a / measure:x:a"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cycle"):
        MetricKernel.from_dir(metrics_dir)
