"""tests/live/test_live_masking.py – live ACL masking tests.

Verifies that with RECOSEARCH_ROLE=analyst the customer_id field in
customer_reviews (OpenSearch) is replaced with ***MASKED***.

The masking is declared in scenario_config.yaml:
    access:
      sensitive_fields:
        - novamart_opensearch.customer_reviews.customer_id
      unmasked_roles: [admin]
      mask: "***MASKED***"

Because the direct mcp_server.search_text function is the unwrapped tool,
we apply mask_result() explicitly – the same wrapping the MCP dispatch chain
uses – to match production behavior.
"""
from __future__ import annotations

from recosearch import mcp_server
import recosearch.acl as acl
from recosearch.acl import mask_result


def test_analyst_role_masks_customer_id_in_reviews(live_opensearch, monkeypatch) -> None:
    monkeypatch.setenv("RECOSEARCH_ROLE", "analyst")
    acl._cache.clear()

    try:
        assert acl.masking_active() is True, "masking must be active for analyst role"

        # Wrap the tool the same way the MCP dispatch chain does
        masked_search = mask_result(mcp_server.search_text)

        result = masked_search(query="quality")
        assert result["status"] == "ok", f"unexpected status: {result}"
        assert result["rows"], "expected at least one review row"

        for row in result["rows"]:
            assert row.get("customer_id") == "***MASKED***", (
                f"customer_id should be masked for analyst, got: {row.get('customer_id')!r}"
            )
    finally:
        acl._cache.clear()


def test_analyst_role_masking_metadata_present(live_opensearch, monkeypatch) -> None:
    monkeypatch.setenv("RECOSEARCH_ROLE", "analyst")
    acl._cache.clear()

    try:
        masked_search = mask_result(mcp_server.search_text)
        result = masked_search(query="quality")

        assert result.get("masking", {}).get("applied") is True, (
            "masking.applied must be True for analyst role"
        )
        assert result["masking"]["role"] == "analyst"
        assert "customer_id" in result["masking"].get("masked_columns", [])
    finally:
        acl._cache.clear()


def test_no_role_leaves_customer_id_unmasked(live_opensearch, monkeypatch) -> None:
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    acl._cache.clear()

    try:
        assert acl.masking_active() is False, "masking must be inactive with no role"

        result = mcp_server.search_text(query="quality")
        assert result["status"] == "ok"
        assert result["rows"], "expected at least one review row"

        # At least one row must have a real (non-masked) customer_id
        plain_ids = [
            row.get("customer_id")
            for row in result["rows"]
            if row.get("customer_id") != "***MASKED***"
        ]
        assert plain_ids, "expected unmasked customer_ids when no role is set"
    finally:
        acl._cache.clear()
