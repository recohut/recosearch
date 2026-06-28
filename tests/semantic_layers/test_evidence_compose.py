from __future__ import annotations

from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim
from recosearch.semantic_layers import ledger


def test_compose_evidence_pack_revenue_only(compile_contract):
    claim_set = ClaimSet(
        subclaims=(
            Subclaim(
                term="revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date="2026-01-31",
                comparable_group="january_close_totals",
                time_period="2026-01",
            ),
        ),
        pack_label="board_pack",
    )
    pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)

    assert pack.decision == "answer"
    assert answer.decision == "answer"
    assert answer.evidence_pack
    pack_dict = dict(answer.evidence_pack)
    assert pack_dict["pack_id"] == pack.pack_id
    assert pack_dict["decision"] == "answer"

    pack_events = [e for e in ledger.events() if e["artifact_type"] == "evidence_pack"]
    assert pack_events
    assert pack_events[-1]["payload"]["pack_id"] == pack.pack_id


def test_compose_evidence_pack_records_replay_refs(compile_contract):
    claim_set = ClaimSet(
        subclaims=(
            Subclaim(
                term="revenue",
                tenant="novashop",
                actor_role="analyst",
                reference_date="2026-01-31",
                comparable_group="january_close_totals",
                time_period="2026-01",
            ),
        ),
        pack_label="board_pack",
    )
    pack, answer = compose_evidence_pack(claim_set, contract=compile_contract)
    assert pack.replay_refs
    assert any(ref.startswith("art-") for ref in pack.replay_refs)
    assert answer.replay_refs
