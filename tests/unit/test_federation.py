"""Offline federation guard tests for combine_slices. No live sources.

Covers the Front 7 tightening: declared-relation enforcement (source-pair) and
fail-closed behavior on missing/null join keys. Uses real declared relations
from the live contract (postgres<->opensearch is declared; postgres<->qdrant is
not).
"""
from __future__ import annotations

from recosearch.federation import combine_slices


def _row(source_id: str, key: str, value, **extra):
    return {
        key: value,
        "_citation": {"evidence_id": f"{source_id}:{value}", "source_ref": {"source_id": source_id}},
        **extra,
    }


def test_declared_relation_join_succeeds() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", units=7)]
    right = [_row("novamart_opensearch", "product_id", "P009", review="great")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"
    assert out["row_count"] == 1
    assert out["rows"][0]["_citation"]["supporting_evidence_ids"]


def test_undeclared_relation_is_refused() -> None:
    # No declared relation connects postgres and qdrant.
    left = [_row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_qdrant", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "refused"
    assert out["reason_code"] == "undeclared_relation"


def test_missing_join_key_fails_closed() -> None:
    left = [_row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_opensearch", "order_id", "ORD-1")]  # lacks product_id
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "refused"
    assert out["reason_code"] == "join_key_missing" and out["side"] == "right"


def test_null_keys_do_not_spurious_match() -> None:
    # Both sides present the key but with null values — must NOT join on None.
    left = [_row("novamart_postgres", "product_id", None), _row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_opensearch", "product_id", None), _row("novamart_opensearch", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"
    # Only the real P009<->P009 pair, never None<->None.
    assert out["row_count"] == 1


def test_exact_default_does_not_match_case_difference() -> None:
    left = [_row("novamart_postgres", "product_id", "p009")]
    right = [_row("novamart_opensearch", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["match_strategy"] == "exact"
    assert out["row_count"] == 0  # exact is strict


def test_casefold_strategy_matches_case_insensitive() -> None:
    left = [_row("novamart_postgres", "product_id", "p009")]
    right = [_row("novamart_opensearch", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id", match_strategy="casefold")
    assert out["status"] == "ok" and out["row_count"] == 1


def test_unknown_match_strategy_refused() -> None:
    left = [_row("novamart_postgres", "product_id", "P009")]
    right = [_row("novamart_opensearch", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id", match_strategy="fuzzy")
    assert out["status"] == "refused" and out["reason_code"] == "unknown_match_strategy"


def test_conflict_surfaced_on_shared_field_mismatch() -> None:
    # Same matched entity, but the two sources disagree on 'category'.
    left = [_row("novamart_postgres", "product_id", "P009", category="Toys")]
    right = [_row("novamart_opensearch", "product_id", "P009", category="Beauty")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["row_count"] == 1
    assert out["conflict_count"] == 1
    conflict = out["conflicts"][0]
    assert conflict["field"] == "category"
    assert conflict["left_value"] == "Toys" and conflict["right_value"] == "Beauty"
    assert conflict["join_value"] == "P009"


def test_no_conflict_when_sides_agree() -> None:
    left = [_row("novamart_postgres", "product_id", "P009", category="Toys")]
    right = [_row("novamart_opensearch", "product_id", "P009", category="Toys")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["conflict_count"] == 0


def test_undeclared_source_skips_relation_check() -> None:
    # A slice with no citation has an undeterminable source, so the relation
    # check is skipped (never happens on the live tool path); the join proceeds
    # and missing supporting citations are caught downstream, not here.
    left = [{"product_id": "P009"}]  # no citation -> source can't be established
    right = [_row("novamart_opensearch", "product_id", "P009")]
    out = combine_slices(left, right, left_key="product_id", right_key="product_id")
    assert out["status"] == "ok"
    assert out["row_count"] == 1
