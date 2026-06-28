from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

IDENTIFIER_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_:.-]*$"

_TERM_SCHEMA = {
    "type": "object",
    "required": ["id", "display_name", "definition", "collection_id", "primary_refs"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "display_name": {"type": "string", "minLength": 1},
        "definition": {"type": "string", "minLength": 1},
        "aliases": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "collection_id": {"type": "string", "minLength": 1},
        "primary_refs": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
    },
}

_GUIDANCE_SCHEMA = {
    "type": "object",
    "required": ["term_id", "when_to_use", "when_to_clarify", "when_to_refuse"],
    "additionalProperties": False,
    "properties": {
        "term_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "when_to_use": {"type": "string", "minLength": 1},
        "when_to_clarify": {"type": "string", "minLength": 1},
        "when_to_refuse": {"type": "string", "minLength": 1},
    },
}

_RELATIONSHIP_SCHEMA = {
    "type": "object",
    "required": ["from_id", "to_id", "kind"],
    "additionalProperties": False,
    "properties": {
        "from_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "to_id": {"type": "string", "minLength": 1},
        "kind": {"type": "string", "minLength": 1},
    },
}

_GOLDEN_CONTEXT_QUESTION_SCHEMA = {
    "type": "object",
    "required": [
        "term",
        "expected_decision",
        "expected_trust_status",
    ],
    "additionalProperties": False,
    "properties": {
        "term": {"type": "string", "minLength": 1},
        "tenant": {"type": "string"},
        "actor_role": {"type": "string"},
        "expected_decision": {"type": "string", "minLength": 1},
        "expected_trust_status": {"type": "string", "minLength": 1},
        "expected_evidence_tier": {"type": "integer", "minimum": 1, "maximum": 3},
        "expected": {"type": "object"},
    },
}

_CERTIFICATION_SCHEMA = {
    "type": "object",
    "required": ["term_id", "definition_hash", "golden_questions"],
    "additionalProperties": False,
    "properties": {
        "term_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "definition_hash": {"type": "string", "minLength": 1},
        "policy_hash": {"type": "string"},
        "certified": {"type": "boolean"},
        "golden_passed": {"type": "boolean"},
        "evidence_tier": {"type": "integer", "minimum": 1, "maximum": 3},
        "ares_confidence_interval": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {"type": "number"},
        },
        "golden_questions": {
            "type": "array",
            "minItems": 1,
            "items": _GOLDEN_CONTEXT_QUESTION_SCHEMA,
        },
    },
}

_CONTEXT_KERNEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "version": {"type": "integer"},
        "terms": {"type": "array", "items": _TERM_SCHEMA},
        "guidance": {"type": "array", "items": _GUIDANCE_SCHEMA},
        "relationships": {"type": "array", "items": _RELATIONSHIP_SCHEMA},
        "certifications": {"type": "array", "items": _CERTIFICATION_SCHEMA},
    },
}

_VALIDATOR = Draft202012Validator(_CONTEXT_KERNEL_SCHEMA)


class ContextSchemaError(ValueError):
    pass


def validate_context_kernel(raw: dict[str, Any]) -> None:
    errors = sorted(_VALIDATOR.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "root"
        raise ContextSchemaError(f"context schema error at {path}: {first.message}")
