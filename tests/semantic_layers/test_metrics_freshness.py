from datetime import date
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import (
    FreshnessSLA,
    MetricKernel,
    MetricQuery,
    assess_freshness,
    check_freshness,
    resolve_freshness_sla,
)
from recosearch.semantic_layers.metrics.freshness import query_max_time_field
from recosearch.semantic_layers.pipeline import execute_metric_query
from recosearch.semantic_layers.sources import resolve_source

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


def test_resolve_freshness_sla_prefers_metric_override(contract):
    kernel = MetricKernel.from_contract(contract)
    metric = kernel.metrics["metric:novashop:order_revenue"]
    source_cfg = contract["sources"]["novashop"]
    metric_with_sla = replace(metric, freshness_sla=FreshnessSLA(max_age_days=7, hard_sla=True))
    sla = resolve_freshness_sla(source_cfg, metric_with_sla)
    assert sla is not None
    assert sla.max_age_days == 7
    assert sla.hard_sla is True


def test_check_freshness_marks_stale_when_age_exceeds_sla():
    result = check_freshness(
        max_data_date=date(2026, 1, 1),
        reference_date=date(2026, 2, 15),
        sla=FreshnessSLA(max_age_days=30, hard_sla=False),
    )
    assert result.is_stale is True
    assert result.age_days == 45


def test_query_max_time_field_reads_latest_order_date(contract):
    kernel = MetricKernel.from_contract(contract)
    entity = kernel.entities["entity:novashop:order"]
    adapter, connection, _ = resolve_source("novashop", contract)
    max_date = query_max_time_field(adapter, connection, entity, dialect="duckdb")
    assert max_date == date(2026, 1, 12)


def test_pipeline_soft_stale_adds_caveat(tmp_path, contract):
    import shutil

    semantic = tmp_path / "semantic"
    shutil.copytree(ROOT / "semantic", semantic)
    source_cfg = yaml.safe_load((semantic / "source_config.yaml").read_text(encoding="utf-8"))
    source_cfg["sources"]["novashop"]["freshness"] = {"max_age_days": 30, "hard_sla": False}
    (semantic / "source_config.yaml").write_text(yaml.safe_dump(source_cfg), encoding="utf-8")
    stale_contract = compile_contract(semantic)

    answer = execute_metric_query(
        MetricQuery(term="order revenue", tenant="novashop", reference_date=date(2026, 6, 27)),
        contract=stale_contract,
    )
    assert answer.decision == "answer"
    assert "stale_data" in answer.caveats
    assert answer.citations[0]["freshness"]["is_stale"] is True
    query_events = [event for event in ledger.events() if event["artifact_type"] == "query"]
    assert query_events
    assert query_events[0]["payload"]["freshness"]["max_data_date"] == "2026-01-12"


def test_pipeline_hard_sla_refuses_stale_data(tmp_path, contract):
    import shutil

    semantic = tmp_path / "semantic"
    shutil.copytree(ROOT / "semantic", semantic)
    source_cfg = yaml.safe_load((semantic / "source_config.yaml").read_text(encoding="utf-8"))
    source_cfg["sources"]["novashop"]["freshness"] = {"max_age_days": 30, "hard_sla": True}
    (semantic / "source_config.yaml").write_text(yaml.safe_dump(source_cfg), encoding="utf-8")
    stale_contract = compile_contract(semantic)

    answer = execute_metric_query(
        MetricQuery(term="order revenue", tenant="novashop", reference_date=date(2026, 6, 27)),
        contract=stale_contract,
    )
    assert answer.decision == "refuse"
    assert answer.reason_code == "METRIC_DATA_STALE"
    assert "stale_data" in answer.caveats
    assert not any(event["artifact_type"] == "query" for event in ledger.events())


def test_assess_freshness_returns_none_without_config(contract):
    kernel = MetricKernel.from_contract(contract)
    entity = kernel.entities["entity:novashop:order"]
    adapter, connection, cfg = resolve_source("novashop", contract)
    cfg_no_freshness = dict(cfg)
    cfg_no_freshness.pop("freshness", None)
    result = assess_freshness(
        adapter,
        connection,
        entity,
        cfg_no_freshness,
        reference_date=date(2026, 1, 31),
    )
    assert result is None


def test_check_freshness_marks_stale_when_max_date_is_null():
    result = check_freshness(
        max_data_date=None,
        reference_date=date(2026, 1, 31),
        sla=FreshnessSLA(max_age_days=30, hard_sla=False),
    )
    assert result.is_stale is True
    assert result.age_days is None
    assert result.max_data_date is None


def test_query_max_time_field_returns_none_without_time_field(contract):
    kernel = MetricKernel.from_contract(contract)
    entity = replace(kernel.entities["entity:novashop:order"], time_field="")
    adapter, connection, _ = resolve_source("novashop", contract)
    assert query_max_time_field(adapter, connection, entity, dialect="duckdb") is None


def test_query_max_time_field_empty_table(tmp_path):
    import duckdb

    from recosearch.semantic_layers.adapters.duckdb import ADAPTER
    from recosearch.semantic_layers.metrics.types import Entity

    db_path = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE empty_orders (order_date DATE)")
    con.close()

    entity = Entity(
        entity_id="entity:test:order",
        source_id="test",
        table="empty_orders",
        primary_key="order_id",
        time_field="order_date",
    )

    connection = duckdb.connect(str(db_path))
    assert query_max_time_field(ADAPTER, connection, entity, dialect="duckdb") is None
    connection.close()


def test_query_max_time_field_all_null_dates(tmp_path):
    import duckdb

    from recosearch.semantic_layers.adapters.duckdb import ADAPTER
    from recosearch.semantic_layers.metrics.types import Entity

    db_path = tmp_path / "null_dates.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE null_orders (order_date DATE)")
    con.execute("INSERT INTO null_orders VALUES (NULL), (NULL)")
    con.close()

    entity = Entity(
        entity_id="entity:test:order",
        source_id="test",
        table="null_orders",
        primary_key="order_id",
        time_field="order_date",
    )

    connection = duckdb.connect(str(db_path))
    assert query_max_time_field(ADAPTER, connection, entity, dialect="duckdb") is None
    connection.close()


def test_assess_freshness_stale_when_entity_has_no_time_field(contract):
    kernel = MetricKernel.from_contract(contract)
    entity = replace(kernel.entities["entity:novashop:order"], time_field="")
    adapter, connection, cfg = resolve_source("novashop", contract)
    result = assess_freshness(
        adapter,
        connection,
        entity,
        cfg,
        reference_date=date(2026, 1, 31),
    )
    assert result is not None
    assert result.max_data_date is None
    assert result.is_stale is True
