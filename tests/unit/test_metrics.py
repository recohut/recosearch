"""Offline metric registry and fallback tests. No live sources.

Includes synthetic contracts to prove the resolver is driven by the semantic
contract, not hardcoded column names.
"""
from __future__ import annotations

from recosearch import metrics, tools
from recosearch.citations import _provenance
from recosearch.contract import compile_semantic_contract
from recosearch.evidence_schema import validate_evidence_envelope
from recosearch.metric_resolver import (
    map_role,
    resolve_and_validate_metric,
    resolve_metric,
    validate_metric_packs,
)

_CONTRACT = compile_semantic_contract()
_REAL = metrics.load_metric_data()
_ENABLED_GLOBAL = {**_REAL, "policy": {**_REAL["policy"], "allow_global": True}}
_ENABLED_ECOM = {**_REAL, "policy": {**_REAL["policy"], "allow_industry": ["ecommerce"]}}


def _global(monkeypatch):
    monkeypatch.setattr(metrics, "load_metric_data", lambda: _ENABLED_GLOBAL)


def _ecom(monkeypatch):
    monkeypatch.setattr(metrics, "load_metric_data", lambda: _ENABLED_ECOM)


def _net_revenue_plan(status="delivered", extra_select=()):
    return {
        "select": [
            *extra_select,
            {"field": "novamart_postgres.orders.total_amount", "aggregation": "sum"},
            {"field": "novamart_postgres.orders.discount_amount", "aggregation": "sum"},
        ],
        "filters": [{"field": "novamart_postgres.orders.order_status", "operator": "=", "value": status}],
    }


def _synthetic(measures, dimensions):
    return {"sources": {"pg": {"type": "postgres"}}, "measures": measures, "dimensions": dimensions, "metrics": {}}


# --- packs + precedence ------------------------------------------------------

def test_metric_packs_are_schema_valid() -> None:
    assert [i for i in validate_metric_packs() if i.is_error] == []


def test_customer_metric_wins_L0() -> None:
    res = resolve_metric("delivered net revenue", _CONTRACT)
    assert res["stamp"]["metric_source"] == "customer" and res["stamp"]["fallback_level"] == "L0"
    assert res["stamp"]["formula_verified"] is False


def test_normalized_customer_alias_L1() -> None:
    res = resolve_metric("Delivered Net Revenue", _CONTRACT)
    assert res["stamp"]["metric_source"] == "customer" and res["stamp"]["fallback_level"] == "L1"


def test_fallback_disabled_by_default() -> None:
    assert resolve_metric("net revenue", _CONTRACT)["status"] == "fallback_disabled"


def test_unknown_metric_clarifies() -> None:
    assert resolve_metric("interstellar revenue", _CONTRACT)["status"] == "clarify"


def test_global_fallback_resolves_when_enabled(monkeypatch) -> None:
    _global(monkeypatch)
    res = resolve_metric("net revenue", _CONTRACT)
    assert res["status"] == "resolved" and res["stamp"]["metric_source"] == "global" and res["stamp"]["fallback_level"] == "L3"


# --- structured formula verification -----------------------------------------

def test_conforming_difference_is_inputs_verified_not_formula_verified(monkeypatch) -> None:
    # MCP returns SUM(gross) and SUM(discount) separately; it does not compute the
    # difference, so net_revenue is inputs-verified, not formula-verified.
    _global(monkeypatch)
    stamp = resolve_and_validate_metric("net revenue", _net_revenue_plan(), _CONTRACT)["stamp"]
    assert stamp["inputs_verified"] is True and stamp["formula_verified"] is False
    assert "derived arithmetic" in stamp["caveat"]
    assert stamp["metric_pack_hash"].startswith("sha256:") and stamp["fallback_policy_hash"].startswith("sha256:")


