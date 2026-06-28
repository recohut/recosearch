from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration
from recosearch.semantic_layers.decisions.apply_proposal import (
    approve_trust_prior_proposal,
    load_trust_overrides,
    reject_trust_prior_proposal,
    trust_overrides_to_dict,
)
from recosearch.semantic_layers.decisions.loader import (
    load_counterfactuals_config,
    load_counterfactuals_from_contract,
)
from recosearch.semantic_layers.decisions.overlay import apply_contract_overlay, deep_merge_contract
from recosearch.semantic_layers.decisions.propose import ProposalError, load_trust_prior_proposal, propose_trust_prior
from recosearch.semantic_layers.decisions.replay import ReplayError, counterfactual_replay
from recosearch.semantic_layers.decisions.schema import DecisionSchemaError, validate_counterfactuals_config
from recosearch.semantic_layers.decisions.stats import match_rate_interval, miss_rate_ci_low


def test_aggregate_filters(compile_contract):
    ledger.clear()
    report = aggregate_calibration(
        contract=compile_contract,
        decision_class="miss",
        term="term:novashop:revenue",
    )
    assert report.n == 0
    assert report.decision_class == "miss"
    assert report.term_id == "term:novashop:revenue"


def test_stats_unknown_method():
    with pytest.raises(ValueError, match="unknown confidence method"):
        match_rate_interval(1, 2, method="bad")
    with pytest.raises(ValueError, match="unknown confidence method"):
        miss_rate_ci_low(1, 2, method="bad")


def test_overlay_merge_tier_bars(compile_contract):
    overlay = {
        "evidence_gates": {
            "evidence_tier_bars": [{"pattern": "board_pack", "min_tier_label": "local-live"}]
        }
    }
    merged = apply_contract_overlay(compile_contract, overlay)
    assert merged["contract_hash"] != compile_contract["contract_hash"]
    bars = merged["evidence_gates"]["evidence_tier_bars"]
    assert any(b["pattern"] == "board_pack" and b["min_tier_label"] == "local-live" for b in bars)


def test_deep_merge_policy_overlay(compile_contract):
    merged = deep_merge_contract(compile_contract, {"policy_hash": "abc"})
    assert merged["policy_hash"] == "abc"


def test_counterfactual_schema_unknown_key(tmp_path):
    raw = {"scenarios": {"x": {"overlay": {"unknown_key": 1}}}}
    with pytest.raises(DecisionSchemaError):
        validate_counterfactuals_config(raw)


def test_counterfactual_schema_bad_overlay(tmp_path):
    raw = {"scenarios": {"x": {"overlay": "not-a-map"}}}
    with pytest.raises(DecisionSchemaError):
        validate_counterfactuals_config(raw)


def test_load_counterfactuals_from_contract_bad(compile_contract):
    bad = dict(compile_contract)
    bad["counterfactuals_config"] = "bad"
    with pytest.raises(ValueError):
        load_counterfactuals_from_contract(bad)


def test_load_trust_overrides_invalid(tmp_path):
    path = tmp_path / "_trust_overrides.yaml"
    path.write_text("not-a-mapping", encoding="utf-8")
    with pytest.raises(ValueError):
        load_trust_overrides(tmp_path)


def test_trust_overrides_to_dict_skips_invalid():
    out = trust_overrides_to_dict({"overrides": ["bad", {"term_id": "t", "ares_confidence_interval": [0.1, 0.2]}]})
    assert len(out["overrides"]) == 1


def test_replay_missing_decision(compile_contract):
    with pytest.raises(ReplayError):
        counterfactual_replay("decision-missing", contract=compile_contract, overrides={}, scenario_label="x")


def test_propose_missing_term(compile_contract):
    ledger.clear()
    from recosearch.semantic_layers.decisions.types import CalibrationReport

    report = CalibrationReport(
        report_id="report-test",
        n=5,
        match_rate=0.2,
        ci_low=0.1,
        ci_high=0.3,
        miss_rate=0.8,
        miss_ci_low=0.9,
        method="wilson",
    )
    empty = dict(compile_contract)
    empty["context_kernel"] = {"version": 1, "terms": [], "guidance": [], "relationships": [], "certifications": []}
    assert propose_trust_prior(report, contract=empty) is None


def test_load_trust_prior_proposal_missing():
    assert load_trust_prior_proposal("proposal-missing") is None


def test_approve_missing_proposal(tmp_path):
    with pytest.raises(ProposalError):
        approve_trust_prior_proposal("proposal-missing", context_dir=tmp_path, operator="op")


def test_reject_missing_proposal():
    with pytest.raises(ProposalError):
        reject_trust_prior_proposal("proposal-missing", operator="op")


