"""DuckDB adapter — structured_query against a local DuckDB database file.

DuckDB needs no server: a single ``.duckdb`` file (or in-memory database) is the
whole source. This makes it the zero-infrastructure adapter — the one used by the
bundled ``examples/novashop-duckdb`` scenario so RecoSearch can be run end to end
with no external services. See docs/usage/getting-started.md.

Governance (read-only SQL guard, semantic-allowlist validation, global rules,
citation tracking, RBAC, field masking) is applied UPSTREAM in tools.py before
``run_query`` is ever called — exactly as for every other adapter. This module
only opens the file read-only, normalises placeholders, enforces the row ceiling,
and returns rows as ``list[dict]``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Iterable

from ..config import _source_ref_by_type
from ..json_utils import _json_safe
from ..settings import MAX_SOURCE_ROWS, ROOT, SEMANTIC_DIR


def _duckdb_ref(ref: Any | None = None):
    return ref if ref is not None else _source_ref_by_type("duckdb")


def _resolve_db_path(raw: Any) -> str:
    """Resolve the declared ``path`` to a concrete database file.

    A relative path is resolved against (in order) the active scenario directory
    and the repo root, so a committed example DB declared as ``./data/foo.duckdb``
    is found regardless of the process working directory. An absolute path or the
    in-memory marker ``:memory:`` is used verbatim. The first existing candidate
    wins; if none exists the scenario-relative candidate is returned so the
    connection fails with a clear, locatable path.
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError("duckdb source is missing required key 'path'")
    if text == ":memory:":
        return text
    p = Path(text).expanduser()
    if p.is_absolute():
        return str(p)
    candidates = [SEMANTIC_DIR / text, ROOT / text, Path.cwd() / text]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


def _duckdb_connection(ref: Any | None = None, *, read_only: bool = True):
    # Lazy import so the package imports even when the optional duckdb driver is
    # absent (capabilities are gated on availability via find_spec below).
    import duckdb  # noqa: PLC0415

    cfg = _duckdb_ref(ref).config
    path = _resolve_db_path(cfg.get("path"))
    # :memory: cannot be opened read-only; everything else is opened read-only as
    # a defence-in-depth layer on top of the upstream SELECT-only guard.
    if path == ":memory:":
        return duckdb.connect(database=path)
    return duckdb.connect(database=path, read_only=read_only)


def _fetch_duckdb(
    sql: str,
    params: Iterable[Any] = (),
    *,
    limit: int = MAX_SOURCE_ROWS,
    ref: Any | None = None,
) -> list[dict[str, Any]]:
    """Execute a read-only query against the DuckDB file and return rows.

    The upstream compiler emits psycopg2-style ``%s`` placeholders (shared with
    the Postgres path); DuckDB uses ``?``. The compiler only ever emits ``%s`` as
    a bind placeholder — never inside a literal — so a direct substitution is
    safe. ``= ANY(?)`` (used for ``in`` filters) is native DuckDB.
    """
    params = list(params)
    bounded_limit = max(1, min(int(limit), MAX_SOURCE_ROWS))
    cleaned = sql.strip().rstrip(";").replace("%s", "?")

    conn = _duckdb_connection(ref)
    try:
        bounded_sql = f"SELECT * FROM ({cleaned}) AS guarded_query LIMIT {bounded_limit}"
        result = conn.execute(bounded_sql, params)
        columns = [desc[0] for desc in result.description]
        return [_json_safe(dict(zip(columns, row))) for row in result.fetchall()]
    finally:
        conn.close()


def _duckdb_health_check(ref: Any | None = None) -> dict[str, Any]:
    """Open the database read-only and run a trivial probe."""
    try:
        conn = _duckdb_connection(ref)
        try:
            conn.execute("SELECT 1").fetchone()
            return {"status": "ok"}
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


from .base import SourceAdapter  # noqa: E402 — after all functions are defined

# available is gated on the driver being importable: with the duckdb extra absent
# the source is reported 'unavailable' (placeholder) rather than crashing import
# or failing every probe.
ADAPTER = SourceAdapter(
    source_type="duckdb",
    capabilities=frozenset({"structured_query"}),
    run_query=_fetch_duckdb,
    sql_dialect="duckdb",
    health_check=_duckdb_health_check,
    available=importlib.util.find_spec("duckdb") is not None,
    config_schema={
        "required": ["path"],
        "identifiers": [],
        "allowed": ["id", "path", "database", "schema", "read_only"],
    },
)
