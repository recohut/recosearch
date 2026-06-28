"""Offline tests for recosearch/scenario.py + semantic/scenario_config.yaml.

Tests:
- load_scenario reads identity fields from the real file (no I/O mocking needed –
  the file is part of the repo and offline tests may read static assets)
- load_roles (rbac) reads roles block
- sensitive_columns (acl) reads access block
- field_role_vocab (vocabularies) reads vocabularies block
- Three fallback tests: temp file with NO roles/access/vocabularies -> RBAC open,
  masking off, vocab defaults only
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import recosearch.rbac as rbac_mod
import recosearch.acl as acl_mod
import recosearch.vocabularies as vocab_mod
from recosearch.scenario import load_scenario, Scenario


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_scenario(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "scenario_config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _patch_scenario(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    import recosearch.settings as settings_mod
    monkeypatch.setattr(settings_mod, "SCENARIO_PATH", path)
    # Each module that uses SCENARIO_PATH imports it directly into its namespace.
    monkeypatch.setattr(rbac_mod, "SCENARIO_PATH", path)
    monkeypatch.setattr(acl_mod, "SCENARIO_PATH", path)
    monkeypatch.setattr(vocab_mod, "SCENARIO_PATH", path)
    monkeypatch.setattr(rbac_mod, "_roles_cache", None)
    acl_mod._cache.clear()
    vocab_mod._cache.clear()


# ---------------------------------------------------------------------------
# load_scenario — identity block from real file
# ---------------------------------------------------------------------------

def test_load_scenario_reads_identity_from_text() -> None:
    yaml_text = textwrap.dedent("""
    scenario:
      scenario_id: test_scenario
      name: Test Scenario Name
      dataset_id: test_dataset
      mcp_name: test-mcp
    """)
    sc = load_scenario(yaml_text)
    assert isinstance(sc, Scenario)
    assert sc.scenario_id == "test_scenario"
    assert sc.name == "Test Scenario Name"
    assert sc.dataset_id == "test_dataset"
    assert sc.mcp_name == "test-mcp"


def test_load_scenario_artifact_id_defaults_to_dataset_semantic() -> None:
    yaml_text = textwrap.dedent("""
    scenario:
      scenario_id: my_scenario
      name: My Scenario
      mcp_name: my-mcp
    """)
    sc = load_scenario(yaml_text)
    # artifact_id defaults to <dataset_id>.semantic when not declared
    assert sc.artifact_id == "my_scenario.semantic"


def test_load_scenario_real_file_has_required_fields() -> None:
    """The real scenario_config.yaml is present and has all required identity fields."""
    sc = load_scenario()  # reads from SCENARIO_PATH (real file)
    assert sc.scenario_id
    assert sc.name
    assert sc.mcp_name


# ---------------------------------------------------------------------------
# load_roles (rbac block)
# ---------------------------------------------------------------------------

def test_load_roles_returns_declared_roles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: s1
      name: S1
      mcp_name: s1-mcp

    roles:
      admin:
        tools: ["*"]
      analyst:
        tools:
          - search_text
          - run_guarded_postgres_sql
    """)
    _patch_scenario(monkeypatch, p)
    roles = rbac_mod.load_roles()
    assert "admin" in roles
    assert "analyst" in roles
    assert "*" in roles["admin"]
    assert "search_text" in roles["analyst"]
    assert "run_guarded_postgres_sql" in roles["analyst"]


def test_load_roles_real_scenario_has_analyst_and_admin() -> None:
    """Real file declares at least admin and analyst roles."""
    # Reset cache so we read the actual file
    rbac_mod._roles_cache = None
    roles = rbac_mod.load_roles()
    assert "admin" in roles
    assert "analyst" in roles


# ---------------------------------------------------------------------------
# sensitive_columns (acl block)
# ---------------------------------------------------------------------------

def test_sensitive_columns_from_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: s1
      name: S1
      mcp_name: s1-mcp

    access:
      sensitive_fields:
        - novamart_opensearch.customer_reviews.customer_id
        - novamart_snowflake.sellers.seller_name
      unmasked_roles: [admin]
      mask: "***MASKED***"
    """)
    _patch_scenario(monkeypatch, p)
    cols = acl_mod.sensitive_columns()
    assert "customer_id" in cols
    assert "seller_name" in cols


def test_sensitive_columns_real_scenario_declares_customer_id() -> None:
    """The real scenario declares customer_id as sensitive."""
    acl_mod._cache.clear()
    cols = acl_mod.sensitive_columns()
    assert "customer_id" in cols


# ---------------------------------------------------------------------------
# field_role_vocab (vocabularies block)
# ---------------------------------------------------------------------------

def test_field_role_vocab_from_text_extends_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: s1
      name: S1
      mcp_name: s1-mcp

    vocabularies:
      field_roles:
        body_text:
          terms: ["review text", "policy text"]
        score:
          terms: ["stars"]
    """)
    _patch_scenario(monkeypatch, p)
    vocab = vocab_mod.field_role_vocab()
    # Defaults preserved
    assert "identity" in vocab
    assert "score" in vocab
    # Extension merged in
    assert "review text" in vocab["body_text"]["terms"]
    assert "stars" in vocab["score"]["terms"]


def test_field_role_vocab_real_scenario_has_all_default_roles() -> None:
    """Real scenario extends but never removes the built-in roles."""
    vocab_mod._cache.clear()
    vocab = vocab_mod.field_role_vocab()
    for role in ("identity", "display_name", "body_text", "timestamp", "score"):
        assert role in vocab, f"Expected built-in role {role!r} to be present"


# ---------------------------------------------------------------------------
# Fallback tests: temp file with NO roles/access/vocabularies blocks
# ---------------------------------------------------------------------------

def test_fallback_no_roles_block_rbac_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No roles block -> RBAC is off (open to all), load_roles returns empty dict."""
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: fallback_test
      name: Fallback Test
      mcp_name: fallback-mcp
    """)
    _patch_scenario(monkeypatch, p)
    roles = rbac_mod.load_roles()
    # Empty dict means "no roles declared" -> open to all
    assert roles == {}


def test_fallback_no_access_block_masking_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No access block -> no sensitive columns -> masking is off."""
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: fallback_test
      name: Fallback Test
      mcp_name: fallback-mcp
    """)
    _patch_scenario(monkeypatch, p)
    # With a role set but no sensitive fields declared, masking must be off
    monkeypatch.setenv("RECOSEARCH_ROLE", "analyst")
    assert acl_mod.masking_active() is False


def test_fallback_no_vocabularies_block_defaults_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No vocabularies block -> defaults only; field_role_vocab still works."""
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: fallback_test
      name: Fallback Test
      mcp_name: fallback-mcp
    """)
    _patch_scenario(monkeypatch, p)
    vocab = vocab_mod.field_role_vocab()
    # All built-in roles present; no crash
    assert "identity" in vocab
    assert "score" in vocab
    # Default terms present
    assert any("rating" in t or "score" in t for t in vocab["score"]["terms"])
