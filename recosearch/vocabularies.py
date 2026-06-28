"""Configurable interpretation vocabularies (field-role + rule stopwords).

The runtime infers field roles and parses rules using small term lists. The
built-in defaults here are domain-NEUTRAL; anything specific to a scenario's
business language (e.g. "review text", "sales", "revenue") lives in the scenario
file's optional ``vocabularies`` block, MERGED over these defaults. A new domain
therefore *extends* the vocabulary in config rather than editing code, and the
package still works with no block present (defaults only).
"""
from __future__ import annotations

from typing import Any

import yaml

from .settings import SCENARIO_PATH

# Domain-neutral structural vocabulary. Scenario-specific terms are added via
# vocabularies.yaml, not here.
_DEFAULT_FIELD_ROLE_VOCAB: dict[str, dict[str, Any]] = {
    "identity": {"kind": "dimension", "terms": ["unique identifier", "identifier of", "identifier for"], "negative": []},
    "display_name": {"kind": "dimension", "terms": ["title", "headline", "display name", "name of"], "negative": []},
    "body_text": {"kind": "dimension", "terms": ["free-text", "full text", "body", "content", "text extracted"], "negative": []},
    "timestamp": {"kind": "dimension", "terms": ["timestamp", "date the", "submitted", "created"], "negative": []},
    "score": {"kind": "measure", "terms": ["rating", "score"], "negative": []},
}
_DEFAULT_METRIC_STOPWORDS: set[str] = {
    "count", "total", "rate", "value", "number", "amount", "of", "the", "per", "ratio", "average", "sum",
}
_DEFAULT_FILTER_STOPWORDS: set[str] = {
    "use", "using", "must", "only", "the", "a", "an", "for", "and", "be", "to", "should", "default",
}

_cache: dict[str, Any] = {}


def _overrides() -> dict[str, Any]:
    try:
        full = yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8")) or {}
        data = full.get("vocabularies") or {}  # no `vocabularies` block -> defaults only
    except FileNotFoundError:
        return {}
    except Exception:  # pragma: no cover - malformed config -> defaults only
        return {}
    return data if isinstance(data, dict) else {}


def _merge_role_vocab(defaults: dict[str, dict[str, Any]], override: dict[str, Any]) -> dict[str, dict[str, Any]]:
    merged = {
        role: {"kind": spec["kind"], "terms": list(spec.get("terms") or []), "negative": list(spec.get("negative") or [])}
        for role, spec in defaults.items()
    }
    for role, spec in (override or {}).items():
        if not isinstance(spec, dict):
            continue
        if role in merged:
            merged[role]["terms"] = list(dict.fromkeys(merged[role]["terms"] + list(spec.get("terms") or [])))
            merged[role]["negative"] = list(dict.fromkeys(merged[role]["negative"] + list(spec.get("negative") or [])))
            if spec.get("kind"):
                merged[role]["kind"] = str(spec["kind"])
        else:  # a brand-new role declared by a scenario
            merged[role] = {"kind": str(spec.get("kind") or "dimension"),
                            "terms": list(spec.get("terms") or []), "negative": list(spec.get("negative") or [])}
    return merged


def _build() -> dict[str, Any]:
    if not _cache:
        data = _overrides()
        stop = data.get("rule_stopwords") or {}
        _cache["field_roles"] = _merge_role_vocab(_DEFAULT_FIELD_ROLE_VOCAB, data.get("field_roles") or {})
        _cache["metric_stop"] = set(_DEFAULT_METRIC_STOPWORDS) | {str(w).casefold() for w in (stop.get("metric") or [])}
        _cache["filter_stop"] = set(_DEFAULT_FILTER_STOPWORDS) | {str(w).casefold() for w in (stop.get("filter") or [])}
    return _cache


def field_role_vocab() -> dict[str, dict[str, Any]]:
    return _build()["field_roles"]


def metric_stopwords() -> set[str]:
    return _build()["metric_stop"]


def filter_stopwords() -> set[str]:
    return _build()["filter_stop"]
