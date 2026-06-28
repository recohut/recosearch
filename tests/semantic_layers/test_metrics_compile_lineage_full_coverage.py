from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recosearch.semantic_layers.metrics import (
    MetricCompiler,
    MetricKernel,
    MetricQuery,
    MetricResolver,
    ReferenceDateRequired,
    TimeGrainNotSupported,
)
from recosearch.semantic_layers.metrics.compile import _agg_expr
from recosearch.semantic_layers.metrics.lineage import _join_plan_relation_edges, project_metric_lineage

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


def _kernel_yaml(tmp_path: Path, content: str) -> MetricKernel:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "kernel.yaml").write_text(content, encoding="utf-8")
    return MetricKernel.from_dir(metrics_dir)


def test_compile_nested_derived_metric_refs(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
  - id: measure:x:count
    entity_id: entity:x:order
    field: order_id
    aggregation: count
metrics:
  - id: metric:x:base
    display_name: base
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:inner
    display_name: inner
    collection_id: global
    kind: derived
    formula: "metric:x:base / measure:x:count"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:outer
    display_name: outer
    collection_id: global
    kind: derived
    formula: "metric:x:inner * measure:x:amount"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="outer"))
    compiled = compiler.compile(resolved, ())
    assert "metric_value" in compiled.sql


def test_compile_derived_without_resolvable_base_raises(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:empty
    display_name: empty
    collection_id: global
    kind: derived
    formula: "1 + 2"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="empty"))
    with pytest.raises(ValueError, match="no resolvable base entity"):
        compiler.compile(resolved, ())


def test_compile_derived_with_time_grain(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
  - id: measure:x:count
    entity_id: entity:x:order
    field: order_id
    aggregation: count
metrics:
  - id: metric:x:avg
    display_name: avg
    collection_id: global
    kind: derived
    formula: "measure:x:amount / measure:x:count"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
time_spine:
  supported_grains: [day]
  period_macros: {}
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="avg"))
    compiled = compiler.compile(resolved, (), time_grain="day")
    assert "time_bucket" in compiled.sql


def test_compile_reuses_existing_join_alias(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
    time_field: ""
  - id: entity:x:product
    source_id: novashop
    table: products
    primary_key: product_id
    time_field: ""
  - id: entity:x:brand
    source_id: novashop
    table: brands
    primary_key: brand_id
    time_field: ""
measures:
  - id: measure:x:amount
    entity_id: entity:x:order
    field: amount
    aggregation: sum
dimensions:
  - id: dimension:x:category
    entity_id: entity:x:product
    field: category
    type: categorical
  - id: dimension:x:brand_name
    entity_id: entity:x:brand
    field: name
    type: categorical
relations:
  - id: relation:x:order_product
    from_entity_id: entity:x:order
    to_entity_id: entity:x:product
    join_key: product_id
    cardinality: many_to_one
  - id: relation:x:product_brand
    from_entity_id: entity:x:product
    to_entity_id: entity:x:brand
    join_key: brand_id
    cardinality: many_to_one
metrics:
  - id: metric:x:total
    display_name: total
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids:
      - dimension:x:category
      - dimension:x:brand_name
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="total"))
    compiled = compiler.compile(resolved, ("dimension:x:category", "dimension:x:brand_name"))
    assert compiled.sql.count("JOIN products AS t1") == 1


def test_compile_rejects_non_mapping_rule_filter(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
rule_definitions:
  broken:
    filter: not-a-mapping
entities:
  - id: entity:x:order
    source_id: novashop
    table: orders
    primary_key: order_id
    time_field: order_date
measures:
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:revenue
    display_name: revenue
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: [broken]
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="revenue"))
    with pytest.raises(ValueError, match="filter must be a mapping"):
        compiler.compile(resolved, (), user_filters=(("status", "delivered"),))


def test_compile_applies_user_filters(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:revenue
    display_name: revenue
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="revenue"))
    compiled = compiler.compile(resolved, (), user_filters=(("status", "delivered"),))
    assert "t0.status = 'delivered'" in compiled.sql


def test_time_grain_expr_unsupported_without_spine(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:revenue
    display_name: revenue
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="revenue"))
    with pytest.raises(TimeGrainNotSupported):
        compiler.compile(resolved, (), time_grain="quarter")


