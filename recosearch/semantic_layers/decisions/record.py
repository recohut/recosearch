from __future__ import annotations

import time
from typing import Any

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.hash import compute_decision_id
from recosearch.semantic_layers.decisions.types import DecisionRecord
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers import policy


class DecisionRecordError(ValueError):
    pass


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


def claim_set_from_snapshot(snapshot: dict[str, Any]) -> ClaimSet:
    subclaims = tuple(_subclaim_from_dict(item) for item in snapshot.get("subclaims", []) or [])
    return ClaimSet(
        subclaims=subclaims,
        pack_label=str(snapshot.get("pack_label", "board_pack")),
        min_tier_label=str(snapshot.get("min_tier_label", "")),
    )


def _claim_set_snapshot_from_pack(payload: dict[str, Any]) -> dict[str, Any]:
    if "claim_set" in payload and isinstance(payload["claim_set"], dict):
        return dict(payload["claim_set"])
    subclaims: list[dict[str, Any]] = []
    for result in payload.get("subclaim_results", []) or []:
        answer = result.get("answer", {}) or {}
        subclaims.append(
            {
                "term": result.get("term", ""),
                "comparable_group": result.get("comparable_group", ""),
                "time_period": result.get("period", ""),
                "actor_role": answer.get("actor_role", "analyst"),
                "scoped_question": answer.get("scoped_question", result.get("term", "")),
            }
        )
    return {"pack_label": "board_pack", "subclaims": subclaims}


def load_decision_record(decision_id: str) -> DecisionRecord | None:
    artifact = ledger.load_by_id(decision_id)
    if artifact is not None:
        payload = dict(artifact.get("payload", {}) or {})
        if payload.get("decision_id") == decision_id:
            return _decision_from_payload(payload)
    for event in ledger.events():
        if event.get("artifact_type") != "decision_record":
            continue
        payload = dict(event.get("payload", {}) or {})
        if payload.get("decision_id") == decision_id:
            return _decision_from_payload(payload)
    return None


def _decision_from_payload(payload: dict[str, Any]) -> DecisionRecord:
    return DecisionRecord(
        decision_id=str(payload["decision_id"]),
        pack_id=str(payload["pack_id"]),
        actor=str(payload.get("actor", "")),
        decision_payload=dict(payload.get("decision_payload", {}) or {}),
        expected_outcome=dict(payload.get("expected_outcome", {}) or {}),
        outcome_due_date=str(payload.get("outcome_due_date", "")),
        contract_hash=str(payload.get("contract_hash", "")),
        policy_hash=str(payload.get("policy_hash", "")),
        recorded_at=float(payload.get("recorded_at", 0.0)),
        claim_set_snapshot=dict(payload.get("claim_set_snapshot", {}) or {}),
        original_pack_decision=str(payload.get("original_pack_decision", "")),
        original_min_tier=str(payload.get("original_min_tier", "")),
    )


def _load_pack_artifact(pack_id: str) -> dict[str, Any] | None:
    artifact = ledger.load_by_id(pack_id)
    if artifact is not None:
        if artifact.get("artifact_type") != "evidence_pack":
            return artifact
        payload = dict(artifact.get("payload", {}) or {})
        if payload.get("pack_id", pack_id) == pack_id:
            return artifact
    for event in ledger.events():
        if event.get("artifact_type") != "evidence_pack":
            continue
        payload = dict(event.get("payload", {}) or {})
        if payload.get("pack_id") == pack_id:
            return event
    return None


def record_decision(
    pack_id: str,
    *,
    actor: str,
    decision_payload: dict[str, Any],
    expected_outcome: dict[str, Any],
    outcome_due_date: str,
    contract: dict[str, Any],
    claim_set_snapshot: dict[str, Any] | None = None,
) -> DecisionRecord:
    contract_hash = str(contract.get("contract_hash", ""))
    pack_artifact = _load_pack_artifact(pack_id)
    if pack_artifact is None:
        raise DecisionRecordError(f"missing evidence pack: {pack_id}")
    if pack_artifact.get("artifact_type") != "evidence_pack":
        raise DecisionRecordError(f"artifact is not an evidence pack: {pack_id}")
    artifact_id = str(pack_artifact.get("artifact_id", ""))
    if artifact_id and ledger.is_expired(artifact_id, contract_hash=contract_hash):
        raise DecisionRecordError(f"evidence pack expired or contract drift: {pack_id}")

    pack_payload = dict(pack_artifact.get("payload", {}) or {})
    snapshot = claim_set_snapshot or _claim_set_snapshot_from_pack(pack_payload)
    policy_hash = policy.compute_policy_hash()

    decision_id = compute_decision_id(
        pack_id=pack_id,
        actor=actor,
        decision_payload=decision_payload,
        contract_hash=contract_hash,
        policy_hash=policy_hash,
    )
    recorded_at = time.time()
    record = DecisionRecord(
        decision_id=decision_id,
        pack_id=pack_id,
        actor=actor,
        decision_payload=dict(decision_payload),
        expected_outcome=dict(expected_outcome),
        outcome_due_date=outcome_due_date,
        contract_hash=contract_hash,
        policy_hash=policy_hash,
        recorded_at=recorded_at,
        claim_set_snapshot=snapshot,
        original_pack_decision=str(pack_payload.get("decision", "")),
        original_min_tier=str(pack_payload.get("evidence_tier_min", "")),
    )

    from recosearch.semantic_layers.ledger import LineageEdge

    ledger.record(
        "decision_record",
        source_id=pack_id,
        evidence_tier=str(pack_payload.get("evidence_tier_min", "")),
        payload=record.to_dict(),
        contract_hash=contract_hash,
        lineage_edges=[LineageEdge(from_id=decision_id, to_id=pack_id, kind="informed_by")],
    )
    return record
