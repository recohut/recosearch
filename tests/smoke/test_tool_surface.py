"""Smoke tests — tool surface.

Verifies that the public tool surface exposed by recosearch.tools is
intact: every expected tool exists as a callable, and query_documents has
the correct parameter signature (source_id, filter, projection, sort, limit).
"""
from __future__ import annotations

import inspect

import recosearch.tools as tools_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tool(name: str):
    """Return the attribute from the tools module or fail with a clear message."""
    obj = getattr(tools_module, name, None)
    assert obj is not None, (
        f"recosearch.tools.{name} does not exist"
    )
    return obj


# ---------------------------------------------------------------------------
# Existence + callable checks
# ---------------------------------------------------------------------------

def test_list_sources_exists_and_callable() -> None:
    assert callable(_get_tool("list_sources"))


def test_get_semantic_contract_exists_and_callable() -> None:
    assert callable(_get_tool("get_semantic_contract"))


def test_generate_semantic_json_exists_and_callable() -> None:
    assert callable(_get_tool("generate_semantic_json"))


def test_health_check_sources_exists_and_callable() -> None:
    assert callable(_get_tool("health_check_sources"))


def test_run_guarded_postgres_sql_exists_and_callable() -> None:
    assert callable(_get_tool("run_guarded_postgres_sql"))


def test_execute_postgres_semantic_query_exists_and_callable() -> None:
    assert callable(_get_tool("execute_postgres_semantic_query"))


def test_search_text_exists_and_callable() -> None:
    assert callable(_get_tool("search_text"))


def test_search_vector_exists_and_callable() -> None:
    assert callable(_get_tool("search_vector"))


def test_combine_slices_exists_and_callable() -> None:
    assert callable(_get_tool("combine_slices"))


def test_validate_analysis_request_exists_and_callable() -> None:
    assert callable(_get_tool("validate_analysis_request"))


def test_validate_cited_evidence_packet_exists_and_callable() -> None:
    assert callable(_get_tool("validate_cited_evidence_packet"))


def test_query_documents_exists_and_callable() -> None:
    assert callable(_get_tool("query_documents"))


# ---------------------------------------------------------------------------
# query_documents signature
# ---------------------------------------------------------------------------

def test_query_documents_signature() -> None:
    """query_documents must accept (source_id, filter, projection, sort, limit)."""
    fn = _get_tool("query_documents")
    params = list(inspect.signature(fn).parameters.keys())
    expected = ["source_id", "filter", "projection", "sort", "limit"]
    for param in expected:
        assert param in params, (
            f"query_documents is missing parameter {param!r}; "
            f"actual params: {params}"
        )
