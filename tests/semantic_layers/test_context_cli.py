import shutil
from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics.cli import cmd_context_certify, cmd_context_export, cmd_context_verify, main

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
CONTEXT_DIR = ROOT / "semantic" / "context"
SEMANTIC_DIR = ROOT / "semantic"


@pytest.fixture(scope="module")
def ensure_shop_db():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))


def _args(command: str, context_dir: Path, semantic_dir: Path | None = None, out: str = ""):
    import argparse

    ns = argparse.Namespace()
    ns.command = command
    ns.context_dir = str(context_dir)
    ns.semantic_dir = str(semantic_dir or SEMANTIC_DIR)
    ns.out = out
    return ns


def test_cmd_context_certify_success(tmp_path, ensure_shop_db, capsys):
    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    code = cmd_context_certify(_args("context-certify", context_dir))
    captured = capsys.readouterr()
    assert code == 0
    assert "context-certified" in captured.out
    assert (context_dir / "_certification_results.yaml").exists()


def test_cmd_context_verify_success(tmp_path, ensure_shop_db, capsys):
    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    assert cmd_context_certify(_args("context-certify", context_dir)) == 0
    capsys.readouterr()
    code = cmd_context_verify(_args("context-verify", context_dir))
    captured = capsys.readouterr()
    assert code == 0
    assert "verified" in captured.out


def test_cmd_context_verify_fails_stale(tmp_path, ensure_shop_db, capsys):
    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    out = context_dir / "_certification_results.yaml"
    out.write_text(
        """
certification_results:
  - term_id: term:novashop:revenue
    definition_hash: deadbeefdeadbeef
    policy_hash: 39fc4112815ff4a5
    certified: true
    golden_passed: true
    evidence_tier: 3
    run_at: "2026-01-01T00:00:00Z"
    tool_version: "0.1.0"
""",
        encoding="utf-8",
    )
    code = cmd_context_verify(_args("context-verify", context_dir))
    captured = capsys.readouterr()
    assert code == 1
    assert "stale certification" in captured.err


def test_cmd_context_export(tmp_path, ensure_shop_db, capsys):
    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    out = tmp_path / "export.json"
    code = cmd_context_export(_args("context-export", context_dir, out=str(out)))
    captured = capsys.readouterr()
    assert code == 0
    assert out.exists()
    assert "exported" in captured.out


def test_main_dispatches_context_subcommands(tmp_path, ensure_shop_db):
    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    assert main(["context-certify", "--context-dir", str(context_dir)]) == 0
    assert main(["context-verify", "--context-dir", str(context_dir)]) == 0
