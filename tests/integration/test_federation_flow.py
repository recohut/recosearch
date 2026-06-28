"""Integration test: combine_slices federation flow (in-process, no live DB).

Covers:
- Declared-relation join (postgres + opensearch on a shared key) ->
  status ok with per-source citations (supporting_evidence_ids populated).
- Undeclared source pair (postgres + qdrant) -> status refused, reason_code
  undeclared_relation.
- Conflicting shared field surfaced in conflicts list.

Uses the _row helper from tests/unit/test_federation.py as the citation shape
contract: source_id in _citation.source_ref.source_id, evidence_id as prefix:value.
"""
from __future__ import annotations

from recosearch.federation import combine_slices


def _row(source_id: str, key: str, value, **extra):
    """Build a cited row matching the production citation shape combine_slices expects."""
    return {
        key: value,
        "_citation": {
            "evidence_id": f"{source_id}:{value}",
            "source_ref": {"source_id": source_id},
            "may_support_final_answer": True,
        },
        **extra,
    }


# ---------------------------------------------------------------------------
# Declared-relation join: postgres <-> opensearch (declared in semantic contract)
# ---------------------------------------------------------------------------

def test_declared_relation_join_returns_ok() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", units=7)]
    right = [_row("novamart_opensearch", "product_id", "P009", review="excellent")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"


def test_declared_relation_join_row_count() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", units=7)]
    right = [_row("novamart_opensearch", "product_id", "P009", review="excellent")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["row_count"] == 1
    assert len(out["rows"]) == 1


def test_declared_relation_join_has_supporting_evidence_ids() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", units=7)]
    right = [_row("novamart_opensearch", "product_id", "P009", review="excellent")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    citation = out["rows"][0]["_citation"]
    # Derived citation must carry ids from both source citations.
    assert citation["supporting_evidence_ids"]
    assert len(citation["supporting_evidence_ids"]) == 2


def test_declared_relation_multiple_rows_joined() -> None:
    left = [
        _row("novamart_postgres", "product_id", "P001", units=3),
        _row("novamart_postgres", "product_id", "P002", units=9),
    ]
    right = [
        _row("novamart_opensearch", "product_id", "P001", review="ok"),
        _row("novamart_opensearch", "product_id", "P002", review="great"),
    ]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"
    assert out["row_count"] == 2


def test_declared_relation_provenance_envelope_present() -> None:
    left = [_row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_opensearch", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    # Provenance envelope must be included for evidence closure.
    assert "provenance" in out
    assert out["provenance"]["evidence_id"]


# ---------------------------------------------------------------------------
# Undeclared source pair: postgres <-> qdrant (not declared in contract)
# ---------------------------------------------------------------------------

def test_undeclared_relation_is_refused() -> None:
    left = [_row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_qdrant", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "refused"
    assert out["reason_code"] == "undeclared_relation"


def test_undeclared_relation_has_empty_rows() -> None:
    left = [_row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_qdrant", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["rows"] == []
    assert out["row_count"] == 0


# ---------------------------------------------------------------------------
# Conflicting shared field: both sides disagree on a non-key field
# ---------------------------------------------------------------------------

def test_conflict_surfaced_on_shared_field_mismatch() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", category="Toys")]
    right = [_row("novamart_opensearch", "product_id", "P009", category="Beauty")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"
    assert out["conflict_count"] == 1
    conflict = out["conflicts"][0]
    assert conflict["field"] == "category"
    assert conflict["left_value"] == "Toys"
    assert conflict["right_value"] == "Beauty"
    assert conflict["join_value"] == "P009"


def test_no_conflict_when_sides_agree() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", category="Toys")]
    right = [_row("novamart_opensearch", "product_id", "P009", category="Toys")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"
    assert out["conflict_count"] == 0
    assert out["conflicts"] == []


def test_multiple_conflicts_all_surfaced() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", category="Toys", brand="Acme")]
    right = [_row("novamart_opensearch", "product_id", "P009", category="Beauty", brand="Beta")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["conflict_count"] == 2
