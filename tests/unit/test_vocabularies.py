"""Offline tests for recosearch/vocabularies.py.

Tests:
- defaults merged with scenario-declared vocabulary block
- no vocabularies block -> defaults only; code works without raising
- metric_stopwords and filter_stopwords contain expected terms
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import recosearch.vocabularies as vocab_mod
from recosearch.vocabularies import (
    field_role_vocab,
    filter_stopwords,
    metric_stopwords,
    _DEFAULT_FIELD_ROLE_VOCAB,
    _DEFAULT_METRIC_STOPWORDS,
    _DEFAULT_FILTER_STOPWORDS,
)


def _patch_scenario(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(vocab_mod, "SCENARIO_PATH", path)
    vocab_mod._cache.clear()


def _tmp_scenario(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "scenario_config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Defaults merged with scenario vocabulary block
# ---------------------------------------------------------------------------

def test_scenario_extends_body_text_terms(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    vocabularies:
      field_roles:
        body_text:
          terms: ["review text", "policy text"]
    """)
    _patch_scenario(monkeypatch, p)
    vocab = field_role_vocab()
    body_terms = vocab["body_text"]["terms"]
    # Scenario extension appended
    assert "review text" in body_terms
    assert "policy text" in body_terms
    # Default terms preserved
    default_terms = _DEFAULT_FIELD_ROLE_VOCAB["body_text"]["terms"]
    for t in default_terms:
        assert t in body_terms, f"Default term {t!r} was lost after merge"


def test_scenario_extends_score_terms(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    vocabularies:
      field_roles:
        score:
          terms: ["stars"]
    """)
    _patch_scenario(monkeypatch, p)
    vocab = field_role_vocab()
    assert "stars" in vocab["score"]["terms"]
    # Original "rating" / "score" terms still present
    default_terms = _DEFAULT_FIELD_ROLE_VOCAB["score"]["terms"]
    for t in default_terms:
        assert t in vocab["score"]["terms"]


def test_scenario_can_add_new_role(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    vocabularies:
      field_roles:
        sentiment:
          kind: measure
          terms: ["positive", "negative"]
    """)
    _patch_scenario(monkeypatch, p)
    vocab = field_role_vocab()
    assert "sentiment" in vocab
    assert vocab["sentiment"]["kind"] == "measure"
    assert "positive" in vocab["sentiment"]["terms"]


def test_scenario_rule_stopwords_merged_into_metric_stopwords(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    vocabularies:
      rule_stopwords:
        metric: ["orders", "revenue"]
    """)
    _patch_scenario(monkeypatch, p)
    stops = metric_stopwords()
    assert "orders" in stops
    assert "revenue" in stops
    # Defaults still present
    for word in _DEFAULT_METRIC_STOPWORDS:
        assert word in stops


def test_scenario_rule_stopwords_merged_into_filter_stopwords(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    vocabularies:
      rule_stopwords:
        filter: ["orders", "sales"]
    """)
    _patch_scenario(monkeypatch, p)
    stops = filter_stopwords()
    assert "orders" in stops
    assert "sales" in stops
    for word in _DEFAULT_FILTER_STOPWORDS:
        assert word in stops


# ---------------------------------------------------------------------------
# No vocabularies block -> defaults only; code works
# ---------------------------------------------------------------------------

def test_no_vocabularies_block_returns_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: s1
      name: S1
      mcp_name: s1-mcp
    """)
    _patch_scenario(monkeypatch, p)
    vocab = field_role_vocab()
    # All defaults present
    for role in _DEFAULT_FIELD_ROLE_VOCAB:
        assert role in vocab


def test_no_vocabularies_block_metric_stopwords_have_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: s1
      name: S1
      mcp_name: s1-mcp
    """)
    _patch_scenario(monkeypatch, p)
    stops = metric_stopwords()
    for word in _DEFAULT_METRIC_STOPWORDS:
        assert word in stops


def test_no_vocabularies_block_filter_stopwords_have_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = _tmp_scenario(tmp_path, """
    scenario:
      scenario_id: s1
      name: S1
      mcp_name: s1-mcp
    """)
    _patch_scenario(monkeypatch, p)
    stops = filter_stopwords()
    for word in _DEFAULT_FILTER_STOPWORDS:
        assert word in stops


def test_missing_scenario_file_returns_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    nonexistent = tmp_path / "no_such_file.yaml"
    _patch_scenario(monkeypatch, nonexistent)
    # Must not raise; returns defaults
    vocab = field_role_vocab()
    assert "identity" in vocab
    assert "score" in vocab


# ---------------------------------------------------------------------------
# metric_stopwords and filter_stopwords contain expected terms
# ---------------------------------------------------------------------------

def test_metric_stopwords_contains_expected_defaults() -> None:
    vocab_mod._cache.clear()
    stops = metric_stopwords()
    for word in ("count", "total", "rate", "value", "number", "average"):
        assert word in stops, f"Expected {word!r} in metric stopwords"


def test_filter_stopwords_contains_expected_defaults() -> None:
    vocab_mod._cache.clear()
    stops = filter_stopwords()
    for word in ("use", "using", "must", "only", "the"):
        assert word in stops, f"Expected {word!r} in filter stopwords"


def test_field_role_vocab_has_all_default_roles() -> None:
    vocab_mod._cache.clear()
    vocab = field_role_vocab()
    for role in ("identity", "display_name", "body_text", "timestamp", "score"):
        assert role in vocab


def test_kind_dimension_or_measure_preserved_in_defaults() -> None:
    vocab_mod._cache.clear()
    vocab = field_role_vocab()
    assert vocab["identity"]["kind"] == "dimension"
    assert vocab["score"]["kind"] == "measure"
