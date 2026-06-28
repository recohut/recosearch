"""Smoke tests — adapter capabilities and contract capability routing.

Verifies that:
  - capabilities_for('postgres') includes 'structured_query'
  - capabilities_for('snowflake') includes 'structured_query'
  - capabilities_for('opensearch') includes 'text_search'
  - capabilities_for('qdrant') includes 'vector_search'
  - capabilities_for('mongodb') includes 'document_query'
  - capabilities_for('duckdb') includes 'structured_query'
  - _source_ids_with_capability resolves the right source IDs per
    capability for the live declared contract
"""
from __future__ import annotations

from recosearch.adapters import capabilities_for
from recosearch.contract import compile_semantic_contract, _source_ids_with_capability


# ---------------------------------------------------------------------------
# capabilities_for() — intrinsic adapter capability tests (no live I/O)
# ---------------------------------------------------------------------------

def test_postgres_has_structured_query() -> None:
    assert "structured_query" in capabilities_for("postgres")


def test_snowflake_has_structured_query() -> None:
    assert "structured_query" in capabilities_for("snowflake")


def test_opensearch_has_text_search() -> None:
    assert "text_search" in capabilities_for("opensearch")


def test_qdrant_has_vector_search() -> None:
    assert "vector_search" in capabilities_for("qdrant")


def test_mongodb_has_document_query() -> None:
    assert "document_query" in capabilities_for("mongodb")


def test_duckdb_has_structured_query() -> None:
    """duckdb adapter has landed and is available when the driver is installed —
    it advertises structured_query."""
    assert "structured_query" in capabilities_for("duckdb")


# ---------------------------------------------------------------------------
# _source_ids_with_capability — contract-level routing tests
# ---------------------------------------------------------------------------

def _contract():
    return compile_semantic_contract()


def test_structured_query_sources_include_postgres() -> None:
    sources = _source_ids_with_capability(_contract(), "structured_query")
    postgres_sources = [s for s in sources if "postgres" in s]
    assert postgres_sources, (
        f"Expected a postgres source in structured_query capability; got {sources}"
    )


def test_structured_query_sources_include_snowflake() -> None:
    sources = _source_ids_with_capability(_contract(), "structured_query")
    snowflake_sources = [s for s in sources if "snowflake" in s]
    assert snowflake_sources, (
        f"Expected a snowflake source in structured_query capability; got {sources}"
    )


def test_text_search_sources_include_opensearch() -> None:
    sources = _source_ids_with_capability(_contract(), "text_search")
    os_sources = [s for s in sources if "opensearch" in s]
    assert os_sources, (
        f"Expected an opensearch source in text_search capability; got {sources}"
    )


def test_vector_search_sources_include_qdrant() -> None:
    sources = _source_ids_with_capability(_contract(), "vector_search")
    qd_sources = [s for s in sources if "qdrant" in s]
    assert qd_sources, (
        f"Expected a qdrant source in vector_search capability; got {sources}"
    )


def test_document_query_sources_include_mongodb() -> None:
    sources = _source_ids_with_capability(_contract(), "document_query")
    mg_sources = [s for s in sources if "mongodb" in s]
    assert mg_sources, (
        f"Expected a mongodb source in document_query capability; got {sources}"
    )


def test_duckdb_source_has_structured_query_in_contract() -> None:
    """duckdb sources declared in source_config provide structured_query (and only
    that — never a search/document capability)."""
    contract = _contract()
    duckdb_sources = [
        source_id
        for source_id, source in contract.get("sources", {}).items()
        if isinstance(source, dict) and source.get("type") == "duckdb"
    ]
    if not duckdb_sources:
        return  # no duckdb source declared in this scenario — nothing to assert
    structured = set(_source_ids_with_capability(contract, "structured_query"))
    assert all(s in structured for s in duckdb_sources), (
        f"duckdb source(s) {duckdb_sources} should provide structured_query; got {structured}"
    )
    for capability in ("text_search", "vector_search", "document_query"):
        capable = set(_source_ids_with_capability(contract, capability))
        overlapping = [s for s in duckdb_sources if s in capable]
        assert not overlapping, (
            f"duckdb source(s) {overlapping} unexpectedly have capability {capability!r}"
        )


