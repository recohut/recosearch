"""Complex cross-layer SOTA business case — Novashop January 2026 board close.

CFO board pack asks for a multi-claim close packet: recognized revenue, deferred
revenue exposure, and a comparable-group foot check. Each layer contributes a
distinct invariant; L4 alone certifies pack-level exit that L1–L3 per-claim
adjudication cannot provide.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import duckdb
import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.events import MetadataChanged, get_event_bus
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack, execute_subclaim
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers.ontology.validate import clear_validation_cache
from recosearch.semantic_layers.pipeline import execute_context_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
NOVASHOP_DB = ROOT / "examples" / "novashop" / "shop.duckdb"
JANUARY_REFERENCE = "2026-01-31"
JANUARY_DATE = date(2026, 1, 31)

TERM_REVENUE = "term:novashop:revenue"
TERM_DEFERRED = "term:novashop:deferred_revenue"
METRIC_ORDER_REVENUE = "metric:novashop:order_revenue"
METRIC_DEFERRED = "metric:novashop:deferred_revenue"

BOARD_PACK_DEFERRED_QUALIFIERS = (
    ("recognition_status", "recognized"),
    ("reported_as", "NetRevenue"),
    ("refund_treatment", "after_refunds"),
    ("period", "2026-01"),
)

CLOSE_GROUP = "january_close_totals"


@pytest.fixture(autouse=True)
def _clear_runtime_state():
    get_event_bus().clear()
    ledger.clear()
    clear_validation_cache()
    yield
    get_event_bus().clear()
    ledger.clear()
    clear_validation_cache()


def ensure_novashop_db() -> Path:
    if not NOVASHOP_DB.exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return NOVASHOP_DB


def raw_duckdb_order_total(*, status: str) -> float:
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


def _without_l3(contract: dict) -> dict:
    stripped = copy.deepcopy(contract)
    stripped.pop("ontology_kernel", None)
    return stripped


def _ctx(answer) -> dict:
    return dict(answer.context_resolution or ())


def _metric(answer) -> dict:
    return dict(answer.metric_resolution or ())


def _constraint(answer) -> dict:
    return dict(answer.constraint_decision or ())


def _revenue_subclaim(**overrides) -> Subclaim:
    defaults = dict(
        term="revenue",
        tenant="novashop",
        actor_role="analyst",
        reference_date=JANUARY_REFERENCE,
        comparable_group=CLOSE_GROUP,
        time_period="2026-01",
        scoped_question="What was Novashop recognized revenue for January 2026 close?",
    )
    defaults.update(overrides)
    return Subclaim(**defaults)


def _deferred_exposure_subclaim(**overrides) -> Subclaim:
    defaults = dict(
        term="deferred revenue",
        tenant="novashop",
        actor_role="analyst",
        reference_date=JANUARY_REFERENCE,
        comparable_group=CLOSE_GROUP,
        time_period="2026-01",
        scoped_question="What is Novashop deferred revenue exposure for January 2026 close?",
    )
    defaults.update(overrides)
    return Subclaim(**defaults)


def _deferred_as_recognized_subclaim() -> Subclaim:
    return Subclaim(
        term="deferred revenue",
        tenant="novashop",
        actor_role="analyst",
        reference_date=JANUARY_REFERENCE,
        claim_qualifiers=BOARD_PACK_DEFERRED_QUALIFIERS,
        scoped_question="Can deferred revenue be reported as recognized net after refunds?",
    )


class TestComplexSotaJanuaryBoardClose:
    """CFO January close packet — L1+L2+L3+L4 integrated SOTA wedge."""

    def test_l1_governed_revenue_matches_duckdb_oracle_at_order_grain(self, compile_contract):
        """L1: fanout-safe order-grain metric matches DuckDB delivered-revenue oracle."""
        expected = raw_duckdb_order_total(status="delivered")
        result = execute_subclaim(_revenue_subclaim(), contract=compile_contract)
        metric = _metric(result.answer)

        assert result.answer.decision == "answer"
        assert result.answer.result[0]["metric_value"] == expected
        assert metric.get("resolved_metric_id") == METRIC_ORDER_REVENUE
        assert metric.get("grain") == "order"
        assert result.grain == "order"

    def test_l2_trust_context_present_on_close_subclaims(self, compile_contract):
        """L2: policy/trust envelope is resolved before L1 executes on board subclaims."""
        for subclaim in (_revenue_subclaim(), _deferred_exposure_subclaim()):
            result = execute_subclaim(subclaim, contract=compile_contract)
            ctx = _ctx(result.answer)

            assert result.answer.decision == "answer"
            assert ctx.get("term_id") in (TERM_REVENUE, TERM_DEFERRED)
            assert ctx.get("trust_status") in ("trusted", "usable_with_caveats")
            assert ctx.get("drift_status") != "expired"
            assert ctx.get("evidence_tier") == 3

    def test_l2_policy_drift_blocks_board_subclaim_before_l3(self, compile_contract, monkeypatch):
        """L2 wedge: stale policy hash refuses subclaim before metric or L3 constraint."""
        monkeypatch.setattr(
            "recosearch.semantic_layers.policy.compute_policy_hash",
            lambda: "deadbeef00000000",
        )
        answer = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=compile_contract,
            actor=identity.resolve(role="analyst"),
            scoped_question="What was Novashop revenue in January 2026?",
            reference_date=JANUARY_DATE,
        )
        ctx = _ctx(answer)

        assert answer.decision == "refuse"
        assert answer.reason_code == "CONTEXT_NOT_USABLE"
        assert ctx.get("drift_status") == "expired"
        assert ctx.get("trust_status") == "not_usable"
        assert not _metric(answer).get("resolved_metric_id")

    def test_l3_deferred_as_recognized_net_refuses_with_constraint_violation(
        self, compile_contract
    ):
        """L3: invalid close claim refused with proof; L1+L2 alone would admit without L3."""
        expected_deferred = raw_duckdb_order_total(status="pending")

        without_l3 = execute_context_query(
            ContextQuery(
                term="deferred revenue",
                tenant="novashop",
                claim_qualifiers=BOARD_PACK_DEFERRED_QUALIFIERS,
            ),
            contract=_without_l3(compile_contract),
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_DATE,
        )
        assert without_l3.decision == "answer"
        assert without_l3.result[0]["metric_value"] == expected_deferred

        with_l3 = execute_context_query(
            ContextQuery(
                term="deferred revenue",
                tenant="novashop",
                claim_qualifiers=BOARD_PACK_DEFERRED_QUALIFIERS,
            ),
            contract=compile_contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_DATE,
        )
        constraint = _constraint(with_l3)

        assert with_l3.decision == "refuse"
        assert with_l3.reason_code == "CONSTRAINT_VIOLATION"
        assert with_l3.result is None
        assert constraint.get("decision") == "refuse"
        assert any(
            "deferred_as_recognized_net" in v.get("message", "")
            for v in (constraint.get("violations") or [])
        )

    def test_l4_valid_revenue_only_close_packet_answers_with_evidence_pack(
        self, compile_contract
    ):
        """L4: registered comparable group foots; pack exits answer with EvidencePack."""
        expected = raw_duckdb_order_total(status="delivered")
        claim_set = ClaimSet(
            subclaims=(_revenue_subclaim(),),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "answer"
        assert pack.consistency_report.ok
        assert answer.decision == "answer"
        assert answer.result[0]["values"][0]["metric_value"] == expected
        evidence = dict(answer.evidence_pack)
        assert evidence["pack_id"] == pack.pack_id
        assert evidence["contract_hash"] == compile_contract["contract_hash"]
        assert evidence["consistency_ok"] is True
        assert any(e["artifact_type"] == "evidence_pack" for e in ledger.events())

    def test_l4_deferred_exposure_triggers_review_with_ticket_and_evidence_pack(
        self, compile_contract
    ):
        """L4: multi-claim close with deferred exposure → review_required + ReviewTicket."""
        claim_set = ClaimSet(
            subclaims=(_revenue_subclaim(), _deferred_exposure_subclaim()),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "review_required"
        assert answer.decision == "review_required"
        assert answer.reason_code == "EVIDENCE_REVIEW_REQUIRED"
        assert pack.review_ticket is not None
        assert any("review_trigger:" in r for r in pack.composite_reasons)
        ticket_events = [e for e in ledger.events() if e["artifact_type"] == "review_ticket"]
        assert ticket_events
        assert ticket_events[-1]["payload"]["ticket_id"] == pack.review_ticket.ticket_id
        assert dict(answer.evidence_pack)["decision"] == "review_required"

    def test_l4_comparable_group_period_mismatch_triggers_review(self, compile_contract):
        """L4: registered group members must share period to foot board totals."""
        claim_set = ClaimSet(
            subclaims=(
                _revenue_subclaim(time_period="2026-01"),
                _revenue_subclaim(time_period="2026-02"),
            ),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "review_required"
        assert answer.decision == "review_required"
        assert not pack.consistency_report.ok
        assert any("period mismatch" in r for r in pack.composite_reasons)
        assert pack.review_ticket is not None

    def test_l4_l3_constraint_refuse_folds_to_pack_refuse(self, compile_contract):
        """L4: L3 CONSTRAINT_VIOLATION on subclaim folds to pack refuse."""
        claim_set = ClaimSet(
            subclaims=(_deferred_as_recognized_subclaim(),),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "refuse"
        assert answer.decision == "refuse"
        assert answer.reason_code == "EVIDENCE_PACK_REFUSED"
        assert any("subclaim_refuse:" in r for r in pack.composite_reasons)

    def test_l1_l3_per_claim_answers_cannot_certify_multi_claim_pack_without_l4(
        self, compile_contract
    ):
        """Negative wedge: each subclaim passes L1–L3 alone; only L4 blocks pack exit."""
        revenue = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=compile_contract,
            actor=identity.resolve(role="analyst"),
            scoped_question="What was Novashop revenue in January 2026?",
            reference_date=JANUARY_DATE,
        )
        deferred = execute_context_query(
            ContextQuery(term="deferred revenue", tenant="novashop"),
            contract=compile_contract,
            actor=identity.resolve(role="analyst"),
            scoped_question="What is Novashop deferred revenue exposure for January 2026?",
            reference_date=JANUARY_DATE,
        )

        assert revenue.decision == "answer"
        assert deferred.decision == "answer"
        assert _constraint(revenue).get("decision") == "valid"
        assert _constraint(deferred).get("decision") == "valid"

        claim_set = ClaimSet(
            subclaims=(_revenue_subclaim(), _deferred_exposure_subclaim()),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "review_required"
        assert answer.decision == "review_required"
        assert pack.review_ticket is not None
        assert not pack.consistency_report.ok or any(
            "review_trigger:" in r for r in pack.composite_reasons
        )

    def test_l1_l3_period_mismatch_per_claim_answers_pack_foot_fails_at_l4(
        self, compile_contract
    ):
        """Negative wedge: per-claim revenue answers; L4 catches period mismatch in group."""
        jan = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=compile_contract,
            actor=identity.resolve(role="analyst"),
            reference_date=JANUARY_DATE,
        )
        feb = execute_context_query(
            ContextQuery(term="revenue", tenant="novashop"),
            contract=compile_contract,
            actor=identity.resolve(role="analyst"),
            reference_date=date(2026, 2, 28),
        )

        assert jan.decision == "answer"
        assert feb.decision == "answer"

        claim_set = ClaimSet(
            subclaims=(
                _revenue_subclaim(time_period="2026-01"),
                _revenue_subclaim(time_period="2026-02"),
            ),
            pack_label="board_pack",
        )
        pack, _ = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "review_required"
        assert any("period mismatch" in r for r in pack.composite_reasons)
