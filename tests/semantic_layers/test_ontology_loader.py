from __future__ import annotations

from pathlib import Path

import pytest

from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader, load_ontology_kernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


@pytest.fixture(scope="module")
def metric_kernel():
    return MetricKernel.from_dir(SEMANTIC / "metrics")


@pytest.fixture(scope="module")
def context_kernel(metric_kernel):
    return load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)


@pytest.fixture(scope="module")
def ontology_kernel(context_kernel):
    return load_ontology_kernel(SEMANTIC, context_kernel=context_kernel)


def test_loader_parses_ttl_and_mappings(ontology_kernel):
    assert ontology_kernel.ontology_hash.startswith("onto-")
    assert ontology_kernel.reasoner_mode == "none"
    assert "term:novashop:revenue" in ontology_kernel.mappings
    assert ontology_kernel.mappings["term:novashop:revenue"].revenue_type == "Revenue"


def test_loader_rejects_unknown_term(metric_kernel, context_kernel, tmp_path):
    import shutil

    onto_dir = tmp_path / "ontology"
    shutil.copytree(SEMANTIC / "ontology", onto_dir)
    mappings = (onto_dir / "_claim_mappings.yaml").read_text(encoding="utf-8")
    (onto_dir / "_claim_mappings.yaml").write_text(
        mappings
        + "\n  - term_id: term:unknown:foo\n    revenue_type: Revenue\n    claim_class: RevenueClaim\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown L2 term"):
        OntologyKernelLoader.from_dir(onto_dir, context_kernel=context_kernel)


def test_from_contract_roundtrip(ontology_kernel):
    payload = OntologyKernelLoader.to_dict(ontology_kernel)
    restored = OntologyKernelLoader.from_contract({"ontology_kernel": payload})
    assert restored.ontology_hash == ontology_kernel.ontology_hash
    assert restored.mappings.keys() == ontology_kernel.mappings.keys()
