from __future__ import annotations

from pathlib import Path

import pytest

from recosearch.semantic_layers.envelope import Answer, DECISION_REFUSE, DECISION_REVIEW
from recosearch.semantic_layers.evidence.certify import (
    validate_evidence_registry,
    verify_evidence_certification_results,
)
from recosearch.semantic_layers.evidence.compose import execute_subclaim, pack_to_answer
from recosearch.semantic_layers.evidence.gate import apply_composite_gate
from recosearch.semantic_layers.evidence.hash import compute_pack_id, compute_ticket_id
from recosearch.semantic_layers.evidence.review import create_review_ticket
from recosearch.semantic_layers.evidence.schema import EvidenceSchemaError
from recosearch.semantic_layers.evidence.types import (
    ClaimSet,
    ComparableGroupRule,
    ConsistencyReport,
    EvidenceGateKernel,
    EvidencePack,
    EvidenceTierBar,
    ReviewTicket,
    Subclaim,
    SubclaimResult,
)
import recosearch.semantic_layers.evidence.gate as gate_module

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


def _answer(**kwargs) -> Answer:
    defaults = dict(
        decision="answer",
        evidence_tier="local-equivalent",
        context_resolution=(("term_id", "term:novashop:revenue"),),
        metric_resolution=(("grain", "month"), ("time_period", "2026-01")),
    )
    defaults.update(kwargs)
    return Answer(**defaults)


def _kernel(**overrides) -> EvidenceGateKernel:
    defaults = dict(
        tier_bars={
            "board_pack": EvidenceTierBar(
                pattern="board_pack",
                min_tier_label="local-equivalent",
                min_tier_rank=3,
            )
        },
        review_triggers={},
        comparable_groups={
            "january_close_totals": ComparableGroupRule(
                group_id="january_close_totals",
                description="",
            )
        },
        default_min_tier_label="local-equivalent",
        default_min_tier_rank=3,
    )
    defaults.update(overrides)
    return EvidenceGateKernel(**defaults)


def test_apply_composite_gate_clarify_path_triggers_review():
    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue"),
            answer=_answer(decision="clarify", reason="need period"),
            grain="month",
            period="2026-01",
        ),
    )
    pack = apply_composite_gate(
        ClaimSet(subclaims=(results[0].subclaim,), pack_label="board_pack"),
        results,
        kernel=_kernel(),
        contract_hash="hash-v1",
    )
    assert pack.decision == "review_required"
    assert any("subclaim_clarify:" in r for r in pack.composite_reasons)
    assert pack.review_ticket is not None


def test_apply_composite_gate_tier_below_bar_triggers_review():
    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue"),
            answer=_answer(evidence_tier="fixture-backed"),
            grain="month",
            period="2026-01",
        ),
    )
    pack = apply_composite_gate(
        ClaimSet(subclaims=(results[0].subclaim,), pack_label="board_pack"),
        results,
        kernel=_kernel(),
        contract_hash="hash-v1",
    )
    assert pack.decision == "review_required"
    assert any("evidence_tier_below_bar" in r for r in pack.composite_reasons)


def test_apply_composite_gate_uses_claim_min_tier_label():
    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue"),
            answer=_answer(evidence_tier="fixture-backed"),
            grain="month",
            period="2026-01",
        ),
    )
    pack = apply_composite_gate(
        ClaimSet(
            subclaims=(results[0].subclaim,),
            pack_label="other_pack",
            min_tier_label="fixture-backed",
        ),
        results,
        kernel=_kernel(),
        contract_hash="hash-v1",
    )
    assert pack.decision == "answer"


