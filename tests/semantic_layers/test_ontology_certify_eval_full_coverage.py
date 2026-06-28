from __future__ import annotations

from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

import pytest

from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.ontology.certify import (
    apply_ontology_certification_results,
    run_ontology_certifications,
    run_pipeline_golden_case,
    verify_ontology_certification_results,
)
from recosearch.semantic_layers.ontology.eval import pass_k
from recosearch.semantic_layers.ontology.types import (
    ConstraintDecision,
    GoldenConstraintCase,
    OntologyCertification,
    OntologyKernel,
)

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    from recosearch.semantic_layers.contract import compile_contract

    return compile_contract()


def _golden_case(*, expected_decision: str = "valid") -> GoldenConstraintCase:
    return GoldenConstraintCase(
        term_id="term:novashop:revenue",
        tenant="novashop",
        actor_role="analyst",
        claim_qualifiers=(),
        expected_decision=expected_decision,
    )


def _context_kernel() -> SimpleNamespace:
    binding = TermBinding(
        term_id="term:novashop:revenue",
        display_name="revenue",
        definition="revenue",
        aliases=(),
        collection_id="coll:novashop:finance",
        primary_refs=("metric:novashop:order_revenue",),
    )
    return SimpleNamespace(terms={"term:novashop:revenue": binding})


def _ontology_kernel_with_mismatched_cert_key(
    golden_case: GoldenConstraintCase,
) -> OntologyKernel:
    cert = OntologyCertification(
        ontology_hash="resolved-cert-hash",
        reasoner_mode="none",
        golden_cases=(golden_case,),
    )
    return OntologyKernel(
        namespace="http://example.org/novashop/",
        ontology_ttl="@prefix ex: <http://example.org/novashop/> .",
        shapes_ttl="@prefix sh: <http://www.w3.org/ns/shacl#> .",
        mappings=MappingProxyType({}),
        ontology_hash="kernel-hash",
        certifications=MappingProxyType({"storage-key": cert}),
    )


def test_run_ontology_certifications_falls_back_to_first_cert():
    case = _golden_case()
    ontology_kernel = _ontology_kernel_with_mismatched_cert_key(case)
    decision = ConstraintDecision(decision="valid", reason="ok")

    with patch(
        "recosearch.semantic_layers.ontology.certify.validate_claim",
        return_value=decision,
    ):
        results = run_ontology_certifications(
            ontology_kernel,
            _context_kernel(),
            {},
        )

    assert "resolved-cert-hash" in results
    assert results["resolved-cert-hash"]["certified"] is True
    assert results["resolved-cert-hash"]["golden_cases"][0]["passed"] is True


def test_run_ontology_certifications_marks_failure_on_case_mismatch():
    case = _golden_case(expected_decision="refuse")
    ontology_kernel = _ontology_kernel_with_mismatched_cert_key(case)
    decision = ConstraintDecision(decision="valid", reason="ok")

    with patch(
        "recosearch.semantic_layers.ontology.certify.validate_claim",
        return_value=decision,
    ):
        results = run_ontology_certifications(
            ontology_kernel,
            _context_kernel(),
            {},
        )

    payload = results["resolved-cert-hash"]
    assert payload["certified"] is False
    assert payload["golden_passed"] is False
    assert payload["golden_cases"][0]["passed"] is False


def test_verify_ontology_certification_results_missing_persisted():
    cert = OntologyCertification(
        ontology_hash="kernel-hash",
        reasoner_mode="none",
        golden_cases=(),
    )
    ontology_kernel = OntologyKernel(
        namespace="http://example.org/novashop/",
        ontology_ttl="",
        shapes_ttl="",
        mappings=MappingProxyType({}),
        ontology_hash="kernel-hash",
        certifications=MappingProxyType({"kernel-hash": cert}),
        persisted_certification_results=MappingProxyType({}),
    )

    failures = verify_ontology_certification_results(ontology_kernel)

    assert failures == ["missing persisted ontology certification results"]


def test_apply_ontology_certification_results_skips_unknown_cert_hash():
    existing_cert = OntologyCertification(
        ontology_hash="kernel-hash",
        reasoner_mode="none",
        golden_cases=(),
        certified=False,
        golden_passed=False,
    )
    ontology_kernel = OntologyKernel(
        namespace="http://example.org/novashop/",
        ontology_ttl="",
        shapes_ttl="",
        mappings=MappingProxyType({}),
        ontology_hash="kernel-hash",
        certifications=MappingProxyType({"kernel-hash": existing_cert}),
    )
    results = {
        "unknown-cert-hash": {"certified": True, "golden_passed": True},
        "kernel-hash": {"certified": True, "golden_passed": True},
    }

    updated = apply_ontology_certification_results(ontology_kernel, results)

    assert updated.certifications["kernel-hash"].certified is True
    assert "unknown-cert-hash" in updated.persisted_certification_results


def test_run_pipeline_golden_case_executes(contract):
    case = GoldenConstraintCase(
        term_id="term:novashop:revenue",
        tenant="novashop",
        actor_role="analyst",
        claim_qualifiers=(("period", "2026-01"),),
        expected_decision="answer",
    )

    result = run_pipeline_golden_case(case, contract)

    assert result.decision in {"answer", "clarify", "refuse"}


def test_pass_k_returns_zero_for_empty_questions_or_invalid_k(contract):
    assert pass_k([], contract, k=2) == 0.0
    assert pass_k([{"term": "revenue", "expected_decision": "answer"}], contract, k=0) == 0.0


def test_pass_k_decision_fallback_for_dict_without_decision_key(contract):
    def runner(_question: dict, _contract: dict) -> dict:
        return {"status": "ok"}

    score = pass_k(
        [{"term": "revenue", "expected_decision": "answer"}],
        contract,
        k=1,
        runner=runner,
    )

    assert score == 0.0
