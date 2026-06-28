from __future__ import annotations

import pytest
import yaml

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.decisions.calibrate import CalibrationError, generate_calibration_signal
from recosearch.semantic_layers.decisions.certify import (
    CERTIFICATION_FILENAME,
    load_decision_certifications,
    run_decision_certifications,
    validate_decisions_registry,
    verify_decision_certification_results,
)
from recosearch.semantic_layers.decisions.loader import load_decisions_config_from_contract
from recosearch.semantic_layers.decisions.outcomes import load_outcome_record
from recosearch.semantic_layers.decisions.record import (
    _claim_set_snapshot_from_pack,
    load_decision_record,
    record_decision,
)
from recosearch.semantic_layers.decisions.replay import ReplayError, replay_decision
from recosearch.semantic_layers.decisions.calibrate import _field_value, _values_match
from recosearch.semantic_layers.decisions.schema import validate_decision_certifications
from recosearch.semantic_layers.decisions.types import AdvisoryTargetRule, CalibrationMatchRule, DecisionKernel
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


def test_field_value_nested():
    assert _field_value({"a": {"b": 1}}, "a.b") == 1
    assert _field_value({"a": 1}, "missing") is None


def test_values_match_numeric_tolerance():
    assert _values_match(1.0, 1.005, mode="numeric_tolerance") is True
    assert _values_match("x", "y", mode="numeric_tolerance") is False


def test_claim_set_snapshot_from_pack_subclaim_results():
    snapshot = _claim_set_snapshot_from_pack(
        {
            "subclaim_results": [
                {
                    "term": "revenue",
                    "comparable_group": "january_close_totals",
                    "period": "2026-01",
                    "answer": {"actor_role": "analyst", "scoped_question": "q"},
                }
            ]
        }
    )
    assert snapshot["subclaims"][0]["term"] == "revenue"


def test_load_decision_record_missing():
    assert load_decision_record("decision-missing") is None


def test_replay_missing_decision(compile_contract):
    try:
        replay_decision("decision-missing", contract=compile_contract)
    except ReplayError as exc:
        assert "missing decision record" in str(exc)
    else:
        raise AssertionError("expected ReplayError")


def test_verify_decision_certification_invalid_entry(tmp_path):
    out = tmp_path / "_decision_certification_results.yaml"
    out.write_text(yaml.safe_dump({"certification_results": ["bad"]}), encoding="utf-8")
    failures = verify_decision_certification_results(tmp_path)
    assert "invalid certification entry" in failures


def test_verify_decision_certification_failed_case(tmp_path):
    out = tmp_path / "_decision_certification_results.yaml"
    out.write_text(
        yaml.safe_dump(
            {
                "certification_results": [
                    {"case_id": "x", "passed": False, "reason": "boom"},
                ]
            }
        ),
        encoding="utf-8",
    )
    failures = verify_decision_certification_results(tmp_path)
    assert failures == ["x: boom"]


def test_verify_decision_certification_invalid_root(tmp_path):
    out = tmp_path / "_decision_certification_results.yaml"
    out.write_text("[]\n", encoding="utf-8")
    failures = verify_decision_certification_results(tmp_path)
    assert failures == ["decision certification results must be a mapping"]


def test_validate_decision_certifications_schema_error():
    try:
        validate_decision_certifications({"certifications": []})
    except Exception as exc:
        assert "certifications" in str(exc)
    else:
        raise AssertionError("expected schema error")


def test_decision_kernel_types():
    kernel = DecisionKernel(
        calibration_match_rules=(CalibrationMatchRule(field="status"),),
        advisory_target_rules=(AdvisoryTargetRule(pattern="revenue*", target="term:novashop:revenue"),),
        partial_match_fields=frozenset({"amount"}),
    )
    assert kernel.partial_match_fields == frozenset({"amount"})


def test_load_decision_record_by_direct_id(compile_contract, monkeypatch):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    record = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )

    def _fake_load(artifact_id: str):
        if artifact_id == record.decision_id:
            return {
                "artifact_type": "decision_record",
                "payload": record.to_dict(),
            }
        return None

    monkeypatch.setattr(ledger, "load_by_id", _fake_load)
    loaded = load_decision_record(record.decision_id)
    assert loaded is not None
    assert loaded.decision_id == record.decision_id