def test_verify_evidence_certification_results_invalid_root(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_certification_results.yaml").write_text("not-a-mapping\n", encoding="utf-8")
    failures = verify_evidence_certification_results(evidence_dir)
    assert failures == ["certification results must be a mapping"]


def test_verify_evidence_certification_results_invalid_entry(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_certification_results.yaml").write_text(
        "certification_results:\n  - not-a-mapping\n",
        encoding="utf-8",
    )
    failures = verify_evidence_certification_results(evidence_dir)
    assert "invalid certification entry" in failures


def test_evidence_schema_error_repr():
    err = EvidenceSchemaError("field", "bad value")
    assert "field" in str(err)
    assert err.path == "field"
    assert err.reason == "bad value"


def test_compute_pack_id_deterministic():
    payload = {"pack_label": "board_pack", "subclaims": [], "min_tier_label": ""}
    a = compute_pack_id(claim_set_payload=payload, contract_hash="hash-v1")
    b = compute_pack_id(claim_set_payload=payload, contract_hash="hash-v1")
    c = compute_pack_id(claim_set_payload=payload, contract_hash="hash-v2")
    assert a == b
    assert a != c
    assert a.startswith("pack-")


def test_compute_ticket_id_deterministic():
    triggers = ("review_trigger:term:novashop:deferred_revenue",)
    ticket_id = compute_ticket_id(pack_id="pack-abc", triggers=triggers)
    assert ticket_id.startswith("ticket-")


def test_create_review_ticket():
    ticket = create_review_ticket(
        pack_id="pack-abc",
        triggers=("review_trigger:term:novashop:deferred_revenue",),
        required_role="controller",
    )
    assert ticket.ticket_id.startswith("ticket-")
    assert ticket.pack_id == "pack-abc"
    assert ticket.status == "pending"
    assert ticket.to_dict()["required_role"] == "controller"


def test_evidence_pack_to_dict_and_tuple_with_review_ticket():
    ticket = create_review_ticket(
        pack_id="pack-abc",
        triggers=("trigger-a",),
    )
    pack = EvidencePack(
        pack_id="pack-abc",
        decision="review_required",
        contract_hash="hash-v1",
        subclaim_results=(),
        composite_reasons=("trigger-a",),
        evidence_tier_min="local-equivalent",
        consistency_report=ConsistencyReport(ok=True),
        review_ticket=ticket,
        replay_refs=("art-1",),
        expired=False,
    )
    payload = pack.to_dict()
    assert payload["review_ticket"]["ticket_id"] == ticket.ticket_id
    assert dict(pack.to_tuple())["review_ticket_id"] == ticket.ticket_id


def test_subclaim_result_to_dict():
    result = SubclaimResult(
        subclaim=Subclaim(term="revenue", comparable_group="january_close_totals"),
        answer=_answer(),
        grain="month",
        period="2026-01",
    )
    payload = result.to_dict()
    assert payload["term"] == "revenue"
    assert payload["grain"] == "month"
    assert payload["answer"]["decision"] == "answer"


def test_consistency_report_to_dict():
    report = ConsistencyReport(ok=False, reasons=("mismatch",))
    assert report.to_dict() == {"ok": False, "reasons": ["mismatch"]}


def test_claim_set_to_dict():
    claim_set = ClaimSet(
        subclaims=(Subclaim(term="revenue", industry="retail"),),
        pack_label="board_pack",
        min_tier_label="local-equivalent",
    )
    payload = claim_set.to_dict()
    assert payload["pack_label"] == "board_pack"
    assert payload["subclaims"][0]["industry"] == "retail"


def test_apply_composite_gate_empty_results_uses_contract_only_tier():
    pack = apply_composite_gate(
        ClaimSet(subclaims=(), pack_label="other_pack"),
        (),
        kernel=_kernel(
            tier_bars={},
            default_min_tier_label="contract-only",
            default_min_tier_rank=1,
        ),
        contract_hash="hash-v1",
    )
    assert pack.evidence_tier_min == "contract-only"
    assert pack.decision == "answer"


def test_apply_composite_gate_uses_default_tier_when_pack_label_unmatched():
    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue"),
            answer=_answer(evidence_tier="fixture-backed"),
            grain="month",
            period="2026-01",
        ),
    )
    pack = apply_composite_gate(
        ClaimSet(subclaims=(results[0].subclaim,), pack_label="unmatched_pack"),
        results,
        kernel=_kernel(tier_bars={}, default_min_tier_label="fixture-backed", default_min_tier_rank=2),
        contract_hash="hash-v1",
    )
    assert pack.decision == "answer"


def test_min_tier_label_fallback_when_rank_unmapped(monkeypatch):
    monkeypatch.setattr(gate_module, "TIER_LABEL_TO_RANK", {})
    result = SubclaimResult(
        subclaim=Subclaim(term="revenue"),
        answer=_answer(evidence_tier="custom-tier"),
    )
    assert gate_module._min_tier_label((result,)) == "contract-only"


