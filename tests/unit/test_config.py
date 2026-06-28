"""Offline tests for recosearch/config.py.

Tests:
- _source_refs() ${ENV} interpolation (set/unset env var via monkeypatch)
- validate_source_config: plaintext-secret warning, unknown-type error
- resolve_source_id: single source auto-select, missing -> refusal
- _redact_source_config masks password/token
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import recosearch.config as config_mod
from recosearch.config import (
    _redact_source_config,
    _resolve_env_refs,
    validate_source_config,
    SourceRef,
)
from recosearch.errors import SEVERITY_WARNING, SEVERITY_ERROR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_yaml(extra: str = "") -> str:
    return textwrap.dedent(f"""
    sources:
      postgres:
        id: novamart_postgres
        host: localhost
        port: 15432
        database: mydb
        user: novamart
        {extra}
    """)


# ---------------------------------------------------------------------------
# ENV interpolation via _resolve_env_refs
# ---------------------------------------------------------------------------

def test_env_ref_resolved_when_var_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SECRET", "supersecret")
    body = {"password": "${MY_SECRET}", "host": "localhost"}
    result = _resolve_env_refs(body)
    assert result["password"] == "supersecret"
    assert result["host"] == "localhost"


def test_env_ref_left_as_literal_when_var_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_MISSING_VAR", raising=False)
    body = {"password": "${MY_MISSING_VAR}"}
    result = _resolve_env_refs(body)
    # Unset variable -> the original literal ref is preserved
    assert result["password"] == "${MY_MISSING_VAR}"


def test_non_env_ref_values_pass_through() -> None:
    body = {"host": "localhost", "port": 5432}
    result = _resolve_env_refs(body)
    assert result == {"host": "localhost", "port": 5432}


# ---------------------------------------------------------------------------
# validate_source_config — plaintext secret warning
# ---------------------------------------------------------------------------

def test_plaintext_password_produces_warning() -> None:
    yaml_text = _minimal_yaml("password: opensecret")
    issues = validate_source_config(yaml_text)
    codes = [i.code for i in issues]
    severities = [i.severity for i in issues]
    assert "config_plaintext_secret" in codes
    assert SEVERITY_WARNING in severities


def test_env_ref_password_no_warning() -> None:
    yaml_text = _minimal_yaml("password: ${PG_PASSWORD}")
    issues = validate_source_config(yaml_text)
    warning_codes = [i.code for i in issues if i.severity == SEVERITY_WARNING]
    # No plaintext-secret warning when the value is an env ref
    assert "config_plaintext_secret" not in warning_codes


# ---------------------------------------------------------------------------
# validate_source_config — unknown type error
# ---------------------------------------------------------------------------

def test_unknown_source_type_produces_error() -> None:
    yaml_text = textwrap.dedent("""
    sources:
      mythicaldb:
        id: novamart_mythical
        host: localhost
    """)
    issues = validate_source_config(yaml_text)
    error_codes = [i.code for i in issues if i.severity == SEVERITY_ERROR]
    assert "config_unknown_source_type" in error_codes


def test_known_source_type_no_type_error() -> None:
    yaml_text = _minimal_yaml()
    issues = validate_source_config(yaml_text)
    error_codes = [i.code for i in issues if i.severity == SEVERITY_ERROR]
    assert "config_unknown_source_type" not in error_codes


# ---------------------------------------------------------------------------
# resolve_source_id
# ---------------------------------------------------------------------------

def _make_ref(source_id: str, source_type: str, capability: str) -> SourceRef:
    return SourceRef(
        source_id=source_id,
        source_type=source_type,
        config_key=source_type,
        config={"id": source_id},
    )


def test_resolve_source_id_single_match_auto_selects(monkeypatch: pytest.MonkeyPatch) -> None:
    """When exactly one source matches the capability, it auto-selects."""
    ref = _make_ref("novamart_postgres", "postgres", "structured_query")
    monkeypatch.setattr(config_mod, "sources_with_capability", lambda cap: [ref])
    sid, refusal = config_mod.resolve_source_id("structured_query")
    assert sid == "novamart_postgres"
    assert refusal is None


def test_resolve_source_id_missing_capability_returns_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """No source matching the capability -> refused."""
    monkeypatch.setattr(config_mod, "sources_with_capability", lambda cap: [])
    sid, refusal = config_mod.resolve_source_id("structured_query")
    assert sid is None
    assert refusal is not None
    assert refusal["status"] == "refused"
    assert refusal["reason_code"] == "no_source_for_capability"


def test_resolve_source_id_multiple_without_hint_returns_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple matching sources and no explicit source_id -> selection_required."""
    refs = [
        _make_ref("novamart_postgres", "postgres", "structured_query"),
        _make_ref("novamart_duckdb", "duckdb", "structured_query"),
    ]
    monkeypatch.setattr(config_mod, "sources_with_capability", lambda cap: refs)
    sid, refusal = config_mod.resolve_source_id("structured_query")
    assert sid is None
    assert refusal is not None
    assert refusal["reason_code"] == "source_selection_required"


