"""Offline tests for recosearch/analysis_request.py validate_analysis_request.

Uses the real semantic.json (no live DB needed — validate_analysis_request reads
only the compiled contract).

Tests:
- Empty request -> clarification_needed with missing metric_focus and source_scope
- Request with declared metric + single source -> ok (or fewer missing inputs)
- Undeclared metric -> clarification_needed with metric_focus in missing
- Time window missing when date fields present
- Multiple sources without join info triggers cross_source_relation_fields missing
"""
from __future__ import annotations

import pytest

from recosearch.analysis_request import validate_analysis_request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _missing_inputs(result: dict) -> list[str]:
    return [m["input"] for m in result.get("missing_inputs", [])]


def _metric_statuses(result: dict) -> dict[str, str]:
    return {m["requested"]: m["status"] for m in result.get("metric_resolutions", [])}


# ---------------------------------------------------------------------------
# Empty request -> clarification_needed
# ---------------------------------------------------------------------------

def test_empty_request_returns_clarification_needed() -> None:
    result = validate_analysis_request({})
    assert result["status"] == "clarification_needed"


def test_empty_request_missing_metric_focus() -> None:
    result = validate_analysis_request({})
    assert "metric_focus" in _missing_inputs(result)


def test_empty_request_missing_source_scope() -> None:
    """Multiple sources declared in real contract; no source_scope declared -> missing."""
    result = validate_analysis_request({})
    # When multiple sources are present and no source_ids/scope declared -> source_scope missing
    assert "source_scope" in _missing_inputs(result)


def test_empty_request_missing_time_window() -> None:
    """Real contract has date/timestamp fields -> time_window required."""
    result = validate_analysis_request({})
    assert "time_window" in _missing_inputs(result)


def test_none_request_treated_as_empty() -> None:
    result = validate_analysis_request(None)
    assert result["status"] == "clarification_needed"


# ---------------------------------------------------------------------------
# Declared metric + single postgres source -> ok (or fewer missing)
# ---------------------------------------------------------------------------

def test_declared_metric_single_source_assume_all_time_is_ok() -> None:
    result = validate_analysis_request({
        "metric_ids": ["delivered_order_revenue"],
        "expected_sources": ["novamart_postgres"],
        "assume_all_time": True,
    })
    assert result["status"] == "ok"
    assert result["missing_inputs"] == []


def test_declared_metric_resolves_in_metric_resolutions() -> None:
    result = validate_analysis_request({
        "metric_ids": ["delivered_order_revenue"],
        "expected_sources": ["novamart_postgres"],
        "assume_all_time": True,
    })
    statuses = _metric_statuses(result)
    assert "delivered_order_revenue" in statuses
    assert statuses["delivered_order_revenue"] == "resolved"


def test_bad_review_count_metric_resolves() -> None:
    result = validate_analysis_request({
        "metric_ids": ["bad_review_count"],
        "expected_sources": ["novamart_opensearch"],
        "assume_all_time": True,
        # Provide the text search focus so that missing input goes away
        "text_search_focus": "negative reviews",
    })
    metric_resolutions = result.get("metric_resolutions", [])
    assert any(m["requested"] == "bad_review_count" and m["status"] == "resolved"
               for m in metric_resolutions)


def test_all_three_customer_metrics_are_declared() -> None:
    """The real contract declares delivered_order_revenue, delivered_net_revenue, bad_review_count."""
    result = validate_analysis_request({
        "metric_ids": ["delivered_order_revenue"],
        "expected_sources": ["novamart_postgres"],
        "assume_all_time": True,
    })
    available_metrics = [m["metric_id"] for m in result["available_options"].get("metrics", [])]
    assert "delivered_order_revenue" in available_metrics
    assert "delivered_net_revenue" in available_metrics
    assert "bad_review_count" in available_metrics


# ---------------------------------------------------------------------------
# Undeclared metric -> clarification_needed
# ---------------------------------------------------------------------------

def test_undeclared_metric_returns_clarification_needed() -> None:
    result = validate_analysis_request({
        "metric_ids": ["totally_made_up_metric_xyz"],
        "assume_all_time": True,
    })
    assert result["status"] == "clarification_needed"


def test_undeclared_metric_status_is_clarify() -> None:
    result = validate_analysis_request({
        "metric_ids": ["no_such_metric"],
        "assume_all_time": True,
    })
    statuses = _metric_statuses(result)
    assert "no_such_metric" in statuses
    assert statuses["no_such_metric"] == "clarify"


def test_undeclared_metric_triggers_metric_focus_in_missing() -> None:
    result = validate_analysis_request({
        "metric_ids": ["unknown_metric_abc"],
        "assume_all_time": True,
    })
    assert "metric_focus" in _missing_inputs(result)


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_result_has_expected_top_level_keys() -> None:
    result = validate_analysis_request({})
    for key in ("status", "missing_inputs", "suggested_clarification_questions",
                "available_options", "metric_resolutions", "planner_guidance"):
        assert key in result, f"Missing expected key {key!r} in response"


def test_planner_guidance_present_and_non_empty() -> None:
    result = validate_analysis_request({})
    guidance = result.get("planner_guidance", {})
    assert guidance.get("llm_responsibility")
    assert guidance.get("mcp_responsibility")


def test_suggested_clarification_questions_match_missing_inputs() -> None:
    result = validate_analysis_request({})
    questions = result.get("suggested_clarification_questions", [])
    missing = _missing_inputs(result)
    question_ids = [q["question_id"] for q in questions]
    for m in missing:
        assert m in question_ids, f"Missing clarification question for input {m!r}"


def test_available_options_has_metrics_and_sources() -> None:
    result = validate_analysis_request({})
    opts = result.get("available_options", {})
    assert isinstance(opts.get("metrics"), list)
    assert isinstance(opts.get("sources"), list)


# ---------------------------------------------------------------------------
# Cross-source request triggers relation fields missing
# ---------------------------------------------------------------------------

def test_two_sources_without_join_triggers_cross_source_missing() -> None:
    result = validate_analysis_request({
        "metric_ids": ["delivered_order_revenue"],
        "expected_sources": ["novamart_postgres", "novamart_opensearch"],
        "assume_all_time": True,
    })
    # Multiple sources with no join keys declared -> cross_source_relation_fields missing
    assert "cross_source_relation_fields" in _missing_inputs(result)


def test_two_sources_with_join_keys_reduces_missing() -> None:
    result = validate_analysis_request({
        "metric_ids": ["delivered_order_revenue"],
        "expected_sources": ["novamart_postgres", "novamart_opensearch"],
        "assume_all_time": True,
        "join_keys": ["order_id"],
    })
    assert "cross_source_relation_fields" not in _missing_inputs(result)
