from __future__ import annotations

from typing import Any

from ..config import _source_ref_by_type
from ..json_utils import _json_safe
from ..settings import MAX_SOURCE_ROWS


def _mongo_ref(ref: Any | None = None):
    return ref if ref is not None else _source_ref_by_type("mongodb")


def _mongo_connection(ref: Any | None = None):
    # Lazy import so the package imports even if the optional driver is absent.
    import pymongo  # noqa: PLC0415

    cfg = _mongo_ref(ref).config

    url: str = str(cfg.get("url") or "")
    user = cfg.get("user")
    password = cfg.get("password")
    database = str(cfg.get("database") or "")

    # Build the MongoClient; if url already contains credentials, username/password
    # kwargs are still accepted by pymongo and take precedence.
    connect_kwargs: dict[str, Any] = {}
    if user:
        connect_kwargs["username"] = user
    if password:
        connect_kwargs["password"] = password

    client = pymongo.MongoClient(url, **connect_kwargs)
    return client[database]


def _mongo_find(
    query: dict[str, Any],
    *,
    ref: Any | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Execute a read-only find() against a MongoDB collection and return rows as list[dict].

    ``query`` must be a dict with keys:
      - collection (str): collection name to query
      - filter (dict): MongoDB filter document (empty dict = match-all)
      - projection (list | None): list of field names to include, or None for all fields
      - sort (list[[field, 1|-1]] | None): sort specification pairs, or None

    The SQL/doc guard runs upstream in tools.py; here we only enforce the row cap
    and execute the find.
    """
    bounded_limit = max(1, min(int(limit), MAX_SOURCE_ROWS))

    collection_name: str = str(query.get("collection") or "")
    filter_doc: dict[str, Any] = query.get("filter") or {}
    projection_spec = query.get("projection")
    sort_spec = query.get("sort")

    db = _mongo_connection(ref)
    collection = db[collection_name]

    # Build projection dict from list of field names (include mode).
    mongo_projection: dict[str, int] | None = None
    if projection_spec is not None:
        mongo_projection = {field: 1 for field in projection_spec}

    cursor = collection.find(filter_doc, mongo_projection)

    if sort_spec is not None:
        cursor = cursor.sort(sort_spec)

    cursor = cursor.limit(bounded_limit)

    rows: list[dict[str, Any]] = []
    for doc in cursor:
        # Convert ObjectId _id to str so JSON serialisation works.
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        rows.append(_json_safe(doc))

    return rows


def _mongo_health_check(ref: Any | None = None) -> dict[str, Any]:
    """Minimal connectivity check — runs db.command('ping')."""
    try:
        db = _mongo_connection(ref)
        db.command("ping")
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


from .base import SourceAdapter  # noqa: E402 — after all functions are defined

ADAPTER = SourceAdapter(
    source_type="mongodb",
    capabilities=frozenset({"document_query"}),
    run_query=_mongo_find,
    sql_dialect=None,
    health_check=_mongo_health_check,
    available=True,
    config_schema={
        "required": ["url", "database", "collection"],
        "identifiers": ["database", "collection"],
        "allowed": ["id", "url", "database", "collection", "user", "password"],
    },
)