def test_resolve_source_id_explicit_id_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit source_id in candidates -> resolved."""
    ref = _make_ref("novamart_postgres", "postgres", "structured_query")
    monkeypatch.setattr(config_mod, "sources_with_capability", lambda cap: [ref])
    sid, refusal = config_mod.resolve_source_id("structured_query", source_id="novamart_postgres")
    assert sid == "novamart_postgres"
    assert refusal is None


def test_resolve_source_id_explicit_id_not_in_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit source_id not in candidates -> refused."""
    ref = _make_ref("novamart_postgres", "postgres", "structured_query")
    monkeypatch.setattr(config_mod, "sources_with_capability", lambda cap: [ref])
    sid, refusal = config_mod.resolve_source_id("structured_query", source_id="novamart_unknown")
    assert sid is None
    assert refusal is not None
    assert refusal["reason_code"] == "source_not_found_for_capability"


# ---------------------------------------------------------------------------
# _redact_source_config — masks password and token
# ---------------------------------------------------------------------------

def test_redact_masks_password() -> None:
    ref = SourceRef(
        source_id="novamart_postgres",
        source_type="postgres",
        config_key="postgres",
        config={"id": "novamart_postgres", "host": "localhost", "password": "opensecret"},
    )
    redacted = _redact_source_config(ref)
    assert redacted["password"] == "***REDACTED***"
    assert redacted["host"] == "localhost"


def test_redact_masks_token() -> None:
    ref = SourceRef(
        source_id="novamart_snowflake",
        source_type="snowflake",
        config_key="snowflake",
        config={"id": "novamart_snowflake", "token": "mytoken123"},
    )
    redacted = _redact_source_config(ref)
    assert redacted["token"] == "***REDACTED***"


def test_redact_adds_type_field() -> None:
    ref = SourceRef(
        source_id="novamart_postgres",
        source_type="postgres",
        config_key="postgres",
        config={"id": "novamart_postgres", "host": "localhost"},
    )
    redacted = _redact_source_config(ref)
    assert redacted["type"] == "postgres"


def test_redact_leaves_non_secret_fields_intact() -> None:
    ref = SourceRef(
        source_id="novamart_postgres",
        source_type="postgres",
        config_key="postgres",
        config={"id": "novamart_postgres", "host": "localhost", "port": 5432},
    )
    redacted = _redact_source_config(ref)
    assert redacted["host"] == "localhost"
    assert redacted["port"] == 5432


# --- `env:` file credential loading (inline > env-file > ${ENV}) ---

def _write_env(tmp_path: Path, body: str) -> str:
    f = tmp_path / "src.env"
    f.write_text(textwrap.dedent(body))
    return str(f)


def test_env_file_fills_missing_field(tmp_path: Path) -> None:
    from recosearch.config import _resolve_source_config
    p = _write_env(tmp_path, "password=from_env_file\nuser=envuser\n")
    resolved = _resolve_source_config({"env": p, "account": "A"})
    assert resolved["password"] == "from_env_file"
    assert resolved["user"] == "envuser"
    assert "env" not in resolved  # meta-key consumed


def test_inline_password_wins_over_env_file(tmp_path: Path) -> None:
    from recosearch.config import _resolve_source_config
    p = _write_env(tmp_path, "password=from_env_file\n")
    resolved = _resolve_source_config({"env": p, "password": "inline_pw"})
    assert resolved["password"] == "inline_pw"


def test_env_ref_resolves_from_env_file(tmp_path: Path) -> None:
    from recosearch.config import _resolve_source_config
    p = _write_env(tmp_path, "PASSWORD=secret_from_file\n")
    resolved = _resolve_source_config({"env": p, "password": "${PASSWORD}"})
    assert resolved["password"] == "secret_from_file"


def test_no_inline_no_env_leaves_field_absent() -> None:
    from recosearch.config import _resolve_source_config
    resolved = _resolve_source_config({"account": "A"})
    assert "password" not in resolved  # undeclared -> required-key validation will flag it


def test_missing_env_file_is_tolerated() -> None:
    from recosearch.config import _resolve_source_config
    resolved = _resolve_source_config({"env": "/does/not/exist.env", "account": "A"})
    assert "env" not in resolved and "password" not in resolved
