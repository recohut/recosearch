"""Live cross-source federation tests: Postgres + Snowflake joined via combine_slices."""
from __future__ import annotations

from recosearch import mcp_server


def test_postgres_snowflake_federation_returns_ok(live_postgres, live_snowflake) -> None:
    pg = mcp_server.run_guarded_postgres_sql(
        "SELECT product_id, seller_id FROM products WHERE product_id != 'P003' LIMIT 5"
    )
    sf = mcp_server.run_guarded_postgres_sql(
        "SELECT seller_id, seller_name FROM sellers LIMIT 10"
    )
    combined = mcp_server.combine_slices(
        sf["rows"],
        pg["rows"],
        left_key="SELLER_ID",
        right_key="seller_id",
    )
    assert combined["status"] == "ok", f"combine_slices failed: {combined}"


def test_postgres_snowflake_federation_returns_rows(live_postgres, live_snowflake) -> None:
    pg = mcp_server.run_guarded_postgres_sql(
        "SELECT product_id, seller_id FROM products WHERE product_id != 'P003' LIMIT 5"
    )
    sf = mcp_server.run_guarded_postgres_sql(
        "SELECT seller_id, seller_name FROM sellers LIMIT 10"
    )
    combined = mcp_server.combine_slices(
        sf["rows"],
        pg["rows"],
        left_key="SELLER_ID",
        right_key="seller_id",
    )
    assert combined["row_count"] > 0, "expected at least one joined row"


def test_postgres_snowflake_federation_rows_carry_both_citations(live_postgres, live_snowflake) -> None:
    pg = mcp_server.run_guarded_postgres_sql(
        "SELECT product_id, seller_id FROM products WHERE product_id != 'P003' LIMIT 5"
    )
    sf = mcp_server.run_guarded_postgres_sql(
        "SELECT seller_id, seller_name FROM sellers LIMIT 10"
    )
    combined = mcp_server.combine_slices(
        sf["rows"],
        pg["rows"],
        left_key="SELLER_ID",
        right_key="seller_id",
    )
    assert combined["status"] == "ok"
    assert combined["rows"], "expected non-empty rows"

    first_row = combined["rows"][0]
    cit = first_row["_citation"]

    # The combined citation must include evidence from both sources
    assert cit.get("supporting_evidence_ids"), "combined row must carry supporting_evidence_ids"
    supporting_sources = cit.get("supporting_sources", [])
    assert "novamart_snowflake" in supporting_sources, (
        f"novamart_snowflake not in supporting_sources: {supporting_sources}"
    )
    assert "novamart_postgres" in supporting_sources, (
        f"novamart_postgres not in supporting_sources: {supporting_sources}"
    )
