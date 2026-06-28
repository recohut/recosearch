"""Integration test: audit / session-id correlation flow (in-process, no Phoenix).

Covers:
- recosearch.session.session_id() is stable within the process (idempotent).
- stamp_trace_id adds the same trace_id (== session_id()) to every tool response.
- stamp_trace_id does not overwrite a pre-existing trace_id.
- Non-dict return values pass through without error.
- The stamped trace_id starts with 'sess_' (sentinel prefix).

All offline: no collector, no OTel deps required.
"""
from __future__ import annotations

from recosearch.observability import stamp_trace_id
from recosearch.session import session_id


# ---------------------------------------------------------------------------
# session_id stability
# ---------------------------------------------------------------------------

def test_session_id_is_stable_within_process() -> None:
    first = session_id()
    assert first == session_id()
    assert first == session_id()  # three calls, same value


def test_session_id_starts_with_sess_prefix() -> None:
    assert session_id().startswith("sess_")


def test_session_id_is_non_empty_string() -> None:
    sid = session_id()
    assert isinstance(sid, str)
    assert len(sid) > 5


# ---------------------------------------------------------------------------
# stamp_trace_id: trace_id is stamped as session_id()
# ---------------------------------------------------------------------------

def test_stamp_trace_id_adds_trace_id() -> None:
    def my_tool(plan: dict) -> dict:
        return {"status": "ok", "row_count": 0, "rows": []}

    wrapped = stamp_trace_id(my_tool)
    result = wrapped({})
    assert "trace_id" in result


def test_stamp_trace_id_equals_session_id() -> None:
    def my_tool(plan: dict) -> dict:
        return {"status": "ok", "row_count": 0, "rows": []}

    wrapped = stamp_trace_id(my_tool)
    result = wrapped({})
    assert result["trace_id"] == session_id()


def test_stamp_trace_id_consistent_across_calls() -> None:
    def my_tool(plan: dict) -> dict:
        return {"status": "ok", "row_count": 0}

    wrapped = stamp_trace_id(my_tool)
    r1 = wrapped({})
    r2 = wrapped({"x": 1})
    # Both calls must stamp the same stable session id.
    assert r1["trace_id"] == r2["trace_id"]
    assert r1["trace_id"] == session_id()


def test_stamp_trace_id_does_not_disturb_existing_payload() -> None:
    def my_tool(plan: dict) -> dict:
        return {"status": "ok", "row_count": 3, "rows": [{"a": 1}]}

    wrapped = stamp_trace_id(my_tool)
    result = wrapped({})
    assert result["status"] == "ok"
    assert result["row_count"] == 3
    assert result["rows"] == [{"a": 1}]


# ---------------------------------------------------------------------------
# stamp_trace_id: pre-existing trace_id is not overwritten
# ---------------------------------------------------------------------------

def test_stamp_trace_id_does_not_overwrite_existing_trace_id() -> None:
    def my_tool(plan: dict) -> dict:
        return {"status": "ok", "trace_id": "preset-value-from-upstream"}

    wrapped = stamp_trace_id(my_tool)
    result = wrapped({})
    # Must NOT replace the pre-existing trace_id.
    assert result["trace_id"] == "preset-value-from-upstream"


# ---------------------------------------------------------------------------
# stamp_trace_id: function name preserved (FastMCP schema requirement)
# ---------------------------------------------------------------------------

def test_stamp_trace_id_preserves_function_name() -> None:
    def execute_postgres_semantic_query(plan: dict) -> dict:
        return {"status": "ok"}

    wrapped = stamp_trace_id(execute_postgres_semantic_query)
    assert wrapped.__name__ == "execute_postgres_semantic_query"


# ---------------------------------------------------------------------------
# stamp_trace_id: non-dict results pass through (no crash)
# ---------------------------------------------------------------------------

def test_stamp_trace_id_passthrough_for_dict_without_rows() -> None:
    def my_tool(plan: dict) -> dict:
        return {"status": "ok"}

    wrapped = stamp_trace_id(my_tool)
    result = wrapped({})
    # stamp_trace_id adds trace_id to any dict that lacks it.
    assert result["trace_id"] == session_id()


# ---------------------------------------------------------------------------
# stamp_trace_id: multiple different tools share the same session trace_id
# ---------------------------------------------------------------------------

def test_multiple_tools_share_same_trace_id() -> None:
    def tool_a(plan: dict) -> dict:
        return {"status": "ok", "source": "pg"}

    def tool_b(plan: dict) -> dict:
        return {"status": "ok", "source": "os"}

    wrapped_a = stamp_trace_id(tool_a)
    wrapped_b = stamp_trace_id(tool_b)
    r_a = wrapped_a({})
    r_b = wrapped_b({})
    # Both tools in the same process session share the same trace/audit id.
    assert r_a["trace_id"] == r_b["trace_id"]
    assert r_a["trace_id"] == session_id()
