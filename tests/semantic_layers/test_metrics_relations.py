from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics import FanoutNotAllowed, MetricCompiler, MetricKernel, MetricQuery, MetricResolver

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


def test_compile_join_for_product_category(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(order_revenue, ("dimension:novashop:product_category",))
    assert "JOIN products AS t1" in compiled.sql
    assert "ON t0.product_id = t1.product_id" in compiled.sql
    assert "t1.category" in compiled.sql
    assert compiled.plan.relation_path
    assert compiled.plan.relation_path[0]["relation_id"] == "relation:novashop:order_product"


def test_compile_two_hop_join(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "two_hop.yaml").write_text(
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
      - dimension:x:brand_name
""",
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    compiler = MetricCompiler(kernel)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="total"))
    compiled = compiler.compile(resolved, ("dimension:x:brand_name",))
    assert "JOIN products AS t1" in compiled.sql
    assert "JOIN brands AS t2" in compiled.sql
    assert "t2.name" in compiled.sql
    assert len(compiled.plan.relation_path) == 2


def test_compile_raises_when_no_relation_path(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "no_path.yaml").write_text(
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
  - id: entity:x:orphan
    source_id: novashop
    table: orphans
    primary_key: orphan_id
    time_field: ""
measures:
  - id: measure:x:amount
    entity_id: entity:x:order
    field: amount
    aggregation: sum
dimensions:
  - id: dimension:x:orphan_name
    entity_id: entity:x:orphan
    field: name
    type: categorical
metrics:
  - id: metric:x:total
    display_name: total
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids:
      - dimension:x:orphan_name
""",
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    compiler = MetricCompiler(kernel)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="total"))
    with pytest.raises(ValueError, match="no relation path"):
        compiler.compile(resolved, ("dimension:x:orphan_name",))


def test_compile_chooses_deterministic_shortest_path(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "tie_break.yaml").write_text(
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
entities:
  - id: entity:x:a
    source_id: novashop
    table: a
    primary_key: a_id
    time_field: ""
  - id: entity:x:b
    source_id: novashop
    table: b
    primary_key: b_id
    time_field: ""
  - id: entity:x:c
    source_id: novashop
    table: c
    primary_key: c_id
    time_field: ""
  - id: entity:x:d
    source_id: novashop
    table: d
    primary_key: d_id
    time_field: ""
measures:
  - id: measure:x:amount
    entity_id: entity:x:a
    field: amount
    aggregation: sum
dimensions:
  - id: dimension:x:d_name
    entity_id: entity:x:d
    field: name
    type: categorical
relations:
  - id: relation:x:b_path
    from_entity_id: entity:x:a
    to_entity_id: entity:x:b
    join_key: b_id
    cardinality: many_to_one
  - id: relation:x:c_path
    from_entity_id: entity:x:a
    to_entity_id: entity:x:c
    join_key: c_id
    cardinality: many_to_one
  - id: relation:x:b_to_d
    from_entity_id: entity:x:b
    to_entity_id: entity:x:d
    join_key: d_id
    cardinality: many_to_one
  - id: relation:x:c_to_d
    from_entity_id: entity:x:c
    to_entity_id: entity:x:d
    join_key: d_id
    cardinality: many_to_one
metrics:
  - id: metric:x:total
    display_name: total
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids:
      - dimension:x:d_name
""",
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    compiler = MetricCompiler(kernel)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="total"))
    compiled = compiler.compile(resolved, ("dimension:x:d_name",))
    relation_ids = [step["relation_id"] for step in compiled.plan.relation_path]
    assert relation_ids == ["relation:x:b_path", "relation:x:b_to_d"]


def test_compile_blocks_multi_hop_fanout(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "multi_hop_fanout.yaml").write_text(
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
entities:
  - id: entity:x:parent
    source_id: novashop
    table: parents
    primary_key: parent_id
    time_field: ""
  - id: entity:x:middle
    source_id: novashop
    table: middles
    primary_key: middle_id
    time_field: ""
  - id: entity:x:child
    source_id: novashop
    table: children
    primary_key: child_id
    time_field: ""
measures:
  - id: measure:x:amount
    entity_id: entity:x:parent
    field: amount
    aggregation: sum
dimensions:
  - id: dimension:x:child_name
    entity_id: entity:x:child
    field: name
    type: categorical
relations:
  - id: relation:x:parent_middle
    from_entity_id: entity:x:parent
    to_entity_id: entity:x:middle
    join_key: parent_id
    cardinality: many_to_one
  - id: relation:x:middle_child
    from_entity_id: entity:x:middle
    to_entity_id: entity:x:child
    join_key: middle_id
    cardinality: one_to_many
metrics:
  - id: metric:x:total
    display_name: total
    collection_id: global
    measure_id: measure:x:amount
    grain: parent
    filter_rules: []
    allowed_dimension_ids:
      - dimension:x:child_name
""",
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    compiler = MetricCompiler(kernel)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="total"))
    with pytest.raises(FanoutNotAllowed) as exc:
        compiler.compile(resolved, ("dimension:x:child_name",))
    assert exc.value.relation_id == "relation:x:middle_child"


def test_compile_blocks_one_to_many_fanout(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "fanout.yaml").write_text(
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
entities:
  - id: entity:x:parent
    source_id: novashop
    table: parents
    primary_key: parent_id
    time_field: ""
  - id: entity:x:child
    source_id: novashop
    table: children
    primary_key: child_id
    time_field: ""
measures:
  - id: measure:x:amount
    entity_id: entity:x:parent
    field: amount
    aggregation: sum
dimensions:
  - id: dimension:x:child_name
    entity_id: entity:x:child
    field: name
    type: categorical
relations:
  - id: relation:x:parent_child
    from_entity_id: entity:x:parent
    to_entity_id: entity:x:child
    join_key: parent_id
    cardinality: one_to_many
metrics:
  - id: metric:x:total
    display_name: total
    collection_id: global
    measure_id: measure:x:amount
    grain: parent
    filter_rules: []
    allowed_dimension_ids:
      - dimension:x:child_name
""",
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    compiler = MetricCompiler(kernel)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="total"))
    with pytest.raises(FanoutNotAllowed) as exc:
        compiler.compile(resolved, ("dimension:x:child_name",))
    assert exc.value.metric_id == "metric:x:total"
