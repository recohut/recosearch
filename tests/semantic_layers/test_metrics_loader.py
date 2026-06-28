from pathlib import Path
import shutil

import pytest

from recosearch.semantic_layers.metrics import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


def test_metric_kernel_from_dir_loads_collections_entities_metrics():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    assert len(kernel.collections) == 3
    assert "novashop_custom" in kernel.collections
    assert kernel.collections["novashop_custom"].priority == 100
    assert "entity:novashop:order" in kernel.entities
    assert "measure:novashop:total_amount" in kernel.measures
    assert "dimension:novashop:order_status" in kernel.dimensions
    assert "metric:novashop:order_revenue" in kernel.metrics


def test_metric_kernel_rule_definitions_active_maps_to_delivered():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    active = kernel.rule_definitions["active"]
    assert active["filter"]["status"] == "delivered"


def test_metric_kernel_to_dict_round_trip():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    restored = MetricKernel.from_contract({"metric_kernel": kernel.to_dict()})
    assert set(restored.metrics) == set(kernel.metrics)
    assert restored.metrics["metric:novashop:order_revenue"].display_name == "order revenue"


def test_metric_kernel_rejects_unknown_measure_reference():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    raw = kernel.to_dict()
    raw["metrics"].append(
        {
            "id": "metric:bad:missing_measure",
            "display_name": "bad",
            "collection_id": "global",
            "measure_id": "measure:missing",
            "grain": "order",
            "filter_rules": [],
            "allowed_dimension_ids": [],
        }
    )
    with pytest.raises(ValueError, match="unknown measure"):
        MetricKernel.from_contract({"metric_kernel": raw})


@pytest.mark.parametrize(
    "duplicate_yaml",
    [
        "metric_collections:\n  - id: novashop_custom\n    priority: 1\n    scope: {}\n",
        "entities:\n  - id: entity:novashop:order\n    source_id: novashop\n    table: orders\n    primary_key: order_id\n    time_field: order_date\n",
        "measures:\n  - id: measure:novashop:total_amount\n    entity_id: entity:novashop:order\n    field: total_amount\n    aggregation: sum\n",
        "dimensions:\n  - id: dimension:novashop:order_status\n    entity_id: entity:novashop:order\n    field: status\n    type: categorical\n",
        "metrics:\n  - id: metric:novashop:order_revenue\n    display_name: order revenue\n    collection_id: novashop_custom\n    measure_id: measure:novashop:total_amount\n    grain: order\n    filter_rules: []\n    allowed_dimension_ids: []\n",
        "rule_definitions:\n  active:\n    filter:\n      status: delivered\n",
    ],
)
def test_metric_kernel_from_dir_rejects_duplicate_ids(tmp_path, duplicate_yaml):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    (metrics_dir / "zz_duplicate.yaml").write_text(duplicate_yaml, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        MetricKernel.from_dir(metrics_dir)


def test_metric_kernel_internal_maps_are_read_only():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    with pytest.raises(TypeError):
        kernel.metrics["metric:new"] = kernel.metrics["metric:novashop:order_revenue"]  # type: ignore[index]
