from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.loader import load_ontology_kernel
from recosearch.semantic_layers.ontology.types import ConstraintViolation
from recosearch.semantic_layers.ontology.validate import _classify, clear_validation_cache, validate_claim

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"
JANUARY = date(2026, 1, 31)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_validation_cache()
    yield
    clear_validation_cache()


@pytest.fixture(scope="module")
def metric_kernel():
    return MetricKernel.from_dir(SEMANTIC / "metrics")


@pytest.fixture(scope="module")
def context_kernel(metric_kernel):
    return load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)


@pytest.fixture(scope="module")
def ontology_kernel(context_kernel):
    return load_ontology_kernel(SEMANTIC, context_kernel=context_kernel)


def test_classify_no_violations_returns_valid():
    decision, reason, reason_code = _classify([])
    assert decision == "valid"
    assert reason == "claim conforms to ontology constraints"
    assert reason_code == ""


def test_classify_soft_warning_falls_back_to_refuse():
    violation = ConstraintViolation(
        shape="shape:soft",
        focus="focus:node",
        severity="http://www.w3.org/ns/shacl#Warning",
        message="soft ontology warning",
        source_iri="component:soft",
    )
    decision, reason, reason_code = _classify([violation])
    assert decision == "refuse"
    assert reason == "soft ontology warning"
    assert reason_code == "CONSTRAINT_VIOLATION"


def test_validate_claim_normalizes_invalid_classify_decision(
    context_kernel, ontology_kernel, monkeypatch
):
    binding = context_kernel.terms["term:novashop:gross_revenue"]
    qualifiers = (("reported_as", "NetRevenue"), ("period", "2026-01"))

    def _invalid_classify(_violations):
        return "bogus", "unexpected classifier output", "NOT_A_DECISION"

    monkeypatch.setattr(
        "recosearch.semantic_layers.ontology.validate._classify",
        _invalid_classify,
    )

    decision = validate_claim(
        binding,
        "metric:novashop:gross_revenue",
        ontology_kernel,
        claim_qualifiers=qualifiers,
        use_cache=False,
    )
    assert decision.decision == "refuse"
    assert decision.reason_code == "CONSTRAINT_VIOLATION"
