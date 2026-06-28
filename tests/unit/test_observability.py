"""Offline tests for tool-level observability wrapping. No live sources, no
collector. Asserts the wrapper is inert and transparent when tracing is off.
"""
from __future__ import annotations

import os

from recosearch import observability
from recosearch.observability import init_tracing, traced_tool


def _sample(plan: dict, source_id: str | None = None, limit: int = 5) -> dict:
    return {"status": "ok", "row_count": 1, "echo": {"plan": plan, "source_id": source_id, "limit": limit}}


def test_disabled_by_default_is_passthrough(monkeypatch):
    monkeypatch.delenv("RECOSEARCH_TRACING_ENABLED", raising=False)
    # With tracing off, the same function object is returned untouched.
    assert traced_tool(_sample) is _sample


def test_disabled_call_returns_unchanged(monkeypatch):
    monkeypatch.delenv("RECOSEARCH_TRACING_ENABLED", raising=False)
    wrapped = traced_tool(_sample)
    assert wrapped({"a": 1}, source_id="pg", limit=3) == _sample({"a": 1}, source_id="pg", limit=3)


def test_init_tracing_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("RECOSEARCH_TRACING_ENABLED", raising=False)
    monkeypatch.setattr(observability, "_INITIALIZED", False)
    monkeypatch.setattr(observability, "_TRACER", None)
    init_tracing()  # must not raise and must not configure a tracer
    assert observability._TRACER is None
