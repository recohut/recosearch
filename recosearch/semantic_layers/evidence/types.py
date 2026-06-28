from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from recosearch.semantic_layers.envelope import Answer

EVIDENCE_PACK_DECISIONS = frozenset({"answer", "review_required", "refuse", "clarify"})
TIER_LABEL_TO_RANK: dict[str, int] = {
    # Tiers 1-3 are assigned by the current certify implementation.
    # Tiers 4-7 are declared as valid gate-bar targets so operators can
    # configure evidence_tier_bars requiring live-data tiers, but certify
    # does not yet assign them — they are aspirational / config-only labels.
    "contract-only": 1,
    "fixture-backed": 2,
    "local-equivalent": 3,
    "local-live": 4,
    "cloud-dev-live": 5,
    "customer-pilot-live": 6,
    "production-ready": 7,
}


@dataclass(frozen=True, slots=True)
class Subclaim:
    term: str
    tenant: str = "novashop"
    industry: str | None = None
    actor_role: str = "analyst"
    claim_qualifiers: tuple[tuple[str, str], ...] = ()
    comparable_group: str = ""
    reference_date: str = ""
    time_period: str = ""
    scoped_question: str = ""


@dataclass(frozen=True, slots=True)
class SubclaimResult:
    subclaim: Subclaim
    answer: Answer
    grain: str = ""
    period: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.subclaim.term,
            "comparable_group": self.subclaim.comparable_group,
            "grain": self.grain,
            "period": self.period,
            "answer": self.answer.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReviewTicket:
    ticket_id: str
    pack_id: str
    triggers: tuple[str, ...]
    required_role: str
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "pack_id": self.pack_id,
            "triggers": list(self.triggers),
            "required_role": self.required_role,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    ok: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class EvidenceTierBar:
    pattern: str
    min_tier_label: str
    min_tier_rank: int


@dataclass(frozen=True, slots=True)
class ReviewTrigger:
    pattern: str
    required_role: str = "controller"


@dataclass(frozen=True, slots=True)
class ComparableGroupRule:
    group_id: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceGateKernel:
    tier_bars: Mapping[str, EvidenceTierBar]
    review_triggers: Mapping[str, ReviewTrigger]
    comparable_groups: Mapping[str, ComparableGroupRule]
    default_min_tier_label: str = "fixture-backed"
    default_min_tier_rank: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "tier_bars", MappingProxyType(dict(self.tier_bars)))
        object.__setattr__(self, "review_triggers", MappingProxyType(dict(self.review_triggers)))
        object.__setattr__(self, "comparable_groups", MappingProxyType(dict(self.comparable_groups)))


@dataclass(frozen=True, slots=True)
class ClaimSet:
    subclaims: tuple[Subclaim, ...]
    pack_label: str = "board_pack"
    min_tier_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_label": self.pack_label,
            "min_tier_label": self.min_tier_label,
            "subclaims": [
                {
                    "term": s.term,
                    "tenant": s.tenant,
                    "industry": s.industry,
                    "actor_role": s.actor_role,
                    "claim_qualifiers": [list(p) for p in s.claim_qualifiers],
                    "comparable_group": s.comparable_group,
                    "reference_date": s.reference_date,
                    "time_period": s.time_period,
                    "scoped_question": s.scoped_question,
                }
                for s in self.subclaims
            ],
        }


@dataclass(frozen=True, slots=True)
class EvidencePack:
    pack_id: str
    decision: str
    contract_hash: str
    subclaim_results: tuple[SubclaimResult, ...]
    composite_reasons: tuple[str, ...]
    evidence_tier_min: str
    consistency_report: ConsistencyReport
    review_ticket: ReviewTicket | None = None
    replay_refs: tuple[str, ...] = ()
    expired: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "pack_id": self.pack_id,
            "decision": self.decision,
            "contract_hash": self.contract_hash,
            "composite_reasons": list(self.composite_reasons),
            "evidence_tier_min": self.evidence_tier_min,
            "consistency_report": self.consistency_report.to_dict(),
            "replay_refs": list(self.replay_refs),
            "expired": self.expired,
            "subclaim_results": [r.to_dict() for r in self.subclaim_results],
        }
        if self.review_ticket is not None:
            out["review_ticket"] = self.review_ticket.to_dict()
        return out

    def to_tuple(self) -> tuple[tuple[str, Any], ...]:
        items: list[tuple[str, Any]] = [
            ("pack_id", self.pack_id),
            ("decision", self.decision),
            ("contract_hash", self.contract_hash),
            ("evidence_tier_min", self.evidence_tier_min),
            ("consistency_ok", self.consistency_report.ok),
            ("composite_reasons", list(self.composite_reasons)),
            ("expired", self.expired),
        ]
        if self.review_ticket is not None:
            items.append(("review_ticket_id", self.review_ticket.ticket_id))
        return tuple(items)
