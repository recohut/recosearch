"""tests/live/test_live_health.py – live health-check tests.

Calls mcp_server.health_check_sources() and verifies that the three
local sources (postgres, opensearch, qdrant) are reported as ok.
"""
from __future__ import annotations

from recosearch import mcp_server


def test_health_check_postgres_ok(live_postgres) -> None:
    health = mcp_server.health_check_sources()
    result = health["results"].get("novamart_postgres", {})
    assert result.get("status") == "ok", (
        f"novamart_postgres health check failed: {result}"
    )


def test_health_check_opensearch_ok(live_opensearch) -> None:
    health = mcp_server.health_check_sources()
    result = health["results"].get("novamart_opensearch", {})
    assert result.get("status") == "ok", (
        f"novamart_opensearch health check failed: {result}"
    )


def test_health_check_qdrant_ok(live_qdrant) -> None:
    health = mcp_server.health_check_sources()
    result = health["results"].get("novamart_qdrant", {})
    assert result.get("status") == "ok", (
        f"novamart_qdrant health check failed: {result}"
    )
