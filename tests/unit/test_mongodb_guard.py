"""Offline MongoDB adapter tests.

No live MongoDB connection is required. The adapter's executor (_mongo_find /
ADAPTERS['mongodb'].run_query) is monkeypatched to return a fixed list of
fake documents.  Guard tests exercise the query_documents GUARD path that runs
before execution, so those tests need no DB patch at all.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_DOCS = [
    {"seller_id": "SEL-03", "event_type": "payout", "event_id": "E1"},
]


def _patch_mongo_run_query(monkeypatch) -> None:
    """Replace the mongodb adapter's run_query with a no-op that returns _FAKE_DOCS.

    ADAPTERS is a plain dict in recosearch.adapters; we swap out the entry
    with a new SourceAdapter whose run_query returns our fake rows.  The frozen
    dataclass prohibits in-place mutation, so we replace the whole entry.
    """
    from recosearch.adapters import ADAPTERS
    from recosearch.adapters.base import SourceAdapter

    original = ADAPTERS["mongodb"]
    fake_adapter = SourceAdapter(
        source_type="mongodb",
        capabilities=original.capabilities,
        run_query=lambda q, ref=None, limit=100: list(_FAKE_DOCS),
        health_check=original.health_check,
        sql_dialect=original.sql_dialect,
        available=original.available,
        config_schema=original.config_schema,
    )
    monkeypatch.setitem(ADAPTERS, "mongodb", fake_adapter)


# ---------------------------------------------------------------------------
# 1. Happy-path: query_documents returns ok, rows carry _citation, source_boundary
#    mentions the mongo source.
# ---------------------------------------------------------------------------

def test_query_documents_ok_with_patched_adapter(monkeypatch) -> None:
    """query_documents returns status 'ok' and rows with _citation when the
    adapter is monkeypatched to return fake documents."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    _patch_mongo_run_query(monkeypatch)

    from recosearch.tools import query_documents

    result = query_documents(filter={"seller_id": "SEL-03"})

    assert result["status"] == "ok"
    assert result["row_count"] > 0
    assert len(result["rows"]) == result["row_count"]


def test_query_documents_rows_carry_citation(monkeypatch) -> None:
    """Every row returned by query_documents must include a '_citation' key."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    _patch_mongo_run_query(monkeypatch)

    from recosearch.tools import query_documents

    result = query_documents(filter={"seller_id": "SEL-03"})

    assert result["status"] == "ok"
    for row in result["rows"]:
        assert "_citation" in row, f"row missing _citation: {row}"


def test_query_documents_citation_has_expected_keys(monkeypatch) -> None:
    """_citation must contain at minimum evidence_id, source_ref, and record_ref."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    _patch_mongo_run_query(monkeypatch)

    from recosearch.tools import query_documents

    result = query_documents(filter={"seller_id": "SEL-03"})

    citation = result["rows"][0]["_citation"]
    assert "evidence_id" in citation
    assert "source_ref" in citation
    assert "record_ref" in citation


def test_query_documents_source_boundary_mentions_mongo_source(monkeypatch) -> None:
    """source_boundary must reference the declared mongo source (novamart_mongodb)."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    _patch_mongo_run_query(monkeypatch)

    from recosearch.tools import query_documents

    result = query_documents(filter={"seller_id": "SEL-03"})

    assert "novamart_mongodb" in result["source_boundary"]


def test_query_documents_no_filter_returns_docs(monkeypatch) -> None:
    """query_documents with an empty filter returns the fake documents."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    _patch_mongo_run_query(monkeypatch)

    from recosearch.tools import query_documents

    result = query_documents()

    assert result["status"] == "ok"
    assert result["row_count"] > 0


# ---------------------------------------------------------------------------
# 2. Guard refusals — run BEFORE execution; no DB patch needed.
# ---------------------------------------------------------------------------

