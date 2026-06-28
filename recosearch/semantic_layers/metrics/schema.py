from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

IDENTIFIER_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_:.-]*$"

_COLLECTION_SCHEMA = {
    "type": "object",
    "required": ["id", "priority"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "priority": {"type": "integer"},
        "scope": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}

_ENTITY_SCHEMA = {
    "type": "object",
    "required": ["id", "source_id", "table", "primary_key"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "source_id": {"type": "string", "minLength": 1},
        "table": {"type": "string", "minLength": 1},
        "primary_key": {"type": "string", "minLength": 1},
        "time_field": {"type": "string"},
        "external_ref": {"type": "string"},
    },
}

_MEASURE_SCHEMA = {
    "type": "object",
    "required": ["id", "entity_id", "field", "aggregation"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "entity_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "field": {"type": "string", "minLength": 1},
        "aggregation": {"type": "string", "minLength": 1},
        "external_ref": {"type": "string"},
    },
}

_DIMENSION_SCHEMA = {
    "type": "object",
    "required": ["id", "entity_id", "field", "type"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "entity_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "field": {"type": "string", "minLength": 1},
        "type": {"type": "string", "minLength": 1},
    },
}

_RELATION_SCHEMA = {
    "type": "object",
    "required": ["id", "from_entity_id", "to_entity_id", "join_key", "cardinality"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "from_entity_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "to_entity_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "join_key": {"type": "string", "minLength": 1},
        "cardinality": {
            "type": "string",
            "enum": ["one_to_one", "one_to_many", "many_to_one", "many_to_many"],
        },
    },
}

_METRIC_SCHEMA = {
    "type": "object",
    "required": ["id", "display_name", "collection_id", "grain"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "display_name": {"type": "string", "minLength": 1},
        "collection_id": {"type": "string", "minLength": 1},
        "grain": {"type": "string", "minLength": 1},
        "measure_id": {"type": "string"},
        "kind": {"type": "string", "enum": ["measure", "derived"]},
        "formula": {"type": "string"},
        "filter_rules": {"type": "array", "items": {"type": "string"}},
        "allowed_dimension_ids": {"type": "array", "items": {"type": "string"}},
        "synonyms": {"type": "array", "items": {"type": "string"}},
        "external_ref": {"type": "string"},
        "owners": {"type": "array", "items": {"type": "string"}},
        "version": {"type": "string"},
        "status": {"type": "string"},
        "certification_tier": {"type": "string"},
        "deprecated": {"type": "boolean"},
        "superseded_by": {"type": "string"},
        "definition_hash": {"type": "string"},
        "freshness_sla": {
            "type": "object",
            "required": ["max_age_days"],
            "additionalProperties": False,
            "properties": {
                "max_age_days": {"type": "integer", "minimum": 0},
                "hard_sla": {"type": "boolean"},
            },
        },
    },
}

_FRESHNESS_SCHEMA = {
    "type": "object",
    "required": ["max_age_days"],
    "additionalProperties": False,
    "properties": {
        "max_age_days": {"type": "integer", "minimum": 0},
        "hard_sla": {"type": "boolean"},
    },
}

_GOLDEN_QUESTION_SCHEMA = {
    "type": "object",
    "required": ["term", "expected"],
    "additionalProperties": False,
    "properties": {
        "term": {"type": "string", "minLength": 1},
        "tenant": {"type": "string"},
        "dimensions": {"type": "array", "items": {"type": "string"}},
        "expected": {"type": "object"},
    },
}

_CERTIFICATION_SCHEMA = {
    "type": "object",
    "required": ["metric_id", "definition_hash"],
    "additionalProperties": False,
    "properties": {
        "metric_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "definition_hash": {"type": "string", "minLength": 1},
        "golden_questions": {"type": "array", "items": _GOLDEN_QUESTION_SCHEMA},
        "certified": {"type": "boolean"},
        "golden_passed": {"type": "boolean"},
    },
}

_CERTIFICATION_RESULT_SCHEMA = {
    "type": "object",
    "required": ["metric_id", "definition_hash", "certified", "golden_passed", "run_at", "tool_version"],
    "additionalProperties": False,
    "properties": {
        "metric_id": {"type": "string", "pattern": IDENTIFIER_PATTERN},
        "definition_hash": {"type": "string", "minLength": 1},
        "certified": {"type": "boolean"},
        "golden_passed": {"type": "boolean"},
        "run_at": {"type": "string", "minLength": 1},
        "tool_version": {"type": "string", "minLength": 1},
    },
}

_TIME_SPINE_SCHEMA = {
    "type": "object",
    "required": ["supported_grains"],
    "additionalProperties": False,
    "properties": {
        "timezone": {"type": "string"},
        "min_grain": {"type": "string"},
        "supported_grains": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "period_macros": {"type": "object", "additionalProperties": {"type": "object"}},
    },
}

METRIC_KERNEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["version"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "integer"},
        "metric_collections": {"type": "array", "items": _COLLECTION_SCHEMA},
        "rule_definitions": {"type": "object", "additionalProperties": {"type": "object"}},
        "entities": {"type": "array", "items": _ENTITY_SCHEMA},
        "measures": {"type": "array", "items": _MEASURE_SCHEMA},
        "dimensions": {"type": "array", "items": _DIMENSION_SCHEMA},
        "relations": {"type": "array", "items": _RELATION_SCHEMA},
        "metrics": {"type": "array", "items": _METRIC_SCHEMA},
        "certifications": {"type": "array", "items": _CERTIFICATION_SCHEMA},
        "time_spine": {"oneOf": [{"type": "null"}, _TIME_SPINE_SCHEMA]},
    },
}

