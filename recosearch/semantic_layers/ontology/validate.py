from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

from pyshacl import validate as pyshacl_validate
from rdflib import Graph
from rdflib.namespace import SH

from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.ontology.claim import build_claim_graph, claim_payload_for_cache
from recosearch.semantic_layers.ontology.types import (
    CONSTRAINT_DECISIONS,
    ConstraintDecision,
    ConstraintViolation,
    OntologyKernel,
)

_CACHE_LOCK = threading.Lock()
_VALIDATION_CACHE: dict[str, _CachedBase] = {}


@dataclass(frozen=True, slots=True)
class _CachedBase:
    decision: str
    reason: str
    reason_code: str
    violations: tuple[ConstraintViolation, ...]
    claim_hash: str
    validation_report: str


def clear_validation_cache() -> None:
    with _CACHE_LOCK:
        _VALIDATION_CACHE.clear()


def _cache_key(payload: dict[str, Any]) -> str:
    return "|".join(f"{k}={payload[k]}" for k in sorted(payload))


def _parse_graphs(kernel: OntologyKernel) -> tuple[Graph, Graph]:
    ontology_graph = Graph()
    ontology_graph.parse(data=kernel.ontology_ttl, format="turtle")
    shapes_graph = Graph()
    shapes_graph.parse(data=kernel.shapes_ttl, format="turtle")
    return ontology_graph, shapes_graph


def _assess_drift(kernel: OntologyKernel) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    for stored in kernel.persisted_certification_results.values():
        stored_hash = str(stored.get("ontology_hash", ""))
        stored_mode = str(stored.get("reasoner_mode", kernel.reasoner_mode))
        if stored_hash and stored_hash != kernel.ontology_hash:
            reasons.append("ontology_changed")
        if stored_mode != kernel.reasoner_mode:
            reasons.append("reasoner_mode_changed")
    if reasons:
        return "at_risk", tuple(sorted(set(reasons)))
    return "current", ()


def _parse_violations(results_graph: Graph, *, claim_hash: str) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []
    for result in results_graph.subjects(predicate=SH.resultSeverity):
        severity = str(results_graph.value(result, SH.resultSeverity) or "")
        message = str(results_graph.value(result, SH.resultMessage) or "")
        focus = str(results_graph.value(result, SH.focusNode) or "")
        source = str(results_graph.value(result, SH.sourceConstraintComponent) or "")
        shape = str(results_graph.value(result, SH.sourceShape) or "")
        why_not = (
            ("claim_hash", claim_hash),
            ("focus_node", focus),
            ("failed_shape", shape),
            ("constraint_component", source),
        )
        violations.append(
            ConstraintViolation(
                shape=shape,
                focus=focus,
                severity=severity,
                message=message,
                source_iri=source,
                why_not=why_not,
            )
        )
    return violations


def _is_hard_violation(violation: ConstraintViolation) -> bool:
    if violation.message.startswith("clarify:"):
        return False
    return "Violation" in violation.severity or violation.severity.endswith("#Violation")


def _classify(violations: list[ConstraintViolation]) -> tuple[str, str, str]:
    if not violations:
        return "valid", "claim conforms to ontology constraints", ""

    hard = [v for v in violations if _is_hard_violation(v)]
    if hard:
        return (
            "refuse",
            hard[0].message or "ontology constraint violation",
            "CONSTRAINT_VIOLATION",
        )

    clarify_messages = [v.message for v in violations if v.message.startswith("clarify:")]
    if clarify_messages:
        return "clarify", clarify_messages[0].removeprefix("clarify:"), "CONSTRAINT_CLARIFY"

    return (
        "refuse",
        violations[0].message or "ontology constraint violation",
        "CONSTRAINT_VIOLATION",
    )


def _compose_violations(
    base_violations: tuple[ConstraintViolation, ...],
    *,
    plan_context: tuple[tuple[str, Any], ...],
    lineage_context: tuple[tuple[str, Any], ...],
) -> tuple[ConstraintViolation, ...]:
    composed: list[ConstraintViolation] = []
    for violation in base_violations:
        composed.append(
            ConstraintViolation(
                shape=violation.shape,
                focus=violation.focus,
                severity=violation.severity,
                message=violation.message,
                source_iri=violation.source_iri,
                why_not=(
                    *violation.why_not,
                    *plan_context,
                    *lineage_context,
                ),
            )
        )
    return tuple(composed)


def _compose_decision(
    base: _CachedBase,
    kernel: OntologyKernel,
    *,
    plan_context: tuple[tuple[str, Any], ...],
    lineage_context: tuple[tuple[str, Any], ...],
) -> ConstraintDecision:
    drift_status, drift_reasons = _assess_drift(kernel)
    return ConstraintDecision(
        decision=base.decision,
        reason=base.reason,
        reason_code=base.reason_code,
        violations=_compose_violations(
            base.violations,
            plan_context=plan_context,
            lineage_context=lineage_context,
        ),
        ontology_hash=kernel.ontology_hash,
        reasoner_mode=kernel.reasoner_mode,
        claim_hash=base.claim_hash,
        validation_report=base.validation_report,
        drift_status=drift_status,
        drift_reasons=drift_reasons,
    )


def validate_claim(
    binding: TermBinding,
    metric_id: str,
    kernel: OntologyKernel,
    *,
    claim_qualifiers: tuple[tuple[str, str], ...] = (),
    reference_date: date | None = None,
    use_cache: bool = True,
    lineage_context: tuple[tuple[str, Any], ...] = (),
    plan_context: tuple[tuple[str, Any], ...] = (),
) -> ConstraintDecision:
    cache_payload = claim_payload_for_cache(
        binding,
        metric_id,
        kernel,
        claim_qualifiers=claim_qualifiers,
        reference_date=reference_date,
    )
    cache_key = _cache_key(cache_payload)
    if use_cache:
        with _CACHE_LOCK:
            cached = _VALIDATION_CACHE.get(cache_key)
        if cached is not None:
            return _compose_decision(
                cached,
                kernel,
                plan_context=plan_context,
                lineage_context=lineage_context,
            )

    data_graph, claim_hash = build_claim_graph(
        binding,
        metric_id,
        kernel,
        claim_qualifiers=claim_qualifiers,
        reference_date=reference_date,
    )
    ontology_graph, shapes_graph = _parse_graphs(kernel)

    conforms, results_graph, results_text = pyshacl_validate(
        data_graph,
        shacl_graph=shapes_graph,
        ont_graph=ontology_graph,
        inference=kernel.reasoner_mode,
        advanced=True,
        allow_warnings=True,
    )

    violations = _parse_violations(results_graph, claim_hash=claim_hash) if results_graph else []
    if conforms and not violations:
        decision, reason, reason_code = "valid", "claim conforms to ontology constraints", ""
    else:
        decision, reason, reason_code = _classify(violations)

    if decision not in CONSTRAINT_DECISIONS:
        decision = "refuse"
        reason_code = "CONSTRAINT_VIOLATION"

    base = _CachedBase(
        decision=decision,
        reason=reason,
        reason_code=reason_code,
        violations=tuple(violations),
        claim_hash=claim_hash,
        validation_report=results_text or "",
    )
    if use_cache:
        with _CACHE_LOCK:
            _VALIDATION_CACHE[cache_key] = base
    return _compose_decision(
        base,
        kernel,
        plan_context=plan_context,
        lineage_context=lineage_context,
    )
