from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration
from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
from recosearch.semantic_layers.decisions.loader import load_counterfactuals_from_contract
from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.decisions.replay import counterfactual_replay, replay_decision
from recosearch.semantic_layers.decisions.schema import validate_counterfactuals_config, validate_decision_certifications, validate_decisions_config
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

TOOL_VERSION = "0.1.0"
CERTIFICATION_FILENAME = "_certification.yaml"
CERTIFICATION_RESULTS_FILENAME = "_decision_certification_results.yaml"


def _subclaim_from_dict(raw: dict[str, Any]) -> Subclaim:
    qualifiers = tuple(tuple(str(part) for part in pair) for pair in raw.get("claim_qualifiers", []) or [])
    return Subclaim(
        term=str(raw["term"]),
        tenant=str(raw.get("tenant", "novashop")),
        industry=raw.get("industry"),
        actor_role=str(raw.get("actor_role", "analyst")),
        claim_qualifiers=qualifiers,
        comparable_group=str(raw.get("comparable_group", "")),
        reference_date=str(raw.get("reference_date", "")),
        time_period=str(raw.get("time_period", "")),
        scoped_question=str(raw.get("scoped_question", "")),
    )


def load_decision_certifications(decisions_dir: Path | str) -> list[dict[str, Any]]:
    path = Path(decisions_dir) / CERTIFICATION_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"missing {CERTIFICATION_FILENAME}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_decision_certifications(raw)
    return [dict(case) for case in raw.get("certifications", []) or []]


def run_decision_certifications(
    contract: dict[str, Any],
    *,
    decisions_dir: Path | str,
) -> dict[str, dict[str, Any]]:
    contract_hash = str(contract.get("contract_hash", ""))
    results: dict[str, dict[str, Any]] = {}
    for case in load_decision_certifications(decisions_dir):
        case_id = str(case["case_id"])
        ledger.clear()
        subclaims = tuple(_subclaim_from_dict(item) for item in case["subclaims"])
        claim_set = ClaimSet(
            subclaims=subclaims,
            pack_label=str(case.get("pack_label", "board_pack")),
        )
        pack, _answer = compose_evidence_pack(claim_set, contract=contract)
        expected_pack_decision = case.get("expected_pack_decision")
        if expected_pack_decision is not None and pack.decision != expected_pack_decision:
            results[case_id] = {
                "passed": False,
                "reason": f"pack decision mismatch: {pack.decision}",
                "contract_hash": contract_hash,
            }
            continue

        decision = record_decision(
            pack.pack_id,
            actor=str(case.get("actor", "controller")),
            decision_payload=dict(case.get("decision_payload", {}) or {"action": "review"}),
            expected_outcome=dict(case.get("expected_outcome", {}) or {}),
            outcome_due_date=str(case.get("outcome_due_date", "")),
            contract=contract,
            claim_set_snapshot=claim_set.to_dict(),
        )
        replay_target = case.get("replay_target_contract_hash")
        if case.get("simulate_policy_drift"):
            import recosearch.semantic_layers.policy as policy_module

            original = policy_module.compute_policy_hash
            policy_module.compute_policy_hash = lambda: "deadbeef00000000"  # type: ignore[method-assign]
            try:
                replay = replay_decision(
                    decision.decision_id,
                    contract=contract,
                    target_contract_hash=str(replay_target) if replay_target else None,
                )
            finally:
                policy_module.compute_policy_hash = original  # type: ignore[method-assign]
        else:
            replay = replay_decision(
                decision.decision_id,
                contract=contract,
                target_contract_hash=str(replay_target) if replay_target else None,
            )
        expected_drift = bool(case.get("expected_replay_drift", False))
        drift_ok = replay.drift == expected_drift

        calibration_ok = True
        actual_delta = ""
        if case.get("expected_outcome") and case.get("actual_outcome"):
            record_outcome(
                decision.decision_id,
                actual_outcome=dict(case.get("actual_outcome", {}) or {}),
                contract_hash=contract_hash,
            )
            signal = generate_calibration_signal(decision.decision_id, contract=contract)
            actual_delta = signal.calibration_delta
            expected_delta = case.get("expected_calibration_delta")
            if expected_delta is not None:
                calibration_ok = signal.calibration_delta == expected_delta

        counterfactual_ok = True
        if case.get("counterfactual_scenario"):
            scenarios = load_counterfactuals_from_contract(contract)
            scenario_id = str(case["counterfactual_scenario"])
            scenario = scenarios.get(scenario_id)
            if scenario is None:
                counterfactual_ok = False
            else:
                cf = counterfactual_replay(
                    decision.decision_id,
                    contract=contract,
                    overrides=scenario.overlay,
                    scenario_label=scenario.label,
                )
                expected_changed = case.get("expected_counterfactual_changed")
                if expected_changed is not None:
                    counterfactual_ok = cf.changed == bool(expected_changed)

        proposal_ok = True
        if case.get("expected_proposal_emitted") is not None:
            proposal = propose_trust_prior_from_ledger(contract=contract)
            proposal_ok = (proposal is not None) == bool(case["expected_proposal_emitted"])

        aggregate_ok = True
        report_summary: dict[str, Any] = {}
        if case.get("expected_aggregate_min_n") is not None or case.get("expected_calibration_delta"):
            report = aggregate_calibration(contract=contract)
            report_summary = {
                "n": report.n,
                "match_rate": report.match_rate,
                "ci_low": report.ci_low,
                "ci_high": report.ci_high,
                "method": report.method,
            }
            if case.get("expected_aggregate_min_n") is not None:
                aggregate_ok = report.n >= int(case["expected_aggregate_min_n"])
            if aggregate_ok and case.get("expected_calibration_delta"):
                aggregate_ok = report.method == "wilson" and 0.0 <= report.ci_low <= report.ci_high <= 1.0

        passed = drift_ok and calibration_ok and counterfactual_ok and proposal_ok and aggregate_ok
        results[case_id] = {
            "passed": passed,
            "decision_id": decision.decision_id,
            "pack_id": pack.pack_id,
            "replay_drift": replay.drift,
            "calibration_delta": actual_delta,
            "contract_hash": contract_hash,
            **report_summary,
        }
    return results


