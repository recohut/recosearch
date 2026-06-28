"""Offline DuckDB adapter tests — exercise the executor, placeholder translation,
and health check against a temporary on-disk database (no external services)."""
from __future__ import annotations

import duckdb
import pytest

from recosearch.adapters.duckdb import (
    ADAPTER,
    _duckdb_health_check,
    _fetch_duckdb,
    _resolve_db_path,
)
from recosearch.config import SourceRef


def _ref(path: str) -> SourceRef:
    return SourceRef(source_id="t", source_type="duckdb", config_key="duckdb", config={"path": path})


@pytest.fixture()
def db_path(tmp_path) -> str:
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t(id INTEGER, name VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(1, "a"), (2, "b"), (3, "c")])
    con.close()
    return str(path)


def test_adapter_declares_duckdb_structured_query() -> None:
    assert ADAPTER.source_type == "duckdb"
    assert ADAPTER.capabilities == frozenset({"structured_query"})
    assert ADAPTER.sql_dialect == "duckdb"


def test_health_check_ok(db_path: str) -> None:
    assert _duckdb_health_check(_ref(db_path)) == {"status": "ok"}


def test_health_check_missing_file_errors(tmp_path) -> None:
    result = _duckdb_health_check(_ref(str(tmp_path / "nope.duckdb")))
    assert result["status"] == "error"


def test_fetch_translates_psycopg2_placeholders(db_path: str) -> None:
    # The shared compiler emits %s placeholders; the adapter must translate to ?.
    rows = _fetch_duckdb("SELECT id, name FROM t WHERE id != %s", ["3"], limit=10, ref=_ref(db_path))
    assert {r["name"] for r in rows} == {"a", "b"}


def test_fetch_supports_any_for_in_filters(db_path: str) -> None:
    # `in` filters compile to `= ANY(%s)`; DuckDB supports `= ANY(?)` natively.
    rows = _fetch_duckdb("SELECT id FROM t WHERE id = ANY(%s)", [[1, 2]], limit=10, ref=_ref(db_path))
    assert {r["id"] for r in rows} == {1, 2}


def test_fetch_enforces_row_ceiling(db_path: str) -> None:
    rows = _fetch_duckdb("SELECT id FROM t", limit=2, ref=_ref(db_path))
    assert len(rows) == 2


def test_resolve_db_path_keeps_absolute(tmp_path) -> None:
    p = tmp_path / "x.duckdb"
    p.write_bytes(b"")
    assert _resolve_db_path(str(p)) == str(p)


def test_resolve_db_path_rejects_empty() -> None:
    with pytest.raises(ValueError):
        _resolve_db_path("")