CERTIFICATION_RESULTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["certification_results"],
    "additionalProperties": False,
    "properties": {
        "certification_results": {"type": "array", "items": _CERTIFICATION_RESULT_SCHEMA},
    },
}

SOURCE_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["sources"],
    "additionalProperties": False,
    "properties": {
        "sources": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["type", "id"],
                "properties": {
                    "type": {"type": "string"},
                    "id": {"type": "string"},
                    "mode": {"type": "string"},
                    "operations": {"type": "array", "items": {"type": "string"}},
                    "path": {"type": "string"},
                    "source_role": {"type": "string"},
                    "grain": {"type": "string"},
                    "masking": {"type": "object"},
                    "cost_controls": {"type": "object"},
                    "freshness": _FRESHNESS_SCHEMA,
                },
            },
        },
    },
}

SCENARIO_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scenario": {
            "type": "object",
            "properties": {
                "scenario_id": {"type": "string"},
                "name": {"type": "string"},
                "mcp_name": {"type": "string"},
            },
        },
        "roles": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "tools": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class MetricSchemaError(ValueError):
    def __init__(self, path: str, field: str, reason: str) -> None:
        self.path = path
        self.field = field
        self.reason = reason
        super().__init__(f"{path}: {field}: {reason}")


def _format_path(error: jsonschema.ValidationError) -> str:
    parts: list[str] = []
    for part in error.absolute_path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(str(part))
    return ".".join(parts) if parts else "$"


def _validate(schema: dict[str, Any], data: Any, *, root: str) -> None:
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = _format_path(error)
        field = str(error.validator) if error.validator else "schema"
        reason = error.message
        raise MetricSchemaError(f"{root}.{path}" if path != "$" else root, field, reason)


def validate_metric_kernel(raw: dict[str, Any]) -> None:
    _validate(METRIC_KERNEL_SCHEMA, raw, root="metric_kernel")


def validate_certification_results(raw: dict[str, Any]) -> None:
    _validate(CERTIFICATION_RESULTS_SCHEMA, raw, root="certification_results")


def validate_source_config(raw: dict[str, Any]) -> None:
    _validate(SOURCE_CONFIG_SCHEMA, raw, root="source_config")


def validate_scenario_config(raw: dict[str, Any]) -> None:
    _validate(SCENARIO_CONFIG_SCHEMA, raw, root="scenario_config")
