"""tests/live/test_live_snowflake.py – live Snowflake source tests.

Credentials come from semantic/source_config.yaml (not env vars). The
live_snowflake fixture skips only when the config has no usable password or the
source is unreachable; otherwise it verifies reachability before any test runs.

Tests call run_guarded_postgres_sql routed to the Snowflake source (which
declares the sellers table in source_config.yaml).
"""
from __future__ import annotations

from recosearch import mcp_server


def test_snowflake_sellers_returns_ok(live_snowflake) -> None:
    result = mcp_server.run_guarded_postgres_sql(
        "SELECT seller_id, seller_name FROM sellers LIMIT 3"
    )
    assert result["status"] == "ok", f"unexpected status: {result}"


def test_snowflake_sellers_returns_rows(live_snowflake) -> None:
    result = mcp_server.run_guarded_postgres_sql(
        "SELECT seller_id, seller_name FROM sellers LIMIT 3"
    )
    assert result["row_count"] > 0, "expected at least one seller row"


def test_snowflake_source_boundary_mentions_snowflake(live_snowflake) -> None:
    result = mcp_server.run_guarded_postgres_sql(
        "SELECT seller_id, seller_name FROM sellers LIMIT 3"
    )
    assert result["status"] == "ok"
    boundary = result.get("source_boundary", "")
    assert "snowflake" in boundary.lower(), (
        f"source_boundary should reference snowflake, got: {boundary!r}"
    )
