"""L1 (metric) + L2 (context/trust) business scenario for Novashop.

As a Novashop analyst, answer January revenue and explain which business term,
trusted metric, source, policy, certification tier, and lineage produced it.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.context.certify import (
    persist_context_certification_results,
    run_context_certifications,
)
from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"
CONTEXT_DIR = SEMANTIC / "context"
METRICS_DIR = SEMANTIC / "metrics"

JANUARY_REFERENCE = date(2026, 1, 31)
EXPECTED_REVENUE = 109.97
TERM_REVENUE = "term:novashop:revenue"
METRIC_ORDER_REVENUE = "metric:novashop:order_revenue"
SOURCE_NOVASHOP = "novashop"


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


def _ctx(answer) -> dict:
    return dict(answer.context_resolution or ())


def _metric_ctx(answer) -> dict:
    return dict(answer.metric_resolution or ())


def analyst_january_revenue(contract, *, actor=None):
    """Business question: What was Novashop revenue in January 2026?"""
    return execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
        actor=actor or identity.resolve(role="analyst"),
        scoped_question="What was Novashop revenue in January 2026?",
        reference_date=JANUARY_REFERENCE,
    )


def scenario_explanation(answer) -> dict[str, object]:
    """Structured explanation an analyst would receive alongside the number."""
    ctx = _ctx(answer)
    metric = _metric_ctx(answer)
    return {
        "decision": answer.decision,
        "metric_value": (answer.result[0]["metric_value"] if answer.result else None),
        "business_term": ctx.get("term_id"),
        "trusted_metric": metric.get("resolved_metric_id"),
        "source": metric.get("collection_id", SOURCE_NOVASHOP),
        "trust_status": ctx.get("trust_status"),
        "evidence_tier": ctx.get("evidence_tier"),
        "drift_status": ctx.get("drift_status"),
        "context_card": ctx.get("card_id"),
        "policy_trace": answer.policy_trace,
        "reason_code": answer.reason_code,
    }


class TestNovashopAnalystJanuaryRevenue:
    """End-to-end L2 resolve → L1 execute for the primary business question."""

    def test_happy_path_answer_with_lineage(self, contract):
        answer = analyst_january_revenue(contract)
        explanation = scenario_explanation(answer)

        assert answer.decision == "answer"
        assert explanation["metric_value"] == EXPECTED_REVENUE
        assert explanation["business_term"] == TERM_REVENUE
        assert explanation["trusted_metric"] == METRIC_ORDER_REVENUE
        assert explanation["trust_status"] in ("trusted", "usable_with_caveats")
        assert explanation["evidence_tier"] >= 1
        assert explanation["context_card"]
        assert explanation["context_card"].startswith("ctx-")

        metric_kernel = MetricKernel.from_dir(METRICS_DIR)
        context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
        binding = context_kernel.terms[TERM_REVENUE]
        card = build_context_card(
            binding,
            context_kernel,
            metric_kernel,
            actor_role="analyst",
            contract_hash=contract["contract_hash"],
        )
        assert METRIC_ORDER_REVENUE in card.primary_refs
        assert any(s["source_id"] == SOURCE_NOVASHOP for s in card.technical["data_source"])

        events = [e for e in ledger.events() if e["artifact_type"] == "context"]
        assert events
        edges = events[0]["lineage_edges"]
        assert {"from_id": TERM_REVENUE, "to_id": METRIC_ORDER_REVENUE, "kind": "context_ref"} in edges
        assert {"from_id": TERM_REVENUE, "to_id": SOURCE_NOVASHOP, "kind": "context_ref"} in edges

    def test_customer_ambiguity_clarify_with_context_card(self, contract):
        answer = execute_context_query(
            ContextQuery(term="customer", tenant="novashop"),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            scoped_question="How many customers did we have in January?",
        )
        ctx = _ctx(answer)

        assert answer.decision == "clarify"
        assert ctx["term_id"] == "term:novashop:customer"
        assert ctx["card_id"].startswith("ctx-")
        assert answer.result is None

    def test_guest_revenue_policy_refuse(self, contract):
        answer = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=contract,
            actor=identity.resolve(role="guest"),
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "POLICY"
        assert ctx["term_id"] == TERM_REVENUE
        assert ctx["trust_status"] == "not_usable"
        assert answer.result is None


class TestNovashopContextCertificationRuntime:
    """Persisted context certification upgrades runtime evidence to tier 3."""

    def test_tier3_evidence_after_certify_and_persist(self, contract, tmp_path):
        context_dir = tmp_path / "context"
        shutil.copytree(CONTEXT_DIR, context_dir)
        semantic = tmp_path / "semantic"
        shutil.copytree(SEMANTIC, semantic)
        shutil.rmtree(semantic / "context")
        shutil.copytree(context_dir, semantic / "context")

        metric_kernel = MetricKernel.from_dir(METRICS_DIR)
        context_kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
        results = run_context_certifications(
            context_kernel,
            metric_kernel,
            contract,
            reference_date=JANUARY_REFERENCE,
            run_probe=True,
        )
        assert results[TERM_REVENUE]["probe"]["passed"] is True
        assert results[TERM_REVENUE]["evidence_tier"] == 3

        persist_context_certification_results(context_dir, results)
        shutil.rmtree(semantic / "context")
        shutil.copytree(context_dir, semantic / "context")
        compiled = compile_contract(semantic)

        answer = analyst_january_revenue(compiled)
        ctx = _ctx(answer)

        assert answer.decision == "answer"
        assert answer.result[0]["metric_value"] == EXPECTED_REVENUE
        assert ctx["evidence_tier"] == 3
        assert ctx["trust_status"] in ("trusted", "usable_with_caveats")


class TestNovashopPolicyDrift:
    """Policy hash drift marks context expired and blocks execution."""

    def test_policy_changed_refuse_at_runtime(self, contract, monkeypatch):
        monkeypatch.setattr(
            "recosearch.semantic_layers.policy.compute_policy_hash",
            lambda: "deadbeef00000000",
        )
        answer = analyst_january_revenue(contract)
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "CONTEXT_NOT_USABLE"
        assert ctx["drift_status"] == "expired"
        assert ctx["trust_status"] == "not_usable"
