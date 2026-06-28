from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.loader import load_ontology_kernel
from recosearch.semantic_layers.ontology.validate import clear_validation_cache, validate_claim

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"

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


def test_valid_revenue_claim_conforms(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:order_revenue",
        ontology_kernel,
        reference_date=JANUARY,
    )
    assert decision.decision == "valid"
    assert decision.reason_code == ""


def test_gross_as_net_refuse(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:gross_revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:gross_revenue",
        ontology_kernel,
        claim_qualifiers=(("reported_as", "NetRevenue"), ("period", "2026-01")),
    )
    assert decision.decision == "refuse"
    assert decision.reason_code == "CONSTRAINT_VIOLATION"
    assert decision.violations
    assert any("gross_reported_as_net" in v.message for v in decision.violations)


def test_deferred_as_recognized_net_refuse(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:deferred_revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:deferred_revenue",
        ontology_kernel,
        claim_qualifiers=(
            ("recognition_status", "recognized"),
            ("reported_as", "NetRevenue"),
            ("refund_treatment", "after_refunds"),
            ("period", "2026-01"),
        ),
    )
    assert decision.decision == "refuse"
    assert decision.reason_code == "CONSTRAINT_VIOLATION"
    assert any("deferred_as_recognized_net" in v.message for v in decision.violations)


def test_missing_period_clarify(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:order_revenue",
        ontology_kernel,
    )
    assert decision.decision == "clarify"
    assert decision.reason_code == "CONSTRAINT_CLARIFY"


def test_missing_refund_treatment_for_net_clarify(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:net_revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:net_revenue",
        ontology_kernel,
        claim_qualifiers=(("period", "2026-01"),),
    )
    assert decision.decision == "clarify"
    assert "refund_treatment" in decision.reason


def test_validation_cache_hit(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:revenue"]
    first = validate_claim(
        binding,
        "metric:novashop:order_revenue",
        ontology_kernel,
        reference_date=JANUARY,
    )
    second = validate_claim(
        binding,
        "metric:novashop:order_revenue",
        ontology_kernel,
        reference_date=JANUARY,
    )
    assert first.claim_hash == second.claim_hash
    assert first.decision == second.decision == "valid"


def test_violation_dominates_clarify_warning(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:gross_revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:gross_revenue",
        ontology_kernel,
        claim_qualifiers=(("reported_as", "NetRevenue"),),
    )
    assert decision.decision == "refuse"
    assert decision.reason_code == "CONSTRAINT_VIOLATION"
    severities = {v.severity for v in decision.violations}
    assert any(s.endswith("#Violation") for s in severities)


def test_whynot_recomposed_on_cache_hit(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:gross_revenue"]
    qualifiers = (("reported_as", "NetRevenue"), ("period", "2026-01"))
    first = validate_claim(
        binding,
        "metric:novashop:gross_revenue",
        ontology_kernel,
        claim_qualifiers=qualifiers,
        plan_context=(("plan_id", "plan-a"),),
        lineage_context=(("lineage_id", "line-a"),),
    )
    second = validate_claim(
        binding,
        "metric:novashop:gross_revenue",
        ontology_kernel,
        claim_qualifiers=qualifiers,
        plan_context=(("plan_id", "plan-b"),),
        lineage_context=(("lineage_id", "line-b"),),
    )
    assert first.decision == second.decision == "refuse"
    assert first.reason_code == second.reason_code == "CONSTRAINT_VIOLATION"
    assert first.claim_hash == second.claim_hash
    assert first.violations
    assert second.violations
    first_why = dict(first.violations[0].why_not)
    second_why = dict(second.violations[0].why_not)
    assert first_why["plan_id"] == "plan-a"
    assert first_why["lineage_id"] == "line-a"
    assert second_why["plan_id"] == "plan-b"
    assert second_why["lineage_id"] == "line-b"


def test_cache_thread_safe(context_kernel, ontology_kernel):
    binding = context_kernel.terms["term:novashop:revenue"]
    errors: list[str] = []
    decisions: list[str] = []

    def worker(thread_id: int) -> None:
        try:
            decision = validate_claim(
                binding,
                "metric:novashop:order_revenue",
                ontology_kernel,
                reference_date=JANUARY,
                plan_context=(("thread", str(thread_id)),),
            )
            decisions.append(decision.decision)
        except Exception as exc:  # pragma: no cover - surfaced via errors
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(decisions) == 16
    assert all(d == "valid" for d in decisions)


def test_reasoner_mode_opt_in_rdfs(context_kernel, metric_kernel):
    from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader

    kernel = OntologyKernelLoader.from_dir(
        Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers" / "semantic" / "ontology",
        context_kernel=context_kernel,
        reasoner_mode="rdfs",
    )
    binding = context_kernel.terms["term:novashop:revenue"]
    decision = validate_claim(
        binding,
        "metric:novashop:order_revenue",
        kernel,
        claim_qualifiers=(("period", "2026-01"),),
    )
    assert kernel.reasoner_mode == "rdfs"
    assert decision.reasoner_mode == "rdfs"
    assert decision.decision == "valid"
