"""Process-stable session id for audit correlation.

A stdio MCP server runs as one principal for the life of the spawn, so a single
id generated once per process is the natural unit that ties together every tool
call of a session. It is surfaced two ways:

* as a span attribute (``session.id``) on every traced tool call, so Phoenix can
  group all calls of a session together;
* as a top-level ``trace_id`` on every tool response, so a final answer can cite
  the id and an auditor can look the session up.

It is deliberately NOT placed inside the hashed ``provenance`` payload — that
would make the deterministic ``provenance_id`` / ``evidence_id`` change every run.
"""
from __future__ import annotations

import uuid

_SESSION_ID: str | None = None


def session_id() -> str:
    """Return this process's stable session/trace id, creating it on first use."""
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = "sess_" + uuid.uuid4().hex
    return _SESSION_ID
