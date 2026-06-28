from __future__ import annotations

from types import MappingProxyType

import pytest

from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader
from recosearch.semantic_layers.ontology.types import (
    OntologyCertification,
    OntologyKernel,
    TermMapping,
)


def test_from_dir_missing_required_artifact(tmp_path):
    onto_dir = tmp_path / "ontology"
    onto_dir.mkdir()
    (onto_dir / "_ontology.ttl").write_text("@prefix ns: <http://example.org/ns#> .\n", encoding="utf-8")
    (onto_dir / "_shapes.ttl").write_text("@prefix sh: <http://www.w3.org/ns/shacl#> .\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="missing ontology artifact"):
        OntologyKernelLoader.from_dir(onto_dir)


def test_from_contract_missing_ontology_kernel():
    with pytest.raises(ValueError, match="contract missing ontology_kernel"):
        OntologyKernelLoader.from_contract({})


def test_from_contract_non_mapping_ontology_kernel():
    with pytest.raises(ValueError, match="ontology_kernel must be a mapping"):
        OntologyKernelLoader.from_contract({"ontology_kernel": "not-a-mapping"})


def test_ontology_kernel_post_init_wraps_plain_dicts():
    mapping = TermMapping(
        term_id="term:novashop:revenue",
        revenue_type="Revenue",
        claim_class="RevenueClaim",
    )
    cert = OntologyCertification(
        ontology_hash="onto-test",
        reasoner_mode="none",
        golden_cases=(),
    )
    persisted = {"onto-test": {"ontology_hash": "onto-test", "certified": True}}

    kernel = OntologyKernel(
        namespace="https://recosearch.semantic_layers.example/ontology/ns#",
        ontology_ttl="@prefix ns: <https://recosearch.semantic_layers.example/ontology/ns#> .\n",
        shapes_ttl="@prefix sh: <http://www.w3.org/ns/shacl#> .\n",
        mappings={"term:novashop:revenue": mapping},
        ontology_hash="onto-test",
        certifications={"onto-test": cert},
        persisted_certification_results=persisted,
    )

    assert isinstance(kernel.mappings, MappingProxyType)
    assert kernel.mappings["term:novashop:revenue"] is mapping
    assert isinstance(kernel.certifications, MappingProxyType)
    assert kernel.certifications["onto-test"] is cert
    assert isinstance(kernel.persisted_certification_results, MappingProxyType)
    assert kernel.persisted_certification_results["onto-test"]["certified"] is True
