"""Live Qdrant source tests. Requires Qdrant on localhost:16333."""
from __future__ import annotations

from recosearch import mcp_server


def test_qdrant_search_vector_returns_ok(live_qdrant) -> None:
    result = mcp_server.search_vector(query="prohibited categories")
    assert result["status"] == "ok", f"unexpected status: {result}"


def test_qdrant_search_vector_returns_rows(live_qdrant) -> None:
    result = mcp_server.search_vector(query="prohibited categories")
    assert result["row_count"] > 0, "expected at least one result"


def test_qdrant_search_vector_rows_have_citation(live_qdrant) -> None:
    result = mcp_server.search_vector(query="prohibited categories")
    assert result["status"] == "ok"
    assert result["rows"], "expected non-empty rows"
    for row in result["rows"]:
        assert "_citation" in row, f"row missing _citation: {row}"
        cit = row["_citation"]
        assert cit.get("evidence_id"), "citation must have an evidence_id"
        assert cit.get("source"), "citation must have a source"
