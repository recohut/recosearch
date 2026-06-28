"""Structural schema for the compiled semantic contract.

This module validates the *shape* of the compiled contract only: required keys
and value types for sources, dimensions, measures, metrics, rules, and relations.

It is deliberately NOT a business authority and encodes no business meaning. It
exists so downstream code can trust the contract's types. Business semantics live
in semantic.md; connections live in source_config.yaml.
"""
from __future__ import annotations

from typing import Any, Mapping

from .errors import SEVERITY_ERROR, ContractIssue

_LOC = "semantic.json"

_TOP_LEVEL_MAPPINGS = ("sources", "metrics", "dimensions", "measures", "tables")
_TOP_LEVEL_LISTS = ("rules", "relations", "field_roles")

_FIELD_ROLE_VOCAB = {"identity", "join_key", "display_name", "body_text", "timestamp", "score"}

# Required string fields per section entry.
_ENTRY_STRING_FIELDS = {
    "dimensions": ("source", "table", "column"),
    "measures": ("source", "table", "column"),
    "metrics": ("metric_id", "label", "definition"),
}


def validate_structure(contract: Mapping[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []

    if not isinstance(contract, Mapping):
        return [ContractIssue("schema_not_object", SEVERITY_ERROR, _LOC, "contract must be an object")]

    for key in _TOP_LEVEL_MAPPINGS:
        if not isinstance(contract.get(key, {}), Mapping):
            issues.append(ContractIssue("schema_wrong_type", SEVERITY_ERROR, f"{_LOC}:{key}", f"{key!r} must be an object"))
    for key in _TOP_LEVEL_LISTS:
        if not isinstance(contract.get(key, []), list):
            issues.append(ContractIssue("schema_wrong_type", SEVERITY_ERROR, f"{_LOC}:{key}", f"{key!r} must be a list"))

    for section, fields in _ENTRY_STRING_FIELDS.items():
        entries = contract.get(section, {})
        if not isinstance(entries, Mapping):
            continue
        for entry_id, entry in entries.items():
            entry_loc = f"{_LOC}:{section}.{entry_id}"
            if not isinstance(entry, Mapping):
                issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, entry_loc, f"{section} entry {entry_id!r} must be an object"))
                continue
            for field in fields:
                if not isinstance(entry.get(field), str) or not str(entry.get(field)).strip():
                    issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, entry_loc, f"{section} entry {entry_id!r} requires non-empty string {field!r}"))

    for index, relation in enumerate(contract.get("relations", []) or []):
        rel_loc = f"{_LOC}:relations[{index}]"
        if not isinstance(relation, Mapping):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, rel_loc, "relation must be an object"))
            continue
        for side in ("left", "right"):
            if not isinstance(relation.get(side), str) or not str(relation.get(side)).strip():
                issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, rel_loc, f"relation requires non-empty string {side!r}"))

    for index, rule in enumerate(contract.get("rules", []) or []):
        rule_loc = f"{_LOC}:rules[{index}]"
        if not isinstance(rule, Mapping) or not isinstance(rule.get("rule_id"), str) or not isinstance(rule.get("text"), str):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, rule_loc, "rule must have string rule_id and text"))

    for index, assignment in enumerate(contract.get("field_roles", []) or []):
        fr_loc = f"{_LOC}:field_roles[{index}]"
        if not isinstance(assignment, Mapping):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, "field_role entry must be an object"))
            continue
        if assignment.get("field_role") not in _FIELD_ROLE_VOCAB:
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, f"field_role must be one of {sorted(_FIELD_ROLE_VOCAB)}"))
        if assignment.get("resolution") not in {"resolved", "ambiguous"}:
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, "field_role resolution must be 'resolved' or 'ambiguous'"))
        for key in ("source", "table", "confidence"):
            if not isinstance(assignment.get(key), str) or not str(assignment.get(key)).strip():
                issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, f"field_role requires a non-empty string {key!r}"))
        if not isinstance(assignment.get("evidence"), list):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, "field_role requires an 'evidence' list"))
        if not isinstance(assignment.get("ambiguous_candidates"), list):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, "field_role requires an 'ambiguous_candidates' list"))
        if assignment.get("resolution") == "resolved" and not isinstance(assignment.get("field_id"), str):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, "resolved field_role requires a string field_id"))
        if assignment.get("resolution") == "ambiguous" and not assignment.get("ambiguous_candidates"):
            issues.append(ContractIssue("schema_malformed_entry", SEVERITY_ERROR, fr_loc, "ambiguous field_role requires non-empty ambiguous_candidates"))

    return issues
