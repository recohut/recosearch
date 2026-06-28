from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.context.certify import (
    apply_context_certification_results,
    persist_context_certification_results,
    run_context_certifications,
    verify_context_certification_results,
)
from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
CONTEXT_DIR = ROOT / "semantic" / "context"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_contract_for_certification_strips_persisted_results(contract):
    from recosearch.semantic_layers.context.certify import _contract_for_certification

    clean = _contract_for_certification(contract)
    context_kernel = clean.get("context_kernel", {})
    assert "persisted_certification_results" not in context_kernel
    for cert in context_kernel.get("certifications", []):
        assert "certified" not in cert
        assert "golden_passed" not in cert


def test_contract_for_certification_dict_branch():
    from recosearch.semantic_layers.context.certify import _contract_for_certification

    clean = _contract_for_certification(
        {
            "context_kernel": {
                "certifications": {
                    "term:demo": {
                        "term_id": "term:demo",
                        "certified": True,
                        "golden_passed": False,
                    }
                },
                "persisted_certification_results": {"term:demo": {"certified": True}},
            }
        }
    )
    cert = clean["context_kernel"]["certifications"]["term:demo"]
    assert "certified" not in cert


def test_verify_context_certification_unknown_term():
    from recosearch.semantic_layers.context.certify import verify_context_certification_results
    from recosearch.semantic_layers.context.types import ContextCertification, ContextKernel, TermBinding

    kernel = ContextKernel(
        terms={
            "term:known": TermBinding(
                term_id="term:known",
                display_name="known",
                definition="def",
                aliases=(),
                collection_id="c",
                primary_refs=(),
            )
        },
        guidance={},
        relationships=(),
        alias_index={},
        certifications={
            "term:missing": ContextCertification(
                term_id="term:missing",
                definition_hash="abc",
                policy_hash="def",
                golden_questions=(),
            )
        },
    )
    failures = verify_context_certification_results(kernel)
    assert any("unknown term" in failure for failure in failures)


def test_run_context_certifications_passes(contract):
    metric_kernel = MetricKernel.from_dir(METRICS_DIR)
    context_kernel = load_context_kernel(ROOT / "semantic", metric_kernel=metric_kernel)
    results = run_context_certifications(context_kernel, metric_kernel, contract)
    revenue = results["term:novashop:revenue"]
    assert revenue["hash_match"] is True
    assert revenue["certified"] is True
    assert revenue["golden_questions"][0]["passed"] is True
    assert revenue["evidence_tier"] >= 2


def test_context_certification_tier3_probe(contract):
    metric_kernel = MetricKernel.from_dir(METRICS_DIR)
    context_kernel = load_context_kernel(ROOT / "semantic", metric_kernel=metric_kernel)
    results = run_context_certifications(context_kernel, metric_kernel, contract, run_probe=True)
    assert results["term:novashop:revenue"]["probe"]["passed"] is True
    assert results["term:novashop:revenue"]["evidence_tier"] == 3


def test_stale_context_cert_hash_mismatch(tmp_path):
    import shutil

    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    glossary = context_dir / "_glossary.yaml"
    glossary.write_text(
        glossary.read_text(encoding="utf-8").replace(
            "Total order revenue for Novashop",
            "Mutated revenue definition",
        ),
        encoding="utf-8",
    )
    metric_kernel = MetricKernel.from_dir(METRICS_DIR)
    context_kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    failures = verify_context_certification_results(context_kernel)
    assert any("hash mismatch" in f for f in failures)


def test_persisted_context_results_applied(tmp_path, contract):
    import shutil
    from recosearch.semantic_layers.contract import compile_contract
    from recosearch.semantic_layers.context.types import ContextQuery
    from recosearch.semantic_layers.pipeline import execute_context_query

    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    semantic = tmp_path / "semantic"
    shutil.copytree(ROOT / "semantic", semantic)
    shutil.rmtree(semantic / "context")
    shutil.copytree(context_dir, semantic / "context")
    metric_kernel = MetricKernel.from_dir(METRICS_DIR)
    context_kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    results = run_context_certifications(context_kernel, metric_kernel, contract)
    persist_context_certification_results(context_dir, results)
    shutil.rmtree(semantic / "context")
    shutil.copytree(context_dir, semantic / "context")
    reloaded = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    cert = reloaded.certifications["term:novashop:revenue"]
    assert cert.certified is True
    assert cert.evidence_tier == 3
    assert verify_context_certification_results(reloaded) == []
    compiled = compile_contract(semantic)
    answer = execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=compiled,
    )
    assert dict(answer.context_resolution or ())["evidence_tier"] == 3


def test_failed_golden_decision_mismatch(contract, tmp_path):
    import shutil

    context_dir = tmp_path / "context"
    shutil.copytree(CONTEXT_DIR, context_dir)
    cert_path = context_dir / "_certification.yaml"
    cert_path.write_text(
        cert_path.read_text(encoding="utf-8").replace(
            "expected_decision: answer",
            "expected_decision: refuse",
            1,
        ),
        encoding="utf-8",
    )
    metric_kernel = MetricKernel.from_dir(METRICS_DIR)
    context_kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    results = run_context_certifications(context_kernel, metric_kernel, contract)
    assert results["term:novashop:revenue"]["certified"] is False
    context_kernel = apply_context_certification_results(context_kernel, results)
    failures = verify_context_certification_results(context_kernel)
    assert any("certification failed" in f for f in failures)
