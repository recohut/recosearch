from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.envelope import Answer, DECISION_REFUSE, TIER_CONTRACT
from recosearch.semantic_layers.plan import QueryPlan

ROOT = Path(__file__).resolve().parent
POLICY_RULES_PATH = ROOT / "semantic" / "policy_rules.yaml"


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    decision: str
    reason: str
    reason_code: str
    policy_trace: list[dict[str, Any]] = field(default_factory=list)
    actor_role: str = ""
    source_id: str = ""
    operation: str = ""
    plan_ref: str = ""
    metric_id: str = ""
    evidence_tier: str = TIER_CONTRACT

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision": self.decision,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "policy_trace": self.policy_trace,
            "actor_role": self.actor_role,
            "source_id": self.source_id,
            "operation": self.operation,
            "plan_ref": self.plan_ref,
            "metric_id": self.metric_id,
            "evidence_tier": self.evidence_tier,
        }


def decide(answer: Answer, plan: QueryPlan, *, metric_id: str = "") -> Answer:
    """Evaluate declarative policy and attach the policy decision artifact."""
    policy_decision = evaluate(answer, plan, metric_id=metric_id)
    artifact_id = ledger.record(
        "decision",
        source_id=policy_decision.source_id,
        evidence_tier=policy_decision.evidence_tier,
        payload={"policy_decision": policy_decision.to_dict()},
        lineage_edges=[
            ledger.LineageEdge(
                from_id=policy_decision.decision_id,
                to_id=policy_decision.plan_ref,
                kind="decides_plan",
            ),
            ledger.LineageEdge(
                from_id=policy_decision.decision_id,
                to_id=f"source:{policy_decision.source_id}",
                kind="scopes_source",
            ),
        ],
    )

    if policy_decision.decision == DECISION_REFUSE:
        return Answer(
            decision=DECISION_REFUSE,
            reason=policy_decision.reason,
            reason_code=policy_decision.reason_code,
            contract_version=plan.contract_hash,
            evidence_tier=policy_decision.evidence_tier,
            actor_role=policy_decision.actor_role,
            plan_ref=policy_decision.plan_ref,
            policy_trace=policy_decision.policy_trace,
            source_role_matrix=[
                {
                    "source_id": policy_decision.source_id,
                    "role": policy_decision.actor_role,
                    "operation": policy_decision.operation,
                }
            ],
            replay_refs=[artifact_id],
        )

    if answer.decision == "answer" and not answer.evidence_tier:
        answer.evidence_tier = policy_decision.evidence_tier
    answer.reason_code = policy_decision.reason_code
    answer.policy_trace = policy_decision.policy_trace
    answer.replay_refs.append(artifact_id)
    return answer


def evaluate(answer: Answer, plan: QueryPlan, *, metric_id: str = "") -> PolicyDecision:
    source_id, operation = _source_operation(plan)
    evidence_tier = answer.evidence_tier or TIER_CONTRACT
    actor_role = plan.actor.role or answer.actor_role

    if plan.decision == DECISION_REFUSE:
        trace = [
            {
                "rule_id": "plan_decision_refuse",
                "effect": "deny",
                "matched": True,
                "reason_code": "POLICY_PLAN_REFUSED",
            }
        ]
        return _make_decision(
            decision=DECISION_REFUSE,
            reason="plan-time refusal",
            reason_code="POLICY_PLAN_REFUSED",
            policy_trace=trace,
            actor_role=actor_role,
            source_id=source_id,
            operation=operation,
            plan_ref=plan.plan_id,
            metric_id=metric_id,
            evidence_tier=evidence_tier,
        )

    config = _load_rules()
    for rule in config.get("rules", []):
        if not isinstance(rule, dict):
            continue
        matched = _rule_matches(
            rule.get("match", {}),
            actor_role,
            source_id,
            operation,
            metric_id,
        )
        trace_entry = {
            "rule_id": str(rule.get("id", "unnamed_rule")),
            "effect": str(rule.get("effect", "")),
            "matched": matched,
            "reason_code": str(rule.get("reason_code", "")),
        }
        if matched and rule.get("effect") == "deny":
            return _make_decision(
                decision=DECISION_REFUSE,
                reason=str(rule.get("reason", "policy denied request")),
                reason_code=str(rule.get("reason_code", "POLICY_DENIED")),
                policy_trace=[trace_entry],
                actor_role=actor_role,
                source_id=source_id,
                operation=operation,
                plan_ref=plan.plan_id,
                metric_id=metric_id,
                evidence_tier=evidence_tier,
            )

    default = config.get("default", {})
    return _make_decision(
        decision=str(default.get("decision", "answer")),
        reason=str(default.get("reason", "no deny policy rule matched")),
        reason_code=str(default.get("reason_code", "POLICY_DEFAULT_ALLOW")),
        policy_trace=[
            {
                "rule_id": "default",
                "effect": "allow",
                "matched": True,
                "reason_code": str(default.get("reason_code", "POLICY_DEFAULT_ALLOW")),
            }
        ],
        actor_role=actor_role,
        source_id=source_id,
        operation=operation,
        plan_ref=plan.plan_id,
        metric_id=metric_id,
        evidence_tier=evidence_tier,
    )


