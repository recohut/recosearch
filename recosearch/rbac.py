"""Role-based access control for the MCP tool surface.

The active principal is the role named by the ``RECOSEARCH_ROLE`` environment
variable (set in the MCP client config). There is no login/JWT: the stdio server
runs as a single principal per spawn, so the configured role *is* the caller.

Enforcement is OPT-IN and fail-closed on ambiguity:

* ``RECOSEARCH_ROLE`` unset      -> no enforcement; every tool passes through
  unchanged (byte-for-byte identical to a build without RBAC).
* ``RECOSEARCH_ROLE`` = known    -> only that role's granted tools run; others
  return a governed refusal.
* ``RECOSEARCH_ROLE`` = unknown  -> every tool is denied (deny-all).

:func:`rbac_gate` wraps each tool at the same dispatch chokepoint as tracing.
Allowed tools are returned untouched (zero overhead); denied tools become a
refusing stub that preserves the original signature so FastMCP's schema builder
still works under ``from __future__ import annotations``.
"""
from __future__ import annotations

import functools
import os
import sys
import typing
from typing import Any, Callable

import yaml

from .settings import SCENARIO_PATH

_ALL = "*"
_roles_cache: dict[str, set[str]] | None = None
_summary_logged = False


def _log(message: str) -> None:
    """Diagnostics to stderr only — stdout carries the MCP protocol."""
    print(f"[rbac] {message}", file=sys.stderr)


def active_role() -> str | None:
    """The configured role, or None when enforcement is off."""
    value = (os.environ.get("RECOSEARCH_ROLE") or "").strip()
    return value or None


def load_roles() -> dict[str, set[str]]:
    """Parse the scenario file's ``roles`` block into ``{role: set(tool_names)}``.
    Cached. A role granting ``"*"`` keeps the literal marker meaning 'all tools'.
    No ``roles`` block (or no file) -> empty dict -> RBAC is off (open to all)."""
    global _roles_cache
    if _roles_cache is not None:
        return _roles_cache
    roles: dict[str, set[str]] = {}
    try:
        payload = yaml.safe_load(SCENARIO_PATH.read_text(encoding="utf-8")) or {}
        for name, body in (payload.get("roles") or {}).items():
            tools = (body or {}).get("tools") or []
            roles[str(name)] = {str(tool) for tool in tools}
    except FileNotFoundError:
        _log(f"scenario file not found at {SCENARIO_PATH}; RBAC off (open to all)")
    except Exception as exc:  # pragma: no cover - malformed config
        _log(f"failed to load roles ({exc!r}); RBAC off (open to all)")
    _roles_cache = roles
    return roles


def is_tool_allowed(role: str, tool_name: str, roles: dict[str, set[str]]) -> bool:
    grants = roles.get(role)
    if grants is None:
        return False  # unknown role -> deny all
    return _ALL in grants or tool_name in grants


def _refusal(role: str, tool_name: str, reason_code: str) -> dict[str, Any]:
    return {
        "status": "refused",
        "reason_code": reason_code,
        "role": role,
        "tool": tool_name,
        "rows": [],
        "row_count": 0,
    }


def _refusing_stub(func: Callable[..., Any], refusal: dict[str, Any]) -> Callable[..., Any]:
    """A drop-in for a denied tool: ignores args, returns the refusal, and keeps
    the original signature/type-hints so FastMCP registers it correctly."""
    try:
        resolved_hints = typing.get_type_hints(func)
    except Exception:
        resolved_hints = None

    @functools.wraps(func)
    def stub(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return dict(refusal)

    if resolved_hints is not None:
        stub.__annotations__ = resolved_hints
    return stub


def rbac_gate(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return ``func`` unchanged when allowed (or enforcement off); otherwise a
    refusing stub. Decision is fixed at registration — the role is constant for
    the process lifetime."""
    global _summary_logged
    role = active_role()
    if role is None:
        return func  # no role set -> enforcement off
    roles = load_roles()
    if not roles:
        return func  # business owner declared no roles -> open to all
    if not _summary_logged:
        known = role in roles
        _log(f"enforcement on: role={role!r} ({'known' if known else 'UNKNOWN -> deny all'})")
        _summary_logged = True
    if is_tool_allowed(role, func.__name__, roles):
        return func
    reason = "role_not_recognized" if role not in roles else "role_not_permitted"
    return _refusing_stub(func, _refusal(role, func.__name__, reason))
