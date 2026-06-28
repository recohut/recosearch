"""Live OpenSearch source tests. Requires OpenSearch on localhost:19200."""
from __future__ import annotations

from recosearch import mcp_server


def test_opensearch_search_text_quality_returns_ok(live_opensearch) -> None:
    result = mcp_server.search_text(query="quality")
    assert result["status"] == "ok", f"unexpected status: {result}"


def test_opensearch_search_text_returns_rows(live_opensearch) -> None:
    result = mcp_server.search_text(query="quality")
    assert result["row_count"] > 0, "expected at least one result for query='quality'"


def test_opensearch_search_text_rows_have_citation(live_opensearch) -> None:
    result = mcp_server.search_text(query="quality")
    assert result["status"] == "ok"
    assert result["rows"], "expected non-empty rows"
    for row in result["rows"]:
        assert "_citation" in row, f"row missing _citation: {row}"
        cit = row["_citation"]
        assert cit.get("evidence_id"), "citation must have an evidence_id"
        assert cit.get("source"), "citation must have a source"
