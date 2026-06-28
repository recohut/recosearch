from __future__ import annotations

import copy
from pathlib import Path
from types import MappingProxyType

import pytest

from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.certify import (
    _resolve_cert_hash,
    apply_ontology_certification_results,
    run_ontology_certifications,
    verify_ontology_certification_results,
)
from recosearch.semantic_layers.ontology.claim import build_claim_graph
from recosearch.semantic_layers.ontology.export import write_ontology_export
from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader, load_ontology_kernel
from recosearch.semantic_layers.ontology.types import (
    ConstraintDecision,
    ConstraintViolation,
    GoldenConstraintCase,
    OntologyCertification,
    OntologyKernel,
    TermMapping,
)
from recosearch.semantic_layers.ontology.validate import clear_validation_cache, validate_claim

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


@pytest.fixture(scope="module")
def stacks():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    ontology_kernel = load_ontology_kernel(SEMANTIC, context_kernel=context_kernel)
    return metric_kernel, context_kernel, ontology_kernel


def test_build_claim_graph_unknown_mapping(stacks):
    _, context_kernel, ontology_kernel = stacks
    binding = context_kernel.terms["term:novashop:revenue"]
    bad_kernel = OntologyKernel(
        namespace=ontology_kernel.namespace,
        ontology_ttl=ontology_kernel.ontology_ttl,
        shapes_ttl=ontology_kernel.shapes_ttl,
        mappings=MappingProxyType({}),
        ontology_hash=ontology_kernel.ontology_hash,
    )
    with pytest.raises(ValueError, match="no ontology mapping"):
        build_claim_graph(binding, "metric:novashop:order_revenue", bad_kernel)


def test_loader_missing_directory():
    with pytest.raises(FileNotFoundError):
        OntologyKernelLoader.from_dir("/tmp/does-not-exist-ontology-dir")


def test_load_ontology_kernel_missing_semantic_ontology(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ontology_kernel(tmp_path)


def test_from_contract_with_certifications(stacks):
    _, context_kernel, ontology_kernel = stacks
    payload = OntologyKernelLoader.to_dict(ontology_kernel)
    payload["certifications"] = {
        ontology_kernel.ontology_hash: {
            "ontology_hash": ontology_kernel.ontology_hash,
            "reasoner_mode": "none",
            "golden_cases": [],
            "certified": True,
            "golden_passed": True,
        }
    }
    payload["persisted_certification_results"] = {
        ontology_kernel.ontology_hash: {
            "ontology_hash": ontology_kernel.ontology_hash,
            "certified": True,
        }
    }
    restored = OntologyKernelLoader.from_contract(
        {"ontology_kernel": payload},
        context_kernel=context_kernel,
    )
    assert restored.certifications


def test_constraint_decision_to_dict_full():
    decision = ConstraintDecision(
        decision="refuse",
        reason="violation:gross_reported_as_net",
        reason_code="CONSTRAINT_VIOLATION",
        violations=(
            ConstraintViolation(
                shape="shape:gross",
                focus="focus",
                severity="Violation",
                message="violation:gross_reported_as_net",
                source_iri="component",
                why_not=(("claim_hash", "claim-abc"),),
            ),
        ),
        ontology_hash="onto-abc",
        reasoner_mode="none",
        claim_hash="claim-abc",
        validation_report="report",
        drift_status="at_risk",
        drift_reasons=("ontology_changed",),
    )
    payload = decision.to_dict()
    assert payload["violations"][0]["why_not"]["claim_hash"] == "claim-abc"
    assert payload["drift_reasons"] == ["ontology_changed"]
    assert decision.to_tuple()


def test_verify_ontology_failures(stacks):
    _, _, ontology_kernel = stacks
    drifted = OntologyKernel(
        namespace=ontology_kernel.namespace,
        ontology_ttl=ontology_kernel.ontology_ttl,
        shapes_ttl=ontology_kernel.shapes_ttl,
        mappings=ontology_kernel.mappings,
        ontology_hash="onto-deadbeef",
        reasoner_mode=ontology_kernel.reasoner_mode,
        certifications=ontology_kernel.certifications,
        persisted_certification_results=MappingProxyType(
            {
                "onto-old": {
                    "ontology_hash": "onto-old",
                    "certified": False,
                }
            }
        ),
    )
    failures = verify_ontology_certification_results(drifted)
    assert failures


def test_apply_ontology_certification_results(stacks):
    _, _, ontology_kernel = stacks
    if not ontology_kernel.certifications:
        pytest.skip("no certifications loaded")
    cert_hash = next(iter(ontology_kernel.certifications))
    results = {
        cert_hash: {
            "ontology_hash": ontology_kernel.ontology_hash,
            "certified": True,
            "golden_passed": True,
        }
    }
    updated = apply_ontology_certification_results(ontology_kernel, results)
    assert updated.certifications[cert_hash].certified is True


def test_resolve_cert_hash_placeholder(stacks):
    _, _, ontology_kernel = stacks
    assert _resolve_cert_hash(ontology_kernel) == ontology_kernel.ontology_hash


def test_validate_drift_detection(stacks):
    _, context_kernel, ontology_kernel = stacks
    clear_validation_cache()
    binding = context_kernel.terms["term:novashop:revenue"]
    drifted = OntologyKernel(
        namespace=ontology_kernel.namespace,
        ontology_ttl=ontology_kernel.ontology_ttl,
        shapes_ttl=ontology_kernel.shapes_ttl,
        mappings=ontology_kernel.mappings,
        ontology_hash=ontology_kernel.ontology_hash,
        reasoner_mode=ontology_kernel.reasoner_mode,
        persisted_certification_results=MappingProxyType(
            {
                ontology_kernel.ontology_hash: {
                    "ontology_hash": "onto-stale",
                    "reasoner_mode": "owlrl",
                    "certified": True,
                }
            }
        ),
    )
    decision = validate_claim(
        binding,
        "metric:novashop:order_revenue",
        drifted,
        claim_qualifiers=(("period", "2026-01"),),
        use_cache=False,
    )
    assert decision.drift_status == "at_risk"
    assert "ontology_changed" in decision.drift_reasons


def test_export_jsonld_suffix(stacks, tmp_path):
    _, context_kernel, ontology_kernel = stacks
    from recosearch.semantic_layers.ontology.export import export_validation_report

    binding = context_kernel.terms["term:novashop:revenue"]
    payload = export_validation_report(
        binding,
        "metric:novashop:order_revenue",
        ontology_kernel,
        claim_qualifiers=(("period", "2026-01"),),
    )
    out = write_ontology_export(tmp_path / "bundle.jsonld", payload)
    assert "@id" in out.read_text(encoding="utf-8")


def test_run_ontology_certifications_no_cert_block(stacks):
    _, context_kernel, ontology_kernel = stacks
    bare = OntologyKernel(
        namespace=ontology_kernel.namespace,
        ontology_ttl=ontology_kernel.ontology_ttl,
        shapes_ttl=ontology_kernel.shapes_ttl,
        mappings=ontology_kernel.mappings,
        ontology_hash=ontology_kernel.ontology_hash,
        reasoner_mode=ontology_kernel.reasoner_mode,
    )
    results = run_ontology_certifications(bare, context_kernel, {"contract_hash": "test"})
    assert results[bare.ontology_hash]["golden_cases"] == []
