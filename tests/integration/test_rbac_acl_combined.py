"""Integration test: RBAC gate + ACL masking working together.

Scenarios tested in-process (no live sources):
- RECOSEARCH_ROLE=viewer  -> rbac_gate(run_guarded_postgres_sql) refuses (role_not_permitted)
- RECOSEARCH_ROLE=analyst -> mask_result masks customer_id to ***MASKED***
- RECOSEARCH_ROLE=admin   -> no masking applied (admin is in unmasked_roles)

Reads recosearch/rbac.py and recosearch/acl.py for exact behavior.
"""
from __future__ import annotations

import recosearch.acl as acl
import recosearch.rbac as rbac
from recosearch.acl import mask_result
from recosearch.rbac import rbac_gate


def _reset(monkeypatch, role: str | None) -> None:
    """Clear caches and set/unset the role env var."""
    acl._cache.clear()
    rbac._roles_cache = None
    rbac._summary_logged = True  # suppress stderr noise

    if role is None:
        monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    else:
        monkeypatch.setenv("RECOSEARCH_ROLE", role)


def _make_sql_tool():
    """Fake run_guarded_postgres_sql returning rows with a customer_id PII column."""
    def run_guarded_postgres_sql(plan: dict, source_id: str | None = None) -> dict:
        return {
            "status": "ok",
            "rows": [
                {
                    "customer_id": "CUST-101",
                    "product_id": "P001",
                    "_citation": {
                        "evidence_id": "x:abc",
                        "record_ref": {"customer_id": "CUST-101"},
                    },
                },
                {
                    "customer_id": "CUST-202",
                    "product_id": "P002",
                    "_citation": {
                        "evidence_id": "x:def",
                        "record_ref": {"customer_id": "CUST-202"},
                    },
                },
            ],
            "row_count": 2,
        }
    return run_guarded_postgres_sql


# ---------------------------------------------------------------------------
# viewer: rbac_gate refuses run_guarded_postgres_sql
# ---------------------------------------------------------------------------

def test_viewer_rbac_gate_refuses_sql_tool(monkeypatch) -> None:
    _reset(monkeypatch, "viewer")
    fn = _make_sql_tool()
    gated = rbac_gate(fn)
    # Should be a refusing stub, not the original function.
    assert gated is not fn
    result = gated({})
    assert result["status"] == "refused"
    assert result["reason_code"] == "role_not_permitted"
    assert result["role"] == "viewer"
    assert result["tool"] == "run_guarded_postgres_sql"


def test_viewer_refusal_has_empty_rows(monkeypatch) -> None:
    _reset(monkeypatch, "viewer")
    fn = _make_sql_tool()
    gated = rbac_gate(fn)
    result = gated({})
    assert result["rows"] == []
    assert result["row_count"] == 0


# ---------------------------------------------------------------------------
# analyst: mask_result masks customer_id column
# ---------------------------------------------------------------------------

def test_analyst_masks_customer_id(monkeypatch) -> None:
    _reset(monkeypatch, "analyst")
    fn = _make_sql_tool()
    masked_fn = mask_result(fn)
    result = masked_fn({})
    assert result["status"] == "ok"
    assert result["rows"][0]["customer_id"] == "***MASKED***"
    assert result["rows"][1]["customer_id"] == "***MASKED***"


def test_analyst_non_sensitive_field_untouched(monkeypatch) -> None:
    _reset(monkeypatch, "analyst")
    fn = _make_sql_tool()
    masked_fn = mask_result(fn)
    result = masked_fn({})
    # product_id is not sensitive — must remain visible.
    assert result["rows"][0]["product_id"] == "P001"
    assert result["rows"][1]["product_id"] == "P002"


def test_analyst_masking_metadata_present(monkeypatch) -> None:
    _reset(monkeypatch, "analyst")
    fn = _make_sql_tool()
    masked_fn = mask_result(fn)
    result = masked_fn({})
    assert result["masking"]["applied"] is True
    assert result["masking"]["role"] == "analyst"
    assert "customer_id" in result["masking"]["masked_columns"]


def test_analyst_record_ref_also_masked(monkeypatch) -> None:
    _reset(monkeypatch, "analyst")
    fn = _make_sql_tool()
    masked_fn = mask_result(fn)
    result = masked_fn({})
    # The citation record_ref must also be masked to prevent PII leaking into spans.
    assert result["rows"][0]["_citation"]["record_ref"]["customer_id"] == "***MASKED***"


# ---------------------------------------------------------------------------
# admin: no masking (admin is in unmasked_roles)
# ---------------------------------------------------------------------------

def test_admin_no_masking(monkeypatch) -> None:
    _reset(monkeypatch, "admin")
    fn = _make_sql_tool()
    masked_fn = mask_result(fn)
    # mask_result should return the original function unchanged for admin.
    assert masked_fn is fn


def test_admin_sees_clear_customer_id(monkeypatch) -> None:
    _reset(monkeypatch, "admin")
    fn = _make_sql_tool()
    masked_fn = mask_result(fn)
    result = masked_fn({})
    assert result["rows"][0]["customer_id"] == "CUST-101"
    assert "masking" not in result


# ---------------------------------------------------------------------------
# Combined: viewer blocked entirely (rbac before mask in production chain)
# ---------------------------------------------------------------------------

def test_viewer_blocked_before_masking_would_apply(monkeypatch) -> None:
    """viewer is refused by rbac_gate; masking is irrelevant — tool never runs."""
    _reset(monkeypatch, "viewer")
    fn = _make_sql_tool()
    # Build the inner part of the production chain: mask_result(rbac_gate(fn))
    chain = mask_result(rbac_gate(fn))
    result = chain({})
    assert result["status"] == "refused"
    # No rows returned, no masking metadata.
    assert "masking" not in result
