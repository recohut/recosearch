"""Live Postgres source tests. Requires Postgres on localhost:15432."""
from __future__ import annotations

from recosearch import mcp_server


def test_postgres_select_products_returns_rows_and_excludes_p003(live_postgres) -> None:
    result = mcp_server.run_guarded_postgres_sql(
        "SELECT product_id, product_name FROM products WHERE product_id != 'P003' LIMIT 3"
    )
    assert result["status"] == "ok", f"unexpected status: {result}"
    assert result["row_count"] > 0, "expected at least one row"
    # P003 must be absent (guard enforces the global row-exclusion rule)
    returned_ids = {row["product_id"] for row in result["rows"]}
    assert "P003" not in returned_ids, f"P003 should be excluded but found in {returned_ids}"


def test_postgres_rows_carry_citation(live_postgres) -> None:
    result = mcp_server.run_guarded_postgres_sql(
        "SELECT product_id, product_name FROM products WHERE product_id != 'P003' LIMIT 3"
    )
    assert result["status"] == "ok"
    for row in result["rows"]:
        assert "_citation" in row, f"row missing _citation: {row}"
        assert row["_citation"].get("source_ref", {}).get("source_id") == "novamart_postgres"


def test_postgres_insert_is_refused(live_postgres) -> None:
    result = mcp_server.run_guarded_postgres_sql(
        "INSERT INTO products (product_id) VALUES ('TEST_LIVE')"
    )
    assert result["status"] == "refused", f"INSERT should be refused, got: {result['status']}"
    assert result["guard"]["decision"] == "refuse"
    assert result["guard"]["reason_code"] == "mutating_sql"
