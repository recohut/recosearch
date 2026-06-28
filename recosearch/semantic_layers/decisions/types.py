from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CALIBRATION_DELTAS = frozenset({"match", "miss", "partial"})


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    pack_id: str
    actor: str
    decision_payload: dict[str, Any]
    expected_outcome: dict[str, Any]
    outcome_due_date: str
    contract_hash: str
    policy_hash: str
    recorded_at: float
    claim_set_snapshot: dict[str, Any]
    original_pack_decision: str = ""
    original_min_tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "pack_id": self.pack_id,
            "actor": self.actor,
            "decision_payload": dict(self.decision_payload),
            "expected_outcome": dict(self.expected_outcome),
            "outcome_due_date": self.outcome_due_date,
            "contract_hash": self.contract_hash,
            "policy_hash": self.policy_hash,
            "recorded_at": self.recorded_at,
            "claim_set_snapshot": dict(self.claim_set_snapshot),
            "original_pack_decision": self.original_pack_decision,
            "original_min_tier": self.original_min_tier,
        }


@dataclass(frozen=True, slots=True)
class ReplayResult:
    decision_id: str
    original_contract_hash: str
    replayed_contract_hash: str
    original_decision: str
    replayed_decision: str
    drift: bool
    drift_reasons: tuple[str, ...]
    replayed_pack_id: str = ""
    replayed_min_tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "original_contract_hash": self.original_contract_hash,
            "replayed_contract_hash": self.replayed_contract_hash,
            "original_decision": self.original_decision,
            "replayed_decision": self.replayed_decision,
            "drift": self.drift,
            "drift_reasons": list(self.drift_reasons),
            "replayed_pack_id": self.replayed_pack_id,
            "replayed_min_tier": self.replayed_min_tier,
        }


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    outcome_id: str
    decision_id: str
    actual_outcome: dict[str, Any]
    recorded_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "decision_id": self.decision_id,
            "actual_outcome": dict(self.actual_outcome),
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class CalibrationSignal:
    signal_id: str
    decision_id: str
    outcome_id: str
    expected_outcome: dict[str, Any]
    actual_outcome: dict[str, Any]
    calibration_delta: str
    advisory_targets: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "decision_id": self.decision_id,
            "outcome_id": self.outcome_id,
            "expected_outcome": dict(self.expected_outcome),
            "actual_outcome": dict(self.actual_outcome),
            "calibration_delta": self.calibration_delta,
            "advisory_targets": list(self.advisory_targets),
        }


@dataclass(frozen=True, slots=True)
class AdvisoryTargetRule:
    pattern: str
    target: str


@dataclass(frozen=True, slots=True)
class CalibrationMatchRule:
    field: str
    match_mode: str = "exact"


@dataclass(frozen=True, slots=True)
class TrustPriorTrigger:
    min_n: int = 1
    miss_rate_ci_low_threshold: float = 0.5


CONFIDENCE_METHODS = frozenset({"wilson"})
PROPOSAL_STATUSES = frozenset({"pending", "approved", "rejected"})


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    report_id: str
    n: int
    match_rate: float
    ci_low: float
    ci_high: float
    miss_rate: float
    method: str
    decision_class: str = ""
    term_id: str = ""
    miss_ci_low: float = 0.0
    signal_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "n": self.n,
            "match_rate": self.match_rate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "miss_rate": self.miss_rate,
            "miss_ci_low": self.miss_ci_low,
            "method": self.method,
            "decision_class": self.decision_class,
            "term_id": self.term_id,
            "signal_ids": list(self.signal_ids),
        }


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    decision_id: str
    scenario_label: str
    baseline_decision: str
    counterfactual_decision: str
    changed: bool
    deltas: tuple[str, ...]
    baseline_contract_hash: str = ""
    counterfactual_contract_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "scenario_label": self.scenario_label,
            "baseline_decision": self.baseline_decision,
            "counterfactual_decision": self.counterfactual_decision,
            "changed": self.changed,
            "deltas": list(self.deltas),
            "baseline_contract_hash": self.baseline_contract_hash,
            "counterfactual_contract_hash": self.counterfactual_contract_hash,
        }


@dataclass(frozen=True, slots=True)
class TrustPriorProposal:
    proposal_id: str
    term_id: str
    trigger_report_id: str
    current_ci: tuple[float, float]
    proposed_ci: tuple[float, float]
    proposed_trust_delta: float
    rationale: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "term_id": self.term_id,
            "trigger_report_id": self.trigger_report_id,
            "current_ci": list(self.current_ci),
            "proposed_ci": list(self.proposed_ci),
            "proposed_trust_delta": self.proposed_trust_delta,
            "rationale": self.rationale,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class CounterfactualScenario:
    scenario_id: str
    label: str
    overlay: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DecisionKernel:
    calibration_match_rules: tuple[CalibrationMatchRule, ...]
    advisory_target_rules: tuple[AdvisoryTargetRule, ...]
    partial_match_fields: frozenset[str] = frozenset()
    trust_prior_trigger: TrustPriorTrigger | None = None
    confidence_method: str = "wilson"
