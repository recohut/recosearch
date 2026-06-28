"""L1 + L2 + L3 business scenario — finance-close constraint wedge."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
JANUARY_REFERENCE = date(2026, 1, 31)
EXPECTED_REVENUE = 109.97
TERM_REVENUE = "term:novashop:revenue"
TERM_DEFERRED = "term:novashop:deferred_revenue"


@pytest.fixture(autouse=True)
def _clear_ledger():
    ledger.clear()
    yield
    ledger.clear()


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


class TestFinanceCloseConstraintWedge:
    def test_l1_l2_alone_admit_invalid_deferred_claim(self, contract):
        without_l3 = copy.deepcopy(contract)
        without_l3.pop("ontology_kernel", None)
        answer = execute_context_query(
            ContextQuery(
                term="deferred revenue",
                tenant="novashop",
                claim_qualifiers=(
                    ("recognition_status", "recognized"),
                    ("reported_as", "NetRevenue"),
                    ("refund_treatment", "after_refunds"),
                    ("period", "2026-01"),
                ),
            ),
            contract=without_l3,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        assert answer.decision == "answer"
        assert answer.reason_code != "CONSTRAINT_VIOLATION"

    def test_l3_refuses_deferred_as_recognized_net(self, contract):
        answer = execute_context_query(
            ContextQuery(
                term="deferred revenue",
                tenant="novashop",
                claim_qualifiers=(
                    ("recognition_status", "recognized"),
                    ("reported_as", "NetRevenue"),
                    ("refund_treatment", "after_refunds"),
                    ("period", "2026-01"),
                ),
            ),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        constraint = _constraint(answer)
        assert answer.decision == "refuse"
        assert answer.reason_code == "CONSTRAINT_VIOLATION"
        assert constraint.get("decision") == "refuse"
        assert constraint.get("ontology_hash", "").startswith("onto-")

        events = [e for e in ledger.events() if e["artifact_type"] == "constraint"]
        assert events

    def test_valid_january_revenue_with_constraint_valid(self, contract):
        answer = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            scoped_question="What was Novashop revenue in January 2026?",
            reference_date=JANUARY_REFERENCE,
        )
        constraint = _constraint(answer)
        ctx = _ctx(answer)
        metric = _metric(answer)

        assert answer.decision == "answer"
        assert answer.result[0]["metric_value"] == EXPECTED_REVENUE
        assert constraint.get("decision") == "valid"
        assert ctx.get("term_id") == TERM_REVENUE
        assert metric.get("resolved_metric_id")

    def test_three_layer_composition_envelope(self, contract):
        answer = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        constraint = _constraint(answer)
        ctx = _ctx(answer)
        metric = _metric(answer)

        assert answer.decision == "answer"
        assert ctx.get("trust_status") in ("trusted", "usable_with_caveats")
        assert ctx.get("evidence_tier", 0) >= 1
        assert constraint.get("decision") == "valid"
        assert constraint.get("ontology_hash")
        assert metric.get("definition_hash")
        assert answer.plan_ref
        assert answer.citations
