from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from recosearch.semantic_layers.metrics.loader import MetricKernel, _parse_freshness_sla, _parse_time_spine
from recosearch.semantic_layers.metrics.schema import MetricSchemaError, validate_certification_results

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


def _minimal_raw(**overrides) -> dict:
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
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ],
    }
    base.update(overrides)
    return base


def _write_yaml_dir(tmp_path: Path, name: str, content: str) -> Path:
    metrics_dir = tmp_path / name
    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / "kernel.yaml").write_text(content, encoding="utf-8")
    return metrics_dir


def test_from_dir_rejects_non_mapping_yaml(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "bad.yaml").write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        MetricKernel.from_dir(metrics_dir)


def test_from_dir_skips_null_list_sections(tmp_path):
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
""",
        encoding="utf-8",
    )
    (metrics_dir / "null_sections.yaml").write_text(
        """
entities: null
measures: null
metrics: null
certifications: null
""",
        encoding="utf-8",
    )
    kernel = MetricKernel.from_dir(metrics_dir)
    assert "metric:x:revenue" in kernel.metrics


def test_from_dir_rejects_non_list_section(tmp_path):
    metrics_dir = _write_yaml_dir(
        tmp_path,
        "metrics",
        """
metric_collections:
  id: global
""",
    )
    with pytest.raises(ValueError, match="metric_collections must be a list"):
        MetricKernel.from_dir(metrics_dir)


def test_from_dir_skips_null_rule_definitions(tmp_path):
    metrics_dir = _write_yaml_dir(
        tmp_path,
        "metrics",
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
rule_definitions: null
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
    kernel = MetricKernel.from_dir(metrics_dir)
    assert kernel.rule_definitions == {}


def test_from_dir_rejects_non_mapping_rule_definitions(tmp_path):
    metrics_dir = _write_yaml_dir(
        tmp_path,
        "metrics",
        """
rule_definitions: []
""",
    )
    with pytest.raises(ValueError, match="rule_definitions must be a mapping"):
        MetricKernel.from_dir(metrics_dir)


def test_from_dir_rejects_duplicate_time_spine(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    spine = """
time_spine:
  supported_grains: [day]
  period_macros: {}