def test_load_counterfactuals_config(tmp_path):
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "_counterfactuals.yaml").write_text(
        yaml.safe_dump(
            {
                "scenarios": {
                    "s1": {
                        "label": "s1",
                        "overlay": {"policy_hash": "x"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    scenarios = load_counterfactuals_config(decisions)
    assert "s1" in scenarios


def test_aggregate_filters_with_signals(compile_contract):
    ledger.clear()
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

    pack, _ = compose_evidence_pack(
        ClaimSet(
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
        ),
        contract=compile_contract,
    )
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
    signal = generate_calibration_signal(decision.decision_id, contract=compile_contract)
    assert signal.calibration_delta == "miss"

    by_class = aggregate_calibration(contract=compile_contract, decision_class="match")
    assert by_class.n == 0
    by_term = aggregate_calibration(contract=compile_contract, term="term:novashop:deferred_revenue")
    assert by_term.n == 1
    wrong_term = aggregate_calibration(contract=compile_contract, term="term:missing")
    assert wrong_term.n == 0


def test_breach_without_trigger():
    from recosearch.semantic_layers.decisions.types import CalibrationReport
    from recosearch.semantic_layers.decisions.aggregate import breach_trust_prior_trigger

    contract = {"decisions_config": {"confidence_method": "wilson"}}
    report = CalibrationReport(
        report_id="r",
        n=1,
        match_rate=0.0,
        ci_low=0.0,
        ci_high=0.0,
        miss_rate=1.0,
        miss_ci_low=0.9,
        method="wilson",
    )
    assert breach_trust_prior_trigger(report, contract=contract) is False


def test_breach_below_min_n(compile_contract):
    from recosearch.semantic_layers.decisions.types import CalibrationReport
    from recosearch.semantic_layers.decisions.aggregate import breach_trust_prior_trigger

    contract = dict(compile_contract)
    contract["decisions_config"] = dict(contract["decisions_config"])
    contract["decisions_config"]["trust_prior_trigger"] = {"min_n": 99, "miss_rate_ci_low_threshold": 0.01}
    report = CalibrationReport(
        report_id="r",
        n=1,
        match_rate=0.0,
        ci_low=0.0,
        ci_high=0.0,
        miss_rate=1.0,
        miss_ci_low=0.9,
        method="wilson",
    )
    assert breach_trust_prior_trigger(report, contract=contract) is False


def test_approve_replaces_existing_override(compile_contract, tmp_path):
    from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

    ledger.clear()
    pack, _ = compose_evidence_pack(
        ClaimSet(
            subclaims=(
                Subclaim(term="revenue", tenant="novashop", actor_role="analyst", reference_date="2026-01-31", time_period="2026-01"),
            ),
            pack_label="board_pack",
        ),
        contract=compile_contract,
    )
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
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    approve_trust_prior_proposal(proposal.proposal_id, context_dir=context_dir, operator="op1")
    proposal2 = propose_trust_prior_from_ledger(contract=compile_contract)
    assert proposal2 is not None
    approve_trust_prior_proposal(proposal2.proposal_id, context_dir=context_dir, operator="op2")
    overrides = load_trust_overrides(context_dir)
    assert len(overrides["overrides"]) == 1


def test_reject_non_pending(compile_contract, tmp_path):
    from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

    ledger.clear()
    pack, _ = compose_evidence_pack(
        ClaimSet(
            subclaims=(
                Subclaim(term="revenue", tenant="novashop", actor_role="analyst", reference_date="2026-01-31", time_period="2026-01"),
            ),
            pack_label="board_pack",
        ),
        contract=compile_contract,
    )
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
    reject_trust_prior_proposal(proposal.proposal_id, operator="op")
    with pytest.raises(ProposalError):
        reject_trust_prior_proposal(proposal.proposal_id, operator="op")


def test_propose_resolve_term_paths(compile_contract):
    from recosearch.semantic_layers.decisions.types import CalibrationReport
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

    ledger.clear()
    pack, _ = compose_evidence_pack(
        ClaimSet(
            subclaims=(
                Subclaim(term="revenue", tenant="novashop", actor_role="analyst", reference_date="2026-01-31", time_period="2026-01"),
            ),
            pack_label="board_pack",
        ),
        contract=compile_contract,
    )
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
    signal = generate_calibration_signal(decision.decision_id, contract=compile_contract)
    report = CalibrationReport(
        report_id="report-x",
        n=1,
        match_rate=0.0,
        ci_low=0.0,
        ci_high=0.1,
        miss_rate=1.0,
        miss_ci_low=0.9,
        method="wilson",
        signal_ids=(signal.signal_id,),
    )
    proposal = propose_trust_prior(report, contract=compile_contract)
    assert proposal is not None
    assert proposal.term_id.startswith("term:")


def test_overlay_append_new_tier_bar(compile_contract):
    overlay = {
        "evidence_gates": {
            "evidence_tier_bars": [{"pattern": "new_pack", "min_tier_label": "local-live"}]
        }
    }
    merged = apply_contract_overlay(compile_contract, overlay)
    patterns = {b["pattern"] for b in merged["evidence_gates"]["evidence_tier_bars"]}
    assert "new_pack" in patterns


def test_miss_rate_ci_low_zero_total():
    assert miss_rate_ci_low(0, 0) == 0.0


def test_schema_unknown_confidence_method():
    from recosearch.semantic_layers.decisions.schema import validate_decisions_config

    with pytest.raises(DecisionSchemaError):
        validate_decisions_config({"confidence_method": "bad"})


def test_counterfactual_min_tier_delta(monkeypatch, compile_contract):
    from recosearch.semantic_layers.decisions.record import record_decision
    from recosearch.semantic_layers.evidence import compose as compose_module
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

    from recosearch.semantic_layers.decisions import replay as replay_module

    original = compose_module.compose_evidence_pack
    calls = {"n": 0}

    def fake_compose(claim_set, *, contract):
        pack, answer = original(claim_set, contract=contract)
        calls["n"] += 1
        if calls["n"] == 2:
            from dataclasses import replace

            pack = replace(pack, evidence_tier_min="local-live")
        return pack, answer

    monkeypatch.setattr(compose_module, "compose_evidence_pack", fake_compose)
    monkeypatch.setattr(replay_module, "compose_evidence_pack", fake_compose)

    ledger.clear()
    pack, _ = compose_evidence_pack(
        ClaimSet(
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
        ),
        contract=compile_contract,
    )
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "ok"},
        outcome_due_date="2026-04-15",
        contract=compile_contract,
    )
    result = counterfactual_replay(
        decision.decision_id,
        contract=compile_contract,
        overrides={"policy_hash": "x"},
        scenario_label="tier_only",
    )
    assert any("min_tier" in d for d in result.deltas)


def test_loader_counterfactual_edge_cases(tmp_path):
    from recosearch.semantic_layers.decisions.loader import load_counterfactuals_config, load_counterfactuals_from_contract

    empty = tmp_path / "decisions"
    empty.mkdir()
    assert load_counterfactuals_config(empty) == {}

    bad = tmp_path / "decisions2"
    bad.mkdir()
    (bad / "_counterfactuals.yaml").write_text("not-a-mapping", encoding="utf-8")
    with pytest.raises(ValueError):
        load_counterfactuals_config(bad)

    contract = {
        "counterfactuals_config": {
            "scenarios": {"s": {"overlay": {"policy_hash": "p"}}}
        }
    }
    loaded = load_counterfactuals_from_contract(contract)
    assert "s" in loaded
    assert load_counterfactuals_from_contract({}) == {}


def test_merge_tier_bars_skips_invalid_items():
    from recosearch.semantic_layers.decisions.overlay import _merge_tier_bars

    merged = _merge_tier_bars(
        [{"pattern": "a", "min_tier_label": "local-live"}],
        ["bad", {"pattern": "b", "min_tier_label": "fixture-backed"}],
    )
    patterns = {item["pattern"] for item in merged}
    assert patterns == {"a", "b"}


def test_overlay_skips_contract_hash_and_bad_tier_items(compile_contract):
    merged = deep_merge_contract(
        compile_contract,
        {
            "contract_hash": "ignored",
            "evidence_gates": {
                "evidence_tier_bars": ["bad", {"pattern": "x", "min_tier_label": "local-live"}]
            },
        },
    )
    assert "contract_hash" in merged
    patterns = {b["pattern"] for b in merged["evidence_gates"]["evidence_tier_bars"] if isinstance(b, dict)}
    assert "x" in patterns


def test_propose_term_id_and_fallback_ci(compile_contract, monkeypatch):
    from recosearch.semantic_layers.context.loader import ContextKernelLoader
    from recosearch.semantic_layers.context.types import ContextCertification, ContextKernel
    from recosearch.semantic_layers.decisions.propose import _current_ci_for_term, _resolve_primary_term_id, propose_trust_prior
    from recosearch.semantic_layers.decisions.types import CalibrationReport
    from types import MappingProxyType

    cert = ContextCertification(
        term_id="term:novashop:revenue",
        definition_hash="abc",
        policy_hash="def",
        golden_questions=(),
        ares_confidence_interval=None,
    )
    kernel = ContextKernel(
        terms=MappingProxyType({}),
        guidance=MappingProxyType({}),
        relationships=(),
        alias_index=MappingProxyType({}),
        certifications=MappingProxyType({"term:novashop:revenue": cert}),
        persisted_certification_results=MappingProxyType({}),
    )
    monkeypatch.setattr(ContextKernelLoader, "from_contract", lambda contract, metric_kernel=None: kernel)

    report = CalibrationReport(
        report_id="r1",
        n=1,
        match_rate=0.0,
        ci_low=0.0,
        ci_high=0.2,
        miss_rate=1.0,
        miss_ci_low=0.9,
        method="wilson",
        term_id="term:novashop:revenue",
    )
    assert _resolve_primary_term_id(report, contract=compile_contract) == "term:novashop:revenue"
    assert _current_ci_for_term("term:novashop:revenue", contract=compile_contract) == (0.0, 1.0)
    proposal = propose_trust_prior(report, contract=compile_contract)
    assert proposal is not None


def test_propose_resolve_from_context_cert_fallback(compile_contract):
    from recosearch.semantic_layers.decisions.propose import _resolve_primary_term_id
    from recosearch.semantic_layers.decisions.types import CalibrationReport

    report = CalibrationReport(
        report_id="r2",
        n=1,
        match_rate=0.0,
        ci_low=0.0,
        ci_high=0.2,
        miss_rate=1.0,
        miss_ci_low=0.9,
        method="wilson",
        signal_ids=("signal-not-in-ledger",),
    )
    term = _resolve_primary_term_id(report, contract=compile_contract)
    assert term.startswith("term:")


def test_propose_skips_unrelated_signals(compile_contract):
    from recosearch.semantic_layers.decisions.propose import _resolve_primary_term_id
    from recosearch.semantic_layers.decisions.types import CalibrationReport

    ledger.record(
        "calibration_signal",
        source_id="decision-x",
        payload={
            "signal_id": "signal-other",
            "advisory_targets": ["term:novashop:customer"],
        },
    )
    report = CalibrationReport(
        report_id="r3",
        n=1,
        match_rate=0.0,
        ci_low=0.0,
        ci_high=0.2,
        miss_rate=1.0,
        miss_ci_low=0.9,
        method="wilson",
        signal_ids=("signal-wanted",),
    )
    term = _resolve_primary_term_id(report, contract=compile_contract)
    assert term.startswith("term:")


def test_load_trust_prior_proposal_skips_other_ids(compile_contract):
    ledger.record(
        "trust_prior_proposal",
        source_id="proposal-other",
        payload={"proposal_id": "proposal-other", "term_id": "t", "trigger_report_id": "r", "current_ci": [0, 1], "proposed_ci": [0, 1], "proposed_trust_delta": 0, "rationale": "", "status": "pending"},
    )
    from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
    from recosearch.semantic_layers.decisions.outcomes import record_outcome
    from recosearch.semantic_layers.decisions.record import record_decision
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

    pack, _ = compose_evidence_pack(
        ClaimSet(
            subclaims=(
                Subclaim(term="revenue", tenant="novashop", actor_role="analyst", reference_date="2026-01-31", time_period="2026-01"),
            ),
            pack_label="board_pack",
        ),
        contract=compile_contract,
    )
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
    loaded = load_trust_prior_proposal(proposal.proposal_id)
    assert loaded is not None
    assert loaded.proposal_id == proposal.proposal_id


def test_validate_counterfactual_overlay_mapping_error():
    with pytest.raises(DecisionSchemaError):
        validate_counterfactuals_config({"scenarios": {"x": {"overlay": 123}}})


def test_certify_missing_counterfactual_scenario(compile_contract, tmp_path):
    from recosearch.semantic_layers.decisions.certify import run_decision_certifications

    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "_decisions.yaml").write_text(
        (Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers" / "semantic/decisions/_decisions.yaml").read_text(),
        encoding="utf-8",
    )
    (decisions / "_counterfactuals.yaml").write_text(
        (Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers" / "semantic/decisions/_counterfactuals.yaml").read_text(),
        encoding="utf-8",
    )
    (decisions / "_certification.yaml").write_text(
        yaml.safe_dump(
            {
                "certifications": [
                    {
                        "case_id": "bad_cf",
                        "expected_replay_drift": False,
                        "counterfactual_scenario": "missing_scenario",
                        "subclaims": [{"term": "revenue", "tenant": "novashop", "actor_role": "analyst"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    results = run_decision_certifications(compile_contract, decisions_dir=decisions)
    assert results["bad_cf"]["passed"] is False


def test_validate_registry_bad_counterfactual(tmp_path):
    from recosearch.semantic_layers.decisions.certify import validate_decisions_registry

    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "_decisions.yaml").write_text("{}", encoding="utf-8")
    (decisions / "_certification.yaml").write_text(
        yaml.safe_dump({"certifications": [{"case_id": "c", "expected_replay_drift": False, "subclaims": [{"term": "t"}]}]}),
        encoding="utf-8",
    )
    (decisions / "_counterfactuals.yaml").write_text(
        yaml.safe_dump({"scenarios": {"x": {"overlay": {"bad_key": 1}}}}),
        encoding="utf-8",
    )
    failures = validate_decisions_registry(decisions)
    assert failures

