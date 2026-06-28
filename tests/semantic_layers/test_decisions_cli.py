from __future__ import annotations

import json
from argparse import Namespace

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.contract import ROOT, SEMANTIC_DIR
from recosearch.semantic_layers.decisions.certify import CERTIFICATION_RESULTS_FILENAME
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers.metrics.cli import (
    cmd_decision_aggregate,
    cmd_decision_calibrate,
    cmd_decision_certify,
    cmd_decision_counterfactual,
    cmd_decision_outcome,
    cmd_decision_propose,
    cmd_decision_record,
    cmd_decision_replay,
    cmd_decision_verify,
    cmd_proposal_approve,
    cmd_proposal_reject,
)


def _claim_set() -> ClaimSet:
    return ClaimSet(
        subclaims=(
            Subclaim(
                term="revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date="2026-01-31",
                time_period="2026-01",
            ),
        ),
        pack_label="board_pack",
    )


def _args(**kwargs):
    defaults = {"semantic_dir": str(SEMANTIC_DIR)}
    defaults.update(kwargs)
    return Namespace(**defaults)


def test_cmd_decision_record_success_prints_json(compile_contract, capsys):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    assert (
        cmd_decision_record(
            _args(
                pack_id=pack.pack_id,
                actor="controller",
                decision_payload=json.dumps({"action": "approve"}),
                expected_outcome=json.dumps({"status": "recognized"}),
                outcome_due_date="2026-07-01",
            )
        )
        == 0
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["pack_id"] == pack.pack_id
    decision_id = payload["decision_id"]

    assert cmd_decision_replay(_args(decision_id=decision_id)) == 0
    assert (
        cmd_decision_outcome(
            _args(
                decision_id=decision_id,
                actual_outcome=json.dumps({"status": "recognized"}),
            )
        )
        == 0
    )
    assert cmd_decision_calibrate(_args(decision_id=decision_id)) == 0
    assert cmd_decision_aggregate(_args()) == 0
    assert cmd_decision_propose(_args()) in (0, 0)
    assert cmd_decision_counterfactual(_args(decision_id=decision_id, scenario="raise_tier_bar_to_local_live")) == 0
    assert (
        cmd_decision_counterfactual(
            _args(
                decision_id=decision_id,
                scenario="",
                overrides=json.dumps({"policy_hash": "cli-test-hash"}),
            )
        )
        == 0
    )


def test_cmd_decision_record_failure():
    assert (
        cmd_decision_record(
            _args(
                pack_id="pack-missing",
                actor="controller",
                decision_payload=json.dumps({"action": "approve"}),
                expected_outcome=json.dumps({"status": "recognized"}),
                outcome_due_date="2026-07-01",
            )
        )
        == 1
    )


def test_cmd_decision_certify_and_verify(tmp_path):
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    for name in ("_decisions.yaml", "_certification.yaml"):
        (decisions_dir / name).write_text(
            (ROOT / "semantic" / "decisions" / name).read_text(encoding="utf-8")
        )
    assert cmd_decision_certify(_args(decisions_dir=str(decisions_dir))) == 0
    assert cmd_decision_verify(_args(decisions_dir=str(decisions_dir))) == 0


def test_cmd_decision_verify_fails_without_certification(tmp_path):
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    for name in ("_decisions.yaml", "_certification.yaml"):
        (decisions_dir / name).write_text(
            (ROOT / "semantic" / "decisions" / name).read_text(encoding="utf-8")
        )
    results_path = decisions_dir / CERTIFICATION_RESULTS_FILENAME
    if results_path.exists():
        results_path.unlink()
    assert cmd_decision_verify(_args(decisions_dir=str(decisions_dir))) == 1


def test_cmd_decision_replay_failure():
    assert cmd_decision_replay(_args(decision_id="decision-missing")) == 1


def test_cmd_decision_outcome_failure():
    assert (
        cmd_decision_outcome(
            _args(
                decision_id="decision-missing",
                actual_outcome=json.dumps({"status": "recognized"}),
            )
        )
        == 1
    )


def test_cmd_decision_calibrate_failure():
    assert cmd_decision_calibrate(_args(decision_id="decision-missing")) == 1


def test_cmd_decision_record_invalid_json():
    assert (
        cmd_decision_record(
            _args(
                pack_id="pack-missing",
                actor="controller",
                decision_payload=json.dumps([]),
                expected_outcome=json.dumps({"status": "recognized"}),
                outcome_due_date="2026-07-01",
            )
        )
        == 1
    )


def test_cmd_decision_certify_registry_failure(tmp_path):
    assert cmd_decision_certify(_args(decisions_dir=str(tmp_path))) == 1


def test_cmd_decision_certify_verify_failure_after_persist(compile_contract, tmp_path, monkeypatch):
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    for name in ("_decisions.yaml", "_certification.yaml"):
        (decisions_dir / name).write_text(
            (ROOT / "semantic" / "decisions" / name).read_text(encoding="utf-8")
        )

    def _stale_verify(*_args, **_kwargs):
        return ["stale decision certification (hash mismatch)"]

    monkeypatch.setattr(
        "recosearch.semantic_layers.metrics.cli.verify_decision_certification_results",
        _stale_verify,
    )
    assert cmd_decision_certify(_args(decisions_dir=str(decisions_dir))) == 1


def test_cmd_world_sota_proposal_gate(tmp_path, compile_contract, capsys):
    from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision

    ledger.clear()
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "defer_revenue_recognition"},
        expected_outcome={"status": "a", "period": "2026-Q2", "amount": 1.0},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
    )
    record_outcome(
        decision.decision_id,
        actual_outcome={"status": "b", "period": "2026-Q3", "amount": 2.0},
        contract_hash=str(compile_contract.get("contract_hash", "")),
    )
    generate_calibration_signal(decision.decision_id, contract=compile_contract)
    proposal = propose_trust_prior_from_ledger(contract=compile_contract)
    assert proposal is not None
    assert cmd_decision_propose(_args()) == 0
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    assert cmd_proposal_approve(_args(proposal_id=proposal.proposal_id, context_dir=str(context_dir))) == 0
    assert cmd_proposal_reject(_args(proposal_id=proposal.proposal_id)) == 1


