"""L1 + L2 + L3 finance-close board-pack scenario — Novashop January close.

Business story
--------------
A controller preparing the January 2026 board pack asks whether deferred (unearned)
revenue can be reported as recognized net revenue after refunds for the period.
L1 metrics and L2 context/trust can resolve a number for that framing, but that
answer is wrong for close reporting. L3 ontology constraints must refuse with
proof-carrying why_not. Guest policy and L2 policy-drift gates must block before
L3. A valid January revenue question must still answer through all layers.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import duckdb
import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.ontology.validate import clear_validation_cache
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
NOVASHOP_DB = ROOT / "examples" / "novashop" / "shop.duckdb"
JANUARY_REFERENCE = date(2026, 1, 31)
TERM_REVENUE = "term:novashop:revenue"
TERM_DEFERRED = "term:novashop:deferred_revenue"
METRIC_ORDER_REVENUE = "metric:novashop:order_revenue"
METRIC_DEFERRED = "metric:novashop:deferred_revenue"
DEFERRED_TERM_ALIASES = (
    "deferred revenue",
    "unearned revenue",
    "deferred sales",
)

BOARD_PACK_DEFERRED_QUALIFIERS = (
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


def ensure_novashop_db() -> Path:
    """Build examples/novashop/shop.duckdb when missing."""
    if not NOVASHOP_DB.exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return NOVASHOP_DB


def raw_duckdb_order_total(*, status: str) -> float:
    """Independent DuckDB oracle: sum January 2026 order totals for a delivery status."""
    db_path = ensure_novashop_db()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        (total,) = con.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0)
            FROM orders
            WHERE status = ?
              AND order_date >= DATE '2026-01-01'
              AND order_date < DATE '2026-02-01'
            """,
            [status],
        ).fetchone()
    finally:
        con.close()
    return float(total)


@pytest.fixture(scope="module")
def contract():
    ensure_novashop_db()
    return compile_contract()


def _constraint(answer) -> dict:
    return dict(answer.constraint_decision or ())


def _ctx(answer) -> dict:
    return dict(answer.context_resolution or ())


def _metric(answer) -> dict:
    return dict(answer.metric_resolution or ())


def _without_l3(contract: dict) -> dict:
    stripped = copy.deepcopy(contract)
    stripped.pop("ontology_kernel", None)
    return stripped


def _deferred_as_recognized_violation(violations: list) -> dict:
    return next(
        v
        for v in violations
        if "deferred_as_recognized_net" in v.get("message", "")
    )


def board_pack_deferred_recognition_query(*, term: str = "deferred revenue") -> ContextQuery:
    """Controller question: treat January deferred revenue as recognized net after refunds."""
    return ContextQuery(
        term=term,
        tenant="novashop",
        claim_qualifiers=BOARD_PACK_DEFERRED_QUALIFIERS,
    )


def analyst_january_revenue(contract, *, actor=None):
    """Valid close question: What was Novashop revenue in January 2026?"""
    return execute_context_query(
        ContextQuery(term="revenue", tenant="novashop"),
        contract=contract,
        actor=actor or identity.resolve(role="analyst"),
        scoped_question="What was Novashop revenue in January 2026?",
        reference_date=JANUARY_REFERENCE,
    )


