from __future__ import annotations

import pytest

from recosearch.semantic_layers.envelope import Answer, DECISION_REFUSE, DECISION_REVIEW
from recosearch.semantic_layers.evidence.gate import apply_composite_gate, check_comparable_consistency
from recosearch.semantic_layers.evidence.types import (
    ClaimSet,
    ComparableGroupRule,
    ConsistencyReport,
    EvidenceGateKernel,
    EvidenceTierBar,
    ReviewTrigger,
    Subclaim,
    SubclaimResult,
)


def _answer(
    *,
    decision: str = "answer",
    evidence_tier: str = "local-equivalent",
    term_id: str = "term:novashop:revenue",
    grain: str = "month",
    period: str = "2026-01",
    reason_code: str = "",
    reason: str = "",
) -> Answer:
    return Answer(
        decision=decision,
        evidence_tier=evidence_tier,
        context_resolution=(("term_id", term_id),),
        metric_resolution=(("grain", grain), ("time_period", period)),
        reason_code=reason_code,
        reason=reason,
    )


def _result(
    *,
    term: str = "revenue",
    comparable_group: str = "january_close_totals",
    answer: Answer | None = None,
    grain: str = "month",
    period: str = "2026-01",
) -> SubclaimResult:
    return SubclaimResult(
        subclaim=Subclaim(
            term=term,
            comparable_group=comparable_group,
            reference_date="2026-01-31",
            time_period=period,
        ),
        answer=answer or _answer(),
        grain=grain,
        period=period,
    )


def _kernel(**overrides) -> EvidenceGateKernel:
    defaults = dict(
        tier_bars={
            "board_pack": EvidenceTierBar(
                pattern="board_pack",
                min_tier_label="local-equivalent",
                min_tier_rank=3,
            )
        },
        review_triggers={
            "deferred": ReviewTrigger(
                pattern="term:novashop:deferred_revenue",
                required_role="controller",
            )
        },
        comparable_groups={
            "january_close_totals": ComparableGroupRule(
                group_id="january_close_totals",
                description="board pack foot group",
            )
        },
        default_min_tier_label="fixture-backed",
        default_min_tier_rank=2,
    )
    defaults.update(overrides)
    return EvidenceGateKernel(**defaults)


def _claim_set(**kwargs) -> ClaimSet:
    defaults = dict(
        subclaims=(_result().subclaim,),
        pack_label="board_pack",
    )
    defaults.update(kwargs)
    return ClaimSet(**defaults)


def test_apply_composite_gate_unknown_min_tier_label_raises():
    results = (_result(),)
    with pytest.raises(ValueError, match="unknown evidence tier label"):
        apply_composite_gate(
            _claim_set(min_tier_label="not-a-real-tier"),
            results,
            kernel=_kernel(review_triggers={}),
            contract_hash="contract-abc",
        )


def test_apply_composite_gate_refuses_with_all_subclaim_reasons():
    results = (
        _result(
            answer=_answer(
                decision=DECISION_REFUSE,
                reason_code="CONSTRAINT_VIOLATION",
            )
        ),
        _result(
            term="deferred revenue",
            answer=_answer(
                decision=DECISION_REFUSE,
                term_id="term:novashop:deferred_revenue",
                reason_code="POLICY",
            ),
        ),
    )
    pack = apply_composite_gate(
        _claim_set(subclaims=(results[0].subclaim, results[1].subclaim)),
        results=results,
        kernel=_kernel(review_triggers={}),
        contract_hash="contract-abc",
    )
    assert pack.decision == DECISION_REFUSE
    assert len(pack.composite_reasons) == 2


def test_apply_composite_gate_review_on_unexpected_subclaim_decision():
    results = (
        _result(answer=_answer(decision=DECISION_REVIEW, reason_code="EVIDENCE_REVIEW_REQUIRED")),
    )
    pack = apply_composite_gate(
        _claim_set(subclaims=(results[0].subclaim,)),
        results=results,
        kernel=_kernel(review_triggers={}),
        contract_hash="contract-abc",
    )
    assert pack.decision == DECISION_REVIEW
    assert any("subclaim_unexpected_decision:" in r for r in pack.composite_reasons)