def test_ref_to_sql_nested_derived_and_errors(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
  - id: measure:x:count
    entity_id: entity:x:order
    field: order_id
    aggregation: count
metrics:
  - id: metric:x:ratio
    display_name: ratio
    collection_id: global
    kind: derived
    formula: "measure:x:amount / measure:x:count"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:scaled
    display_name: scaled
    collection_id: global
    kind: derived
    formula: "metric:x:ratio * 2"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="scaled"))
    compiled = compiler.compile(resolved, ())
    assert "NULLIF" in compiled.sql

    shell = MagicMock(kind="derived", formula="", measure_id="")
    compiler._kernel = MagicMock(
        measures=kernel.measures,
        metrics={**dict(kernel.metrics), "metric:x:shell": shell},
    )
    with pytest.raises(ValueError, match="no measure"):
        compiler._ref_to_sql("metric:x:shell", "t0")

    with pytest.raises(ValueError, match="unknown formula ref"):
        compiler._ref_to_sql("entity:x:order", "t0")


def test_period_bounds_errors(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:revenue
    display_name: revenue
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
time_spine:
  supported_grains: [day]
  period_macros:
    custom_window:
      days: 7
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="revenue"))

    with pytest.raises(ReferenceDateRequired):
        compiler.compile(resolved, (), time_period="ytd")

    with pytest.raises(ValueError, match="unknown time period"):
        compiler.compile(resolved, (), time_period="missing", reference_date=date(2026, 1, 31))

    with pytest.raises(ValueError, match="unsupported period macro"):
        compiler.compile(resolved, (), time_period="custom_window", reference_date=date(2026, 1, 31))

    raw = kernel.to_dict()
    raw.pop("time_spine", None)
    no_spine_kernel = MetricKernel.from_contract({"metric_kernel": raw})
    compiler_no_spine = MetricCompiler(no_spine_kernel)
    with pytest.raises(ValueError, match="time spine not configured"):
        compiler_no_spine._period_bounds("ytd", date(2026, 1, 31))


def test_agg_expr_rejects_unsupported_aggregation():
    with pytest.raises(ValueError, match="unsupported aggregation"):
        _agg_expr("MEDIAN", "t0", "amount")


def test_join_plan_relation_edges_skips_blank_and_duplicate_relation_ids():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    edges = _join_plan_relation_edges(
        kernel,
        [
            {"relation_id": ""},
            {"relation_id": "relation:novashop:order_product"},
            {"relation_id": "relation:novashop:order_product"},
        ],
    )
    relation_edges = [edge for edge in edges if edge.from_id == "relation:novashop:order_product"]
    assert len(relation_edges) == 2


def test_project_metric_lineage_includes_time_field_edge():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    resolver = MetricResolver(kernel)
    compiler = MetricCompiler(kernel)
    resolved = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    compiled = compiler.compile(resolved, (), time_grain="month", reference_date=date(2026, 1, 31))
    edges = project_metric_lineage(kernel, resolved, compiled.column_lineage)
    assert any(
        edge.from_id == resolved.metric_id
        and edge.kind == "reads_column"
        and edge.to_id == "novashop.orders.order_date"
        for edge in edges
    )


def test_compile_revenue_per_customer_nested_lineage():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(
        MetricQuery(term="metric:novashop:revenue_per_customer", tenant="novashop")
    )
    compiled = compiler.compile(resolved, ())
    edges = project_metric_lineage(kernel, resolved, compiled.column_lineage)
    assert compiled.sql
    assert edges


def test_compile_derived_via_measure_kind_metric_ref_only(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
  - id: measure:x:count
    entity_id: entity:x:order
    field: order_id
    aggregation: count
metrics:
  - id: metric:x:count_metric
    display_name: count metric
    collection_id: global
    measure_id: measure:x:count
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:scaled
    display_name: scaled
    collection_id: global
    kind: derived
    formula: "metric:x:count_metric * 2"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="scaled"))
    compiled = compiler.compile(resolved, ())
    assert "COUNT(t0.order_id)" in compiled.sql


def test_compile_doubly_nested_derived_metric_ref(tmp_path):
    kernel = _kernel_yaml(
        tmp_path,
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
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:base
    display_name: base
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:wrap
    display_name: wrap
    collection_id: global
    kind: derived
    formula: "metric:x:base"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
  - id: metric:x:outer
    display_name: outer
    collection_id: global
    kind: derived
    formula: "metric:x:wrap"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="outer"))
    compiled = compiler.compile(resolved, ())
    assert "SUM(t0.total_amount)" in compiled.sql
