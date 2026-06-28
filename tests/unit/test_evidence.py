"""Offline evidence-envelope tests.

Build envelopes/citations with the canonical builders (pure functions — no live
sources) and validate the closure graph end to end.
"""
from __future__ import annotations

from recosearch.citations import _attach_citations, _provenance
from recosearch.evidence_validator import validate_cited_evidence_packet
from recosearch.evidence_schema import (
    SCHEMA_VERSION,
    validate_citation,
    validate_evidence_envelope,
)
from recosearch.federation import combine_slices


def _atomic_result(source_id, source_type, boundary, rows, *, may_support=True, status="ok", tool="probe"):
    provenance = _provenance(
        tool_name=tool,
        source=boundary,
        source_id=source_id,
        source_type=source_type,
        fields=["f"],
        user_filters=[{"field": "f", "operator": "=", "value": 1}],
        global_rules_applied=[{"rule_id": "sha256:abc123", "rule_type": "row_exclusion", "effect": "exclude", "application_mode": "enforced", "source": source_id, "table": "t", "column": "x", "operator": "!=", "value": "P003", "reason": "blacklist"}],
        row_count=len(rows),
        citation_mode="claim_support" if may_support else "exploratory",
        may_support_final_answer=may_support,
    )
    cited = _attach_citations(rows, provenance=provenance, source=boundary, prefix="x", identity_fields=["id"])
    return {"status": status, "provenance": provenance, "rows": cited}


def _evidence_id(result, row_index=0):
    return result["rows"][row_index]["_citation"]["evidence_id"]


# --- schema + canonical shape ------------------------------------------------

def test_envelope_is_schema_valid_and_query_level_citable() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [{"id": "1"}])
    env = result["provenance"]
    assert validate_evidence_envelope(env) == []
    assert env["schema_version"] == SCHEMA_VERSION
    assert env["evidence_id"] == env["provenance_id"]  # envelope is itself citable
    assert set(env["filters_by_role"]) == {"user", "default", "rule"}
    assert env["rule_impact"] and env["rule_impact"][0]["effect"] == "exclude"
    assert env["claim_mode"] == env["citation_mode"]  # no drift


def test_atomic_citation_is_schema_valid_and_backward_compatible() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [{"id": "1"}])
    citation = result["rows"][0]["_citation"]
    assert validate_citation(citation) == []
    assert citation["evidence_kind"] == "atomic"
    assert citation["source"] == "rs_pg.orders"  # old scalar key preserved
    assert citation["source_ref"]["source_type"] == "postgres"
    assert citation["contract_hash"].startswith("sha256:")


# --- query-level / absence-of-evidence ---------------------------------------

def test_zero_result_envelope_supports_absence_claim() -> None:
    result = _atomic_result("rs_qd", "qdrant", "rs_qd.policy", [], may_support=True)
    packet = {
        "claims": [{"claim": "No matching policy chunks were found.", "claim_type": "custom",
                    "required_sources": ["rs_qd.policy"], "evidence_ids": [result["provenance"]["evidence_id"]]}],
        "tool_results": [result],
    }
    assert validate_cited_evidence_packet(packet)["valid"] is True


def test_exploratory_envelope_cannot_support_claim() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [], may_support=False)
    packet = {
        "claims": [{"claim": "x", "claim_type": "custom", "evidence_ids": [result["provenance"]["evidence_id"]]}],
        "tool_results": [result],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is False
    assert out["errors"][0]["reason_code"] == "evidence_not_claim_supporting"


def test_refused_tool_output_cannot_support_claim() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [{"id": "1"}], status="refused")
    packet = {
        "claims": [{"claim": "x", "claim_type": "custom", "evidence_ids": [_evidence_id(result)]}],
        "tool_results": [result],
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is False
    assert any(e["reason_code"] == "evidence_not_claim_supporting" for e in out["errors"])


# --- contract pinning --------------------------------------------------------

def test_contract_hash_mismatch_fails_by_default_and_relaxes() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [{"id": "1"}])
    result["provenance"]["contract_hash"] = "sha256:stale"
    result["rows"][0]["_citation"]["contract_hash"] = "sha256:stale"
    packet = {
        "claims": [{"claim": "x", "claim_type": "custom", "evidence_ids": [_evidence_id(result)]}],
        "tool_results": [result],
    }
    assert any(e["reason_code"] == "contract_hash_mismatch" for e in validate_cited_evidence_packet(packet)["errors"])
    assert validate_cited_evidence_packet(packet, allow_contract_drift=True)["valid"] is True


def test_dangling_provenance_id_is_error() -> None:
    result = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [{"id": "1"}])
    result.pop("provenance")  # citation now points at a missing envelope
    packet = {
        "claims": [{"claim": "x", "claim_type": "custom", "evidence_ids": [_evidence_id(result)]}],
        "tool_results": [result],
    }
    assert any(e["reason_code"] == "dangling_provenance_id" for e in validate_cited_evidence_packet(packet)["errors"])


# --- derived evidence closure ------------------------------------------------

def _join():
    left = _atomic_result("rs_pg", "postgres", "rs_pg.orders", [{"id": "L1", "k": "J"}])
    right = _atomic_result("rs_os", "opensearch", "rs_os.reviews", [{"id": "R1", "k": "J"}])
    combined = combine_slices(left["rows"], right["rows"], left_key="k", right_key="k")
    return left, right, combined


def test_derived_closure_valid_when_all_sources_present() -> None:
    left, right, combined = _join()
    derived_citation = combined["rows"][0]["_citation"]
    assert derived_citation["evidence_kind"] == "derived"
    assert derived_citation["source_ref"]["source_type"] == "federation"
    packet = {
        "claims": [{"claim": "cross-source verdict", "claim_type": "cross_source_verdict",
                    "required_sources": ["rs_pg", "rs_os.reviews"],
                    "evidence_ids": [combined["rows"][0]["_citation"]["evidence_id"]]}],
        "tool_results": [left, right, combined],
    }
    assert validate_cited_evidence_packet(packet)["valid"] is True


def test_derived_claim_fails_if_supporting_atomic_evidence_omitted() -> None:
    # Closure test: cite the combined row but omit the original Postgres/OpenSearch
    # tool results. Mixed-source answers must cite each source separately.
    _left, _right, combined = _join()
    packet = {
        "claims": [{"claim": "cross-source verdict", "claim_type": "cross_source_verdict",
                    "required_sources": ["rs_pg", "rs_os.reviews"],
                    "evidence_ids": [combined["rows"][0]["_citation"]["evidence_id"]]}],
        "tool_results": [combined],  # supporting atomic citations are missing
    }
    out = validate_cited_evidence_packet(packet)
    assert out["valid"] is False
    assert any(e["reason_code"] == "unresolved_supporting_evidence" for e in out["errors"])


def test_derived_citation_without_supporting_ids_is_error() -> None:
    combined = combine_slices([{"id": "L", "k": "J"}], [{"id": "R", "k": "J"}], left_key="k", right_key="k")
    packet = {
        "claims": [{"claim": "x", "claim_type": "custom",
                    "evidence_ids": [combined["rows"][0]["_citation"]["evidence_id"]]}],
        "tool_results": [combined],
    }
    assert any(e["reason_code"] == "derived_missing_supporting_ids" for e in validate_cited_evidence_packet(packet)["errors"])


def test_unknown_evidence_id_is_error() -> None:
    out = validate_cited_evidence_packet({"claims": [{"claim": "x", "evidence_ids": ["nope:123"]}], "tool_results": []})
    assert out["valid"] is False
    assert out["errors"][0]["reason_code"] == "unknown_evidence_id"
