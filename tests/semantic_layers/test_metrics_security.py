from pathlib import Path

import pytest

from recosearch.semantic_layers.compiler import _check_identifier
from recosearch.semantic_layers.metrics import MetricCompiler, MetricKernel, MetricQuery, MetricResolver
from recosearch.semantic_layers.metrics.freshness import query_max_time_field
from recosearch.semantic_layers.metrics.schema import MetricSchemaError, validate_metric_kernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


def _minimal_kernel(**overrides) -> dict:
    base = {
        "version": 1,
        "metric_collections": [{"id": "global", "priority": 10, "scope": {}}],
        "entities": [
            {
                "id": "entity:x:order",
                "source_id": "novashop",
                "table": "orders",
                "primary_key": "order_id",
                "time_field": "order_date",
            }
        ],
        "measures": [
            {
                "id": "measure:x:amount",
                "entity_id": "entity:x:order",
                "field": "total_amount",
                "aggregation": "sum",
            }
        ],
        "metrics": [
            {
                "id": "metric:x:revenue",
                "display_name": "revenue",
                "collection_id": "global",
                "measure_id": "measure:x:amount",
                "grain": "order",
            }
        ],
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "value,kind",
    [
        ("orders; DROP TABLE x", "table"),
        ("1invalid", "column"),
        ("total amount", "column"),
        ("bad key", "column"),
    ],
)
def test_check_identifier_rejects_unsafe_tokens(value, kind):
    with pytest.raises(ValueError, match="invalid"):
        _check_identifier(value, kind)


def test_schema_rejects_invalid_entity_id_pattern():
    raw = _minimal_kernel(
        entities=[
            {
                "id": "bad entity id",
                "source_id": "novashop",
                "table": "orders",
                "primary_key": "order_id",
                "time_field": "order_date",
            }
        ]
    )
    with pytest.raises(MetricSchemaError):
        validate_metric_kernel(raw)


def test_compile_rejects_unsafe_table_name(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "unsafe.yaml").write_text(
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
entities:
  - id: entity:x:order
    source_id: novashop
    table: "orders; DROP TABLE x"
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
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    compiler = MetricCompiler(kernel)
    resolved = MetricResolver(kernel).resolve(MetricQuery(term="revenue"))
    with pytest.raises(ValueError, match="invalid"):
        compiler.compile(resolved, ())


def test_loader_rejects_derived_formula_with_function(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "bad_formula.yaml").write_text(
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
  - id: metric:x:bad
    display_name: bad
    collection_id: global
    kind: derived
    formula: "SUM(measure:x:amount)"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="functions"):
        MetricKernel.from_dir(metrics_dir)


def test_query_max_time_field_rejects_unsafe_table_name():
    import duckdb

    from recosearch.semantic_layers.adapters.duckdb import ADAPTER
    from recosearch.semantic_layers.metrics.types import Entity

    entity = Entity(
        entity_id="entity:test:order",
        source_id="test",
        table="orders; DROP TABLE x",
        primary_key="order_id",
        time_field="order_date",
    )

    connection = duckdb.connect(":memory:")
    with pytest.raises(ValueError, match="invalid"):
        query_max_time_field(ADAPTER, connection, entity, dialect="duckdb")
    connection.close()


def test_novashop_fixture_has_no_identifier_violations():
    MetricKernel.from_dir(METRICS_DIR)
