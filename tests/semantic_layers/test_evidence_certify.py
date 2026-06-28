from __future__ import annotations

import shutil
from pathlib import Path

from recosearch.semantic_layers.evidence.certify import (
    persist_evidence_certification_results,
    run_evidence_certifications,
    validate_evidence_registry,
    verify_evidence_certification_results,
)

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_run_evidence_certifications(compile_contract, tmp_path):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(SEMANTIC / "evidence", evidence_dir)
    results = run_evidence_certifications(compile_contract, evidence_dir=evidence_dir)
    assert results["board_pack_revenue_only"]["passed"] is True
    assert results["board_pack_revenue_only"]["actual_decision"] == "answer"
    assert results["board_pack_with_deferred"]["passed"] is True
    assert results["board_pack_with_deferred"]["actual_decision"] == "review_required"
    assert results["board_pack_unknown_comparable_group"]["passed"] is True
    assert results["board_pack_period_mismatch"]["passed"] is True


def test_persist_and_verify_evidence_certification(tmp_path, compile_contract):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(SEMANTIC / "evidence", evidence_dir)
    results = run_evidence_certifications(compile_contract, evidence_dir=evidence_dir)
    out_path = persist_evidence_certification_results(evidence_dir, results)
    assert out_path.exists()
    assert verify_evidence_certification_results(evidence_dir, compile_contract) == []


def test_validate_evidence_registry(tmp_path):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(SEMANTIC / "evidence", evidence_dir)
    assert validate_evidence_registry(evidence_dir) == []


def test_validate_evidence_registry_missing_gates(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    failures = validate_evidence_registry(evidence_dir)
    assert "missing _gates.yaml" in failures
    assert "missing _certification.yaml" in failures


def test_verify_evidence_certification_results_missing_file(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    assert verify_evidence_certification_results(evidence_dir) == ["missing certification results"]


def test_verify_evidence_certification_results_failed_case(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_certification_results.yaml").write_text(
        "certification_results:\n  - case_id: bad_case\n    passed: false\n",
        encoding="utf-8",
    )
    failures = verify_evidence_certification_results(evidence_dir)
    assert any("bad_case" in f for f in failures)


def test_verify_evidence_certification_results_stale_contract_hash(tmp_path, compile_contract):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(SEMANTIC / "evidence", evidence_dir)
    results = run_evidence_certifications(compile_contract, evidence_dir=evidence_dir)
    persist_evidence_certification_results(evidence_dir, results)
    stale = dict(compile_contract)
    stale["contract_hash"] = "deadbeefdeadbeef"
    failures = verify_evidence_certification_results(evidence_dir, stale)
    assert any("stale evidence certification (hash mismatch)" in f for f in failures)
