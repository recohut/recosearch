from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
import sqlglot.expressions as exp

from recosearch.semantic_layers.metrics.formula import FormulaError, _validate_ast
from recosearch.semantic_layers.metrics.freshness import query_max_time_field, resolve_freshness_sla
from recosearch.semantic_layers.metrics.relations import (
    RelationStep,
    invert_cardinality,
    path_has_additive_fanout,
    plan_relation_path,
)
from recosearch.semantic_layers.metrics.types import Entity, FreshnessSLA

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


def test_validate_ast_accepts_identifier_ref_token():
    from recosearch.semantic_layers.metrics.formula import _validate_ast

    refs = {"__ref_0__": "measure:x:a"}
    _validate_ast(exp.Identifier(this="__ref_0__"), refs)


def test_resolve_freshness_sla_returns_none_when_max_age_missing():
    sla = resolve_freshness_sla({"freshness": {"hard_sla": True}})
    assert sla is None


def test_query_max_time_field_handles_empty_rows():
    class EmptyAdapter:
        @staticmethod
        def run_structured_query(_connection, _sql, row_limit=1):
            return []

    entity = Entity(
        entity_id="entity:test:order",
        source_id="test",
        table="orders",
        primary_key="order_id",
        time_field="order_date",
    )
    assert query_max_time_field(EmptyAdapter(), object(), entity) is None


def test_validate_ast_rejects_unknown_identifier():
    with pytest.raises(FormulaError, match="unknown identifier"):
        _validate_ast(exp.Identifier(this="unknown_token"), {})


def test_query_max_time_field_returns_none_for_unsupported_type():
    class RowsAdapter:
        def run_structured_query(self, _connection, _sql, row_limit=1):
            return [{"max_date": 12345}]

    entity = Entity(
        entity_id="entity:test:order",
        source_id="test",
        table="orders",
        primary_key="order_id",
        time_field="order_date",
    )
    assert query_max_time_field(RowsAdapter(), object(), entity) is None


def test_query_max_time_field_parses_datetime_and_string():
    class RowsAdapter:
        def __init__(self, rows):
            self._rows = rows

        def run_structured_query(self, _connection, _sql, row_limit=1):
            return self._rows

    entity = Entity(
        entity_id="entity:test:order",
        source_id="test",
        table="orders",
        primary_key="order_id",
        time_field="order_date",
    )

    dt_value = datetime(2026, 1, 15, 12, 30)
    assert (
        query_max_time_field(RowsAdapter([{"max_date": dt_value}]), object(), entity)
        == date(2026, 1, 15)
    )
    assert (
        query_max_time_field(RowsAdapter([{"max_date": "2026-02-01T10:00:00"}]), object(), entity)
        == date(2026, 2, 1)
    )
    assert (
        query_max_time_field(RowsAdapter([{"max_date": date(2026, 3, 3)}]), object(), entity)
        == date(2026, 3, 3)
    )


def test_invert_cardinality_rejects_unknown():
    with pytest.raises(ValueError, match="unknown cardinality"):
        invert_cardinality("invalid")


def test_plan_relation_path_same_entity_returns_empty():
    assert plan_relation_path({}, "entity:x:a", "entity:x:a") == []


def test_path_has_additive_fanout_ignored_for_non_sum():
    step = RelationStep(
        relation_id="relation:x:parent_child",
        from_entity_id="entity:x:parent",
        to_entity_id="entity:x:child",
        join_key="parent_id",
        cardinality="one_to_many",
    )
    assert path_has_additive_fanout([step], "count") is None


def test_freshness_result_to_dict_includes_none_max_date():
    from recosearch.semantic_layers.metrics.freshness import check_freshness

    result = check_freshness(
        max_data_date=None,
        reference_date=date(2026, 1, 31),
        sla=FreshnessSLA(max_age_days=7, hard_sla=False),
    )
    payload = result.to_dict()
    assert payload["max_data_date"] is None
    assert payload["is_stale"] is True