class TestFinanceCloseBoardPackScenario:
    """All-layer board-pack close: bad claim admitted without L3, refused with proof, precedence, valid path."""

    @pytest.mark.parametrize("deferred_term", DEFERRED_TERM_ALIASES)
    def test_step1_l1_l2_admit_invalid_deferred_as_recognized_net(
        self, contract, deferred_term
    ):
        """Without L3, prior layers resolve deferred revenue as if it were recognized net."""
        expected_deferred = raw_duckdb_order_total(status="pending")
        answer = execute_context_query(
            board_pack_deferred_recognition_query(term=deferred_term),
            contract=_without_l3(contract),
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)
        metric = _metric(answer)

        assert answer.decision == "answer"
        assert answer.reason_code != "CONSTRAINT_VIOLATION"
        assert not answer.constraint_decision
        assert ctx.get("term_id") == TERM_DEFERRED
        assert metric.get("resolved_metric_id") == METRIC_DEFERRED
        assert answer.result is not None
        assert answer.result[0]["metric_value"] == expected_deferred

    @pytest.mark.parametrize("deferred_term", DEFERRED_TERM_ALIASES)
    def test_step2_l3_refuses_with_proof_carrying_constraint_decision(
        self, contract, deferred_term
    ):
        """Full contract: L3 refuses deferred-as-recognized-net with structured violations and ledger."""
        answer = execute_context_query(
            board_pack_deferred_recognition_query(term=deferred_term),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        constraint = _constraint(answer)
        metric = _metric(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "CONSTRAINT_VIOLATION"
        assert answer.result is None
        assert not metric.get("resolved_metric_id")
        assert not any(e["artifact_type"] == "query" for e in ledger.events())

        assert constraint.get("decision") == "refuse"
        assert constraint.get("ontology_hash", "").startswith("onto-")
        assert constraint.get("claim_hash", "").startswith("claim-")

        violations = constraint.get("violations") or []
        assert isinstance(violations, list) and violations
        target_violation = _deferred_as_recognized_violation(violations)

        why_not = target_violation.get("why_not") or {}
        assert isinstance(why_not, dict)
        assert why_not.get("claim_hash") == constraint.get("claim_hash")
        assert why_not.get("metric_id") == METRIC_DEFERRED
        assert why_not.get("term_id") == TERM_DEFERRED
        assert why_not.get("focus_node")
        assert why_not.get("failed_shape")
        assert why_not.get("constraint_component")

        events = [e for e in ledger.events() if e["artifact_type"] == "constraint"]
        assert events
        assert events[-1]["payload"]["claim_hash"] == constraint.get("claim_hash")
        edges = events[-1]["lineage_edges"]
        assert any(e["kind"] == "constraint_violation" for e in edges)

    def test_step3_guest_policy_blocks_before_l3_constraint(self, contract):
        """Guest actor on the same board-pack claim: POLICY refuse, no L3 artifact or metric."""
        answer = execute_context_query(
            board_pack_deferred_recognition_query(),
            contract=contract,
            actor=identity.resolve(role="guest"),
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "POLICY"
        assert ctx.get("term_id") == TERM_DEFERRED
        assert ctx.get("trust_status") == "not_usable"
        assert not answer.constraint_decision
        assert answer.result is None
        assert not _metric(answer).get("resolved_metric_id")

    def test_precedence_guest_policy_wins_over_drift_on_deferred_board_pack(
        self, contract, monkeypatch
    ):
        """Guest + stale policy hash on board-pack claim: POLICY wins before drift or L3."""
        monkeypatch.setattr(
            "recosearch.semantic_layers.policy.compute_policy_hash",
            lambda: "deadbeef00000000",
        )
        answer = execute_context_query(
            board_pack_deferred_recognition_query(),
            contract=contract,
            actor=identity.resolve(role="guest"),
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "POLICY"
        assert ctx.get("trust_status") == "not_usable"
        assert not answer.constraint_decision
        assert answer.result is None
        assert not _metric(answer).get("resolved_metric_id")

    def test_step4_policy_drift_blocks_before_l3_on_deferred_board_pack(
        self, contract, monkeypatch
    ):
        """Analyst with stale policy hash: L2 trust refuses board-pack claim before metric or L3."""
        monkeypatch.setattr(
            "recosearch.semantic_layers.policy.compute_policy_hash",
            lambda: "deadbeef00000000",
        )
        answer = execute_context_query(
            board_pack_deferred_recognition_query(),
            contract=contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_REFERENCE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "CONTEXT_NOT_USABLE"
        assert ctx.get("term_id") == TERM_DEFERRED
        assert ctx.get("drift_status") == "expired"
        assert ctx.get("trust_status") == "not_usable"
        assert not answer.constraint_decision
        assert answer.result is None
        assert not _metric(answer).get("resolved_metric_id")

    def test_step5_valid_january_revenue_answers_through_all_layers(self, contract):
        """Valid close path: revenue answer, L3 valid, lineage plan_ref and citations present."""
        expected_revenue = raw_duckdb_order_total(status="delivered")
        answer = analyst_january_revenue(contract)
        constraint = _constraint(answer)
        ctx = _ctx(answer)
        metric = _metric(answer)

        assert answer.decision == "answer"
        assert answer.result[0]["metric_value"] == expected_revenue
        assert constraint.get("decision") == "valid"
        assert constraint.get("ontology_hash", "").startswith("onto-")
        assert constraint.get("claim_hash", "").startswith("claim-")
        assert constraint.get("reasoner_mode")
        assert constraint.get("drift_status") == "current"
        assert ctx.get("term_id") == TERM_REVENUE
        assert metric.get("resolved_metric_id") == METRIC_ORDER_REVENUE
        assert isinstance(answer.plan_ref, str) and answer.plan_ref
        assert answer.citations[0]["metric_id"] == METRIC_ORDER_REVENUE
        assert answer.citations[0].get("query_hash")
