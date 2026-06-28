"""Offline tests for recosearch/field_roles.py.

Tests:
- resolve_field_roles on the real compiled semantic.json contract
- identity_columns / searchable_columns non-empty for customer_reviews source/table
- ambiguity surfaced as resolution "ambiguous" via a synthetic contract
"""
from __future__ import annotations

from typing import Any

import pytest

from recosearch.contract import compile_semantic_contract
from recosearch.field_roles import (
    resolve_field_roles,
    identity_columns,
    searchable_columns,
    _resolve_role,
)


def _load_real_contract() -> dict[str, Any]:
    return compile_semantic_contract()


# ---------------------------------------------------------------------------
# Helpers for synthetic contracts
# ---------------------------------------------------------------------------

def _synthetic_contract(
    source_id: str,
    table: str,
    dimensions: dict[str, dict[str, Any]],
    measures: dict[str, dict[str, Any]] | None = None,
    relations: list[dict[str, Any]] | None = None,
    field_roles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "sources": {source_id: {"type": "postgres"}},
        "dimensions": dimensions,
        "measures": measures or {},
        "relations": relations or [],
        "field_roles": field_roles or [],
    }


# ---------------------------------------------------------------------------
# resolve_field_roles on the real contract
# ---------------------------------------------------------------------------

def test_resolve_field_roles_returns_list() -> None:
    contract = _load_real_contract()
    roles = resolve_field_roles(contract)
    assert isinstance(roles, list)
    assert len(roles) > 0


def test_resolve_field_roles_has_required_keys() -> None:
    contract = _load_real_contract()
    roles = resolve_field_roles(contract)
    for assignment in roles:
        assert "field_role" in assignment
        assert "resolution" in assignment
        assert "source" in assignment
        assert "table" in assignment


def test_resolve_field_roles_includes_identity_for_products() -> None:
    """novamart_postgres.products has a clear identity field (product_id)."""
    contract = _load_real_contract()
    roles = resolve_field_roles(contract)
    identity_resolved = [
        a for a in roles
        if a["field_role"] == "identity"
        and a["resolution"] == "resolved"
        and a["source"] == "novamart_postgres"
        and a["table"] == "products"
    ]
    assert identity_resolved, "Expected a resolved identity role for novamart_postgres.products"


def test_resolve_field_roles_join_key_from_relations() -> None:
    """Relations in the real contract produce join_key assignments."""
    contract = _load_real_contract()
    roles = resolve_field_roles(contract)
    join_keys = [a for a in roles if a["field_role"] == "join_key" and a["resolution"] == "resolved"]
    assert join_keys, "Expected at least one join_key from declared relations"


# ---------------------------------------------------------------------------
# identity_columns and searchable_columns — customer_reviews
# ---------------------------------------------------------------------------

def test_identity_columns_non_empty_for_customer_reviews() -> None:
    """The real contract has join_key / identity roles for customer_reviews."""
    contract = _load_real_contract()
    # Uses pre-compiled field_roles from the contract dict (not re-resolving)
    cols = identity_columns(contract, "novamart_opensearch", "customer_reviews")
    assert cols, f"Expected non-empty identity columns for customer_reviews, got {cols!r}"


def test_searchable_columns_non_empty_for_customer_reviews() -> None:
    """customer_reviews has body_text (review_text) and display_name (review_title) roles."""
    contract = _load_real_contract()
    cols = searchable_columns(contract, "novamart_opensearch", "customer_reviews")
    assert cols, f"Expected non-empty searchable columns for customer_reviews, got {cols!r}"


def test_identity_columns_returns_actual_column_names() -> None:
    """identity_columns returns column name strings, not field IDs."""
    contract = _load_real_contract()
    cols = identity_columns(contract, "novamart_postgres", "products")
    for col in cols:
        assert isinstance(col, str)
        assert "." not in col, f"Expected raw column name, got field ID-like {col!r}"


# ---------------------------------------------------------------------------
# Ambiguity surfaced as resolution "ambiguous" via synthetic contract
# ---------------------------------------------------------------------------

def test_resolve_role_returns_ambiguous_when_two_fields_score_equally() -> None:
    """Two equally-scoring identity candidates -> resolution 'ambiguous'."""
    dimensions = {
        "src.tbl.id_a": {
            "column": "id_a",
            "label": "identifier of entity A",
            "description": "unique identifier for the record",
            "source": "src",
            "table": "tbl",
        },
        "src.tbl.id_b": {
            "column": "id_b",
            "label": "identifier of entity B",
            "description": "another unique identifier for the record",
            "source": "src",
            "table": "tbl",
        },
    }
    contract = _synthetic_contract("src", "tbl", dimensions)
    result = _resolve_role(contract, "identity", "src", "tbl")
    assert result is not None, "Expected a result (not None) for two matching candidates"
    assert result["resolution"] == "ambiguous", (
        f"Expected resolution='ambiguous', got {result['resolution']!r}"
    )
    assert result["field_id"] is None


def test_resolve_role_ambiguous_lists_candidates() -> None:
    dimensions = {
        "src.tbl.foo_id": {
            "column": "foo_id",
            "label": "unique identifier for foo",
            "description": "unique identifier for each foo record",
            "source": "src",
            "table": "tbl",
        },
        "src.tbl.bar_id": {
            "column": "bar_id",
            "label": "unique identifier for bar",
            "description": "unique identifier for each bar record",
            "source": "src",
            "table": "tbl",
        },
    }
    contract = _synthetic_contract("src", "tbl", dimensions)
    result = _resolve_role(contract, "identity", "src", "tbl")
    assert result is not None
    assert len(result["ambiguous_candidates"]) >= 2


def test_resolve_role_single_winner_is_resolved() -> None:
    """One clear identity field -> resolved, not ambiguous."""
    dimensions = {
        "src.tbl.item_id": {
            "column": "item_id",
            "label": "unique identifier for each item",
            "description": "unique identifier for each item record",
            "source": "src",
            "table": "tbl",
        },
        "src.tbl.description": {
            "column": "description",
            "label": "free-text description of the item",
            "description": "full text description body",
            "source": "src",
            "table": "tbl",
        },
    }
    contract = _synthetic_contract("src", "tbl", dimensions)
    result = _resolve_role(contract, "identity", "src", "tbl")
    # Either resolved or None (no match) — must NOT be ambiguous
    if result is not None:
        assert result["resolution"] != "ambiguous", (
            f"Expected 'resolved', got {result['resolution']!r}"
        )


def test_resolve_field_roles_on_synthetic_includes_join_keys_from_relations() -> None:
    dimensions = {
        "s1.t1.user_id": {
            "column": "user_id",
            "label": "unique identifier for the user",
            "description": "identifier for each user",
            "source": "s1",
            "table": "t1",
        },
        "s2.t2.user_id": {
            "column": "user_id",
            "label": "user identifier",
            "description": "identifier for the user",
            "source": "s2",
            "table": "t2",
        },
    }
    contract = {
        "sources": {"s1": {"type": "postgres"}, "s2": {"type": "opensearch"}},
        "dimensions": dimensions,
        "measures": {},
        "relations": [{"left": "s1.t1.user_id", "right": "s2.t2.user_id"}],
        "field_roles": [],
    }
    assignments = resolve_field_roles(contract)
    join_key_fields = [a["field_id"] for a in assignments if a["field_role"] == "join_key"]
    assert "s1.t1.user_id" in join_key_fields
    assert "s2.t2.user_id" in join_key_fields