def test_cmd_world_sota_null_proposal_and_failures(compile_contract, capsys):
    assert cmd_decision_propose(_args()) == 0
    assert capsys.readouterr().out.strip() == "null"
    assert cmd_decision_counterfactual(_args(decision_id="decision-missing", scenario="missing")) == 1
    assert (
        cmd_decision_counterfactual(
            _args(decision_id="decision-missing", scenario="", overrides=json.dumps({"policy_hash": "x"}))
        )
        == 1
    )
    assert cmd_proposal_approve(_args(proposal_id="proposal-missing", context_dir=str(SEMANTIC_DIR / "context"))) == 1
    assert cmd_proposal_reject(_args(proposal_id="proposal-missing")) == 1


def test_cmd_decision_aggregate_failure(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("aggregate failed")

    monkeypatch.setattr("recosearch.semantic_layers.metrics.cli.aggregate_calibration", _boom)
    assert cmd_decision_aggregate(_args()) == 1


def test_cmd_decision_propose_failure(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("propose failed")

    monkeypatch.setattr("recosearch.semantic_layers.metrics.cli.propose_trust_prior_from_ledger", _boom)
    assert cmd_decision_propose(_args()) == 1


def test_cmd_proposal_reject_success(compile_contract, tmp_path):
    from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision

    ledger.clear()
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "defer_revenue_recognition"},
        expected_outcome={"status": "a", "period": "2026-Q2", "amount": 1.0},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
    )
    record_outcome(
        decision.decision_id,
        actual_outcome={"status": "b", "period": "2026-Q3", "amount": 2.0},
        contract_hash=str(compile_contract.get("contract_hash", "")),
    )
    generate_calibration_signal(decision.decision_id, contract=compile_contract)
    proposal = propose_trust_prior_from_ledger(contract=compile_contract)
    assert proposal is not None
    assert cmd_proposal_reject(_args(proposal_id=proposal.proposal_id)) == 0