def test_load_outcome_record_by_direct_id(compile_contract, monkeypatch):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    decision = record_decision(
        pack.pack_id,
        actor="controller",
        decision_payload={"action": "approve"},
        expected_outcome={"status": "recognized"},
        outcome_due_date="2026-07-01",
        contract=compile_contract,
        claim_set_snapshot=_claim_set().to_dict(),
    )
    from recosearch.semantic_layers.decisions.outcomes import record_outcome

    outcome = record_outcome(
        decision.decision_id,
        actual_outcome={"status": "recognized"},
        contract_hash=compile_contract["contract_hash"],
    )

    def _fake_load(artifact_id: str):
        if artifact_id == outcome.outcome_id:
            return {
                "artifact_type": "outcome_record",
                "payload": outcome.to_dict(),
            }
        return None

    monkeypatch.setattr(ledger, "load_by_id", _fake_load)
    loaded = load_outcome_record(outcome.outcome_id)
    assert loaded is not None
    assert loaded.outcome_id == outcome.outcome_id


def test_load_pack_artifact_by_pack_id(compile_contract):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    from recosearch.semantic_layers.decisions.record import _load_pack_artifact

    loaded = _load_pack_artifact(pack.pack_id)
    assert loaded is not None
    assert loaded["artifact_type"] == "evidence_pack"


def test_load_pack_artifact_via_load_by_id(compile_contract, monkeypatch):
    pack, _ = compose_evidence_pack(_claim_set(), contract=compile_contract)
    from recosearch.semantic_layers.decisions.record import _load_pack_artifact

    payload = {
        "artifact_type": "evidence_pack",
        "payload": {"pack_id": pack.pack_id, "decision": "answer"},
    }

    def _fake_load(artifact_id: str):
        if artifact_id == pack.pack_id:
            return payload
        return None

    monkeypatch.setattr(ledger, "load_by_id", _fake_load)
    loaded = _load_pack_artifact(pack.pack_id)
    assert loaded is payload


def test_generate_calibration_missing_decision(compile_contract):
    with pytest.raises(CalibrationError, match="missing decision record"):
        generate_calibration_signal("decision-missing", contract=compile_contract)


def test_load_decisions_config_from_contract_empty():
    kernel = load_decisions_config_from_contract({})
    assert kernel.calibration_match_rules == ()


def test_load_decision_certifications_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_decision_certifications(tmp_path)


def test_load_decision_certifications_invalid_root(tmp_path):
    path = tmp_path / CERTIFICATION_FILENAME
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_decision_certifications(tmp_path)


def test_run_decision_certifications_pack_decision_mismatch(compile_contract, tmp_path):
    cert = tmp_path / CERTIFICATION_FILENAME
    cert.write_text(
        yaml.safe_dump(
            {
                "certifications": [
                    {
                        "case_id": "bad_pack",
                        "expected_replay_drift": False,
                        "expected_pack_decision": "refuse",
                        "subclaims": [{"term": "revenue", "tenant": "novashop"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "_decisions.yaml").write_text("calibration_match_rules: []\n", encoding="utf-8")
    results = run_decision_certifications(compile_contract, decisions_dir=tmp_path)
    assert results["bad_pack"]["passed"] is False


def test_validate_decisions_registry_invalid_config(tmp_path):
    (tmp_path / "_decisions.yaml").write_text(
        "calibration_match_rules:\n  - field: status\n    match_mode: fuzzy\n",
        encoding="utf-8",
    )
    (tmp_path / CERTIFICATION_FILENAME).write_text("certifications: []\n", encoding="utf-8")
    failures = validate_decisions_registry(tmp_path)
    assert failures


def test_validate_decisions_registry_invalid_cert(tmp_path):
    (tmp_path / "_decisions.yaml").write_text("calibration_match_rules: []\n", encoding="utf-8")
    (tmp_path / CERTIFICATION_FILENAME).write_text("certifications: []\n", encoding="utf-8")
    failures = validate_decisions_registry(tmp_path)
    assert failures


def test_validate_decisions_registry_missing_cert(tmp_path):
    (tmp_path / "_decisions.yaml").write_text("calibration_match_rules: []\n", encoding="utf-8")
    failures = validate_decisions_registry(tmp_path)
    assert any("missing" in f for f in failures)


def test_verify_decision_certification_none_root(tmp_path):
    out = tmp_path / "_decision_certification_results.yaml"
    out.write_text("null\n", encoding="utf-8")
    failures = verify_decision_certification_results(tmp_path)
    assert failures == ["decision certification results must be a mapping"]