def test_single_aggregate_metric_is_formula_verified(monkeypatch) -> None:
    # units_sold = sum(order_quantity): the aggregate IS the metric, no derived arithmetic.
    _global(monkeypatch)
    plan = {
        "select": [{"field": "novamart_postgres.orders.quantity", "aggregation": "sum"}],
        "filters": [{"field": "novamart_postgres.orders.order_status", "operator": "=", "value": "delivered"}],
    }
    stamp = resolve_and_validate_metric("units sold", plan, _CONTRACT)["stamp"]
    assert stamp["formula_verified"] is True and stamp["inputs_verified"] is True


def test_group_by_dimension_is_allowed(monkeypatch) -> None:
    _global(monkeypatch)
    plan = _net_revenue_plan(extra_select=({"field": "novamart_postgres.products.category"},))
    assert resolve_and_validate_metric("net revenue", plan, _CONTRACT)["stamp"]["inputs_verified"] is True


def test_status_override_is_not_verified(monkeypatch) -> None:
    _global(monkeypatch)
    stamp = resolve_and_validate_metric("net revenue", _net_revenue_plan(status="cancelled"), _CONTRACT)["stamp"]
    assert stamp["formula_verified"] is False and "status_override" in stamp["caveat"]


def test_missing_default_filter_is_refused(monkeypatch) -> None:
    _global(monkeypatch)
    plan = _net_revenue_plan()
    plan["filters"] = []
    assert resolve_and_validate_metric("net revenue", plan, _CONTRACT)["refused"] == "metric_plan_mismatch"


def test_extra_aggregate_breaks_formula_match(monkeypatch) -> None:
    _global(monkeypatch)
    plan = _net_revenue_plan(extra_select=({"field": "novamart_postgres.orders.quantity", "aggregation": "sum"},))
    assert resolve_and_validate_metric("net revenue", plan, _CONTRACT)["refused"] == "metric_plan_mismatch"


def test_unmapped_required_field_is_refused(monkeypatch) -> None:
    _global(monkeypatch)
    # gross_margin needs product_cost, which this scenario does not declare.
    assert resolve_and_validate_metric("gross margin", _net_revenue_plan(), _CONTRACT)["refused"] == "metric_required_fields_unmapped"


def test_ratio_metric_inputs_only(monkeypatch) -> None:
    _global(monkeypatch)
    plan = {
        "select": [
            {"field": "novamart_postgres.orders.order_status", "aggregation": "count"},
            {"field": "novamart_postgres.orders.order_id", "aggregation": "count"},
        ],
        "filters": [],
    }
    stamp = resolve_and_validate_metric("return rate", plan, _CONTRACT)["stamp"]
    assert stamp["formula_verified"] is False and "ratio" in stamp["caveat"]


# --- industry -> global delegation -------------------------------------------

def test_industry_delegates_to_global(monkeypatch) -> None:
    _ecom(monkeypatch)
    decision = resolve_and_validate_metric("net revenue", _net_revenue_plan(), _CONTRACT)
    stamp = decision["stamp"]
    assert stamp["metric_source"] == "industry" and stamp["delegated_from"] == "global" and stamp["formula_source"] == "global"
    assert stamp["inputs_verified"] is True


# --- contract-driven (synthetic contracts) -----------------------------------

def test_role_mapping_is_contract_driven() -> None:
    contract = _synthetic(
        measures={
            "pg.sales.revenue_amount": {"source": "pg", "table": "sales", "column": "revenue_amount", "description": "revenue value of the sale line"},
            "pg.sales.line_discount": {"source": "pg", "table": "sales", "column": "line_discount", "description": "discount applied to the line"},
            "pg.sales.cogs_amount": {"source": "pg", "table": "sales", "column": "cogs_amount", "description": "cost of goods sold for the line"},
        },
        dimensions={
            "pg.sales.order_state": {"source": "pg", "table": "sales", "column": "order_state", "description": "order fulfillment state such as delivered or returned"},
            "pg.sales.order_ref": {"source": "pg", "table": "sales", "column": "order_ref", "description": "unique order id for the sale"},
        },
    )
    assert map_role(contract, "gross_amount") == ("ok", "pg.sales.revenue_amount")
    assert map_role(contract, "discount_amount") == ("ok", "pg.sales.line_discount")
    assert map_role(contract, "product_cost") == ("ok", "pg.sales.cogs_amount")
    assert map_role(contract, "order_status") == ("ok", "pg.sales.order_state")
    assert map_role(contract, "order_identifier") == ("ok", "pg.sales.order_ref")


