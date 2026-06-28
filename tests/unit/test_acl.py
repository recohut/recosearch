"""Offline ACL / masking tests. No live sources. Verifies role-based masking of
sensitive columns and the opt-in semantics (unset role / unmasked role = no-op).
"""
from __future__ import annotations

import recosearch.acl as acl
from recosearch.acl import mask_result, mask_rows, masking_active, sensitive_columns


def _reset(monkeypatch, role: str | None) -> None:
    acl._cache.clear()
    if role is None:
        monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    else:
        monkeypatch.setenv("RECOSEARCH_ROLE", role)


def sample_tool(sql: str) -> dict:
    return {"status": "ok", "row_count": 2, "rows": [
        {"customer_id": "CUST-101", "product_id": "P001",
         "_citation": {"record_ref": {"customer_id": "CUST-101", "product_id": "P001"}}},
        {"customer_id": "CUST-102", "product_id": "P002", "_citation": {"record_ref": {}}},
    ]}


def test_acl_declares_sensitive_columns() -> None:
    assert "customer_id" in sensitive_columns()


def test_mask_rows_masks_sensitive_column_and_record_ref() -> None:
    rows = sample_tool("x")["rows"]
    masked = mask_rows(rows, {"customer_id"}, "***MASKED***")
    assert masked[0]["customer_id"] == "***MASKED***"
    assert masked[0]["product_id"] == "P001"  # non-sensitive untouched
    assert masked[0]["_citation"]["record_ref"]["customer_id"] == "***MASKED***"


def test_mask_rows_handles_federated_prefixes() -> None:
    rows = [{"left_customer_id": "CUST-1", "right_product_id": "P001"}]
    masked = mask_rows(rows, {"customer_id"}, "***MASKED***")
    assert masked[0]["left_customer_id"] == "***MASKED***"
    assert masked[0]["right_product_id"] == "P001"


def test_unset_role_no_masking(monkeypatch) -> None:
    _reset(monkeypatch, None)
    assert masking_active() is False
    assert mask_result(sample_tool) is sample_tool  # no-op


def test_admin_role_unmasked(monkeypatch) -> None:
    _reset(monkeypatch, "admin")
    assert masking_active() is False
    assert mask_result(sample_tool) is sample_tool  # admin sees clear


def test_analyst_role_masks_pii(monkeypatch) -> None:
    _reset(monkeypatch, "analyst")
    assert masking_active() is True
    gated = mask_result(sample_tool)
    out = gated("SELECT ...")
    assert out["rows"][0]["customer_id"] == "***MASKED***"
    assert out["rows"][0]["product_id"] == "P001"
    assert out["masking"]["applied"] is True
    assert out["masking"]["role"] == "analyst"
