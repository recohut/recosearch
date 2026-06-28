from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.certify import (
    persist_ontology_certification_results,
    run_ontology_certifications,
    verify_ontology_certification_results,
)
from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader, load_ontology_kernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_run_ontology_certifications(contract):
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    ontology_kernel = load_ontology_kernel(SEMANTIC, context_kernel=context_kernel)
    results = run_ontology_certifications(ontology_kernel, context_kernel, contract)
    assert results
    first = next(iter(results.values()))
    assert first["certified"] is True
    assert first["reasoner_mode"] == "none"


def test_persist_and_verify_ontology_certification(tmp_path, contract):
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(SEMANTIC / "ontology", ontology_dir)
    ontology_kernel = OntologyKernelLoader.from_dir(ontology_dir, context_kernel=context_kernel)

    results = run_ontology_certifications(ontology_kernel, context_kernel, contract)
    persist_ontology_certification_results(ontology_dir, results)
    reloaded = OntologyKernelLoader.from_dir(ontology_dir, context_kernel=context_kernel)
    assert verify_ontology_certification_results(reloaded) == []
