"""Offline tests for recosearch/citations.py.

Tests:
- _provenance returns expected keys and deterministic provenance_id/evidence_id
- _attach_citations adds _citation with evidence_id/source to each row
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# Patch contract-level I/O so no files are read during import or test.
_CONTRACT_ID_PATCH = "recosearch.citations._contract_id"
_CONTRACT_HASH_PATCH = "recosearch.citations._contract_hash_id"
_FAKE_CONTRACT_ID = "test_contract_id"
_FAKE_CONTRACT_HASH = "sha256:000000000000dead"


def _provenance(**kwargs):
    """Call _provenance with contract functions mocked out."""
    with (
        patch(_CONTRACT_ID_PATCH, return_value=_FAKE_CONTRACT_ID),
        patch(_CONTRACT_HASH_PATCH, return_value=_FAKE_CONTRACT_HASH),
    ):
        from recosearch.citations import _provenance as _prov
        return _prov(**kwargs)


def _attach_citations(rows, *, provenance, source, prefix, identity_fields=None):
    """Call _attach_citations with contract functions mocked out."""
    with (
        patch(_CONTRACT_ID_PATCH, return_value=_FAKE_CONTRACT_ID),
        patch(_CONTRACT_HASH_PATCH, return_value=_FAKE_CONTRACT_HASH),
    ):
        from recosearch.citations import _attach_citations as _ac
        return _ac(rows, provenance=provenance, source=source, prefix=prefix, identity_fields=identity_fields)


# ---------------------------------------------------------------------------
# _provenance — expected keys
# ---------------------------------------------------------------------------

REQUIRED_PROVENANCE_KEYS = {
    "tool_name",
    "source",
    "semantic_contract_id",
    "fields",
    "filters",
    "row_count",
    "citation_mode",
    "may_support_final_answer",
    "schema_version",
    "evidence_kind",
    "source_ref",
    "provenance_id",
    "evidence_id",
    "contract_hash",
}


def test_provenance_returns_expected_keys() -> None:
    prov = _provenance(
        tool_name="run_guarded_postgres_sql",
        source="novamart_postgres",
        source_id="novamart_postgres",
        source_type="postgres",
        row_count=3,
    )
    for key in REQUIRED_PROVENANCE_KEYS:
        assert key in prov, f"Missing expected key {key!r} in provenance"


def test_provenance_tool_name_stored() -> None:
    prov = _provenance(
        tool_name="search_text",
        source="novamart_opensearch",
    )
    assert prov["tool_name"] == "search_text"
    assert prov["source"] == "novamart_opensearch"


def test_provenance_row_count_stored() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres", row_count=42)
    assert prov["row_count"] == 42


def test_provenance_citation_mode_default() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    assert prov["citation_mode"] == "claim_support"


def test_provenance_custom_citation_mode() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres", citation_mode="exploratory")
    assert prov["citation_mode"] == "exploratory"


def test_provenance_source_ref_contains_source_id() -> None:
    prov = _provenance(
        tool_name="my_tool",
        source="novamart_postgres.orders",
        source_id="novamart_postgres",
        source_type="postgres",
    )
    ref = prov["source_ref"]
    assert ref["source_id"] == "novamart_postgres"
    assert ref["source_type"] == "postgres"


# ---------------------------------------------------------------------------
# _provenance — determinism
# ---------------------------------------------------------------------------

def test_provenance_id_deterministic_same_inputs() -> None:
    kwargs = dict(
        tool_name="run_guarded_postgres_sql",
        source="novamart_postgres",
        source_id="novamart_postgres",
        source_type="postgres",
        fields=["order_id", "total_amount"],
        row_count=5,
    )
    prov1 = _provenance(**kwargs)
    prov2 = _provenance(**kwargs)
    assert prov1["provenance_id"] == prov2["provenance_id"]
    assert prov1["evidence_id"] == prov2["evidence_id"]


def test_provenance_id_changes_with_different_tool_name() -> None:
    prov_a = _provenance(tool_name="search_text", source="novamart_opensearch")
    prov_b = _provenance(tool_name="run_guarded_postgres_sql", source="novamart_opensearch")
    # Different inputs -> (very likely) different provenance_id
    assert prov_a["provenance_id"] != prov_b["provenance_id"]


def test_provenance_evidence_id_equals_provenance_id() -> None:
    """At the query level, evidence_id == provenance_id (unified query citation)."""
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    assert prov["evidence_id"] == prov["provenance_id"]


# ---------------------------------------------------------------------------
# _attach_citations — adds _citation to each row
# ---------------------------------------------------------------------------

def test_attach_citations_adds_citation_key() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"order_id": "ORD-1", "total_amount": 100}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg")
    assert "_citation" in cited[0]


def test_attach_citations_evidence_id_present() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"order_id": "ORD-1"}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg",
                               identity_fields=["order_id"])
    citation = cited[0]["_citation"]
    assert "evidence_id" in citation
    assert citation["evidence_id"]


def test_attach_citations_source_stored_in_citation() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_opensearch")
    rows = [{"review_id": "R1"}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_opensearch", prefix="es",
                               identity_fields=["review_id"])
    assert cited[0]["_citation"]["source"] == "novamart_opensearch"


def test_attach_citations_record_ref_uses_identity_fields() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"order_id": "ORD-2", "customer_id": "CUST-1", "total_amount": 50}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg",
                               identity_fields=["order_id"])
    record_ref = cited[0]["_citation"]["record_ref"]
    # Only the identity field(s) in record_ref
    assert record_ref == {"order_id": "ORD-2"}


def test_attach_citations_row_index_fallback_when_no_identity_fields() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"total_amount": 99}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg")
    record_ref = cited[0]["_citation"]["record_ref"]
    assert "row_index" in record_ref
    assert record_ref["row_index"] == 0


def test_attach_citations_evidence_id_deterministic() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"order_id": "ORD-99"}]
    cited1 = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg",
                                identity_fields=["order_id"])
    cited2 = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg",
                                identity_fields=["order_id"])
    assert cited1[0]["_citation"]["evidence_id"] == cited2[0]["_citation"]["evidence_id"]


def test_attach_citations_multiple_rows_distinct_evidence_ids() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"order_id": "ORD-1"}, {"order_id": "ORD-2"}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg",
                               identity_fields=["order_id"])
    eid1 = cited[0]["_citation"]["evidence_id"]
    eid2 = cited[1]["_citation"]["evidence_id"]
    # Rows with different keys get different evidence_ids
    assert eid1 != eid2


def test_attach_citations_original_row_fields_preserved() -> None:
    prov = _provenance(tool_name="my_tool", source="novamart_postgres")
    rows = [{"order_id": "ORD-3", "channel": "Shopify"}]
    cited = _attach_citations(rows, provenance=prov, source="novamart_postgres", prefix="pg")
    assert cited[0]["order_id"] == "ORD-3"
    assert cited[0]["channel"] == "Shopify"
