from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics import MetricKernel, compute_definition_hash

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


def test_definition_hash_stable_for_order_revenue():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    metric = kernel.metrics["metric:novashop:order_revenue"]
    assert metric.definition_hash == "0e66426cb4be77f6"
    assert len(metric.definition_hash) == 16


def test_definition_hash_changes_when_definition_changes():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    raw = kernel.to_dict()
    metric = next(m for m in raw["metrics"] if m["id"] == "metric:novashop:order_revenue")
    original_hash = compute_definition_hash(metric)
    metric["grain"] = "transaction"
    changed_hash = compute_definition_hash(metric)
    assert original_hash != changed_hash


def test_deprecated_metric_requires_superseded_by(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "base.yaml").write_text(
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
    deprecated: true
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="superseded_by"):
        MetricKernel.from_dir(metrics_dir)


def test_invalid_status_rejected(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "base.yaml").write_text(
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
    status: bogus
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid status"):
        MetricKernel.from_dir(metrics_dir)


def test_order_revenue_has_governance_fields():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    metric = kernel.metrics["metric:novashop:order_revenue"]
    assert metric.owners == ("team:novashop-analytics", "team:novashop-finance")
    assert metric.version == "1.0.0"
    assert metric.status == "certified"
    assert metric.certification_tier == "golden"
