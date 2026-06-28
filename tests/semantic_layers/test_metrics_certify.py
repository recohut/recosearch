from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics.certify import (
    apply_certification_results,
    persist_certification_results,
    run_certifications,
    verify_certification_results,
)
from recosearch.semantic_layers.metrics import MetricKernel, MetricQuery, MetricResolver
from recosearch.semantic_layers.pipeline import execute_metric_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_run_certifications_passes_for_order_revenue(contract):
    kernel = MetricKernel.from_dir(METRICS_DIR)
    results = run_certifications(kernel, contract)
    cert = results["metric:novashop:order_revenue"]
    assert cert["hash_match"] is True
    assert cert["certified"] is True
    assert cert["golden_questions"][0]["passed"] is True


def test_stale_certification_caveat_when_hash_mismatch(tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    order_path = metrics_dir / "order_revenue.yaml"
    text = order_path.read_text(encoding="utf-8").replace("grain: order", "grain: transaction")
    order_path.write_text(text, encoding="utf-8")

    kernel = MetricKernel.from_dir(metrics_dir)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    assert resolved.status == "uncertified"
    assert "stale_certification" in resolved.caveat_codes


def test_failed_certification_caveat_when_golden_questions_fail(tmp_path):
    import shutil

    import recosearch.semantic_layers.contract as mod
    from recosearch.semantic_layers.contract import compile_contract as cc

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    cert_path = metrics_dir / "_certifications.yaml"
    text = cert_path.read_text(encoding="utf-8").replace("metric_value: 109.97", "metric_value: 0")
    cert_path.write_text(text, encoding="utf-8")

    semantic = tmp_path / "semantic"
    shutil.copytree(mod.SEMANTIC_DIR, semantic, dirs_exist_ok=True)
    shutil.rmtree(semantic / "metrics")
    shutil.copytree(metrics_dir, semantic / "metrics")

    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))

    mutated_contract = cc(semantic)
    kernel = MetricKernel.from_dir(metrics_dir)
    results = run_certifications(kernel, mutated_contract)
    assert results["metric:novashop:order_revenue"]["certified"] is False
    kernel = apply_certification_results(kernel, results)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))
    assert resolved.status == "uncertified"
    assert "failed_certification" in resolved.caveat_codes
    assert "stale_certification" not in resolved.caveat_codes


def test_stale_certification_surfaces_in_pipeline_answer(tmp_path):
    import shutil

    import recosearch.semantic_layers.contract as mod
    from recosearch.semantic_layers.contract import compile_contract as cc

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    order_path = metrics_dir / "order_revenue.yaml"
    text = order_path.read_text(encoding="utf-8").replace("grain: order", "grain: transaction")
    order_path.write_text(text, encoding="utf-8")

    semantic = tmp_path / "semantic"
    shutil.copytree(mod.SEMANTIC_DIR, semantic, dirs_exist_ok=True)
    shutil.rmtree(semantic / "metrics")
    shutil.copytree(metrics_dir, semantic / "metrics")

    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))

    mutated_contract = cc(semantic)
    answer = execute_metric_query(
        MetricQuery(term="order revenue", tenant="novashop"),
        contract=mutated_contract,
    )
    assert answer.decision == "answer"
    assert "stale_certification" in answer.caveats


def test_persisted_certification_results_applied_on_load(contract, tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    kernel = MetricKernel.from_dir(metrics_dir)
    results = run_certifications(kernel, contract)
    persist_certification_results(metrics_dir, results)

    reloaded = MetricKernel.from_dir(metrics_dir)
    cert = reloaded.certifications["metric:novashop:order_revenue"]
    assert cert.certified is True
    assert cert.golden_passed is True
    assert verify_certification_results(reloaded) == []


def test_verify_detects_stale_persisted_results(tmp_path):
    import shutil

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
    kernel = MetricKernel.from_dir(metrics_dir)
    failures = verify_certification_results(kernel)
    assert any("stale certification" in failure for failure in failures)
