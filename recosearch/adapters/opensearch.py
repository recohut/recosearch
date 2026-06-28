from __future__ import annotations

from typing import Any, Mapping

from ..json_utils import _json_safe


def _opensearch_search(body: Mapping[str, Any], *, url: str, index: str) -> list[dict[str, Any]]:
    """Execute a text-search query against a resolved source (url + index).

    Source selection / boundary is enforced upstream by the capability resolver;
    this is just the text_search capability executor (no business assumptions)."""
    import requests  # noqa: PLC0415 — lazy so the package imports without this driver

    search_url = f"{str(url).rstrip('/')}/{index}/_search"
    response = requests.get(search_url, json=body, timeout=10)
    response.raise_for_status()
    hits = response.json().get("hits", {}).get("hits", [])
    return [
        {
            **_json_safe(hit.get("_source", {})),
            "_score": hit.get("_score"),
            "_id": hit.get("_id"),
        }
        for hit in hits
    ]


def _opensearch_health_check(ref: Any | None = None) -> dict[str, Any]:
    """Minimal reachability probe: GET /{index}/_count and return the document count."""
    # ref is a SourceRef with .config dict; fall back to None means caller must pass ref.
    import requests  # noqa: PLC0415 — lazy so the package imports without this driver

    if ref is None:
        raise ValueError("opensearch health_check requires a SourceRef with url and index")
    url = str(ref.config.get("url", "")).rstrip("/")
    index = str(ref.config.get("index", ""))
    count_url = f"{url}/{index}/_count"
    response = requests.get(count_url, timeout=10)
    response.raise_for_status()
    count = response.json().get("count")
    return {"status": "ok", "count": count}


from .base import SourceAdapter  # noqa: E402 — after all functions are defined

ADAPTER = SourceAdapter(
    source_type="opensearch",
    capabilities=frozenset({"text_search"}),
    run_query=_opensearch_search,
    sql_dialect=None,
    health_check=_opensearch_health_check,
    available=True,
    config_schema={
        "required": ["url", "index"],
        "identifiers": ["index"],
        "allowed": ["id", "url", "index", "user", "password", "token", "api_key"],
    },
)
