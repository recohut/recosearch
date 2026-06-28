import shutil
from io import StringIO
from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics.cli import cmd_certify, cmd_verify, main

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"
SEMANTIC_DIR = ROOT / "semantic"


@pytest.fixture(scope="module")
def ensure_shop_db():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))


def _args(command: str, metrics_dir: Path, semantic_dir: Path | None = None):
    import argparse

    ns = argparse.Namespace()
    ns.command = command
    ns.metrics_dir = str(metrics_dir)
    ns.semantic_dir = str(semantic_dir or SEMANTIC_DIR)
    return ns


def test_cmd_certify_success(tmp_path, ensure_shop_db, capsys):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    code = cmd_certify(_args("certify", metrics_dir))
    captured = capsys.readouterr()
    assert code == 0
    assert "certified" in captured.out
    assert (metrics_dir / "_certification_results.yaml").exists()
    assert captured.err == ""


def test_cmd_verify_success(tmp_path, ensure_shop_db, capsys):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    assert cmd_certify(_args("certify", metrics_dir)) == 0
    capsys.readouterr()
    code = cmd_verify(_args("verify", metrics_dir))
    captured = capsys.readouterr()
    assert code == 0
    assert "verified" in captured.out
    assert captured.err == ""


def test_cmd_verify_fails_stale_hash(tmp_path, ensure_shop_db, capsys):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    out = metrics_dir / "_certification_results.yaml"
    out.write_text(
        """
certification_results:
  - metric_id: metric:novashop:order_revenue
    definition_hash: deadbeefdeadbeef
    certified: true
    golden_passed: true
    run_at: "2026-01-01T00:00:00Z"
    tool_version: "0.1.0"
""",
        encoding="utf-8",
    )
    code = cmd_verify(_args("verify", metrics_dir))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "stale certification" in captured.err


def test_cmd_certify_fails_when_golden_questions_fail(tmp_path, ensure_shop_db, capsys):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    cert_path = metrics_dir / "_certifications.yaml"
    text = cert_path.read_text(encoding="utf-8").replace("metric_value: 109.97", "metric_value: 0")
    cert_path.write_text(text, encoding="utf-8")

    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, semantic)
    shutil.rmtree(semantic / "metrics")
    shutil.copytree(metrics_dir, semantic / "metrics")

    code = cmd_certify(_args("certify", metrics_dir, semantic))
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "certification failed" in captured.err


def test_main_dispatches_verify_subcommand(tmp_path, ensure_shop_db):
    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    assert main(["certify", "--metrics-dir", str(metrics_dir), "--semantic-dir", str(SEMANTIC_DIR)]) == 0
    assert main(["verify", "--metrics-dir", str(metrics_dir)]) == 0


def test_main_requires_subcommand(capsys):
    with pytest.raises(SystemExit):
        main([])
    captured = capsys.readouterr()
    assert "required" in captured.err.lower() or captured.err