def test_ambiguous_role_is_refused() -> None:
    contract = _synthetic(
        measures={
            "pg.t.rev_a": {"source": "pg", "table": "t", "column": "rev_a", "description": "gross revenue amount"},
            "pg.t.rev_b": {"source": "pg", "table": "t", "column": "rev_b", "description": "monetary revenue value"},
        },
        dimensions={},
    )
    status, _candidates = map_role(contract, "gross_amount")
    assert status == "ambiguous"


def test_weak_close_match_is_refused() -> None:
    # A field that matches gross_amount and discount_amount equally is not confident.
    contract = _synthetic(
        measures={"pg.t.x": {"source": "pg", "table": "t", "column": "x", "description": "monetary discount value of the line"}},
        dimensions={},
    )
    assert map_role(contract, "gross_amount")[0] == "unmapped"
    assert map_role(contract, "discount_amount")[0] == "unmapped"


def test_discount_rate_does_not_map_to_discount_amount() -> None:
    contract = _synthetic(
        measures={"pg.t.discount_rate": {"source": "pg", "table": "t", "column": "discount_rate", "description": "discount rate percentage applied"}},
        dimensions={},
    )
    assert map_role(contract, "discount_amount")[0] == "unmapped"


def test_shipping_cost_does_not_map_to_product_cost() -> None:
    contract = _synthetic(
        measures={"pg.t.shipping_cost": {"source": "pg", "table": "t", "column": "shipping_cost", "description": "shipping cost charged per order"}},
        dimensions={},
    )
    assert map_role(contract, "product_cost")[0] == "unmapped"


def test_role_vocabulary_is_schema_valid() -> None:
    from recosearch.metric_resolver_schema import validate_roles
    assert [i for i in validate_roles() if i.is_error] == []


def test_malformed_role_vocabulary_is_flagged() -> None:
    from recosearch.metric_resolver_schema import validate_roles
    bad = {"roles": {"weird": {"kind": "metric", "match_terms": [], "concept": ""}}, "value_roles": {}}
    assert any(i.code == "metric_pack_invalid" for i in validate_roles(bad))


# --- provenance + evidence schema --------------------------------------------

def test_metric_resolution_validates_in_evidence_schema(monkeypatch) -> None:
    _global(monkeypatch)
    stamp = resolve_and_validate_metric("net revenue", _net_revenue_plan(), _CONTRACT)["stamp"]
    envelope = _provenance(tool_name="execute_postgres_semantic_query", source="novamart_postgres", source_id="novamart_postgres",
                           source_type="postgres", fields=["novamart_postgres.orders.total_amount"], row_count=1, metric_resolution=stamp)
    assert validate_evidence_envelope(envelope) == []


def test_malformed_metric_resolution_is_flagged() -> None:
    envelope = _provenance(tool_name="t", source="novamart_postgres", source_id="novamart_postgres", source_type="postgres", row_count=0,
                           metric_resolution={"metric_id": "x"})
    assert any(i.code == "metric_resolution_malformed" for i in validate_evidence_envelope(envelope))


# --- execute refuses before touching the database ----------------------------

def test_execute_refuses_unknown_metric_offline() -> None:
    res = tools.execute_postgres_semantic_query(_net_revenue_plan(), metric_id="interstellar revenue")
    assert res["status"] == "refused" and res["reason_code"] == "metric_unknown_clarify"


def test_execute_refuses_disabled_fallback_offline() -> None:
    res = tools.execute_postgres_semantic_query(_net_revenue_plan(), metric_id="net revenue")
    assert res["status"] == "refused" and res["reason_code"] == "metric_fallback_disabled"
