from __future__ import annotations

import time
from typing import Any

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.hash import compute_outcome_id
from recosearch.semantic_layers.decisions.record import load_decision_record
from recosearch.semantic_layers.decisions.types import OutcomeRecord


class OutcomeRecordError(ValueError):
    pass


def load_outcome_record(outcome_id: str) -> OutcomeRecord | None:
    artifact = ledger.load_by_id(outcome_id)
    if artifact is not None:
        payload = dict(artifact.get("payload", {}) or {})
        if payload.get("outcome_id") == outcome_id:
            return _outcome_from_payload(payload)
    for event in ledger.events():
        if event.get("artifact_type") != "outcome_record":
            continue
        payload = dict(event.get("payload", {}) or {})
        if payload.get("outcome_id") == outcome_id:
            return _outcome_from_payload(payload)
    return None


def _outcome_from_payload(payload: dict[str, Any]) -> OutcomeRecord:
    return OutcomeRecord(
        outcome_id=str(payload["outcome_id"]),
        decision_id=str(payload["decision_id"]),
        actual_outcome=dict(payload.get("actual_outcome", {}) or {}),
        recorded_at=float(payload.get("recorded_at", 0.0)),
    )


def find_outcome_for_decision(decision_id: str) -> OutcomeRecord | None:
    for event in ledger.events():
        if event.get("artifact_type") != "outcome_record":
            continue
        payload = event.get("payload", {}) or {}
        if payload.get("decision_id") == decision_id:
            return _outcome_from_payload(payload)
    return None


def record_outcome(
    decision_id: str,
    *,
    actual_outcome: dict[str, Any],
    contract_hash: str = "",
) -> OutcomeRecord:
    decision = load_decision_record(decision_id)
    if decision is None:
        raise OutcomeRecordError(f"missing decision record: {decision_id}")

    outcome_id = compute_outcome_id(decision_id=decision_id, actual_outcome=actual_outcome)
    recorded_at = time.time()
    record = OutcomeRecord(
        outcome_id=outcome_id,
        decision_id=decision_id,
        actual_outcome=dict(actual_outcome),
        recorded_at=recorded_at,
    )

    from recosearch.semantic_layers.ledger import LineageEdge

    ledger.record(
        "outcome_record",
        source_id=decision_id,
        payload=record.to_dict(),
        contract_hash=contract_hash or decision.contract_hash,
        lineage_edges=[LineageEdge(from_id=outcome_id, to_id=decision_id, kind="realizes")],
    )
    return record
