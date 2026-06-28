from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import MetricKernel, MetricQuery
from recosearch.semantic_layers.pipeline import execute_metric_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(autouse=True)
def _clear_ledger():
    ledger.clear()
    yield
    ledger.clear()


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_pipeline_clarifies_disallowed_dimension(contract):
    answer = execute_metric_query(
        MetricQuery(
            term="order revenue",
            tenant="novashop",
            dimensions=("dimension:novashop:customer_name",),
            reference_date=date(2026, 1, 31),
        ),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert "dimension:novashop:customer_name not allowed" in answer.reason


def test_pipeline_clarifies_unsupported_time_grain(contract):
    answer = execute_metric_query(
        MetricQuery(
            term="order revenue",
            tenant="novashop",
            time_grain="quarter",
            reference_date=date(2026, 1, 31),
        ),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert "time grain quarter not supported" in answer.reason


def test_pipeline_refuses_fanout_with_reason_code(tmp_path):
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
    base_contract = compile_contract()
    contract = dict(base_contract)
    contract["metric_kernel"] = MetricKernel.from_dir(metrics_dir).to_dict()

    answer = execute_metric_query(
        MetricQuery(term="total", dimensions=("dimension:x:child_name",)),
        contract=contract,
    )
    assert answer.decision == "refuse"
    assert answer.reason_code == "METRIC_FANOUT_BLOCKED"
    assert "fanout join relation:x:parent_child" in answer.reason
