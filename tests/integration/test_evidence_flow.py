"""Integration test: evidence provenance + packet validation flow (in-process).

Covers:
- Build a provenance envelope via recosearch.citations._provenance.
- Attach row citations via _attach_citations.
- Assemble a packet and validate it with validate_cited_evidence_packet -> valid True.
- A packet with a dangling evidence_id (citation referencing missing envelope) -> error.

Follows the pattern from tests/unit/test_evidence.py: _atomic_result helper
produces self-consistent provenances with all required fields.
"""
from __future__ import annotations

from recosearch.citations import _attach_citations, _provenance
from recosearch.evidence_validator import validate_cited_evidence_packet


# ---------------------------------------------------------------------------
# Helpers (mirroring the _atomic_result pattern from test_evidence.py)
# ---------------------------------------------------------------------------

def _make_provenance(
    source_id: str,
    source_type: str,
    boundary: str,
    rows: list[dict],
    *,
    may_support: bool = True,
):
    return _provenance(
        tool_name="run_guarded_postgres_sql",
        source=boundary,
        source_id=source_id,
        source_type=source_type,
        fields=["product_id"],
        user_filters=[{"field": "product_id", "operator": "=", "value": "P001"}],
        global_rules_applied=[
            {
                "rule_id": "sha256:abc123",
                "rule_type": "row_exclusion",
                "effect": "exclude",
                "application_mode": "enforced",
                "source": source_id,
                "table": "products",
                "column": "status",
                "operator": "!=",
                "value": "active",
                "reason": "filter inactive",
            }
        ],
        row_count=len(rows),
        citation_mode="claim_support" if may_support else "exploratory",
        may_support_final_answer=may_support,
    )


def _atomic_result(
    source_id: str,
    source_type: str,
    boundary: str,
    rows: list[dict],
    *,
    may_support: bool = True,
):
    prov = _make_provenance(source_id, source_type, boundary, rows, may_support=may_support)
    cited_rows = _attach_citations(
        rows,
        provenance=prov,
        source=boundary,
        prefix="pg",
        identity_fields=["id"],
    )
    return {"status": "ok", "provenance": prov, "rows": cited_rows}


def _evidence_id(result, row_index: int = 0) -> str:
    return result["rows"][row_index]["_citation"]["evidence_id"]


# ---------------------------------------------------------------------------
# Happy path: provenance built, rows cited, packet validates as valid
# ---------------------------------------------------------------------------

def test_provenance_has_required_fields() -> None:
    prov = _make_provenance("rs_pg", "postgres", "rs_pg.products", [{"id": "1"}])
    assert prov["provenance_id"]
    assert prov["evidence_id"] == prov["provenance_id"]
    assert prov["schema_version"]
    assert prov["contract_hash"].startswith("sha256:")


def test_attached_citations_have_evidence_ids() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "1"}])
    citation = result["rows"][0]["_citation"]
    assert citation["evidence_id"]
    assert citation["provenance_id"] == result["provenance"]["provenance_id"]


def test_valid_packet_validates_true() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "1"}])
    packet = {
        "claims": [
            {
                "claim": "Product P001 has 10 units.",
                "claim_type": "custom",
                "evidence_ids": [_evidence_id(result)],
            }
        ],
        "tool_results": [result],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is True
    assert out["status"] == "ok"


def test_valid_packet_no_errors() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "1"}])
    packet = {
        "claims": [
            {
                "claim": "Claim about product.",
                "claim_type": "custom",
                "evidence_ids": [_evidence_id(result)],
            }
        ],
        "tool_results": [result],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["errors"] == []


def test_valid_packet_with_envelope_citation() -> None:
    """Citing the query-level envelope (provenance_id) instead of a row evidence_id."""
    result = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "1"}])
    prov_eid = result["provenance"]["evidence_id"]
    packet = {
        "claims": [
            {
                "claim": "Result from rs_pg.products.",
                "claim_type": "custom",
                "evidence_ids": [prov_eid],
            }
        ],
        "tool_results": [result],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is True


# ---------------------------------------------------------------------------
# Dangling evidence id: citation references a missing provenance envelope
# ---------------------------------------------------------------------------

def test_dangling_evidence_id_is_error() -> None:
    """An evidence_id that appears in no tool_result's rows or provenance -> error."""
    packet = {
        "claims": [
            {
                "claim": "Some claim.",
                "claim_type": "custom",
                "evidence_ids": ["nope:deadbeef"],
            }
        ],
        "tool_results": [],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is False
    assert any(e["reason_code"] == "unknown_evidence_id" for e in out["errors"])


def test_dangling_provenance_id_is_error() -> None:
    """Row citation references a provenance_id not present in tool_results."""
    result = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "2"}])
    # Remove the provenance envelope so the citation dangles.
    result_without_prov = {k: v for k, v in result.items() if k != "provenance"}
    packet = {
        "claims": [
            {
                "claim": "Dangling.",
                "claim_type": "custom",
                "evidence_ids": [_evidence_id(result)],
            }
        ],
        "tool_results": [result_without_prov],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is False
    assert any(e["reason_code"] == "dangling_provenance_id" for e in out["errors"])


# ---------------------------------------------------------------------------
# Edge cases: empty rows, multiple claims
# ---------------------------------------------------------------------------

def test_zero_row_result_with_absence_claim() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.products", [], may_support=True)
    prov_eid = result["provenance"]["evidence_id"]
    packet = {
        "claims": [
            {
                "claim": "No products matched.",
                "claim_type": "custom",
                "required_sources": ["rs_pg.products"],
                "evidence_ids": [prov_eid],
            }
        ],
        "tool_results": [result],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is True


def test_multiple_claims_both_valid() -> None:
    r1 = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "1"}])
    r2 = _atomic_result("rs_pg", "postgres", "rs_pg.products", [{"id": "2"}])
    packet = {
        "claims": [
            {"claim": "Claim A.", "claim_type": "custom", "evidence_ids": [_evidence_id(r1)]},
            {"claim": "Claim B.", "claim_type": "custom", "evidence_ids": [_evidence_id(r2)]},
        ],
        "tool_results": [r1, r2],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is True
