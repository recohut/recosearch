"""L2-only business scenario: live drift via event bus (Novashop).

An analyst resolves revenue (or alias sales) with trusted context first. After a
policy-change or schema-change event on the global bus, the next resolve is
not_usable with auditable drift fields — L1 metric execution alone still runs.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import identity, ledger
from recosearch.semantic_layers.context.events import MetadataChanged, get_event_bus
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import MetricQuery
from recosearch.semantic_layers.mcp_tools import handle_resolve_context
from recosearch.semantic_layers.pipeline import execute_context_query, execute_metric_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
JANUARY_REFERENCE = date(2026, 1, 31)
TERM_REVENUE = "term:novashop:revenue"
METRIC_ORDER_REVENUE = "metric:novashop:order_revenue"
REVENUE_TERM_ALIASES = ("revenue", "sales")

DRIFT_EVENTS = (
    pytest.param(
        "policy-change",
        TERM_REVENUE,
        "policy_changed",
        id="policy-change-on-term",
    ),
    pytest.param(
        "schema-change",
        METRIC_ORDER_REVENUE,
        "schema_changed",
        id="schema-change-on-metric",
    ),
)


@pytest.fixture(autouse=True)
def _clear_runtime_state():
    get_event_bus().clear()
    ledger.clear()
    yield
    get_event_bus().clear()
    ledger.clear()


def ensure_novashop_db() -> None:
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))


@pytest.fixture(scope="module")
def contract():
    ensure_novashop_db()
    return compile_contract()


def _ctx(answer) -> dict:
    return dict(answer.context_resolution or ())


def _trust_fields(term: str, contract) -> dict:
    payload = handle_resolve_context(
        {"term": term, "tenant": "novashop"},
        contract=contract,
        actor=identity.resolve(role="analyst"),
    )
    trust = payload["card"]["trust"]
    return {
        "status": trust["status"],
        "drift_status": trust["drift_status"],
        "expiry_reasons": list(trust["expiry_reasons"]),
    }


def analyst_january_query(contract, *, term: str):
    return execute_context_query(
        ContextQuery(term=term, tenant="novashop"),
        contract=contract,
        actor=identity.resolve(role="analyst"),
        scoped_question=f"What was Novashop {term} in January 2026?",
        reference_date=JANUARY_REFERENCE,
    )


class TestL2LiveDriftBusinessScenario:
    """Prove L2 trust envelope gates on live bus drift before L1 executes."""

    @pytest.mark.parametrize("term", REVENUE_TERM_ALIASES)
    def test_analyst_trusted_before_metadata_event(self, contract, term):
        answer = analyst_january_query(contract, term=term)
        ctx = _ctx(answer)
        trust = _trust_fields(term, contract)

        assert answer.decision == "answer"
        assert answer.result is not None
        assert ctx["term_id"] == TERM_REVENUE
        assert trust["status"] in ("trusted", "usable_with_caveats")
        assert trust["drift_status"] != "expired"
        assert "policy_changed" not in trust["expiry_reasons"]
        assert "schema_changed" not in trust["expiry_reasons"]
        assert ctx["trust_status"] in ("trusted", "usable_with_caveats")
        assert ctx["drift_status"] != "expired"
        assert ctx["evidence_tier"] == 3

    @pytest.mark.parametrize("term", REVENUE_TERM_ALIASES)
    @pytest.mark.parametrize("event_kind,event_ref,expected_reason", DRIFT_EVENTS)
    def test_live_drift_event_blocks_next_resolve(
        self, contract, term, event_kind, event_ref, expected_reason
    ):
        first = analyst_january_query(contract, term=term)
        assert first.decision == "answer"

        get_event_bus().publish(MetadataChanged(kind=event_kind, ref=event_ref))

        second = analyst_january_query(contract, term=term)
        ctx = _ctx(second)
        trust = _trust_fields(term, contract)

        assert second.decision == "refuse"
        assert second.reason_code == "CONTEXT_NOT_USABLE"
        assert second.result is None
        assert trust["status"] == "not_usable"
        assert trust["drift_status"] == "expired"
        assert expected_reason in trust["expiry_reasons"]
        assert ctx["trust_status"] == "not_usable"
        assert ctx["drift_status"] == "expired"

    @pytest.mark.parametrize("event_kind,event_ref,expected_reason", DRIFT_EVENTS)
    def test_l1_metric_still_runs_without_l2_drift_gate(
        self, contract, event_kind, event_ref, expected_reason
    ):
        """L1 alone cannot detect bus drift; metric query still answers after the event."""
        first = execute_metric_query(
            MetricQuery(
                term="order revenue",
                tenant="novashop",
                reference_date=JANUARY_REFERENCE,
            ),
            contract=contract,
        )
        assert first.decision == "answer"

        get_event_bus().publish(MetadataChanged(kind=event_kind, ref=event_ref))

        second = execute_metric_query(
            MetricQuery(
                term="order revenue",
                tenant="novashop",
                reference_date=JANUARY_REFERENCE,
            ),
            contract=contract,
        )
        assert second.decision == "answer"
        assert second.result is not None

        trust = _trust_fields("revenue", contract)
        assert trust["status"] == "not_usable"
        assert trust["drift_status"] == "expired"
        assert expected_reason in trust["expiry_reasons"]