def test_guard_undeclared_filter_field_is_refused(monkeypatch) -> None:
    """A filter key that is not declared in the semantic contract must be refused
    with reason_code 'field_not_allowed'."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)

    from recosearch.tools import query_documents

    result = query_documents(filter={"bad_field_xyz": "anything"})

    assert result["status"] == "refused"
    assert result["reason_code"] == "field_not_allowed"


def test_guard_undeclared_filter_field_rows_empty(monkeypatch) -> None:
    """A guard refusal must return an empty rows list and row_count == 0."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)

    from recosearch.tools import query_documents

    result = query_documents(filter={"nonexistent_column": "value"})

    assert result["rows"] == []
    assert result["row_count"] == 0


def test_guard_operator_not_allowed_regex(monkeypatch) -> None:
    """A filter using the 'regex' operator (not in the allowed set) must be
    refused with reason_code 'operator_not_allowed'."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)

    from recosearch.tools import query_documents

    result = query_documents(filter={"event_type": {"regex": "payout.*"}})

    assert result["status"] == "refused"
    assert result["reason_code"] == "operator_not_allowed"


def test_guard_operator_not_allowed_where(monkeypatch) -> None:
    """The 'where' operator is also not in the allowed set and must be refused."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)

    from recosearch.tools import query_documents

    result = query_documents(filter={"seller_id": {"where": "true"}})

    assert result["status"] == "refused"
    assert result["reason_code"] == "operator_not_allowed"


def test_guard_dollar_key_refused_not_read_only(monkeypatch) -> None:
    """A filter key that starts with '$' (e.g. '$where') must be refused with
    reason_code 'not_read_only'."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)

    from recosearch.tools import query_documents

    result = query_documents(filter={"$where": "this.event_id == 'E1'"})

    assert result["status"] == "refused"
    assert result["reason_code"] == "not_read_only"


def test_guard_dollar_in_value_dict_refused_not_read_only(monkeypatch) -> None:
    """A filter value dict whose key starts with '$' (e.g. {'$gt': 0}) is a raw
    Mongo operator injection and must be refused with reason_code 'not_read_only'."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)

    from recosearch.tools import query_documents

    result = query_documents(filter={"seller_id": {"$gt": ""}})

    assert result["status"] == "refused"
    assert result["reason_code"] == "not_read_only"


def test_guard_allowed_operators_are_accepted(monkeypatch) -> None:
    """Known-safe operators (eq, gt, lt, in, etc.) must NOT trigger a guard
    refusal (execution then runs through the patched adapter)."""
    monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    _patch_mongo_run_query(monkeypatch)

    from recosearch.tools import query_documents

    # 'eq' is in the allowed operator set
    result = query_documents(filter={"seller_id": {"eq": "SEL-03"}})

    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# 3. Capability wiring: capabilities_for('mongodb') == {'document_query'}.
# ---------------------------------------------------------------------------

def test_capabilities_for_mongodb_returns_document_query() -> None:
    """The mongodb adapter must advertise exactly the 'document_query' capability."""
    from recosearch.adapters import capabilities_for

    assert capabilities_for("mongodb") == {"document_query"}


def test_mongodb_adapter_is_available() -> None:
    """The mongodb adapter must be marked available=True so its capabilities
    are included in the advertised ADAPTER_CAPABILITIES map."""
    from recosearch.adapters import adapter_for_type

    adapter = adapter_for_type("mongodb")
    assert adapter is not None
    assert adapter.available is True


def test_mongodb_adapter_source_type() -> None:
    """The mongodb adapter's source_type must be 'mongodb'."""
    from recosearch.adapters import adapter_for_type

    adapter = adapter_for_type("mongodb")
    assert adapter is not None
    assert adapter.source_type == "mongodb"


def test_mongodb_capability_in_adapter_capabilities_map() -> None:
    """ADAPTER_CAPABILITIES must include 'mongodb' -> {'document_query'}."""
    from recosearch.adapters import ADAPTER_CAPABILITIES

    assert "mongodb" in ADAPTER_CAPABILITIES
    assert ADAPTER_CAPABILITIES["mongodb"] == {"document_query"}


def test_mongodb_suggested_tool_is_query_documents() -> None:
    """suggested_tools_for('mongodb') must include 'query_documents'."""
    from recosearch.adapters import suggested_tools_for

    tools = suggested_tools_for("mongodb")
    assert "query_documents" in tools
