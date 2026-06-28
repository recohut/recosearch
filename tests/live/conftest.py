"""Probe-and-skip fixtures for live source tests.

Each fixture performs a cheap reachability check and calls pytest.skip() if the
source is down. Tests declare the fixture they need; the skip fires before any
test body runs.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def live_postgres():
    """Skip if the local Postgres service (port 15432) is not reachable."""
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(
            host="localhost",
            port=15432,
            database=os.environ.get("PG_DATABASE", "novamart"),
            user=os.environ.get("PG_USER", "novamart"),
            password=os.environ.get("PG_PASSWORD", ""),
            connect_timeout=3,
        )
        conn.close()
    except Exception as exc:
        pytest.skip(f"Postgres not reachable on localhost:15432 – {exc}")
    return True


@pytest.fixture(scope="session")
def live_opensearch():
    """Skip if the local OpenSearch service (port 19200) is not reachable."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:19200", timeout=3) as resp:
            if resp.status >= 500:
                raise RuntimeError(f"OpenSearch returned HTTP {resp.status}")
    except Exception as exc:
        pytest.skip(f"OpenSearch not reachable on localhost:19200 – {exc}")
    return True


@pytest.fixture(scope="session")
def live_qdrant():
    """Skip if the local Qdrant service (port 16333) is not reachable."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:16333/collections", timeout=3) as resp:
            if resp.status >= 500:
                raise RuntimeError(f"Qdrant returned HTTP {resp.status}")
    except Exception as exc:
        pytest.skip(f"Qdrant not reachable on localhost:16333 – {exc}")
    return True


@pytest.fixture(scope="session")
def live_snowflake():
    """Skip if Snowflake credentials are unresolved or the source is unreachable.

    Credentials are resolved from env vars via source_config.yaml (${SF_*} refs).
    """
    from recosearch.adapters import adapter_for_type
    from recosearch.config import _source_refs

    sf_ref = next((r for r in _source_refs().values() if r.source_type == "snowflake"), None)
    if sf_ref is None:
        pytest.skip("no snowflake source declared in source_config.yaml")
    password = str(sf_ref.config.get("password") or "")
    if not password or password.startswith("${"):
        pytest.skip("SF_PASSWORD env var is not set")
    health = adapter_for_type("snowflake").health_check(sf_ref)
    if health.get("status") != "ok":
        pytest.skip(f"snowflake not reachable – {health.get('error')}")
    return True
