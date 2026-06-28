"""Robust L1+L2+L3 end-to-end proof-carrying tests for L3 risk fixes.

Focuses on risk-fix contracts: cache-hit stability, why_not recomposition,
guest/policy drift refusal paths, and deferred-revenue metric wedge.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.loader import load_ontology_kernel
from recosearch.semantic_layers.ontology.validate import clear_validation_cache, validate_claim
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"
JANUARY_REFERENCE = date(2026, 1, 31)
EXPECTED_DEFERRED = 49.99
TERM_DEFERRED = "term:novashop:deferred_revenue"
METRIC_DEFERRED = "metric:novashop:deferred_revenue"
TERM_REVENUE = "term:novashop:revenue"
INVALID_DEFERRED_QUALIFIERS = (
    ("recognition_status", "recognized"),
    ("reported_as", "NetRevenue"),
    ("refund_treatment", "after_refunds"),
    ("period", "2026-01"),
)


@pytest.fixture(autouse=True)
def _clear_runtime_state():
    ledger.clear()
    clear_validation_cache()
    yield
    ledger.clear()
    clear_validation_cache()


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def _constraint(answer) -> dict:
    return dict(answer.constraint_decision or ())


def _ctx(answer) -> dict:
    return dict(answer.context_resolution or ())


def _metric(answer) -> dict:
    return dict(answer.metric_resolution or ())


def _invalid_deferred_query(*, term: str = "deferred revenue") -> ContextQuery:
    return ContextQuery(
        term=term,
        tenant="novashop",
        claim_qualifiers=INVALID_DEFERRED_QUALIFIERS,
    )


class TestConstraintCacheHitStableDecisionE2E:
    """Same invalid deferred claim through the pipeline must not corrupt cached verdict fields."""

    def test_two_pipeline_calls_share_stable_constraint_decision(self, contract):
        query = _invalid_deferred_query()
        first = execute_context_query(
            query,
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        second = execute_context_query(
            query,
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )

        first_constraint = _constraint(first)
        second_constraint = _constraint(second)

        assert first.decision == second.decision == "refuse"
        assert first.reason_code == second.reason_code == "CONSTRAINT_VIOLATION"
        assert first_constraint.get("decision") == second_constraint.get("decision") == "refuse"
        assert (
            first_constraint.get("reason_code")
            == second_constraint.get("reason_code")
            == "CONSTRAINT_VIOLATION"
        )
        assert first_constraint.get("claim_hash") == second_constraint.get("claim_hash")
        assert first_constraint.get("claim_hash", "").startswith("claim-")


class TestWhyNotRecomposedOnCacheHit:
    """why_not must recompose per request context even when SHACL verdict is cached."""

    def test_e2e_stable_verdict_supplemental_whynot_differs(self, contract):
        # E2E: pipeline does not accept custom plan_context; repeated calls with the same
        # invalid deferred claim exercise the validation cache and must keep stable verdict
        # fields on Answer.constraint_decision (decision, reason_code, claim_hash).
        query = _invalid_deferred_query()
        first_answer = execute_context_query(
            query,
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        second_answer = execute_context_query(
            _invalid_deferred_query(term="unearned revenue"),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )

        first_constraint = _constraint(first_answer)
        second_constraint = _constraint(second_answer)

        assert first_constraint.get("decision") == "refuse"
        assert second_constraint.get("decision") == "refuse"
        assert first_constraint.get("reason_code") == "CONSTRAINT_VIOLATION"
        assert second_constraint.get("reason_code") == "CONSTRAINT_VIOLATION"
        assert first_constraint.get("claim_hash") == second_constraint.get("claim_hash")

        first_violations = first_constraint.get("violations") or []
        second_violations = second_constraint.get("violations") or []
        assert first_violations and second_violations
        assert first_violations == second_violations

        first_why = first_violations[0]["why_not"]
        assert isinstance(first_why, dict)
        assert first_why.get("claim_hash") == first_constraint.get("claim_hash")
        assert first_why.get("metric_id") == METRIC_DEFERRED
        assert first_why.get("term_id") == TERM_DEFERRED
        assert first_why.get("focus_node")
        assert first_why.get("failed_shape")
        assert first_why.get("constraint_component")

        # Supplemental (not replacement): validate_claim exposes plan/lineage context directly
        # and proves why_not is recomposed on cache hit while verdict fields stay stable.
        metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
        context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
        ontology_kernel = load_ontology_kernel(SEMANTIC, context_kernel=context_kernel)
        binding = context_kernel.terms[TERM_DEFERRED]
        lineage_a = (("lineage_id", "line-a"), ("execution_pass", "first"))
        lineage_b = (("lineage_id", "line-b"), ("execution_pass", "second"))
        plan_a = (("metric_id", METRIC_DEFERRED), ("term_id", TERM_DEFERRED), ("plan_id", "plan-a"))
        plan_b = (("metric_id", METRIC_DEFERRED), ("term_id", TERM_DEFERRED), ("plan_id", "plan-b"))

        first_decision = validate_claim(
            binding,
            METRIC_DEFERRED,
            ontology_kernel,
            claim_qualifiers=INVALID_DEFERRED_QUALIFIERS,
            reference_date=JANUARY_REFERENCE,
            plan_context=plan_a,
            lineage_context=lineage_a,
        )
        second_decision = validate_claim(
            binding,
            METRIC_DEFERRED,
            ontology_kernel,
            claim_qualifiers=INVALID_DEFERRED_QUALIFIERS,
            reference_date=JANUARY_REFERENCE,
            plan_context=plan_b,
            lineage_context=lineage_b,
        )

        assert first_decision.decision == second_decision.decision == "refuse"
        assert first_decision.reason_code == second_decision.reason_code == "CONSTRAINT_VIOLATION"
        assert first_decision.claim_hash == second_decision.claim_hash
        assert first_decision.violations and second_decision.violations

        first_why = dict(first_decision.violations[0].why_not)
        second_why = dict(second_decision.violations[0].why_not)
        assert first_why["plan_id"] == "plan-a"
        assert first_why["lineage_id"] == "line-a"
        assert second_why["plan_id"] == "plan-b"
        assert second_why["lineage_id"] == "line-b"
        assert first_why != second_why


class TestGuestRevenueAndPolicyDriftE2E:
    """L2 trust/policy gates must refuse before metric execution."""

    def test_guest_revenue_refuses_with_policy_reason(self, contract):
        answer = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=contract,
            actor=identity.resolve(role="guest"),
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "POLICY"
        assert ctx.get("term_id") == TERM_REVENUE
        assert ctx.get("trust_status") == "not_usable"
        assert answer.result is None
        assert not _constraint(answer)

    def test_policy_hash_drift_refuses_context_not_usable(self, contract, monkeypatch):
        monkeypatch.setattr(
            "recosearch.semantic_layers.policy.compute_policy_hash",
            lambda: "deadbeef00000000",
        )
        answer = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            scoped_question="What was Novashop revenue in January 2026?",
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "CONTEXT_NOT_USABLE"
        assert ctx.get("drift_status") == "expired"
        assert ctx.get("trust_status") == "not_usable"
        assert answer.result is None
        assert not _constraint(answer)


class TestDeferredRevenueMetricWedgeE2E:
    """Deferred revenue resolves to metric:novashop:deferred_revenue; L3 blocks bad recognized-net claims."""

    def test_plain_deferred_resolves_without_l3_invalid_claim_refuses_with_l3(self, contract):
        without_l3 = copy.deepcopy(contract)
        without_l3.pop("ontology_kernel", None)

        plain = execute_context_query(
            ContextQuery(term="deferred revenue", tenant="novashop"),
            contract=without_l3,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        plain_metric = _metric(plain)

        assert plain.decision == "answer"
        assert plain.result[0]["metric_value"] == EXPECTED_DEFERRED
        assert _ctx(plain).get("term_id") == TERM_DEFERRED
        assert plain_metric.get("resolved_metric_id") == METRIC_DEFERRED
        assert not _constraint(plain)

        invalid = execute_context_query(
            _invalid_deferred_query(),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        constraint = _constraint(invalid)

        assert invalid.decision == "refuse"
        assert invalid.reason_code == "CONSTRAINT_VIOLATION"
        assert constraint.get("decision") == "refuse"
        assert constraint.get("reason_code") == "CONSTRAINT_VIOLATION"
        assert constraint.get("claim_hash", "").startswith("claim-")
        violations = constraint.get("violations") or []
        assert violations
        assert any(
            "deferred_as_recognized_net" in v.get("message", "") for v in violations
        )
        why_not = violations[0].get("why_not") or {}
        assert why_not.get("claim_hash") == constraint.get("claim_hash")
        assert why_not.get("metric_id") == METRIC_DEFERRED
        assert why_not.get("term_id") == TERM_DEFERRED
        assert invalid.result is None

        events = [e for e in ledger.events() if e["artifact_type"] == "constraint"]
        assert events
