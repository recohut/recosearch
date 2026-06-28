"""Smoke tests — server boot / contract sanity.

Verifies that:
  - mcp_server can be imported without error
  - mcp_server.register_tools is callable
  - validated_contract().is_valid is True
  - compile_semantic_contract() returns a dict with non-empty
    dimensions, measures, and relations sections
"""
from __future__ import annotations

from recosearch import mcp_server
from recosearch.contract import compile_semantic_contract, validated_contract


def test_mcp_server_import() -> None:
    """mcp_server module is importable; no top-level exceptions."""
    assert mcp_server is not None


def test_register_tools_is_callable() -> None:
    """mcp_server.register_tools must be a callable (used to wire tools to FastMCP)."""
    assert callable(mcp_server.register_tools)


def test_validated_contract_is_valid() -> None:
    """The compiled + validated contract has no error-severity issues."""
    vc = validated_contract()
    assert vc.is_valid, (
        f"Contract is invalid; errors: {[i.as_dict() for i in vc.errors]}"
    )


def test_compile_semantic_contract_has_dimensions() -> None:
    """compile_semantic_contract() returns a non-empty dimensions dict."""
    contract = compile_semantic_contract()
    assert isinstance(contract, dict)
    dimensions = contract.get("dimensions")
    assert dimensions, "Expected at least one dimension; got none"


def test_compile_semantic_contract_has_measures() -> None:
    """compile_semantic_contract() returns a non-empty measures dict."""
    contract = compile_semantic_contract()
    measures = contract.get("measures")
    assert measures, "Expected at least one measure; got none"


def test_compile_semantic_contract_has_relations() -> None:
    """compile_semantic_contract() returns a non-empty relations list."""
    contract = compile_semantic_contract()
    relations = contract.get("relations")
    assert relations, "Expected at least one relation; got none"
