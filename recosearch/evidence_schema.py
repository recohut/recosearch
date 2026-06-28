"""Structural schema for the evidence contract.

Validates the shape of evidence envelopes (query/tool-level) and citations
(row/chunk-level), so the packet validator can trust types and the closure graph.
Hand-rolled (no new deps), mirroring contract_schema.py. Not a business authority.
"""
from __future__ import annotations

from typing import Any, Mapping

from .errors import SEVERITY_ERROR, ContractIssue

SCHEMA_VERSION = 1

_ENVELOPE_LOC = "evidence_envelope"
_CITATION_LOC = "citation"
_VALID_KINDS = {"atomic", "derived"}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_source_ref(source_ref: Any, loc: str) -> list[ContractIssue]:
    if not isinstance(source_ref, Mapping):
        return [ContractIssue("evidence_source_ref_malformed", SEVERITY_ERROR, loc, "source_ref must be an object")]
    issues: list[ContractIssue] = []
    for key in ("source_id", "source_type", "boundary"):
        if not _is_nonempty_str(source_ref.get(key)):
            issues.append(ContractIssue("evidence_source_ref_malformed", SEVERITY_ERROR, loc, f"source_ref.{key} must be a non-empty string"))
    return issues


def validate_evidence_envelope(envelope: Any) -> list[ContractIssue]:
    if not isinstance(envelope, Mapping):
        return [ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "envelope must be an object")]
    issues: list[ContractIssue] = []

    if envelope.get("schema_version") != SCHEMA_VERSION:
        issues.append(ContractIssue("evidence_schema_version_mismatch", SEVERITY_ERROR, _ENVELOPE_LOC, f"schema_version must be {SCHEMA_VERSION}"))
    if envelope.get("evidence_kind") not in _VALID_KINDS:
        issues.append(ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "evidence_kind must be 'atomic' or 'derived'"))
    for key in ("provenance_id", "evidence_id", "contract_hash", "claim_mode", "tool_name"):
        if not _is_nonempty_str(envelope.get(key)):
            issues.append(ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, f"{key} must be a non-empty string"))
    if not isinstance(envelope.get("may_support_final_answer"), bool):
        issues.append(ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "may_support_final_answer must be a boolean"))
    issues.extend(_check_source_ref(envelope.get("source_ref"), _ENVELOPE_LOC))
    filters_by_role = envelope.get("filters_by_role")
    if not isinstance(filters_by_role, Mapping) or any(not isinstance(filters_by_role.get(role), list) for role in ("user", "default", "rule")):
        issues.append(ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "filters_by_role must have list user/default/rule"))
    if not isinstance(envelope.get("query_hash"), Mapping):
        issues.append(ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "query_hash must be an object"))
    rule_impact = envelope.get("rule_impact")
    if not isinstance(rule_impact, list):
        issues.append(ContractIssue("evidence_envelope_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "rule_impact must be a list"))
    else:
        for entry in rule_impact:
            if (
                not isinstance(entry, Mapping)
                or any(not _is_nonempty_str(entry.get(key)) for key in ("rule_id", "rule_type", "effect", "application_mode", "source"))
                or not (entry.get("text") or entry.get("reason"))
            ):
                issues.append(ContractIssue("rule_impact_entry_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "each rule_impact entry needs rule_id/rule_type/effect/application_mode/source and text-or-reason"))
                break

    resolution = envelope.get("metric_resolution")
    if resolution is not None:
        if not isinstance(resolution, Mapping):
            issues.append(ContractIssue("metric_resolution_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "metric_resolution must be an object"))
        else:
            if resolution.get("metric_source") not in {"customer", "industry", "global"}:
                issues.append(ContractIssue("metric_resolution_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "metric_resolution.metric_source must be customer/industry/global"))
            if not isinstance(resolution.get("formula_verified"), bool):
                issues.append(ContractIssue("metric_resolution_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "metric_resolution.formula_verified must be a boolean"))
            if "inputs_verified" in resolution and not isinstance(resolution.get("inputs_verified"), bool):
                issues.append(ContractIssue("metric_resolution_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, "metric_resolution.inputs_verified must be a boolean"))
            for key in ("metric_id", "fallback_level", "fallback_policy_version", "fallback_policy_hash"):
                if not _is_nonempty_str(resolution.get(key)):
                    issues.append(ContractIssue("metric_resolution_malformed", SEVERITY_ERROR, _ENVELOPE_LOC, f"metric_resolution.{key} must be a non-empty string"))
    return issues


def validate_citation(citation: Any) -> list[ContractIssue]:
    if not isinstance(citation, Mapping):
        return [ContractIssue("citation_malformed", SEVERITY_ERROR, _CITATION_LOC, "citation must be an object")]
    issues: list[ContractIssue] = []

    if citation.get("schema_version") != SCHEMA_VERSION:
        issues.append(ContractIssue("evidence_schema_version_mismatch", SEVERITY_ERROR, _CITATION_LOC, f"schema_version must be {SCHEMA_VERSION}"))
    kind = citation.get("evidence_kind")
    if kind not in _VALID_KINDS:
        issues.append(ContractIssue("citation_malformed", SEVERITY_ERROR, _CITATION_LOC, "evidence_kind must be 'atomic' or 'derived'"))
    for key in ("evidence_id", "provenance_id", "contract_hash", "claim_mode"):
        if not _is_nonempty_str(citation.get(key)):
            issues.append(ContractIssue("citation_malformed", SEVERITY_ERROR, _CITATION_LOC, f"{key} must be a non-empty string"))
    if not isinstance(citation.get("may_support_final_answer"), bool):
        issues.append(ContractIssue("citation_malformed", SEVERITY_ERROR, _CITATION_LOC, "may_support_final_answer must be a boolean"))
    issues.extend(_check_source_ref(citation.get("source_ref"), _CITATION_LOC))
    if kind == "derived":
        supporting = citation.get("supporting_evidence_ids")
        if not isinstance(supporting, list) or not supporting:
            issues.append(ContractIssue("citation_malformed", SEVERITY_ERROR, _CITATION_LOC, "derived citation must list supporting_evidence_ids"))
    return issues
