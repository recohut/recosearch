from __future__ import annotations

from typing import Any

from ..json_utils import _json_safe
from ..settings import EMBEDDING_MODEL

# Driver + model are imported lazily inside the functions below so the package
# imports cleanly when the optional qdrant/sentence-transformers extras are absent
# (e.g. a zero-infra install that only pulls the duckdb extra). With
# `from __future__ import annotations` the type hint below is never evaluated.
_EMBEDDER: "SentenceTransformer | None" = None  # noqa: F821 — lazy-imported type


def _embed_query(text: str) -> list[float]:
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415 — lazy

    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer(EMBEDDING_MODEL)
    return _EMBEDDER.encode(text, normalize_embeddings=True).tolist()


def _vector_search(query: str, *, url: str, collection: str, limit: int = 5) -> list[dict[str, Any]]:
    """Vector-search capability executor against a resolved source (url +
    collection). No business assumptions about what the vectors represent."""
    from qdrant_client import QdrantClient  # noqa: PLC0415 — lazy

    client = QdrantClient(url=str(url), check_compatibility=False)
    result = client.query_points(
        collection_name=str(collection),
        query=_embed_query(query),
        limit=max(1, min(int(limit), 10)),
        with_payload=True,
    )
    return [
        {
            "id": str(point.id),
            "score": float(point.score),
            **_json_safe(point.payload or {}),
        }
        for point in result.points
    ]


def _qdrant_health_check(ref: Any | None = None) -> dict[str, Any]:
    """Minimal reachability probe: get_collection() to confirm the collection exists."""
    from qdrant_client import QdrantClient  # noqa: PLC0415 — lazy

    if ref is None:
        raise ValueError("qdrant health_check requires a SourceRef with url and collection")
    url = str(ref.config.get("url", ""))
    collection = str(ref.config.get("collection", ""))
    client = QdrantClient(url=url, check_compatibility=False)
    info = client.get_collection(collection)
    return {"status": "ok", "points_count": info.points_count}


from .base import SourceAdapter  # noqa: E402 — after all functions are defined

ADAPTER = SourceAdapter(
    source_type="qdrant",
    capabilities=frozenset({"vector_search"}),
    run_query=_vector_search,
    sql_dialect=None,
    health_check=_qdrant_health_check,
    available=True,
    config_schema={
        "required": ["url", "collection"],
        "identifiers": ["collection"],
        "allowed": ["id", "url", "collection", "api_key", "token"],
    },
)
