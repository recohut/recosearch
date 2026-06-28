from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from recosearch.semantic_layers.evidence.types import TIER_LABEL_TO_RANK

KNOWN_TIER_LABELS = frozenset(TIER_LABEL_TO_RANK)
KNOWN_PACK_DECISIONS = frozenset({"answer", "review_required", "refuse", "clarify"})


_TIER_BAR_SCHEMA = {
    "type": "object",
    "required": ["pattern", "min_tier_label"],
    "additionalProperties": False,
    "properties": {
        "pattern": {"type": "string", "minLength": 1},
        "min_tier_label": {"type": "string", "minLength": 1},
    },
}

_REVIEW_TRIGGER_SCHEMA = {
    "type": "object",
    "required": ["pattern"],
    "additionalProperties": False,
    "properties": {
        "pattern": {"type": "string", "minLength": 1},
        "required_role": {"type": "string"},
    },
}

_COMPARABLE_GROUP_SCHEMA = {
    "type": "object",
    "required": ["group_id"],
    "additionalProperties": False,
    "properties": {
        "group_id": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
    },
}

EVIDENCE_GATES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "default_min_tier_label": {"type": "string"},
        "evidence_tier_bars": {"type": "array", "items": _TIER_BAR_SCHEMA},
        "review_triggers": {"type": "array", "items": _REVIEW_TRIGGER_SCHEMA},
        "comparable_groups": {"type": "array", "items": _COMPARABLE_GROUP_SCHEMA},
    },
}

_SUBCLAIM_SCHEMA = {
    "type": "object",
    "required": ["term"],
    "additionalProperties": False,
    "properties": {
        "term": {"type": "string", "minLength": 1},
        "tenant": {"type": "string"},
        "industry": {"type": ["string", "null"]},
        "actor_role": {"type": "string"},
        "claim_qualifiers": {
            "type": "array",
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"type": "string"},
            },
        },
        "comparable_group": {"type": "string"},
        "reference_date": {"type": "string"},
        "time_period": {"type": "string"},
        "scoped_question": {"type": "string"},
    },
}

_CERT_CASE_SCHEMA = {
    "type": "object",
    "required": ["case_id", "expected_decision", "subclaims"],
    "additionalProperties": False,
    "properties": {
        "case_id": {"type": "string", "minLength": 1},
        "pack_label": {"type": "string"},
        "expected_decision": {"type": "string", "minLength": 1},
        "subclaims": {"type": "array", "minItems": 1, "items": _SUBCLAIM_SCHEMA},
    },
}

EVIDENCE_CERTIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["certifications"],
    "additionalProperties": False,
    "properties": {
        "certifications": {"type": "array", "minItems": 1, "items": _CERT_CASE_SCHEMA},
    },
}


class EvidenceSchemaError(ValueError):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def validate_evidence_gates(raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(EVIDENCE_GATES_SCHEMA)
    for error in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) or "$"
        raise EvidenceSchemaError(path, error.message)
    default_label = raw.get("default_min_tier_label")
    if default_label is not None and default_label not in KNOWN_TIER_LABELS:
        raise EvidenceSchemaError("default_min_tier_label", f"unknown tier label: {default_label}")
    for index, item in enumerate(raw.get("evidence_tier_bars", []) or []):
        label = item.get("min_tier_label")
        if label not in KNOWN_TIER_LABELS:
            raise EvidenceSchemaError(
                f"evidence_tier_bars[{index}].min_tier_label",
                f"unknown tier label: {label}",
            )


def validate_evidence_certifications(raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(EVIDENCE_CERTIFICATION_SCHEMA)
    for error in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) or "$"
        raise EvidenceSchemaError(path, error.message)
    for index, item in enumerate(raw.get("certifications", []) or []):
        expected = item.get("expected_decision")
        if expected not in KNOWN_PACK_DECISIONS:
            raise EvidenceSchemaError(
                f"certifications[{index}].expected_decision",
                f"unknown pack decision: {expected}",
            )
