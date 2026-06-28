from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

TRUST_STATUSES = frozenset({"trusted", "usable_with_caveats", "not_usable"})
DRIFT_STATUSES = frozenset({"current", "at_risk", "expired"})
CONTEXT_DECISIONS = frozenset({"resolved", "clarify", "unknown"})

EVIDENCE_TIER_LABELS: dict[int, str] = {
    1: "contract-only",
    2: "fixture-backed",
    3: "local-equivalent",
}


@dataclass(frozen=True, slots=True)
class TermBinding:
    term_id: str
    display_name: str
    definition: str
    aliases: tuple[str, ...]
    collection_id: str
    primary_refs: tuple[str, ...]
    definition_hash: str = ""


@dataclass(frozen=True, slots=True)
class GoldenContextQuestion:
    term: str
    tenant: str
    actor_role: str
    expected_decision: str
    expected_trust_status: str
    expected_evidence_tier: int
    expected: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ContextCertification:
    term_id: str
    definition_hash: str
    policy_hash: str
    golden_questions: tuple[GoldenContextQuestion, ...]
    certified: bool | None = None
    golden_passed: bool | None = None
    evidence_tier: int | None = None
    ares_confidence_interval: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class ClientGuidance:
    term_id: str
    when_to_use: str
    when_to_clarify: str
    when_to_refuse: str


@dataclass(frozen=True, slots=True)
class RelationshipEdge:
    from_id: str
    to_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class ContextQuery:
    term: str
    tenant: str = "default"
    industry: str | None = None
    actor_role: str = ""
    claim_qualifiers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ClaimScope:
    sources: tuple[str, ...]
    roles: tuple[str, ...]
    metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProvenanceFacets:
    schema: tuple[dict[str, Any], ...]
    column_lineage: tuple[tuple[str, str, str], ...]
    ownership: tuple[str, ...]
    data_source: tuple[dict[str, str], ...]
    semantic_metric: dict[str, Any] | None
    policy_decision: dict[str, Any] | None
    certification_tier: dict[str, Any] | None
    why_provenance: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class TrustSignal:
    signal_id: str
    status: str
    evidence_tier: int
    evidence_label: str
    claim_scope: ClaimScope
    drift_status: str
    expiry_reasons: tuple[str, ...]
    no_overclaim_labels: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextCard:
    card_id: str
    term_id: str
    display_name: str
    definition: str
    primary_refs: tuple[str, ...]
    related_refs: tuple[str, ...]
    technical: dict[str, Any]
    semantic: dict[str, Any]
    operational: dict[str, Any]
    relationships: dict[str, Any]
    trust: TrustSignal
    client_guidance: dict[str, Any]
    caveats: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "term_id": self.term_id,
            "display_name": self.display_name,
            "definition": self.definition,
            "primary_refs": list(self.primary_refs),
            "related_refs": list(self.related_refs),
            "technical": self.technical,
            "semantic": self.semantic,
            "operational": self.operational,
            "relationships": self.relationships,
            "trust": {
                "signal_id": self.trust.signal_id,
                "status": self.trust.status,
                "evidence_tier": self.trust.evidence_tier,
                "evidence_label": self.trust.evidence_label,
                "claim_scope": {
                    "sources": list(self.trust.claim_scope.sources),
                    "roles": list(self.trust.claim_scope.roles),
                    "metrics": list(self.trust.claim_scope.metrics),
                },
                "drift_status": self.trust.drift_status,
                "expiry_reasons": list(self.trust.expiry_reasons),
                "no_overclaim_labels": list(self.trust.no_overclaim_labels),
                "reasons": list(self.trust.reasons),
            },
            "client_guidance": self.client_guidance,
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True, slots=True)
class ContextResolution:
    decision: str
    term_id: str
    reason: str
    binding: TermBinding | None = None
    candidates: tuple[tuple[str, str], ...] = ()
    card: ContextCard | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision": self.decision,
            "term_id": self.term_id,
            "reason": self.reason,
        }
        if self.candidates:
            out["candidates"] = [{"term_id": tid, "display_name": name} for tid, name in self.candidates]
        if self.card is not None:
            out["card"] = self.card.to_dict()
        return out


@dataclass(frozen=True, slots=True)
class ContextKernel:
    terms: Mapping[str, TermBinding]
    guidance: Mapping[str, ClientGuidance]
    relationships: tuple[RelationshipEdge, ...]
    alias_index: Mapping[str, tuple[str, ...]]
    certifications: Mapping[str, ContextCertification] = field(
        default_factory=lambda: MappingProxyType({})
    )
    persisted_certification_results: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "terms", MappingProxyType(dict(self.terms)))
        object.__setattr__(self, "guidance", MappingProxyType(dict(self.guidance)))
        object.__setattr__(self, "alias_index", MappingProxyType(dict(self.alias_index)))
        if not isinstance(self.certifications, MappingProxyType):
            object.__setattr__(self, "certifications", MappingProxyType(dict(self.certifications)))
        if not isinstance(self.persisted_certification_results, MappingProxyType):
            object.__setattr__(
                self,
                "persisted_certification_results",
                MappingProxyType(dict(self.persisted_certification_results)),
            )
