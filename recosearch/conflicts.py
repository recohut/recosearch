"""Conflict-surfacing checks for federation joins.

Basic, extensible structure: a registry of *check* functions. Each inspects one
joined ``(left, right)`` pair and returns a list of contradiction records. The
join runs every registered check per pair and surfaces what they find in the
federation output — contradictions are reported, never hidden, and they do not
fail the join (the caller/LLM decides what to do with them).

To add a new contradiction signal as sources grow, append a check to
``CONFLICT_CHECKS`` — the join itself does not change.

Future work: field-aware checks driven by declared "comparable measures" (e.g.
two sources reporting a different total for the same entity within a tolerance).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping


def _shared_field_mismatch(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    join_key_left: str,
    join_key_right: str,
) -> list[dict[str, Any]]:
    """Flag fields present on BOTH sides whose values disagree for the same
    matched entity — the most basic contradiction signal."""
    conflicts: list[dict[str, Any]] = []
    skip = {join_key_left, join_key_right}
    for field in sorted(set(left) & set(right)):
        if field in skip or field.startswith("_"):
            continue
        if left.get(field) != right.get(field):
            conflicts.append({
                "check": "shared_field_mismatch",
                "field": field,
                "left_value": left.get(field),
                "right_value": right.get(field),
            })
    return conflicts


# Registry of conflict checks. Append new checks here as comparable fields grow.
CONFLICT_CHECKS: list[Callable[..., list[dict[str, Any]]]] = [_shared_field_mismatch]


def detect_conflicts(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    join_key_left: str,
    join_key_right: str,
) -> list[dict[str, Any]]:
    """Run every registered conflict check over one joined pair."""
    found: list[dict[str, Any]] = []
    for check in CONFLICT_CHECKS:
        found.extend(check(left, right, join_key_left=join_key_left, join_key_right=join_key_right))
    return found
