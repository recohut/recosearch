from __future__ import annotations

from typing import Any, Iterable

from ..config import _source_ref_by_type
from ..errors import BoundaryError
from ..json_utils import _json_safe
from ..settings import MAX_SOURCE_ROWS


def _snowflake_ref(ref: Any | None = None):
    return ref if ref is not None else _source_ref_by_type("snowflake")


def _snowflake_connection(ref: Any | None = None):
    # Lazy import so the package imports even if the optional driver is absent.
    import snowflake.connector  # noqa: PLC0415

    cfg = _snowflake_ref(ref).config

    # The config key is 'url' (e.g. "https://<account>.snowflakecomputing.com").
    # snowflake.connector wants 'account', which is the subdomain part.
    url: str = str(cfg.get("url") or "")
    # Strip scheme and trailing path to extract the account identifier.
    account = url.replace("https://", "").replace("http://", "").split(".snowflakecomputing.com")[0]

    connect_kwargs: dict[str, Any] = {
        "account": account,
        "user": cfg.get("user"),
        "password": cfg.get("password"),
        "database": cfg.get("database"),
        "warehouse": cfg.get("warehouse"),
    }
    if cfg.get("schema"):
        connect_kwargs["schema"] = cfg["schema"]
    if cfg.get("role"):
        connect_kwargs["role"] = cfg["role"]

    return snowflake.connector.connect(**connect_kwargs)


def _fetch_snowflake(
    sql: str,
    params: Iterable[Any] = (),
    *,
    limit: int = MAX_SOURCE_ROWS,
    ref: Any | None = None,
) -> list[dict[str, Any]]:
    """Execute a read-only SQL query against Snowflake and return rows as list[dict].

    The SQL guard (validate_postgres_sql with dialect='snowflake') is applied
    upstream in tools.py before this executor is called, so we only enforce the
    row-count ceiling here and connect.
    """
    params = list(params)
    bounded_limit = max(1, min(int(limit), MAX_SOURCE_ROWS))
    cleaned = sql.strip().rstrip(";")

    conn = _snowflake_connection(ref)
    try:
        cur = conn.cursor()
        try:
            bound_sql = f"SELECT * FROM ({cleaned}) AS guarded_query LIMIT {bounded_limit}"
            cur.execute(bound_sql, params if params else None)
            columns = [desc[0] for desc in cur.description]
            return [_json_safe(dict(zip(columns, row))) for row in cur.fetchall()]
        finally:
            cur.close()
    finally:
        conn.close()


def _snowflake_health_check(ref: Any | None = None) -> dict[str, Any]:
    """Minimal connectivity check — runs SELECT 1."""
    try:
        conn = _snowflake_connection(ref)
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT 1")
                cur.fetchone()
                return {"status": "ok"}
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


from .base import SourceAdapter  # noqa: E402 — after all functions are defined

# available=True: the adapter advertises structured_query. Because it shares that
# capability with postgres, resolve_source_id cannot auto-select between them;
# callers must supply an explicit source_id when targeting snowflake.
ADAPTER = SourceAdapter(
    source_type="snowflake",
    capabilities=frozenset({"structured_query"}),
    run_query=_fetch_snowflake,
    sql_dialect="snowflake",
    health_check=_snowflake_health_check,
    available=True,
    config_schema={
        "required": ["url", "database", "warehouse", "user", "password"],
        "identifiers": ["database"],
        "allowed": ["id", "url", "database", "schema", "warehouse", "role", "user", "password"],
    },
)