def persist_decision_certification_results(
    decisions_dir: Path | str,
    results: dict[str, dict[str, Any]],
    *,
    tool_version: str = TOOL_VERSION,
) -> Path:
    run_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entries = []
    for case_id in sorted(results):
        result = results[case_id]
        entries.append(
            {
                "case_id": case_id,
                "passed": bool(result.get("passed")),
                "decision_id": result.get("decision_id", ""),
                "pack_id": result.get("pack_id", ""),
                "replay_drift": result.get("replay_drift"),
                "calibration_delta": result.get("calibration_delta", ""),
                "reason": result.get("reason", ""),
                "contract_hash": result.get("contract_hash", ""),
                "run_at": run_at,
                "tool_version": tool_version,
            }
        )
    payload = {"certification_results": entries}
    out_path = Path(decisions_dir) / CERTIFICATION_RESULTS_FILENAME
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out_path


def verify_decision_certification_results(
    decisions_dir: Path | str,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    path = Path(decisions_dir) / CERTIFICATION_RESULTS_FILENAME
    if not path.exists():
        return ["missing decision certification results"]
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ["decision certification results must be a mapping"]
    expected_hash = str((contract or {}).get("contract_hash", ""))
    failures: list[str] = []
    for item in raw.get("certification_results", []) or []:
        if not isinstance(item, dict):
            failures.append("invalid certification entry")
            continue
        case_id = str(item.get("case_id", "unknown"))
        if not item.get("passed"):
            reason = str(item.get("reason", "certification failed"))
            failures.append(f"{case_id}: {reason}")
            continue
        if expected_hash and str(item.get("contract_hash", "")) != expected_hash:
            failures.append(f"{case_id}: stale decision certification (hash mismatch)")
    return failures


def validate_decisions_registry(decisions_dir: Path | str) -> list[str]:
    failures: list[str] = []
    config_path = Path(decisions_dir) / "_decisions.yaml"
    if not config_path.exists():
        failures.append("missing _decisions.yaml")
    else:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        try:
            validate_decisions_config(raw)
        except Exception as exc:
            failures.append(str(exc))

    cert_path = Path(decisions_dir) / CERTIFICATION_FILENAME
    if not cert_path.exists():
        failures.append(f"missing {CERTIFICATION_FILENAME}")
    else:
        raw = yaml.safe_load(cert_path.read_text(encoding="utf-8")) or {}
        try:
            validate_decision_certifications(raw)
        except Exception as exc:
            failures.append(str(exc))

    counterfactual_path = Path(decisions_dir) / "_counterfactuals.yaml"
    if counterfactual_path.exists():
        raw = yaml.safe_load(counterfactual_path.read_text(encoding="utf-8")) or {}
        try:
            validate_counterfactuals_config(raw)
        except Exception as exc:
            failures.append(str(exc))
    return failures
