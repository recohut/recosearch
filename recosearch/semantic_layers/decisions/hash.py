from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_decision_id(
    *,
    pack_id: str,
    actor: str,
    decision_payload: dict[str, Any],
    contract_hash: str,
    policy_hash: str,
) -> str:
    content = json.dumps(
        {
            "pack_id": pack_id,
            "actor": actor,
            "decision_payload": decision_payload,
            "contract_hash": contract_hash,
            "policy_hash": policy_hash,
        },
        sort_keys=True,
    )
    return "decision-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_outcome_id(*, decision_id: str, actual_outcome: dict[str, Any]) -> str:
    content = json.dumps(
        {"decision_id": decision_id, "actual_outcome": actual_outcome},
        sort_keys=True,
    )
    return "outcome-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_signal_id(
    *,
    decision_id: str,
    outcome_id: str,
    calibration_delta: str,
) -> str:
    content = json.dumps(
        {
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "calibration_delta": calibration_delta,
        },
        sort_keys=True,
    )
    return "signal-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_report_id(
    *,
    n: int,
    matches: int,
    decision_class: str,
    term_id: str,
    method: str,
) -> str:
    content = json.dumps(
        {
            "n": n,
            "matches": matches,
            "decision_class": decision_class,
            "term_id": term_id,
            "method": method,
        },
        sort_keys=True,
    )
    return "report-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_proposal_id(
    *,
    term_id: str,
    trigger_report_id: str,
    proposed_ci: tuple[float, float],
) -> str:
    content = json.dumps(
        {
            "term_id": term_id,
            "trigger_report_id": trigger_report_id,
            "proposed_ci": list(proposed_ci),
        },
        sort_keys=True,
    )
    return "proposal-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_counterfactual_id(
    *,
    decision_id: str,
    scenario_label: str,
    counterfactual_contract_hash: str,
) -> str:
    content = json.dumps(
        {
            "decision_id": decision_id,
            "scenario_label": scenario_label,
            "counterfactual_contract_hash": counterfactual_contract_hash,
        },
        sort_keys=True,
    )
    return "cf-" + hashlib.sha256(content.encode()).hexdigest()[:16]
