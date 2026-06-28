from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics import MetricCompiler, MetricKernel, MetricQuery, MetricResolver, project_kernel_lineage, project_metric_lineage

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(scope="module")
def kernel() -> MetricKernel:
    return MetricKernel.from_dir(METRICS_DIR)


def test_project_kernel_lineage_reaches_columns(kernel: MetricKernel):
    edges = project_kernel_lineage(kernel)
    kinds = {e.kind for e in edges}
    assert "uses_measure" in kinds
    assert "reads_column" in kinds
    column_targets = {e.to_id for e in edges if e.kind == "reads_column"}
    assert "novashop.orders.total_amount" in column_targets


def test_project_kernel_lineage_includes_relation_join_columns(kernel: MetricKernel):
    edges = project_kernel_lineage(kernel)
    relation_edges = [e for e in edges if e.from_id == "relation:novashop:order_product"]
    targets = {e.to_id for e in relation_edges}
    assert "novashop.orders.product_id" in targets
    assert "novashop.products.product_id" in targets


def test_project_metric_lineage_matches_compile(kernel: MetricKernel):
    resolver = MetricResolver(kernel)
    compiler = MetricCompiler(kernel)
    resolved = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    compiled = compiler.compile(resolved, ())
    edges = project_metric_lineage(kernel, resolved, compiled.column_lineage)
    assert any(e.kind == "uses_measure" and e.from_id == resolved.metric_id for e in edges)
    assert any(e.to_id == "novashop.orders.total_amount" for e in edges)


def test_project_metric_lineage_includes_relation_for_product_category(kernel: MetricKernel):
    resolver = MetricResolver(kernel)
    compiler = MetricCompiler(kernel)
    resolved = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    compiled = compiler.compile(resolved, ("dimension:novashop:product_category",))
    edges = project_metric_lineage(
        kernel, resolved, compiled.column_lineage, join_plan=compiled.plan.relation_path
    )
    relation_edges = [e for e in edges if e.from_id == "relation:novashop:order_product"]
    targets = {e.to_id for e in relation_edges}
    assert "novashop.orders.product_id" in targets
    assert "novashop.products.product_id" in targets


def test_project_metric_lineage_derived_avg_order_value_components(kernel: MetricKernel):
    resolver = MetricResolver(kernel)
    compiler = MetricCompiler(kernel)
    resolved = resolver.resolve(MetricQuery(term="average order value", tenant="novashop"))
    compiled = compiler.compile(resolved, ())
    edges = project_metric_lineage(kernel, resolved, compiled.column_lineage)
    assert any(
        e.kind == "uses_measure"
        and e.from_id == "metric:novashop:avg_order_value"
        and e.to_id == "measure:novashop:total_amount"
        for e in edges
    )
    assert any(
        e.kind == "uses_measure"
        and e.from_id == "metric:novashop:avg_order_value"
        and e.to_id == "measure:novashop:order_count"
        for e in edges
    )
    assert any(e.to_id == "novashop.orders.total_amount" for e in edges)
    assert any(e.to_id == "novashop.orders.order_id" for e in edges)
