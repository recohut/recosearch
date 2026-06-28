from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics.schema import (
    MetricSchemaError,
    validate_metric_kernel,
    validate_scenario_config,
    validate_source_config,
)

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


def test_validate_metric_kernel_accepts_novashop_fixture():
    from recosearch.semantic_layers.metrics import MetricKernel

    MetricKernel.from_dir(METRICS_DIR)


def test_validate_metric_kernel_rejects_missing_required_field():
    raw = _minimal_kernel()
    del raw["metrics"][0]["grain"]
    with pytest.raises(MetricSchemaError) as exc:
        validate_metric_kernel(raw)
    assert exc.value.field
    assert exc.value.reason
    assert "metrics" in exc.value.path


def test_validate_metric_kernel_rejects_unknown_cardinality():
    raw = _minimal_kernel(
        relations=[
            {
                "id": "relation:x:bad",
                "from_entity_id": "entity:x:order",
                "to_entity_id": "entity:x:order",
                "join_key": "order_id",
                "cardinality": "invalid",
            }
        ]
    )
    with pytest.raises(MetricSchemaError) as exc:
        validate_metric_kernel(raw)
    assert "invalid" in exc.value.reason


def test_validate_source_config_accepts_fixture():
    import yaml

    raw = yaml.safe_load((ROOT / "semantic" / "source_config.yaml").read_text(encoding="utf-8"))
    validate_source_config(raw)


def test_validate_scenario_config_accepts_fixture():
    import yaml

    raw = yaml.safe_load((ROOT / "semantic" / "scenario_config.yaml").read_text(encoding="utf-8"))
    validate_scenario_config(raw)
