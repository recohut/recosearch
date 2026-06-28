from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers.decisions.schema import validate_counterfactuals_config, validate_decisions_config
from recosearch.semantic_layers.decisions.types import AdvisoryTargetRule, CalibrationMatchRule, CounterfactualScenario, DecisionKernel, TrustPriorTrigger


def _build_kernel(raw: dict[str, Any]) -> DecisionKernel:
    match_rules: list[CalibrationMatchRule] = []
    for item in raw.get("calibration_match_rules", []) or []:
        match_rules.append(
            CalibrationMatchRule(
                field=str(item["field"]),
                match_mode=str(item.get("match_mode", "exact")),
            )
        )

    advisory_rules: list[AdvisoryTargetRule] = []
    for item in raw.get("advisory_target_rules", []) or []:
        advisory_rules.append(
            AdvisoryTargetRule(
                pattern=str(item["pattern"]),
                target=str(item["target"]),
            )
        )

    partial_fields = frozenset(str(f) for f in raw.get("partial_match_fields", []) or [])

    trigger_raw = raw.get("trust_prior_trigger")
    trigger: TrustPriorTrigger | None = None
    if isinstance(trigger_raw, dict):
        trigger = TrustPriorTrigger(
            min_n=int(trigger_raw.get("min_n", 1)),
            miss_rate_ci_low_threshold=float(trigger_raw.get("miss_rate_ci_low_threshold", 0.5)),
        )

    confidence_method = str(raw.get("confidence_method", "wilson"))

    return DecisionKernel(
        calibration_match_rules=tuple(match_rules),
        advisory_target_rules=tuple(advisory_rules),
        partial_match_fields=partial_fields,
        trust_prior_trigger=trigger,
        confidence_method=confidence_method,
    )


def load_decisions_config(dir_path: Path | str) -> DecisionKernel:
    path = Path(dir_path) / "_decisions.yaml"
    if not path.exists():
        return DecisionKernel(
            calibration_match_rules=(),
            advisory_target_rules=(),
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_decisions_config(raw)
    return _build_kernel(raw)


def load_decisions_config_from_contract(contract: dict[str, Any]) -> DecisionKernel:
    raw = contract.get("decisions_config")
    if not raw:
        return DecisionKernel(
            calibration_match_rules=(),
            advisory_target_rules=(),
        )
    if not isinstance(raw, dict):
        raise ValueError("decisions_config must be a mapping")
    validate_decisions_config(raw)
    return _build_kernel(raw)


def config_to_dict(kernel: DecisionKernel) -> dict[str, Any]:
    out: dict[str, Any] = {
        "calibration_match_rules": [
            {"field": rule.field, "match_mode": rule.match_mode}
            for rule in kernel.calibration_match_rules
        ],
        "partial_match_fields": sorted(kernel.partial_match_fields),
        "advisory_target_rules": [
            {"pattern": rule.pattern, "target": rule.target}
            for rule in kernel.advisory_target_rules
        ],
        "confidence_method": kernel.confidence_method,
    }
    if kernel.trust_prior_trigger is not None:
        out["trust_prior_trigger"] = {
            "min_n": kernel.trust_prior_trigger.min_n,
            "miss_rate_ci_low_threshold": kernel.trust_prior_trigger.miss_rate_ci_low_threshold,
        }
    return out


COUNTERFACTUALS_FILENAME = "_counterfactuals.yaml"


def load_counterfactuals_config(dir_path: Path | str) -> dict[str, CounterfactualScenario]:
    path = Path(dir_path) / COUNTERFACTUALS_FILENAME
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_counterfactuals_config(raw)
    scenarios: dict[str, CounterfactualScenario] = {}
    for scenario_id, item in (raw.get("scenarios") or {}).items():
        scenarios[str(scenario_id)] = CounterfactualScenario(
            scenario_id=str(scenario_id),
            label=str(item.get("label", scenario_id)),
            overlay=dict(item.get("overlay") or {}),
        )
    return scenarios


def counterfactuals_to_dict(scenarios: dict[str, CounterfactualScenario]) -> dict[str, Any]:
    return {
        "scenarios": {
            scenario_id: {
                "label": scenario.label,
                "overlay": dict(scenario.overlay),
            }
            for scenario_id, scenario in sorted(scenarios.items())
        }
    }


def load_counterfactuals_from_contract(contract: dict[str, Any]) -> dict[str, CounterfactualScenario]:
    raw = contract.get("counterfactuals_config")
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("counterfactuals_config must be a mapping")
    validate_counterfactuals_config(raw)
    scenarios: dict[str, CounterfactualScenario] = {}
    for scenario_id, item in (raw.get("scenarios") or {}).items():
        scenarios[str(scenario_id)] = CounterfactualScenario(
            scenario_id=str(scenario_id),
            label=str(item.get("label", scenario_id)),
            overlay=dict(item.get("overlay") or {}),
        )
    return scenarios
