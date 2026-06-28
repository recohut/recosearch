from __future__ import annotations

from recosearch.semantic_layers.mcp_tools import handle_compose_evidence_pack


def test_handle_compose_evidence_pack(compile_contract):
    result = handle_compose_evidence_pack(
        {
            "pack_label": "board_pack",
            "subclaims": [
                {
                    "term": "revenue",
                    "tenant": "novashop",
                    "actor_role": "analyst",
                    "reference_date": "2026-01-31",
                    "comparable_group": "january_close_totals",
                    "time_period": "2026-01",
                }
            ],
        },
        contract=compile_contract,
    )
    assert result["pack"]["decision"] == "answer"
    assert result["answer"]["decision"] == "answer"
    assert result["answer"]["evidence_pack"]["pack_id"] == result["pack"]["pack_id"]


def test_handle_compose_evidence_pack_deferred_triggers_review(compile_contract):
    result = handle_compose_evidence_pack(
        {
            "pack_label": "board_pack",
            "subclaims": [
                {
                    "term": "revenue",
                    "tenant": "novashop",
                    "actor_role": "analyst",
                    "reference_date": "2026-01-31",
                },
                {
                    "term": "deferred revenue",
                    "tenant": "novashop",
                    "actor_role": "analyst",
                    "reference_date": "2026-01-31",
                },
            ],
        },
        contract=compile_contract,
    )
    assert result["pack"]["decision"] == "review_required"
    assert result["pack"]["review_ticket"]
