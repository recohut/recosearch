from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics.certify import run_certifications, verify_certification_results
from recosearch.semantic_layers.metrics.cli import (
    _load_contract,
    cmd_context_certify,
    cmd_evidence_certify,
    cmd_evidence_verify,
    cmd_ontology_certify,
    cmd_ontology_export,
    cmd_ontology_validate,
    cmd_ontology_verify,
    main,
)
from recosearch.semantic_layers.metrics import MetricKernel, MetricQuery, MetricResolver

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"
SEMANTIC_DIR = ROOT / "semantic"
CONTEXT_DIR = ROOT / "semantic" / "context"
ONTOLOGY_DIR = ROOT / "semantic" / "ontology"
EVIDENCE_DIR = ROOT / "semantic" / "evidence"
SHOP_DB = ROOT / "examples" / "novashop" / "shop.duckdb"


@pytest.fixture(scope="module")
def ensure_shop_db():
    if not SHOP_DB.exists():
        import runpy as rp

        rp.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))


@pytest.fixture(scope="module")
def contract(ensure_shop_db):
    return compile_contract()


def _args(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


def test_resolve_surfaces_deprecated_metric_caveat(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (metrics_dir / "deprecated.yaml").write_text(
        """
metric_collections:
  - id: global
    priority: 10
    scope: {}
entities:
  - id: entity:x:order
    source_id: novashop
    table: orders
    primary_key: order_id
    time_field: order_date
measures:
  - id: measure:x:amount
    entity_id: entity:x:order
    field: total_amount
    aggregation: sum
metrics:
  - id: metric:x:legacy
    display_name: legacy revenue
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
    deprecated: true
    superseded_by: metric:x:successor
  - id: metric:x:successor
    display_name: successor revenue
    collection_id: global
    measure_id: measure:x:amount
    grain: order
    filter_rules: []
    allowed_dimension_ids: []
""",
        encoding="utf-8",
    )
    resolver = MetricResolver(MetricKernel.from_dir(metrics_dir))
    result = resolver.resolve(MetricQuery(term="legacy revenue"))
    assert result.metric_id == "metric:x:legacy"
    assert "deprecated_metric" in result.caveat_codes


def test_resolve_surfaces_failed_certification_when_certified_false(tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    kernel = MetricKernel.from_dir(metrics_dir)
    cert = kernel.certifications["metric:novashop:order_revenue"]
    results = {
        "metric:novashop:order_revenue": {
            "certified": False,
            "golden_passed": True,
            "golden_questions": [{"passed": True}],
        }
    }
    kernel = kernel.with_certification_results(results)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    assert resolved.status == "uncertified"
    assert "failed_certification" in resolved.caveat_codes


def test_run_certifications_honors_reference_date(contract, tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    kernel = MetricKernel.from_dir(metrics_dir)
    results = run_certifications(kernel, contract, reference_date=date(2026, 1, 31))
    assert results["metric:novashop:order_revenue"]["certified"] is True


def test_verify_detects_stale_certification_block_hash(tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    cert_path = metrics_dir / "_certifications.yaml"
    text = cert_path.read_text(encoding="utf-8").replace(
        "definition_hash: 0e66426cb4be77f6", "definition_hash: deadbeefdeadbeef"
    )
    cert_path.write_text(text, encoding="utf-8")
    kernel = MetricKernel.from_dir(metrics_dir)
    failures = verify_certification_results(kernel)
    assert any("stale certification (hash mismatch)" in failure for failure in failures)


def test_load_contract_builds_shop_db_when_missing(tmp_path, monkeypatch):
    import importlib.util
    import recosearch.semantic_layers.metrics.cli as cli_mod

    semantic_dir = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic_dir)
    fake_root = tmp_path / "project"
    fake_root.mkdir()
    build_dir = fake_root / "examples" / "novashop"
    build_dir.mkdir(parents=True)
    build_script = ROOT / "examples" / "novashop" / "build_db.py"
    (build_dir / "build_db.py").write_text(build_script.read_text(encoding="utf-8"), encoding="utf-8")

    def fake_run_path(path: str) -> None:
        spec = importlib.util.spec_from_file_location("build_db", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()

    monkeypatch.setattr(cli_mod, "ROOT", fake_root)
    monkeypatch.setattr(cli_mod, "SEMANTIC_DIR", semantic_dir)
    monkeypatch.setattr("runpy.run_path", fake_run_path)
    contract = _load_contract(semantic_dir)
    assert contract["contract_hash"]
    assert (fake_root / "examples" / "novashop" / "shop.duckdb").exists()


def test_cmd_ontology_validate_unknown_l2_terms(capsys):
    from recosearch.semantic_layers.ontology.types import TermMapping

    fake_mapping = TermMapping(
        term_id="term:unknown:missing",
        revenue_type="Revenue",
        claim_class="RevenueClaim",
    )
    fake_ontology = SimpleNamespace(
        ontology_hash="onto-test",
        mappings={"term:unknown:missing": fake_mapping},
        reasoner_mode="none",
    )
    fake_context = SimpleNamespace(terms={"term:novashop:revenue": object()})

    with patch(
        "recosearch.semantic_layers.metrics.cli._load_ontology_stack",
        return_value=(fake_ontology, fake_context, None, {}),
    ):
        code = cmd_ontology_validate(
            _args(ontology_dir=str(ONTOLOGY_DIR), semantic_dir=str(SEMANTIC_DIR))
        )
    captured = capsys.readouterr()
    assert code == 1
    assert "unknown L2 terms" in captured.err


def test_cmd_context_certify_failure(tmp_path, ensure_shop_db, capsys):
    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    cert_path = context_dir / "_certification.yaml"
    text = cert_path.read_text(encoding="utf-8").replace(
        "expected_decision: answer", "expected_decision: refuse"
    )
    cert_path.write_text(text, encoding="utf-8")
    code = cmd_context_certify(
        _args(context_dir=str(context_dir), semantic_dir=str(SEMANTIC_DIR))
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err


def test_cmd_ontology_certify_failure(tmp_path, ensure_shop_db, capsys):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic)
    cert_path = semantic / "ontology" / "_certification.yaml"
    text = cert_path.read_text(encoding="utf-8").replace(
        "expected_decision: valid", "expected_decision: refuse"
    )
    cert_path.write_text(text, encoding="utf-8")
    code = cmd_ontology_certify(
        _args(ontology_dir=str(semantic / "ontology"), semantic_dir=str(semantic))
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err


def test_cmd_ontology_verify_failure(tmp_path, ensure_shop_db, capsys):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic)
    out = semantic / "ontology" / "_certification_results.yaml"
    out.write_text(
        """
certification_results:
  - ontology_hash: deadbeef
    certified: true
    golden_passed: true
    run_at: "2026-01-01T00:00:00Z"
    tool_version: "0.1.0"
""",
        encoding="utf-8",
    )
    code = cmd_ontology_verify(
        _args(ontology_dir=str(semantic / "ontology"), semantic_dir=str(semantic))
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err


def test_cmd_ontology_export_no_metric_ref(tmp_path, ensure_shop_db, capsys):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic)
    out = tmp_path / "bundle.json"
    code = cmd_ontology_export(
        _args(
            ontology_dir=str(semantic / "ontology"),
            semantic_dir=str(semantic),
            term_id="term:novashop:customer",
            qualifier=[],
            out=str(out),
        )
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "has no metric ref" in captured.err


def test_cli_main_entrypoint(tmp_path, ensure_shop_db):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "recosearch.semantic_layers.metrics.cli",
            "verify",
            "--metrics-dir",
            str(metrics_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0


def test_cmd_evidence_certify_and_verify_success(tmp_path, ensure_shop_db, capsys):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic)
    evidence_dir = semantic / "evidence"
    code = cmd_evidence_certify(
        _args(evidence_dir=str(evidence_dir), semantic_dir=str(semantic))
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "evidence-certified" in captured.out
    assert (evidence_dir / "_certification_results.yaml").exists()
    code = cmd_evidence_verify(
        _args(evidence_dir=str(evidence_dir), semantic_dir=str(semantic))
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "verified evidence certifications" in captured.out


def test_cmd_evidence_certify_registry_failure(tmp_path, capsys):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_gates.yaml").write_text("not: valid\n", encoding="utf-8")
    code = cmd_evidence_certify(
        _args(evidence_dir=str(evidence_dir), semantic_dir=str(SEMANTIC_DIR))
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err


def test_cmd_evidence_verify_failure(tmp_path, ensure_shop_db, capsys):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_DIR, evidence_dir)
    cert_results = evidence_dir / "_certification_results.yaml"
    if cert_results.exists():
        cert_results.unlink()
    code = cmd_evidence_verify(
        _args(evidence_dir=str(evidence_dir), semantic_dir=str(SEMANTIC_DIR))
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err


def test_cmd_evidence_certify_verify_failure_after_persist(tmp_path, ensure_shop_db, capsys):
    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic)
    evidence_dir = semantic / "evidence"
    with patch(
        "recosearch.semantic_layers.metrics.cli.verify_evidence_certification_results",
        return_value=["stale evidence certification"],
    ):
        code = cmd_evidence_certify(
            _args(evidence_dir=str(evidence_dir), semantic_dir=str(semantic))
        )
    captured = capsys.readouterr()
    assert code == 1
    assert "stale evidence certification" in captured.err


def test_main_module_raises_system_exit():
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("recosearch.semantic_layers.metrics.cli", run_name="__main__")
    assert exc.value.code != 0