def _load_rules() -> dict[str, Any]:
    return yaml.safe_load(POLICY_RULES_PATH.read_text(encoding="utf-8")) or {}


def compute_policy_hash() -> str:
    """Stable fingerprint of the active policy ruleset for drift detection."""
    raw = POLICY_RULES_PATH.read_text(encoding="utf-8")
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _source_operation(plan: QueryPlan) -> tuple[str, str]:
    if not plan.selected_sources:
        return "", plan.capability
    selected = plan.selected_sources[0]
    return str(selected.get("source_id", "")), str(selected.get("operation", plan.capability))


def _rule_matches(
    match: Any,
    actor_role: str,
    source_id: str,
    operation: str,
    metric_id: str,
) -> bool:
    if not isinstance(match, dict):
        return False
    return (
        _value_matches(actor_role, match.get("actor_roles"))
        and _value_matches(source_id, match.get("source_ids"))
        and _value_matches(operation, match.get("operations"))
        and _glob_matches(metric_id, match.get("metric_ids"))
    )


def _glob_matches(value: str, patterns: Any) -> bool:
    if not patterns:
        return True
    if not value:
        return False
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(fnmatch.fnmatch(value, str(pattern)) for pattern in patterns)


def _value_matches(value: str, allowed: Any) -> bool:
    if not allowed:
        return True
    if isinstance(allowed, str):
        allowed = [allowed]
    return "*" in allowed or value in allowed


def project_access(
    actor_role: str,
    *,
    metric_id: str = "",
    source_id: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """Read-only policy projection for context/trust checks without QueryPlan or ledger."""
    config = _load_rules()
    for rule in config.get("rules", []):
        if not isinstance(rule, dict):
            continue
        matched = _rule_matches(
            rule.get("match", {}),
            actor_role,
            source_id,
            "structured_query",
            metric_id,
        )
        if matched and rule.get("effect") == "deny":
            trace = {
                "rule_id": str(rule.get("id", "unnamed_rule")),
                "effect": "deny",
                "matched": True,
                "reason_code": str(rule.get("reason_code", "")),
            }
            return False, str(rule.get("reason_code", "POLICY_DENIED")), trace

    default = config.get("default", {})
    trace = {
        "rule_id": "default",
        "effect": "allow",
        "matched": True,
        "reason_code": str(default.get("reason_code", "POLICY_DEFAULT_ALLOW")),
    }
    return True, str(default.get("reason_code", "POLICY_DEFAULT_ALLOW")), trace


def _make_decision(**payload: Any) -> PolicyDecision:
    decision_payload = json.dumps(payload, sort_keys=True)
    decision_id = "pdec-" + hashlib.sha256(decision_payload.encode()).hexdigest()[:16]
    return PolicyDecision(decision_id=decision_id, **payload)
