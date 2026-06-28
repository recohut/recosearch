"""Offline RBAC tests. No live sources. Verifies the opt-in gate: unset = no
enforcement, known role grants/denies per the scenario roles block, unknown role denies all,
and denied tools return a governed refusal while preserving the call signature.
"""
from __future__ import annotations

import recosearch.rbac as rbac
from recosearch.rbac import is_tool_allowed, load_roles, rbac_gate


def _reset(monkeypatch, role: str | None) -> None:
    # Roles file is static; only the env principal varies per test.
    monkeypatch.setattr(rbac, "_summary_logged", True)
    if role is None:
        monkeypatch.delenv("RECOSEARCH_ROLE", raising=False)
    else:
        monkeypatch.setenv("RECOSEARCH_ROLE", role)


def sample_tool(plan: dict, source_id: str | None = None, limit: int = 5) -> dict:
    return {"status": "ok", "row_count": 1}


def test_roles_file_loads_expected_roles() -> None:
    roles = load_roles()
    assert {"admin", "analyst", "viewer"} <= set(roles)
    assert roles["admin"] == {"*"}
    assert "run_guarded_postgres_sql" in roles["analyst"]
    assert "run_guarded_postgres_sql" not in roles["viewer"]


def test_unset_role_is_passthrough(monkeypatch) -> None:
    _reset(monkeypatch, None)
    assert rbac_gate(sample_tool) is sample_tool  # enforcement off


def test_admin_allows_everything(monkeypatch) -> None:
    _reset(monkeypatch, "admin")
    assert rbac_gate(sample_tool) is sample_tool  # "*" grant -> untouched


def test_viewer_denied_sql_returns_refusal(monkeypatch) -> None:
    _reset(monkeypatch, "viewer")
    # Rename to a tool the viewer is NOT granted.
    sample_tool.__name__ = "run_guarded_postgres_sql"
    gated = rbac_gate(sample_tool)
    assert gated is not sample_tool
    out = gated({"a": 1})
    assert out["status"] == "refused"
    assert out["reason_code"] == "role_not_permitted"
    assert out["role"] == "viewer" and out["tool"] == "run_guarded_postgres_sql"
    sample_tool.__name__ = "sample_tool"  # restore


def test_viewer_allows_search(monkeypatch) -> None:
    _reset(monkeypatch, "viewer")
    sample_tool.__name__ = "search_text"
    assert rbac_gate(sample_tool) is sample_tool
    sample_tool.__name__ = "sample_tool"


def test_unknown_role_denies_all(monkeypatch) -> None:
    _reset(monkeypatch, "intruder")
    gated = rbac_gate(sample_tool)
    out = gated({})
    assert out["status"] == "refused"
    assert out["reason_code"] == "role_not_recognized"


def test_is_tool_allowed_matrix() -> None:
    roles = load_roles()
    assert is_tool_allowed("admin", "generate_semantic_json", roles)
    assert is_tool_allowed("analyst", "run_guarded_postgres_sql", roles)
    assert not is_tool_allowed("analyst", "generate_semantic_json", roles)
    assert not is_tool_allowed("viewer", "run_guarded_postgres_sql", roles)
    assert not is_tool_allowed("nobody", "list_sources", roles)
