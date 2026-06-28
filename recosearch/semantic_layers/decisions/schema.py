from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from recosearch.semantic_layers.decisions.types import CALIBRATION_DELTAS
from recosearch.semantic_layers.evidence.types import EVIDENCE_PACK_DECISIONS

KNOWN_CALIBRATION_DELTAS = CALIBRATION_DELTAS
KNOWN_REPLAY_DECISIONS = frozenset(EVIDENCE_PACK_DECISIONS)
KNOWN_CONFIDENCE_METHODS = frozenset({"wilson"})
KNOWN_COUNTERFACTUAL_OVERLAY_KEYS = frozenset(
    {"evidence_gates", "decisions_config", "policy_hash", "scenario"}
)


_CALIBRATION_MATCH_SCHEMA = {
    "type": "object",
    "required": ["field"],
    "additionalProperties": False,
    "properties": {
        "field": {"type": "string", "minLength": 1},
        "match_mode": {"type": "string"},
    },
}

_ADVISORY_TARGET_SCHEMA = {
    "type": "object",
    "required": ["pattern", "target"],
    "additionalProperties": False,
    "properties": {
        "pattern": {"type": "string", "minLength": 1},
        "target": {"type": "string", "minLength": 1},
    },
}

DECISIONS_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "calibration_match_rules": {
            "type": "array",
            "items": _CALIBRATION_MATCH_SCHEMA,
        },
        "partial_match_fields": {
            "type": "array",
            "items": {"type": "string"},
        },
        "advisory_target_rules": {
            "type": "array",
            "items": _ADVISORY_TARGET_SCHEMA,
        },
        "trust_prior_trigger": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "min_n": {"type": "integer", "minimum": 1},
                "miss_rate_ci_low_threshold": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        "confidence_method": {"type": "string"},
    },
}

_CERT_CASE_SCHEMA = {
    "type": "object",
    "required": ["case_id", "expected_replay_drift", "subclaims"],
    "additionalProperties": False,
    "properties": {
        "case_id": {"type": "string", "minLength": 1},
        "pack_label": {"type": "string"},
        "expected_pack_decision": {"type": "string"},
        "expected_replay_drift": {"type": "boolean"},
        "expected_calibration_delta": {"type": "string"},
        "decision_payload": {"type": "object"},
        "expected_outcome": {"type": "object"},
        "actual_outcome": {"type": "object"},
        "outcome_due_date": {"type": "string"},
        "actor": {"type": "string"},
        "replay_target_contract_hash": {"type": "string"},
        "simulate_policy_drift": {"type": "boolean"},
        "counterfactual_scenario": {"type": "string"},
        "expected_counterfactual_changed": {"type": "boolean"},
        "expected_proposal_emitted": {"type": "boolean"},
        "expected_aggregate_min_n": {"type": "integer"},
        "subclaims": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["term"],
                "additionalProperties": True,
            },
        },
    },
}

DECISION_CERTIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["certifications"],
    "additionalProperties": False,
    "properties": {
        "certifications": {"type": "array", "minItems": 1, "items": _CERT_CASE_SCHEMA},
    },
}


_COUNTERFACTUAL_SCENARIO_SCHEMA = {
    "type": "object",
    "required": ["overlay"],
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string"},
        "overlay": {"type": "object"},
    },
}

COUNTERFACTUALS_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scenarios"],
    "additionalProperties": False,
    "properties": {
        "scenarios": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": _COUNTERFACTUAL_SCENARIO_SCHEMA,
        },
    },
}


class DecisionSchemaError(ValueError):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def validate_decisions_config(raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(DECISIONS_CONFIG_SCHEMA)
    for error in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) or "$"
        raise DecisionSchemaError(path, error.message)
    for index, item in enumerate(raw.get("calibration_match_rules", []) or []):
        mode = str(item.get("match_mode", "exact"))
        if mode not in {"exact", "numeric_tolerance"}:
            raise DecisionSchemaError(
                f"calibration_match_rules[{index}].match_mode",
                f"unknown match mode: {mode}",
            )
    method = raw.get("confidence_method")
    if method is not None and method not in KNOWN_CONFIDENCE_METHODS:
        raise DecisionSchemaError("confidence_method", f"unknown confidence method: {method}")


def validate_counterfactuals_config(raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(COUNTERFACTUALS_CONFIG_SCHEMA)
    for error in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) or "$"
        raise DecisionSchemaError(path, error.message)
    for scenario_id, item in (raw.get("scenarios") or {}).items():
        overlay = item.get("overlay") or {}
        unknown = set(overlay.keys()) - KNOWN_COUNTERFACTUAL_OVERLAY_KEYS
        if unknown:
            raise DecisionSchemaError(
                f"scenarios.{scenario_id}.overlay",
                f"unknown overlay keys: {sorted(unknown)}",
            )


def validate_decision_certifications(raw: dict[str, Any]) -> None:
    validator = Draft202012Validator(DECISION_CERTIFICATION_SCHEMA)
    for error in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) or "$"
        raise DecisionSchemaError(path, error.message)
    for index, item in enumerate(raw.get("certifications", []) or []):
        expected = item.get("expected_calibration_delta")
        if expected is not None and expected not in KNOWN_CALIBRATION_DELTAS:
            raise DecisionSchemaError(
                f"certifications[{index}].expected_calibration_delta",
                f"unknown calibration delta: {expected}",
            )
        pack_decision = item.get("expected_pack_decision")
        if pack_decision is not None and pack_decision not in KNOWN_REPLAY_DECISIONS:
            raise DecisionSchemaError(
                f"certifications[{index}].expected_pack_decision",
                f"unknown pack decision: {pack_decision}",
            )
