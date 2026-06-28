from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.contract import ROOT
from recosearch.semantic_layers.decisions.certify import (
    CERTIFICATION_RESULTS_FILENAME,
    load_decision_certifications,
    persist_decision_certification_results,
    run_decision_certifications,
    validate_decisions_registry,
    verify_decision_certification_results,
)

DECISIONS_DIR = ROOT / "semantic" / "decisions"


def test_load_decision_certifications():
    cases = load_decision_certifications(DECISIONS_DIR)
    assert len(cases) >= 5


def test_run_decision_certifications(compile_contract):
    ledger.clear()
    results = run_decision_certifications(compile_contract, decisions_dir=DECISIONS_DIR)
    assert all(result.get("passed") for result in results.values()), results


def test_persist_and_verify_decision_certifications(compile_contract, tmp_path):
    ledger.clear()
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    for name in ("_decisions.yaml", "_certification.yaml"):
        (decisions_dir / name).write_text((DECISIONS_DIR / name).read_text(encoding="utf-8"))
    results = run_decision_certifications(compile_contract, decisions_dir=decisions_dir)
    persist_decision_certification_results(decisions_dir, results)
    failures = verify_decision_certification_results(decisions_dir, compile_contract)
    assert failures == []


def test_verify_missing_results(tmp_path):
    failures = verify_decision_certification_results(tmp_path)
    assert failures == ["missing decision certification results"]


def test_verify_stale_contract_hash(compile_contract, tmp_path):
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    out = decisions_dir / CERTIFICATION_RESULTS_FILENAME
    out.write_text(
        yaml.safe_dump(
            {
                "certification_results": [
                    {
                        "case_id": "x",
                        "passed": True,
                        "contract_hash": "stale000000000001",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    failures = verify_decision_certification_results(decisions_dir, compile_contract)
    assert any("stale decision certification" in f for f in failures)


def test_validate_decisions_registry():
    failures = validate_decisions_registry(DECISIONS_DIR)
    assert failures == []


def test_validate_decisions_registry_missing(tmp_path):
    failures = validate_decisions_registry(tmp_path)
    assert "missing _decisions.yaml" in failures