"""
    (metrics_dir / "a.yaml").write_text(spine + "\nmetric_collections: []\n", encoding="utf-8")
    (metrics_dir / "b.yaml").write_text(spine + "\nmetric_collections: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate time_spine"):
        MetricKernel.from_dir(metrics_dir)


def test_from_dir_rejects_non_mapping_certification_results(tmp_path):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    (metrics_dir / "_certification_results.yaml").write_text("- bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        MetricKernel.from_dir(metrics_dir)


def test_from_contract_missing_metric_kernel():
    with pytest.raises(ValueError, match="contract missing metric_kernel"):
        MetricKernel.from_contract({})


def test_from_contract_invalid_metric_kernel_type():
    with pytest.raises(ValueError, match="metric_kernel must be a mapping"):
        MetricKernel.from_contract({"metric_kernel": []})


def test_from_raw_rejects_non_mapping_rule_definition(monkeypatch):
    monkeypatch.setattr("recosearch.semantic_layers.metrics.loader.validate_metric_kernel", lambda _raw: None)
    raw = _minimal_raw(rule_definitions={"active": "not-a-mapping"})
    with pytest.raises(ValueError, match="rule_definitions.active must be a mapping"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_duplicate_relation_id():
    raw = _minimal_raw(
        relations=[
            {
                "id": "relation:x:dup",
                "from_entity_id": "entity:x:order",
                "to_entity_id": "entity:x:order",
                "join_key": "order_id",
                "cardinality": "one_to_one",
            },
            {
                "id": "relation:x:dup",
                "from_entity_id": "entity:x:order",
                "to_entity_id": "entity:x:order",
                "join_key": "order_id",
                "cardinality": "one_to_one",
            },
        ]
    )
    with pytest.raises(ValueError, match="duplicate relation id"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_invalid_metric_kind(monkeypatch):
    monkeypatch.setattr("recosearch.semantic_layers.metrics.loader.validate_metric_kernel", lambda _raw: None)
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "kind": "ratio",
                "grain": "order",
            }
        ]
    )
    with pytest.raises(ValueError, match="invalid kind"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_measure_metric_requires_measure_id():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="requires measure_id"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_derived_metric_requires_formula():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "kind": "derived",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="requires formula"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_unknown_measure_in_formula():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "kind": "derived",
                "formula": "measure:missing:a + measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown measure"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_unknown_metric_in_formula():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "kind": "derived",
                "formula": "metric:missing:x / measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown metric"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_unknown_collection():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "missing",
                "measure_id": "measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown collection"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_unknown_dimension():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "measure_id": "measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": ["dimension:missing"],
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown dimension"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_unknown_filter_rule():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "measure_id": "measure:x:amount",
                "grain": "order",
                "filter_rules": ["missing_rule"],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown rule"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_incompatible_derived_grain():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:base",
                "display_name": "base",
                "collection_id": "global",
                "measure_id": "measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            },
            {
                "id": "metric:x:derived",
                "display_name": "derived",
                "collection_id": "global",
                "kind": "derived",
                "formula": "metric:x:base / measure:x:amount",
                "grain": "customer",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            },
        ]
    )
    with pytest.raises(ValueError, match="grain customer incompatible"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_unknown_entity_references():
    raw = _minimal_raw(
        measures=[
            {
                "id": "measure:x:amount",
                "entity_id": "entity:missing",
                "field": "total_amount",
                "aggregation": "sum",
            }
        ]
    )
    with pytest.raises(ValueError, match="references unknown entity"):
        MetricKernel.from_contract({"metric_kernel": raw})

    raw = _minimal_raw(
        dimensions=[
            {
                "id": "dimension:x:status",
                "entity_id": "entity:missing",
                "field": "status",
                "type": "categorical",
            }
        ],
        metrics=[
            {
                "id": "metric:x:revenue",
                "display_name": "revenue",
                "collection_id": "global",
                "measure_id": "measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ],
    )
    with pytest.raises(ValueError, match="references unknown entity"):
        MetricKernel.from_contract({"metric_kernel": raw})

    raw = _minimal_raw(
        relations=[
            {
                "id": "relation:x:bad",
                "from_entity_id": "entity:missing",
                "to_entity_id": "entity:x:order",
                "join_key": "order_id",
                "cardinality": "many_to_one",
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown from_entity"):
        MetricKernel.from_contract({"metric_kernel": raw})

    raw = _minimal_raw(
        relations=[
            {
                "id": "relation:x:bad",
                "from_entity_id": "entity:x:order",
                "to_entity_id": "entity:missing",
                "join_key": "order_id",
                "cardinality": "many_to_one",
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown to_entity"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_from_raw_rejects_certification_errors(monkeypatch):
    monkeypatch.setattr("recosearch.semantic_layers.metrics.loader.validate_metric_kernel", lambda _raw: None)
    raw = _minimal_raw(
        certifications=[
            {
                "metric_id": "metric:x:revenue",
                "definition_hash": "abc",
                "golden_questions": [],
            },
            {
                "metric_id": "metric:x:revenue",
                "definition_hash": "def",
                "golden_questions": [],
            },
        ]
    )
    with pytest.raises(ValueError, match="duplicate certification"):
        MetricKernel.from_contract({"metric_kernel": raw})

    raw = _minimal_raw(
        certifications=[
            {
                "metric_id": "metric:missing",
                "definition_hash": "abc",
                "golden_questions": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="unknown metric"):
        MetricKernel.from_contract({"metric_kernel": raw})

    raw = _minimal_raw(
        certifications=[
            {
                "metric_id": "metric:x:revenue",
                "definition_hash": "abc",
                "golden_questions": [{"term": "revenue", "expected": "not-a-mapping"}],
            }
        ]
    )
    with pytest.raises(ValueError, match="expected must be a mapping"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_detect_cycles_unknown_metric_reference(tmp_path):
    metrics_dir = _write_yaml_dir(
        tmp_path,
        "metrics",
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
  - id: metric:x:derived
    display_name: derived
    collection_id: global
    kind: derived
    formula: "metric:missing:ref / measure:x:amount"
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
    )
    with pytest.raises(ValueError, match="references unknown metric"):
        MetricKernel.from_dir(metrics_dir)


def test_to_dict_includes_deprecated_and_freshness_sla():
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:revenue",
                "display_name": "revenue",
                "collection_id": "global",
                "measure_id": "measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
                "deprecated": True,
                "superseded_by": "metric:x:successor",
                "freshness_sla": {"max_age_days": 7, "hard_sla": True},
            }
        ]
    )
    kernel = MetricKernel.from_contract({"metric_kernel": raw})
    payload = kernel.to_dict()
    metric = payload["metrics"][0]
    assert metric["deprecated"] is True
    assert metric["superseded_by"] == "metric:x:successor"
    assert metric["freshness_sla"] == {"max_age_days": 7, "hard_sla": True}


def test_apply_persisted_certification_results_rejects_bad_entry():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    with pytest.raises(ValueError, match="entries must be mappings"):
        kernel._apply_persisted_certification_results(["bad-entry"])


def test_with_certification_results_skips_unknown_metric_and_derives_golden_passed():
    kernel = MetricKernel.from_dir(METRICS_DIR)
    updated = kernel.with_certification_results(
        {
            "metric:missing": {"certified": True},
            "metric:novashop:order_revenue": {
                "certified": True,
                "golden_questions": [{"passed": True}, {"passed": False}],
            },
        }
    )
    cert = updated.certifications["metric:novashop:order_revenue"]
    assert cert.golden_passed is False


def test_parse_freshness_sla_errors():
    assert _parse_freshness_sla(None) is None
    with pytest.raises(ValueError, match="must be a mapping"):
        _parse_freshness_sla([])
    with pytest.raises(ValueError, match="requires max_age_days"):
        _parse_freshness_sla({})


def test_parse_time_spine_errors():
    assert _parse_time_spine(None) is None
    with pytest.raises(ValueError, match="must be a mapping"):
        _parse_time_spine([])
    with pytest.raises(ValueError, match="period_macros must be a mapping"):
        _parse_time_spine({"supported_grains": ["day"], "period_macros": []})


def test_from_raw_rejects_unknown_metric_in_formula_refs(monkeypatch):
    monkeypatch.setattr("recosearch.semantic_layers.metrics.loader._detect_cycles", lambda _metrics: None)
    raw = _minimal_raw(
        metrics=[
            {
                "id": "metric:x:bad",
                "display_name": "bad",
                "collection_id": "global",
                "kind": "derived",
                "formula": "metric:missing:ref / measure:x:amount",
                "grain": "order",
                "filter_rules": [],
                "allowed_dimension_ids": [],
            }
        ]
    )
    with pytest.raises(ValueError, match="references unknown metric"):
        MetricKernel.from_contract({"metric_kernel": raw})


def test_validate_certification_results_rejects_bad_schema():
    with pytest.raises(MetricSchemaError):
        validate_certification_results({"certification_results": "bad"})

    with pytest.raises(MetricSchemaError):
        validate_certification_results(
            {
                "certification_results": [
                    {
                        "metric_id": "metric:valid:id",
                        "definition_hash": "abc",
                        "certified": True,
                        "golden_passed": True,
                        "tool_version": "0.1.0",
                    }
                ]
            }
        )
