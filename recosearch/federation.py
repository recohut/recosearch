from __future__ import annotations

from typing import Any, Mapping

from .citations import (
    FEDERATION_SOURCE_ID,
    FEDERATION_SOURCE_TYPE,
    _derived_citation,
    _provenance,
)
from .conflicts import detect_conflicts
from .contract import _contract_id, validated_contract
from .entity_resolution import EXACT, normalizer_for
from .settings import MAX_FEDERATION_ROWS


def _refused(reason_code: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "refused",
        "reason_code": reason_code,
        "source_boundary": FEDERATION_SOURCE_ID,
        "rows": [],
        "row_count": 0,
        **extra,
    }


def _slice_source(rows: list[dict[str, Any]]) -> str | None:
    """The declared source id a slice came from, read from its row citations."""
    for row in rows:
        citation = row.get("_citation")
        if isinstance(citation, Mapping):
            ref = citation.get("source_ref")
            if isinstance(ref, Mapping) and ref.get("source_id"):
                return str(ref["source_id"])
            if citation.get("source"):
                return str(citation["source"])
    return None


def _relation_declared_between(contract: Mapping[str, Any], left_source: str, right_source: str) -> bool:
    """True if the contract declares any relation connecting these two sources.

    Source-pair granularity: a declared relation between the two sources is
    required to federate them. Column/field-level matching and fuzzy entity
    resolution are deliberately out of scope here (future work)."""
    pair = {left_source, right_source}
    for relation in contract.get("relations", []):
        if not isinstance(relation, Mapping):
            continue
        sources = {
            str(relation.get(side) or "").split(".")[0]
            for side in ("left", "right")
            if relation.get(side)
        }
        if sources == pair:
            return True
    return False


def _slice_has_key(rows: list[dict[str, Any]], key: str) -> bool:
    return any(key in row and row.get(key) is not None for row in rows)


def combine_slices(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    left_key: str,
    right_key: str,
    left_prefix: str = "left_",
    right_prefix: str = "right_",
    match_strategy: str = EXACT,
    limit: int = 100,
) -> dict[str, Any]:
    """Bounded deterministic join over slices already returned by MCP tools.

    ``match_strategy`` selects the entity-resolution policy for key matching
    (default ``"exact"``); an unregistered strategy is refused. Contradictions
    between matched rows are surfaced in ``conflicts`` (never hidden)."""
    vc = validated_contract()
    if not vc.is_valid:
        return {
            "status": "refused",
            "reason_code": "contract_invalid",
            "issues": [issue.as_dict() for issue in vc.errors],
            "source_boundary": "semantic_contract_only",
            "rows": [],
            "row_count": 0,
        }
    if len(left_rows) > MAX_FEDERATION_ROWS or len(right_rows) > MAX_FEDERATION_ROWS:
        return _refused("federation_slice_too_large", reason="slice size exceeds bounded federation limit")

    # Governance: when both slices come from DECLARED sources, the contract must
    # declare a relation connecting them. Sources that are not declared (or not
    # determinable from citations) skip this check — those are caught downstream
    # by the evidence validator, and never occur on the live tool path.
    declared_sources = set(vc.contract.get("sources", {}))
    left_source = _slice_source(left_rows)
    right_source = _slice_source(right_rows)
    if (
        left_source in declared_sources
        and right_source in declared_sources
        and not _relation_declared_between(vc.contract, left_source, right_source)
    ):
        return _refused("undeclared_relation", left_source=left_source, right_source=right_source,
                        reason="no declared relation connects these sources; cross-source joins must be declared")

    # Fail closed when the join field is absent/null in a non-empty slice, rather
    # than silently matching rows on a missing (None) key.
    if left_rows and not _slice_has_key(left_rows, left_key):
        return _refused("join_key_missing", side="left", join_key=left_key)
    if right_rows and not _slice_has_key(right_rows, right_key):
        return _refused("join_key_missing", side="right", join_key=right_key)

    # Entity resolution: pick the key normalizer for the requested match policy.
    # Fail closed on an unregistered strategy (fuzzy joins need explicit policy).
    normalize = normalizer_for(match_strategy)
    if normalize is None:
        return _refused("unknown_match_strategy", match_strategy=match_strategy,
                        reason=f"match strategy {match_strategy!r} is not a registered entity-resolution policy")

    # 1. Compute the bounded join as (left, right) pairs. Keys are matched through
    # the strategy normalizer; rows missing the key are skipped so a null key
    # never matches another null key.
    bound = max(1, min(int(limit), MAX_FEDERATION_ROWS))
    index: dict[Any, list[dict[str, Any]]] = {}
    for row in right_rows:
        key_value = row.get(right_key)
        if key_value is None:
            continue
        index.setdefault(normalize(key_value), []).append(row)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for left in left_rows:
        left_value = left.get(left_key)
        if left_value is None:
            continue
        for right in index.get(normalize(left_value), []):
            pairs.append((left, right))
            if len(pairs) >= bound:
                break
        if len(pairs) >= bound:
            break

    def _supports(row: Mapping[str, Any]) -> bool:
        citation = row.get("_citation")
        return not isinstance(citation, Mapping) or bool(citation.get("may_support_final_answer"))

    may_support = all(_supports(left) and _supports(right) for left, right in pairs) if pairs else True

    # 2. Build the derived provenance envelope (source identity = federation).
    provenance = _provenance(
        tool_name="combine_slices",
        source=FEDERATION_SOURCE_ID,
        source_id=FEDERATION_SOURCE_ID,
        source_type=FEDERATION_SOURCE_TYPE,
        evidence_kind="derived",
        fields=[left_key, right_key],
        filters=[],
        joins=[{"left_key": left_key, "right_key": right_key}],
        global_rules_applied=[],
        query_body={
            "left_key": left_key,
            "right_key": right_key,
            "match_strategy": match_strategy,
            "left_count": len(left_rows),
            "right_count": len(right_rows),
            "limit": limit,
        },
        row_count=len(pairs),
        may_support_final_answer=may_support,
    )

    # 3. Materialize rows with canonical derived citations, and surface any
    # contradictions between the matched sides (reported, never hidden).
    rows: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for left, right in pairs:
        for conflict in detect_conflicts(left, right, join_key_left=left_key, join_key_right=right_key):
            conflicts.append({"join_value": left.get(left_key), **conflict})
        rows.append(
            {
                **{f"{left_prefix}{key}": value for key, value in left.items()},
                **{f"{right_prefix}{key}": value for key, value in right.items()},
                "_citation": _derived_citation(
                    left=left,
                    right=right,
                    left_key=left_key,
                    right_key=right_key,
                    provenance=provenance,
                ),
            }
        )

    return {
        "status": "ok",
        "source_boundary": FEDERATION_SOURCE_ID,
        "semantic_contract_id": _contract_id(),
        "match_strategy": match_strategy,
        "provenance": provenance,
        "rows": rows,
        "row_count": len(rows),
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
    }
