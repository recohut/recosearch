from __future__ import annotations

from typing import Any

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers import policy
from recosearch.semantic_layers.decisions.hash import compute_counterfactual_id
from recosearch.semantic_layers.decisions.overlay import apply_contract_overlay
from recosearch.semantic_layers.decisions.record import claim_set_from_snapshot, load_decision_record
from recosearch.semantic_layers.decisions.types import CounterfactualResult, ReplayResult
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack


class ReplayError(ValueError):
    pass


def replay_decision(
    decision_id: str,
    *,
    contract: dict[str, Any],
    target_contract_hash: str | None = None,
) -> ReplayResult:
    decision = load_decision_record(decision_id)
    if decision is None:
        raise ReplayError(f"missing decision record: {decision_id}")

    replayed_contract_hash = target_contract_hash or str(contract.get("contract_hash", ""))
    claim_set = claim_set_from_snapshot(decision.claim_set_snapshot)
    pack, _answer = compose_evidence_pack(claim_set, contract=contract)

    original_decision = decision.original_pack_decision
    replayed_decision = pack.decision
    current_policy_hash = policy.compute_policy_hash()

    drift_reasons: list[str] = []
    if decision.contract_hash != replayed_contract_hash:
        drift_reasons.append("contract_hash_changed")
    if decision.policy_hash != current_policy_hash:
        drift_reasons.append("policy_hash_changed")
    if original_decision != replayed_decision:
        drift_reasons.append(f"decision_changed:{original_decision}->{replayed_decision}")
    if decision.original_min_tier != pack.evidence_tier_min:
        drift_reasons.append("min_tier_changed")

    drift = bool(drift_reasons)
    return ReplayResult(
        decision_id=decision_id,
        original_contract_hash=decision.contract_hash,
        replayed_contract_hash=replayed_contract_hash,
        original_decision=original_decision,
        replayed_decision=replayed_decision,
        drift=drift,
        drift_reasons=tuple(sorted(set(drift_reasons))),
        replayed_pack_id=pack.pack_id,
        replayed_min_tier=pack.evidence_tier_min,
    )


def counterfactual_replay(
    decision_id: str,
    *,
    contract: dict[str, Any],
    overrides: dict[str, Any],
    scenario_label: str = "custom",
) -> CounterfactualResult:
    decision = load_decision_record(decision_id)
    if decision is None:
        raise ReplayError(f"missing decision record: {decision_id}")

    baseline_contract_hash = str(contract.get("contract_hash", ""))
    claim_set = claim_set_from_snapshot(decision.claim_set_snapshot)

    baseline_pack, _ = compose_evidence_pack(claim_set, contract=contract)
    baseline_decision = baseline_pack.decision

    overlayed = apply_contract_overlay(contract, overrides)
    counterfactual_contract_hash = str(overlayed.get("contract_hash", ""))
    cf_pack, _ = compose_evidence_pack(claim_set, contract=overlayed)
    counterfactual_decision = cf_pack.decision

    deltas: list[str] = []
    if baseline_decision != counterfactual_decision:
        deltas.append(f"decision:{baseline_decision}->{counterfactual_decision}")
    if baseline_contract_hash != counterfactual_contract_hash:
        deltas.append("contract_hash_changed")
    if baseline_pack.evidence_tier_min != cf_pack.evidence_tier_min:
        deltas.append(
            f"min_tier:{baseline_pack.evidence_tier_min}->{cf_pack.evidence_tier_min}"
        )

    result = CounterfactualResult(
        decision_id=decision_id,
        scenario_label=scenario_label,
        baseline_decision=baseline_decision,
        counterfactual_decision=counterfactual_decision,
        changed=baseline_decision != counterfactual_decision,
        deltas=tuple(deltas),
        baseline_contract_hash=baseline_contract_hash,
        counterfactual_contract_hash=counterfactual_contract_hash,
    )

    cf_id = compute_counterfactual_id(
        decision_id=decision_id,
        scenario_label=scenario_label,
        counterfactual_contract_hash=counterfactual_contract_hash,
    )
    payload = result.to_dict()
    payload["counterfactual_id"] = cf_id
    ledger.record(
        "counterfactual_result",
        source_id=decision_id,
        payload=payload,
        contract_hash=baseline_contract_hash,
    )
    return result


def persist_replay_result(result: ReplayResult, *, contract_hash: str) -> str:
    artifact_id = ledger.record(
        "replay_result",
        source_id=result.decision_id,
        payload=result.to_dict(),
        contract_hash=contract_hash,
    )
    return artifact_id
