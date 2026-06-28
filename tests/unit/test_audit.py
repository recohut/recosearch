"""Offline audit-correlation tests: a stable session/trace id and its stamping
onto tool-response envelopes. No live sources, no collector."""
from __future__ import annotations

from recosearch.observability import stamp_trace_id
from recosearch.session import session_id


def _tool(plan: dict, source_id: str | None = None) -> dict:
    return {"status": "ok", "row_count": 1}


def test_session_id_is_stable_within_process() -> None:
    first = session_id()
    assert first == session_id()
    assert first.startswith("sess_")


def test_trace_id_stamped_onto_dict_response() -> None:
    out = stamp_trace_id(_tool)({"a": 1}, source_id="pg")
    assert out["trace_id"] == session_id()
    # Stamping does not disturb the existing payload.
    assert out["status"] == "ok" and out["row_count"] == 1


def test_existing_trace_id_not_overwritten() -> None:
    def already(plan: dict) -> dict:
        return {"status": "ok", "trace_id": "preset"}

    assert stamp_trace_id(already)({})["trace_id"] == "preset"


def test_non_dict_result_is_passthrough() -> None:
    def scalar(plan: dict) -> dict:
        return {"x": 1}

    # Signature is preserved (FastMCP schema needs it); call still works.
    wrapped = stamp_trace_id(scalar)
    assert wrapped.__name__ == "scalar"
    assert "trace_id" in wrapped({})
