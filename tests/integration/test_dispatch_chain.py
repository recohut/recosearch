"""Integration test: full dispatch-wrapper chain composed in-process.

Composes the real wrappers in the production order:
    stamp_trace_id(traced_tool(mask_result(rbac_gate(fn))))

All wrappers are real imports from recosearch; only the innermost
tool function is a fake. No live DBs, no Phoenix collector.
"""
from __future__ import annotations

import recosearch.acl as acl
import recosearch.rbac as rbac
from recosearch.acl import mask_result
from recosearch.observability import stamp_trace_id, traced_tool
from recosearch.rbac import rbac_gate
from recosearch.session import session_id


def _make_fake_tool():
    """Fake tool with a real enough signature that wrappers do not reject it."""
    def run_guarded_postgres_sql(plan: dict, source_id: str | None = None) -> dict:
        return {
            "status": "ok",
            "rows": [
                {"product_id": "P001", "units": 10},
                {"product_id": "P002", "units": 5},
            ],
            "row_count": 2,
        }
    return run_guarded_postgres_sql


def _build_chain(monkeypatch, role: str | None = None):
    """Return the fully-composed wrapper chain for the given role."""
    # Clear cached state so each test starts clean.
    acl._cache.clear()
    rbac._roles_cache = None
    rbac._summary_logged = True  # suppress stderr chatter

    if role is None:
        monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    else:
        monkeypatch.setenv("RECOSEARCH_ROLE", role)

    # Tracing is off by default; ensure it stays off so traced_tool is a no-op.
    monkeypatch.delenv("RECOSEARCH_TRACING_ENABLED", raising=False)

    fn = _make_fake_tool()
    # Production composition order (outermost -> innermost):
    #   stamp_trace_id -> traced_tool -> mask_result -> rbac_gate -> fn
    return stamp_trace_id(traced_tool(mask_result(rbac_gate(fn))))


# ---------------------------------------------------------------------------
# trace_id stamping
# ---------------------------------------------------------------------------

def test_trace_id_stamped_on_ok_response(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role=None)
    result = chain({})
    assert "trace_id" in result
    assert result["trace_id"] == session_id()


def test_trace_id_matches_session_id(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role=None)
    result = chain({})
    assert result["trace_id"].startswith("sess_")
    assert result["trace_id"] == session_id()


def test_payload_fields_undisturbed_by_chain(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role=None)
    result = chain({})
    assert result["status"] == "ok"
    assert result["row_count"] == 2
    assert len(result["rows"]) == 2


# ---------------------------------------------------------------------------
# RECOSEARCH_ROLE unset -> everything passes through, no masking
# ---------------------------------------------------------------------------

def test_unset_role_no_masking(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role=None)
    result = chain({})
    # No masking key should appear when role is unset.
    assert "masking" not in result
    # product_id rows untouched
    assert result["rows"][0]["product_id"] == "P001"


def test_unset_role_all_rows_visible(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role=None)
    result = chain({})
    assert result["row_count"] == 2
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# admin role -> no masking, tool allowed
# ---------------------------------------------------------------------------

def test_admin_role_tool_allowed(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role="admin")
    result = chain({})
    assert result["status"] == "ok"
    assert "masking" not in result


# ---------------------------------------------------------------------------
# traced_tool is a passthrough when tracing is disabled
# ---------------------------------------------------------------------------

def test_traced_tool_is_transparent_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("RECOSEARCH_TRACING_ENABLED", raising=False)
    fn = _make_fake_tool()
    wrapped = traced_tool(fn)
    # With tracing disabled, traced_tool returns the original function unchanged.
    assert wrapped is fn


# ---------------------------------------------------------------------------
# Chain preserves function name (FastMCP schema builder requirement)
# ---------------------------------------------------------------------------

def test_chain_preserves_function_name(monkeypatch) -> None:
    chain = _build_chain(monkeypatch, role=None)
    assert chain.__name__ == "run_guarded_postgres_sql"
