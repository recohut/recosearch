from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

CONSTRAINT_DECISIONS = frozenset({"valid", "clarify", "refuse"})
DEFAULT_REASONER_MODE = "none"
SUPPORTED_REASONER_MODES = frozenset({"none", "rdfs", "owlrl", "both"})


@dataclass(frozen=True, slots=True)
class TermMapping:
    term_id: str
    revenue_type: str
    claim_class: str


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    shape: str
    focus: str
    severity: str
    message: str
    source_iri: str
    why_not: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ConstraintDecision:
    decision: str
    reason: str
    reason_code: str = ""
    violations: tuple[ConstraintViolation, ...] = ()
    ontology_hash: str = ""
    reasoner_mode: str = DEFAULT_REASONER_MODE
    claim_hash: str = ""
    validation_report: str = ""
    drift_status: str = "current"
    drift_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "decision": self.decision,
            "reason": self.reason,
            "ontology_hash": self.ontology_hash,
            "reasoner_mode": self.reasoner_mode,
            "claim_hash": self.claim_hash,
            "drift_status": self.drift_status,
        }
        if self.reason_code:
            out["reason_code"] = self.reason_code
        if self.violations:
            out["violations"] = [
                {
                    "shape": v.shape,
                    "focus": v.focus,
                    "severity": v.severity,
                    "message": v.message,
                    "source_iri": v.source_iri,
                    "why_not": dict(v.why_not),
                }
                for v in self.violations
            ]
        if self.drift_reasons:
            out["drift_reasons"] = list(self.drift_reasons)
        if self.validation_report:
            out["validation_report"] = self.validation_report
        return out

    def to_tuple(self) -> tuple[tuple[str, Any], ...]:
        items: list[tuple[str, Any]] = [
            ("decision", self.decision),
            ("reason", self.reason),
            ("ontology_hash", self.ontology_hash),
            ("reasoner_mode", self.reasoner_mode),
            ("claim_hash", self.claim_hash),
            ("drift_status", self.drift_status),
        ]
        if self.reason_code:
            items.append(("reason_code", self.reason_code))
        if self.violations:
            items.append(
                (
                    "violations",
                    [
                        {
                            "shape": v.shape,
                            "focus": v.focus,
                            "severity": v.severity,
                            "message": v.message,
                            "source_iri": v.source_iri,
                            "why_not": dict(v.why_not),
                        }
                        for v in self.violations
                    ],
                )
            )
        if self.drift_reasons:
            items.append(("drift_reasons", list(self.drift_reasons)))
        return tuple(items)


@dataclass(frozen=True, slots=True)
class GoldenConstraintCase:
    term_id: str
    tenant: str
    actor_role: str
    claim_qualifiers: tuple[tuple[str, str], ...]
    expected_decision: str
    expected_reason_code: str = ""


@dataclass(frozen=True, slots=True)
class OntologyCertification:
    ontology_hash: str
    reasoner_mode: str
    golden_cases: tuple[GoldenConstraintCase, ...]
    certified: bool | None = None
    golden_passed: bool | None = None


@dataclass(frozen=True, slots=True)
class OntologyKernel:
    namespace: str
    ontology_ttl: str
    shapes_ttl: str
    mappings: Mapping[str, TermMapping]
    ontology_hash: str
    reasoner_mode: str = DEFAULT_REASONER_MODE
    certifications: Mapping[str, OntologyCertification] = field(
        default_factory=lambda: MappingProxyType({})
    )
    persisted_certification_results: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.mappings, MappingProxyType):
            object.__setattr__(self, "mappings", MappingProxyType(dict(self.mappings)))
        if not isinstance(self.certifications, MappingProxyType):
            object.__setattr__(
                self, "certifications", MappingProxyType(dict(self.certifications))
            )
        if not isinstance(self.persisted_certification_results, MappingProxyType):
            object.__setattr__(
                self,
                "persisted_certification_results",
                MappingProxyType(dict(self.persisted_certification_results)),
            )
