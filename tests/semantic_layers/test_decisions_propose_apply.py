from __future__ import annotations

import shutil

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.contract import SEMANTIC_DIR
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration
from recosearch.semantic_layers.decisions.apply_proposal import (
    approve_trust_prior_proposal,
    load_trust_overrides,
    reject_trust_prior_proposal,
)
from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.decisions.propose import ProposalError, propose_trust_prior, propose_trust_prior_from_ledger
from recosearch.semantic_layers.decisions.record import record_decision
from recosearch.semantic_layers.context.loader import ContextKernelLoader
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim


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


def _seed_miss(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "defer_revenue_recognition"},
        expected_outcome={"status": "recognized", "period": "2026-Q2", "amount": 1.0},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
    )
    record_outcome(
        decision.decision_id,
        actual_outcome={"status": "deferred", "period": "2026-Q3", "amount": 2.0},
        contract_hash=str(compile_contract.get("contract_hash", "")),
    )
    generate_calibration_signal(decision.decision_id, contract=compile_contract)


class TestTrustPriorProposal:
    def setup_method(self):
        ledger.clear()

    def test_propose_on_miss_breach(self, compile_contract):
        _seed_miss(compile_contract)
        report = aggregate_calibration(contract=compile_contract)
        proposal = propose_trust_prior(report, contract=compile_contract)
        assert proposal is not None
        assert proposal.status == "pending"
        assert proposal.term_id.startswith("term:novashop:")

    def test_no_proposal_on_match(self, compile_contract):
        pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
        decision = record_decision(
            pack.pack_id,
            actor="controller",
            decision_payload={"action": "approve_board_pack"},
            expected_outcome={"status": "recognized", "period": "2026-Q1", "amount": 1.0},
            outcome_due_date="2026-04-15",
            contract=compile_contract,
        )
        record_outcome(
            decision.decision_id,
            actual_outcome={"status": "recognized", "period": "2026-Q1", "amount": 1.0},
            contract_hash=str(compile_contract.get("contract_hash", "")),
        )
        generate_calibration_signal(decision.decision_id, contract=compile_contract)
        proposal = propose_trust_prior_from_ledger(contract=compile_contract)
        assert proposal is None


class TestApplyProposal:
    def setup_method(self):
        ledger.clear()

    def test_approve_writes_override_and_bumps_contract_hash(self, compile_contract, tmp_path):
        _seed_miss(compile_contract)
        proposal = propose_trust_prior_from_ledger(contract=compile_contract)
        assert proposal is not None
        context_dir = tmp_path / "context"
        context_dir.mkdir()
        before_hash = str(compile_contract.get("contract_hash", ""))
        path = approve_trust_prior_proposal(
            proposal.proposal_id,
            context_dir=context_dir,
            operator="cert-operator",
        )
        assert path.exists()
        overrides = load_trust_overrides(context_dir)
        assert overrides["overrides"][0]["term_id"] == proposal.term_id

        from recosearch.semantic_layers.contract import compile_contract as compile_semantic_contract

        semantic = tmp_path / "semantic"
        shutil.copytree(SEMANTIC_DIR, semantic)
        trust_path = semantic / "context" / "_trust_overrides.yaml"
        trust_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        new_contract = compile_semantic_contract(semantic)
        assert new_contract["contract_hash"] != before_hash
        kernel = ContextKernelLoader.from_contract(new_contract)
        cert = kernel.certifications[proposal.term_id]
        assert cert.ares_confidence_interval == proposal.proposed_ci

    def test_reject_no_override_file(self, compile_contract, tmp_path):
        _seed_miss(compile_contract)
        proposal = propose_trust_prior_from_ledger(contract=compile_contract)
        assert proposal is not None
        context_dir = tmp_path / "context"
        context_dir.mkdir()
        rejected = reject_trust_prior_proposal(proposal.proposal_id, operator="cert-operator")
        assert rejected.status == "rejected"
        assert not (context_dir / "_trust_overrides.yaml").exists()

    def test_approve_non_pending_raises(self, compile_contract, tmp_path):
        _seed_miss(compile_contract)
        proposal = propose_trust_prior_from_ledger(contract=compile_contract)
        assert proposal is not None
        context_dir = tmp_path / "context"
        context_dir.mkdir()
        approve_trust_prior_proposal(proposal.proposal_id, context_dir=context_dir, operator="op")
        with pytest.raises(ProposalError):
            approve_trust_prior_proposal(proposal.proposal_id, context_dir=context_dir, operator="op")