def test_apply_composite_gate_refuses_when_subclaim_refuses():
    results = (
        _result(
            answer=_answer(
                decision=DECISION_REFUSE,
                reason_code="CONSTRAINT_VIOLATION",
                reason="constraint violated",
            )
        ),
    )
    pack = apply_composite_gate(
        _claim_set(),
        results,
        kernel=_kernel(),
        contract_hash="contract-abc",
    )
    assert pack.decision == DECISION_REFUSE
    assert any(r.startswith("subclaim_refuse:") for r in pack.composite_reasons)
    assert pack.review_ticket is None


def test_apply_composite_gate_review_required_on_review_trigger():
    results = (
        _result(
            term="deferred revenue",
            answer=_answer(term_id="term:novashop:deferred_revenue"),
        ),
    )
    pack = apply_composite_gate(
        _claim_set(subclaims=(results[0].subclaim,)),
        results=results,
        kernel=_kernel(),
        contract_hash="contract-abc",
    )
    assert pack.decision == DECISION_REVIEW
    assert any("review_trigger:" in r for r in pack.composite_reasons)
    assert pack.review_ticket is not None
    assert pack.review_ticket.required_role == "controller"


def test_apply_composite_gate_review_on_comparable_group_period_mismatch():
    results = (
        _result(period="2026-01"),
        _result(
            term="revenue",
            answer=_answer(),
            period="2026-02",
        ),
    )
    pack = apply_composite_gate(
        _claim_set(subclaims=(results[0].subclaim, results[1].subclaim)),
        results=results,
        kernel=_kernel(review_triggers={}),
        contract_hash="contract-abc",
    )
    assert pack.decision == DECISION_REVIEW
    assert not pack.consistency_report.ok
    assert any("period mismatch" in r for r in pack.composite_reasons)
    assert pack.review_ticket is not None


def test_apply_composite_gate_answer_when_all_pass():
    results = (_result(),)
    pack = apply_composite_gate(
        _claim_set(),
        results,
        kernel=_kernel(review_triggers={}),
        contract_hash="contract-abc",
    )
    assert pack.decision == "answer"
    assert pack.composite_reasons == ()
    assert pack.review_ticket is None
    assert pack.consistency_report.ok


def test_check_comparable_consistency_grain_mismatch():
    results = (
        _result(grain="month"),
        _result(grain="day", period="2026-01"),
    )
    report = check_comparable_consistency(results, kernel=_kernel())
    assert not report.ok
    assert any("grain mismatch" in r for r in report.reasons)


def test_check_comparable_consistency_unknown_group():
    kernel = _kernel(comparable_groups={})
    results = (_result(comparable_group="unknown_group"),)
    report = check_comparable_consistency(results, kernel=kernel)
    assert not report.ok
    assert any("unknown_comparable_group:unknown_group" in r for r in report.reasons)


def test_check_comparable_consistency_incomplete_when_member_refused():
    results = (
        _result(),
        _result(
            answer=_answer(decision=DECISION_REFUSE, reason_code="CONSTRAINT_VIOLATION"),
        ),
    )
    report = check_comparable_consistency(results, kernel=_kernel())
    assert not report.ok
    assert any("comparable_group_incomplete:january_close_totals" in r for r in report.reasons)


def test_check_comparable_consistency_ok_for_footed_group():
    results = (
        _result(period="2026-01"),
        _result(
            term="net revenue",
            answer=_answer(term_id="term:novashop:net_revenue"),
            period="2026-01",
        ),
    )
    report = check_comparable_consistency(results, kernel=_kernel())
    assert report.ok


def test_apply_composite_gate_review_on_unknown_comparable_group():
    kernel = _kernel(comparable_groups={}, review_triggers={})
    results = (_result(comparable_group="unknown_group"),)
    pack = apply_composite_gate(
        _claim_set(subclaims=(results[0].subclaim,)),
        results=results,
        kernel=kernel,
        contract_hash="contract-abc",
    )
    assert pack.decision == DECISION_REVIEW
    assert any("unknown_comparable_group:unknown_group" in r for r in pack.composite_reasons)


def test_check_comparable_consistency_allows_answer_with_caveats():
    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue", comparable_group="january_close_totals"),
            answer=_answer(decision="answer_with_caveats"),
            grain="month",
            period="2026-01",
        ),
    )
    report = check_comparable_consistency(results, kernel=_kernel())
    assert report.ok


def test_check_comparable_consistency_ok_when_no_group():
    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue"),
            answer=_answer(),
            grain="month",
            period="2026-01",
        ),
    )
    report = check_comparable_consistency(results, kernel=_kernel())
    assert report.ok
