"""Offline rule-compiler tests.

Compile injected and declared semantic.md rules and assert typing, lifecycle
gating, parser exactness, generic classification, and propagation of compiler
metadata into rule_impact. No live sources required.
"""
from __future__ import annotations

from recosearch.citations import _rule_impact
from recosearch.config import _source_refs
from recosearch.contract import (
    _global_rule_filters_for_tables,
    compile_with_issues,
    validated_contract,
)
from recosearch.rules import recorded_policies, rule_id_for


def _compile(semantic_text: str):
    return compile_with_issues(semantic_text=semantic_text, source_refs=_source_refs())


def _codes(semantic_text: str) -> set[str]:
    _contract, issues = _compile(semantic_text)
    return {issue.code for issue in issues}


_DIMS_MEASURES = (
    "# dimensions\n- novamart_postgres.orders.product_id: sku\n- novamart_postgres.orders.customer_id: buyer\n"
    "# measures\n- novamart_postgres.orders.total_amount: total, default sum\n"
)


# --- declared semantic.md mapping (the expected table) -----------------------

def test_declared_rules_classify_as_expected() -> None:
    rules = {r["rule_type"]: r for r in validated_contract().contract["rules"]}
    assert set(rules) == {"row_exclusion", "threshold_state", "metric_default_filter", "metric_field_binding", "precedence"}
    enforced = [r for r in validated_contract().contract["rules"] if r["application_mode"] == "enforced"]
    assert len(enforced) == 1 and enforced[0]["rule_type"] == "row_exclusion"
    assert all(r["application_mode"] == "recorded_only" for t, r in rules.items() if t != "row_exclusion")


def test_rule_ids_are_content_hashes_not_positional() -> None:
    rules = validated_contract().contract["rules"]
    assert all(r["rule_id"].startswith("sha256:") for r in rules)
    assert all(not r["rule_id"].startswith("rule_") for r in rules)
    assert rule_id_for("Ignore product P003 from all calculations") == rule_id_for("ignore   product   p003   FROM ALL CALCULATIONS")


# --- lifecycle status gating -------------------------------------------------

def test_active_exclusion_enforces() -> None:
    contract, _ = _compile(_DIMS_MEASURES + "# rules\n## active\n- Ignore product P003 from all calculations\n")
    assert any(e["value"] == "P003" for e in contract.get("exclusions", []))


def test_draft_exclusion_does_not_enforce() -> None:
    contract, _ = _compile(_DIMS_MEASURES + "# rules\n## draft\n- Ignore product P003 from all calculations\n")
    assert not contract.get("exclusions")
    draft = [r for r in contract["rules"] if r["status"] == "draft"]
    assert draft and draft[0]["application_mode"] == "recorded_only"


def test_bare_rule_after_subsection_is_error_and_not_enforced() -> None:
    text = _DIMS_MEASURES + "# rules\n- Ignore product P003 from all calculations\n## active\n- Some managed rule\n"
    contract, issues = _compile(text)
    codes = {i.code for i in issues}
    assert "rule_status_required" in codes
    assert not contract.get("exclusions")  # the bare exclusion did not silently enforce


def test_no_subsections_defaults_active_backcompat() -> None:
    contract, _ = _compile(_DIMS_MEASURES + "# rules\n- Ignore product P003 from all calculations\n")
    assert any(e["value"] == "P003" for e in contract.get("exclusions", []))


# --- parser exactness --------------------------------------------------------

def test_unknown_rule_status_subsection_is_error() -> None:
    assert "rule_status_unknown" in _codes(_DIMS_MEASURES + "# rules\n## frobnicate\n- a rule\n")


def test_subsection_outside_rules_is_error() -> None:
    assert "subsection_outside_rules" in _codes("# dimensions\n## active\n- novamart_postgres.orders.order_id: x\n")


# --- generic classification (no fixture coupling) ----------------------------

def test_exclusion_compiler_is_generic_not_fixture_coupled() -> None:
    # Different entity (customer) and value (CUST-1) — resolves against declared fields.
    contract, _ = _compile(
        "# dimensions\n- novamart_postgres.orders.customer_id: buyer\n"
        "# measures\n- novamart_postgres.orders.total_amount: total, default sum\n"
        "# rules\n## active\n- Ignore customer CUST-1 from all calculations\n"
    )
    exclusions = contract.get("exclusions", [])
    assert any(e["field_id"] == "novamart_postgres.orders.customer_id" and e["value"] == "CUST-1" for e in exclusions)


