from __future__ import annotations

import shutil
from pathlib import Path

from recosearch.semantic_layers.metrics.cli import main

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_evidence_certify_and_verify_cli(tmp_path):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC, semantic)
    evidence_dir = semantic / "evidence"
    assert (
        main(
            [
                "evidence-certify",
                "--semantic-dir",
                str(semantic),
                "--evidence-dir",
                str(evidence_dir),
            ]
        )
        == 0
    )
    assert (evidence_dir / "_certification_results.yaml").exists()
    assert (
        main(
            [
                "evidence-verify",
                "--evidence-dir",
                str(evidence_dir),
            ]
        )
        == 0
    )


def test_evidence_verify_fails_without_certification(tmp_path):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(SEMANTIC / "evidence", evidence_dir)
    cert_results = evidence_dir / "_certification_results.yaml"
    if cert_results.exists():
        cert_results.unlink()
    assert main(["evidence-verify", "--evidence-dir", str(evidence_dir)]) == 1
