from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Spec enum — refusal/clarify/review are first-class, not errors.
DECISION_ANSWER = "answer"
DECISION_CAVEATS = "answer_with_caveats"
DECISION_CLARIFY = "clarify"
DECISION_REVIEW = "review_required"
DECISION_REFUSE = "refuse"
DECISIONS = frozenset(
    {DECISION_ANSWER, DECISION_CAVEATS, DECISION_CLARIFY, DECISION_REVIEW, DECISION_REFUSE}
)

# Evidence tiers (from rationale Frame 3). Empty string = unset / contract-only.
# Certify currently assigns only tiers 1-3 (contract-only, fixture-backed,
# local-equivalent). Tiers 4-7 are declared for gate-bar configuration but are
# not yet produced by the certification path.
TIER_CONTRACT = "contract-only"
TIER_FIXTURE = "fixture-backed"
TIER_LOCAL_EQUIV = "local-equivalent"
TIER_LOCAL_LIVE = "local-live"
TIER_CLOUD_DEV = "cloud-dev-live"
TIER_PILOT = "customer-pilot-live"
TIER_PROD = "production-ready"


@dataclass
class Answer:
    decision: str
    result: list[dict[str, Any]] | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    contract_version: str = ""
    reason: str = ""
    reason_code: str = ""
    # Stable fields — present from day one so schema never breaks.
    answer_id: str = ""
    evidence_tier: str = ""
    actor_role: str = ""
    scoped_question: str = ""
    plan_ref: str = ""
    policy_trace: list[dict[str, Any]] = field(default_factory=list)
    source_role_matrix: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    replay_refs: list[str] = field(default_factory=list)
    metric_resolution: tuple[tuple[str, Any], ...] = ()
    context_resolution: tuple[tuple[str, Any], ...] = ()
    constraint_decision: tuple[tuple[str, Any], ...] = ()
    evidence_pack: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"unknown decision: {self.decision!r}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision": self.decision,
            "answer_id": self.answer_id,
            "evidence_tier": self.evidence_tier,
            "actor_role": self.actor_role,
            "contract_version": self.contract_version,
            "citations": self.citations,
            "caveats": self.caveats,
            "replay_refs": self.replay_refs,
            "source_role_matrix": self.source_role_matrix,
        }
        if self.result is not None:
            out["result"] = self.result
        if self.reason:
            out["reason"] = self.reason
        if self.reason_code:
            out["reason_code"] = self.reason_code
        if self.policy_trace:
            out["policy_trace"] = self.policy_trace
        if self.scoped_question:
            out["scoped_question"] = self.scoped_question
        if self.plan_ref:
            out["plan_ref"] = self.plan_ref
        if self.metric_resolution:
            out["metric_resolution"] = dict(self.metric_resolution)
        if self.context_resolution:
            out["context_resolution"] = dict(self.context_resolution)
        if self.constraint_decision:
            out["constraint_decision"] = dict(self.constraint_decision)
        if self.evidence_pack:
            out["evidence_pack"] = dict(self.evidence_pack)
        return out


def refuse(reason: str, contract_version: str = "", *, actor_role: str = "") -> Answer:
    return Answer(decision=DECISION_REFUSE, reason=reason, contract_version=contract_version, actor_role=actor_role)


def clarify(reason: str, contract_version: str = "", *, actor_role: str = "") -> Answer:
    return Answer(decision=DECISION_CLARIFY, reason=reason, contract_version=contract_version, actor_role=actor_role)


def review_required(
    reason: str,
    contract_version: str = "",
    *,
    actor_role: str = "",
    reason_code: str = "EVIDENCE_REVIEW_REQUIRED",
    plan_ref: str = "",
    evidence_tier: str = "",
    replay_refs: list[str] | None = None,
    evidence_pack: tuple[tuple[str, Any], ...] = (),
) -> Answer:
    return Answer(
        decision=DECISION_REVIEW,
        reason=reason,
        reason_code=reason_code,
        contract_version=contract_version,
        actor_role=actor_role,
        plan_ref=plan_ref,
        evidence_tier=evidence_tier,
        replay_refs=replay_refs or [],
        evidence_pack=evidence_pack,
    )
