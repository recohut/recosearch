from __future__ import annotations

from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.mcp_tools import (
    handle_describe_constraints,
    handle_list_shapes,
    handle_validate_claim,
)

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"

try:
    from mcp_server import _build_mcp_server

    MCP_AVAILABLE = True
except Exception:
    MCP_AVAILABLE = False


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_validate_claim_mcp(contract):
    result = handle_validate_claim(
        {
            "term_id": "term:novashop:gross_revenue",
            "claim_qualifiers": {"reported_as": "NetRevenue", "period": "2026-01"},
        },
        contract=contract,
    )
    assert result["decision"] == "refuse"
    assert result["reason_code"] == "CONSTRAINT_VIOLATION"
    assert result["violations"][0]["why_not"]


def test_describe_constraints_mcp(contract):
    payload = handle_describe_constraints(contract=contract)
    assert payload["ontology_hash"].startswith("onto-")
    assert "term:novashop:revenue" in payload["mappings"]
    assert payload["shapes"]


def test_list_shapes_mcp(contract):
    shapes = handle_list_shapes(contract=contract)
    assert len(shapes["shapes"]) >= 3


def test_mcp_server_registers_ontology_tools():
    if not MCP_AVAILABLE:
        return
    server = _build_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert "validate_claim" in tool_names
    assert "describe_constraints" in tool_names
    assert "list_shapes" in tool_names
