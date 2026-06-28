"""L1 + L2 + L3 + L4 finance-close board-pack scenario — Novashop January close."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers.ontology.validate import clear_validation_cache

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
NOVASHOP_DB = ROOT / "examples" / "novashop" / "shop.duckdb"
JANUARY_REFERENCE = "2026-01-31"

BOARD_PACK_DEFERRED_QUALIFIERS = (
    ("recognition_status", "recognized"),
    ("reported_as", "NetRevenue"),
    ("refund_treatment", "after_refunds"),
    ("period", "2026-01"),
)


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


def _revenue_subclaim(**overrides) -> Subclaim:
    defaults = dict(
        term="revenue",
        tenant="novashop",
        actor_role="analyst",
        reference_date=JANUARY_REFERENCE,
        comparable_group="january_close_totals",
        time_period="2026-01",
    )
    defaults.update(overrides)
    return Subclaim(**defaults)


class TestL4FinanceCloseBoardPack:
    def test_valid_revenue_only_pack_answers(self, compile_contract):
        clear_validation_cache()
        expected_revenue = raw_duckdb_order_total(status="delivered")
        claim_set = ClaimSet(
            subclaims=(_revenue_subclaim(),),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "answer"
        assert answer.decision == "answer"
        assert answer.result
        assert answer.result[0]["values"][0]["metric_value"] == expected_revenue
        assert dict(answer.evidence_pack)["decision"] == "answer"

    def test_deferred_revenue_term_triggers_review_with_ticket(self, compile_contract):
        clear_validation_cache()
        claim_set = ClaimSet(
            subclaims=(
                _revenue_subclaim(),
                Subclaim(
                    term="deferred revenue",
                    tenant="novashop",
                    actor_role="analyst",
                    reference_date=JANUARY_REFERENCE,
                ),
            ),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "review_required"
        assert answer.decision == "review_required"
        assert answer.reason_code == "EVIDENCE_REVIEW_REQUIRED"
        assert pack.review_ticket is not None
        ticket_events = [e for e in ledger.events() if e["artifact_type"] == "review_ticket"]
        assert ticket_events
        assert ticket_events[-1]["payload"]["ticket_id"] == pack.review_ticket.ticket_id

    def test_comparable_group_period_mismatch_triggers_review(self, compile_contract):
        clear_validation_cache()
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

    def test_deferred_as_recognized_net_subclaim_refuses_pack(self, compile_contract):
        clear_validation_cache()
        claim_set = ClaimSet(
            subclaims=(
                Subclaim(
                    term="deferred revenue",
                    tenant="novashop",
                    actor_role="analyst",
                    reference_date=JANUARY_REFERENCE,
                    claim_qualifiers=BOARD_PACK_DEFERRED_QUALIFIERS,
                    scoped_question="Can deferred revenue be reported as recognized net after refunds?",
                ),
            ),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

        assert pack.decision == "refuse"
        assert answer.decision == "refuse"
        assert answer.reason_code == "EVIDENCE_PACK_REFUSED"
        assert any("subclaim_refuse:" in r for r in pack.composite_reasons)

    def test_evidence_pack_tuple_on_answer(self, compile_contract):
        clear_validation_cache()
        claim_set = ClaimSet(
            subclaims=(_revenue_subclaim(),),
            pack_label="board_pack",
        )
        pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)
        evidence = dict(answer.evidence_pack)
        assert evidence["pack_id"] == pack.pack_id
        assert evidence["contract_hash"] == compile_contract["contract_hash"]
        assert evidence["evidence_tier_min"] == pack.evidence_tier_min
        assert "consistency_ok" in evidence
