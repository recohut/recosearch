from __future__ import annotations

import shutil
from pathlib import Path

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics.cli import main

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_ontology_validate_cli():
    assert main(["ontology-validate"]) == 0


def test_ontology_certify_and_verify(tmp_path):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC, semantic)
    ontology_dir = semantic / "ontology"
    assert main(["ontology-certify", "--semantic-dir", str(semantic), "--ontology-dir", str(ontology_dir)]) == 0
    assert main(["ontology-verify", "--semantic-dir", str(semantic), "--ontology-dir", str(ontology_dir)]) == 0


def test_ontology_export_cli(tmp_path):
    out = tmp_path / "bundle.json"
    assert (
        main(
            [
                "ontology-export",
                "--out",
                str(out),
                "--term-id",
                "term:novashop:revenue",
                "--qualifier",
                "period=2026-01",
            ]
        )
        == 0
    )
    assert out.exists()
    assert "claim_hash" in out.read_text(encoding="utf-8")
