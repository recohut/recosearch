"""Resolved field roles.

Field roles are RESOLVED from the semantic contract (label/description/column),
not declared, and written into semantic.json with provenance so the MCP's
interpretation is auditable. Conservative: threshold + margin + kind + negative
terms; ambiguity is surfaced as `resolution: "ambiguous"` so dependent profiles
refuse instead of guessing. `join_key` is resolved deterministically from declared
relations.
"""
from __future__ import annotations

from typing import Any, Mapping

from .vocabularies import field_role_vocab

# Structural role vocabulary: domain-neutral defaults + scenario extensions from
# the scenario 'vocabularies' block (a new domain extends config, not this module).
_ROLE_VOCAB: dict[str, dict[str, Any]] = field_role_vocab()
_MIN_SCORE = 1
_MARGIN = 1


def _fields(contract: Mapping[str, Any], kind: str, source_id: str, table: str) -> dict[str, dict[str, Any]]:
    section = "measures" if kind == "measure" else "dimensions"
    out: dict[str, dict[str, Any]] = {}
    for field_id, field in contract.get(section, {}).items():
        if isinstance(field, Mapping) and field.get("source") == source_id and field.get("table") == table:
            out[field_id] = field
    return out


def _haystack(field: Mapping[str, Any]) -> str:
    column = str(field.get("column") or "").replace("_", " ")
    return f"{field.get('label', '')} {field.get('description', '')} {column}".casefold()


def _score(haystack: str, spec: Mapping[str, Any]) -> int:
    if any(str(n).casefold() in haystack for n in spec.get("negative") or []):
        return 0
    return sum(1 for t in spec.get("terms") or [] if str(t).casefold() in haystack)


def _resolve_role(contract: Mapping[str, Any], role: str, source_id: str, table: str) -> dict[str, Any] | None:
    spec = _ROLE_VOCAB[role]
    kind = spec["kind"]
    kind_roles = {r: s for r, s in _ROLE_VOCAB.items() if s["kind"] == kind}
    confident: list[tuple[str, int]] = []
    for field_id, field in _fields(contract, kind, source_id, table).items():
        haystack = _haystack(field)
        scores = {r: _score(haystack, s) for r, s in kind_roles.items()}
        ordered = sorted(scores.values(), reverse=True)
        top = ordered[0] if ordered else 0
        second = ordered[1] if len(ordered) > 1 else 0
        top_role = max(scores, key=lambda r: scores[r]) if scores else None
        if top >= _MIN_SCORE and (top - second) >= _MARGIN and top_role == role:
            confident.append((field_id, top))
    if not confident:
        return None
    if len(confident) > 1:
        return {"field_role": role, "field_id": None, "source": source_id, "table": table,
                "resolution": "ambiguous", "confidence": "low", "evidence": [],
                "ambiguous_candidates": sorted(fid for fid, _ in confident)}
    field_id, top = confident[0]
    return {"field_role": role, "field_id": field_id, "source": source_id, "table": table,
            "resolution": "resolved", "confidence": "high" if top > 1 else "medium",
            "evidence": [f"{role} matched declared field description/label"], "ambiguous_candidates": []}


def _tables(contract: Mapping[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for section in ("dimensions", "measures"):
        for field in contract.get(section, {}).values():
            if isinstance(field, Mapping) and field.get("source") and field.get("table"):
                pairs.add((str(field["source"]), str(field["table"])))
    return pairs


def resolve_field_roles(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for source_id, table in sorted(_tables(contract)):
        for role in _ROLE_VOCAB:
            resolved = _resolve_role(contract, role, source_id, table)
            if resolved:
                assignments.append(resolved)
    # join_key from declared relations (deterministic, contract-driven).
    relation_fields: set[str] = set()
    for relation in contract.get("relations", []) or []:
        if isinstance(relation, Mapping):
            for side in ("left", "right"):
                if relation.get(side):
                    relation_fields.add(str(relation[side]))
    index = {**contract.get("dimensions", {}), **contract.get("measures", {})}
    for field_id in sorted(relation_fields):
        field = index.get(field_id)
        if isinstance(field, Mapping):
            assignments.append({"field_role": "join_key", "field_id": field_id,
                                "source": field.get("source"), "table": field.get("table"),
                                "resolution": "resolved", "confidence": "high",
                                "evidence": ["appears in a declared relation"], "ambiguous_candidates": []})
    return assignments


def roles_present(contract: Mapping[str, Any], source_id: str, table: str) -> set[str]:
    """Set of resolved (non-ambiguous) field roles for a source/table."""
    return {
        a["field_role"]
        for a in contract.get("field_roles", [])
        if isinstance(a, Mapping) and a.get("source") == source_id and a.get("table") == table and a.get("resolution") == "resolved"
    }


def _columns_for_roles(contract: Mapping[str, Any], source_id: str, table: str, roles: set[str]) -> list[str]:
    index = {**contract.get("dimensions", {}), **contract.get("measures", {})}
    columns: list[str] = []
    for assignment in contract.get("field_roles", []):
        if (
            isinstance(assignment, Mapping)
            and assignment.get("resolution") == "resolved"
            and assignment.get("source") == source_id
            and assignment.get("table") == table
            and assignment.get("field_role") in roles
        ):
            field = index.get(assignment.get("field_id"))
            if isinstance(field, Mapping) and field.get("column"):
                columns.append(str(field["column"]))
    return list(dict.fromkeys(columns))  # de-dupe, preserve order


def identity_columns(contract: Mapping[str, Any], source_id: str, table: str) -> list[str]:
    """Columns to use as the record citation key — resolved identity/join roles,
    not '_id' name luck."""
    return _columns_for_roles(contract, source_id, table, {"identity", "join_key"})


def searchable_columns(contract: Mapping[str, Any], source_id: str, table: str) -> list[str]:
    """Full-text-searchable columns — resolved body_text/display_name roles."""
    return _columns_for_roles(contract, source_id, table, {"body_text", "display_name"})


def column_for_role(contract: Mapping[str, Any], source_id: str, table: str, role: str) -> str | None:
    columns = _columns_for_roles(contract, source_id, table, {role})
    return columns[0] if columns else None