def test_execute_subclaim_without_reference_date(compile_contract):
    result = execute_subclaim(
        Subclaim(
            term="revenue",
            tenant="novashop",
            actor_role="analyst",
            reference_date="",
        ),
        contract=compile_contract,
    )
    assert result.subclaim.term == "revenue"
    assert result.answer.decision in {"answer", "clarify"}


def test_pack_to_answer_review_and_refuse():
    result = SubclaimResult(
        subclaim=Subclaim(term="revenue"),
        answer=_answer(),
        grain="month",
        period="2026-01",
    )
    review_pack = EvidencePack(
        pack_id="pack-review",
        decision=DECISION_REVIEW,
        contract_hash="hash-v1",
        subclaim_results=(result,),
        composite_reasons=("needs review",),
        evidence_tier_min="local-equivalent",
        consistency_report=ConsistencyReport(ok=True),
    )
    review_answer = pack_to_answer(
        review_pack,
        claim_set=ClaimSet(subclaims=(result.subclaim,)),
        contract_hash="hash-v1",
    )
    assert review_answer.reason_code == "EVIDENCE_REVIEW_REQUIRED"

    refuse_pack = EvidencePack(
        pack_id="pack-refuse",
        decision=DECISION_REFUSE,
        contract_hash="hash-v1",
        subclaim_results=(result,),
        composite_reasons=("subclaim_refuse:term:novashop:revenue",),
        evidence_tier_min="local-equivalent",
        consistency_report=ConsistencyReport(ok=True),
    )
    refuse_answer = pack_to_answer(
        refuse_pack,
        claim_set=ClaimSet(subclaims=(result.subclaim,)),
        contract_hash="hash-v1",
    )
    assert refuse_answer.reason_code == "EVIDENCE_PACK_REFUSED"


def test_validate_evidence_registry_schema_failure(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_gates.yaml").write_text("evidence_tier_bars:\n  - pattern: x\n", encoding="utf-8")
    (evidence_dir / "_certification.yaml").write_text("certifications: []\n", encoding="utf-8")
    failures = validate_evidence_registry(evidence_dir)
    assert failures


def test_load_evidence_certifications_and_subclaim_fields(tmp_path):
    from recosearch.semantic_layers.evidence.certify import _subclaim_from_dict, load_evidence_certifications

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_certification.yaml").write_text(
        """
certifications:
  - case_id: sample
    expected_decision: answer
    subclaims:
      - term: revenue
        tenant: novashop
        actor_role: analyst
        claim_qualifiers:
          - [period, "2026-01"]
        comparable_group: january_close_totals
        reference_date: "2026-01-31"
        time_period: "2026-01"
        scoped_question: revenue?
""",
        encoding="utf-8",
    )
    cases = load_evidence_certifications(evidence_dir)
    assert cases[0]["case_id"] == "sample"
    subclaim = _subclaim_from_dict(cases[0]["subclaims"][0])
    assert subclaim.claim_qualifiers == (("period", "2026-01"),)
    assert subclaim.comparable_group == "january_close_totals"


def test_load_evidence_certifications_missing_file(tmp_path):
    from recosearch.semantic_layers.evidence.certify import load_evidence_certifications

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        load_evidence_certifications(evidence_dir)


def test_load_evidence_certifications_requires_mapping(tmp_path):
    from recosearch.semantic_layers.evidence.certify import load_evidence_certifications

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "_certification.yaml").write_text("- bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_evidence_certifications(evidence_dir)


def test_check_comparable_consistency_incomplete_when_missing_grain_or_period():
    from recosearch.semantic_layers.evidence.gate import check_comparable_consistency

    results = (
        SubclaimResult(
            subclaim=Subclaim(term="revenue", comparable_group="january_close_totals"),
            answer=_answer(),
            grain="",
            period="2026-01",
        ),
    )
    report = check_comparable_consistency(results, kernel=_kernel())
    assert not report.ok
    assert any("comparable_group_incomplete:january_close_totals" in r for r in report.reasons)


def test_validate_evidence_certifications_rejects_unknown_expected_decision():
    from recosearch.semantic_layers.evidence.schema import validate_evidence_certifications

    with pytest.raises(EvidenceSchemaError, match="unknown pack decision"):
        validate_evidence_certifications(
            {
                "certifications": [
                    {
                        "case_id": "bad",
                        "expected_decision": "maybe",
                        "subclaims": [{"term": "revenue"}],
                    }
                ]
            }
        )
