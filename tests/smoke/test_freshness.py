"""Smoke tests — semantic.json freshness.

Verifies that the on-disk semantic.json is in sync with the compiled
contract derived from the current semantic.md and source_config.yaml.
A stale file means the developer ran `--write-semantic-json` against an
older version of the inputs and forgot to regenerate.
"""
from __future__ import annotations

from recosearch.tools import check_semantic_json_fresh


def test_semantic_json_is_fresh() -> None:
    """semantic.json must be in sync with the compiled semantic contract."""
    result = check_semantic_json_fresh()
    assert isinstance(result, dict), "check_semantic_json_fresh() must return a dict"
    assert result.get("fresh") is True, (
        f"semantic.json is stale or missing: {result.get('reason')!r}. "
        "Run `recosearch --write-semantic-json` to regenerate it."
    )