def test_enforceable_rule_not_compiled_when_field_unresolved() -> None:
    assert "enforceable_rule_not_compiled" in _codes(_DIMS_MEASURES + "# rules\n## active\n- Ignore widget WIDG from all calculations\n")


# --- propagation into rule_impact (no hardcoded effect) ----------------------

def test_compiler_metadata_propagates_to_rule_impact() -> None:
    filters = _global_rule_filters_for_tables(["orders"])
    assert filters
    assert all(f["rule_type"] == "row_exclusion" and f["effect"] == "exclude" and f["application_mode"] == "enforced" and f["rule_id"] for f in filters)
    impact = _rule_impact(filters)
    assert impact[0]["effect"] == "exclude"  # reported from compiler, not hardcoded
    assert impact[0]["rule_id"] and impact[0]["application_mode"] == "enforced"


# --- recorded policy context -------------------------------------------------

def test_recorded_policies_are_active_recorded_only() -> None:
    # Engine behavior via a synthetic contract (independent of live business
    # categorization): an active non-exclusion rule is a recorded policy; a
    # non-active one is tracked but never recorded. Also exercises the inline
    # "- <status>: <text>" labelling.
    contract, _ = _compile(
        _ORDERS + "# rules\n"
        "- active: Revenue must use only delivered orders\n"
        "- review: Discount analysis must use the discount value applied to the order line\n"
    )
    policies = recorded_policies(contract)
    assert policies
    assert all(p["status"] == "active" and p["application_mode"] == "recorded_only" for p in policies)
    assert all(p["rule_type"] != "row_exclusion" for p in policies)
    assert "review" not in {p["status"] for p in policies}


# --- wording variants (improved compiler) ------------------------------------

_ORDERS = (
    "# dimensions\n"
    "- novamart_postgres.orders.product_id: product SKU on the order line\n"
    "- novamart_postgres.orders.order_status: fulfillment state such as delivered, returned, cancelled, or pending\n"
    "# measures\n"
    "- novamart_postgres.orders.unit_price: selling price per unit on the order line, default average\n"
    "- novamart_postgres.orders.discount_amount: discount value applied to the order line, default sum\n"
)


def test_generic_exclusion_verb_variants_all_enforce() -> None:
    for rule in (
        "Exclude product P003 from all calculations",
        "Do not include product P003 in calculations",
        "Omit product P003 from every calculation",
        "Remove product P003 from calculations",
        "Product P003 is blacklisted",
    ):
        contract, _ = _compile(_ORDERS + f"# rules\n## active\n- {rule}\n")
        assert any(
            e["field_id"] == "novamart_postgres.orders.product_id" and e["value"] == "P003"
            for e in contract.get("exclusions", [])
        ), rule


def test_threshold_metric_matching_binds_bad_reviews() -> None:
    threshold = next(r for r in validated_contract().contract["rules"] if r["rule_type"] == "threshold_state")
    assert threshold["compiled_policy"]["subject_metric"] == "bad_review_count"


def test_default_filter_handles_use_only_delivered_orders() -> None:
    contract, _ = _compile(_ORDERS + "# rules\n## active\n- Revenue must use only delivered orders\n")
    policy = next(r["compiled_policy"] for r in contract["rules"] if r["rule_type"] == "metric_default_filter")
    assert policy["field_id"] == "novamart_postgres.orders.order_status" and policy["value"] == "delivered"


def test_field_binding_resolves_by_column_name() -> None:
    contract, _ = _compile(_ORDERS + "# rules\n## active\n- Margin analysis must use unit_price from the order line\n")
    binding = [r for r in contract["rules"] if r["rule_type"] == "metric_field_binding"]
    assert binding and binding[0]["compiled_policy"]["field_id"] == "novamart_postgres.orders.unit_price"


def test_field_binding_resolves_by_description_token() -> None:
    contract, _ = _compile(_ORDERS + "# rules\n## active\n- Discounting must use the discount value applied to the order line\n")
    binding = [r for r in contract["rules"] if r["rule_type"] == "metric_field_binding"]
    assert binding and binding[0]["compiled_policy"]["field_id"] == "novamart_postgres.orders.discount_amount"


def test_active_advisory_unstructured_warning() -> None:
    assert "active_advisory_unstructured" in _codes(_ORDERS + "# rules\n## active\n- Prefer concise explanations over verbose ones.\n")


def test_ambiguous_enforcement_rule_warning() -> None:
    assert "ambiguous_enforcement_rule" in _codes(_ORDERS + "# rules\n## active\n- Do not over-rely on SKU-9 when summarizing.\n")
