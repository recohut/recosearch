"""Entity-resolution match strategies for federation joins.

Basic, extensible structure: a registry mapping a strategy name to a key
*normalizer*. The join calls ``normalizer_for(strategy)`` and matches on the
normalized key, so adding a new way to decide "same entity" is a one-line
registry entry — the join logic never changes.

``exact`` is the default and the only always-safe strategy. Fuzzier strategies
are registered here as they are designed and approved; a join that asks for an
unregistered strategy is refused (fail-closed), which is how the
"fuzzy joins require an explicit matching policy" gate is honored today.

Future work (as sources grow): bind an allowed strategy per declared relation in
the contract, and add similarity-based normalizers (e.g. token/edit distance).
"""
from __future__ import annotations

from typing import Any, Callable

EXACT = "exact"


def _exact(value: Any) -> Any:
    return value


def _casefold(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def _trimmed(value: Any) -> Any:
    return value.strip().casefold() if isinstance(value, str) else value


# Registry: strategy name -> key normalizer. Append new strategies here.
MATCH_STRATEGIES: dict[str, Callable[[Any], Any]] = {
    "exact": _exact,
    "casefold": _casefold,
    "trimmed": _trimmed,
}


def normalizer_for(strategy: str) -> Callable[[Any], Any] | None:
    """The key normalizer for ``strategy``, or ``None`` if it is unregistered.
    Callers must fail closed on ``None`` — a fuzzy join needs an explicit,
    registered matching policy."""
    return MATCH_STRATEGIES.get(strategy)
