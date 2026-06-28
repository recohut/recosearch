from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from .contract import _contract_hash_id, _contract_id
from .evidence_schema import SCHEMA_VERSION
from .json_utils import _json_safe

FEDERATION_SOURCE_ID = "bounded_in_memory_slice_combiner"
FEDERATION_SOURCE_TYPE = "federation"


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _evidence_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:{_stable_hash(payload)}"


def _query_hash(payload: Any) -> str:
    return _stable_hash(payload)


def _source_ref(source_id: str, source_type: str, boundary: str) -> dict[str, str]:
    return {"source_id": source_id, "source_type": source_type, "boundary": boundary}


def _rule_impact(global_rules_applied: Any) -> list[dict[str, Any]]:
    """Record impact of rules that actually affected this execution. Reports the
    compiler-produced metadata (rule_id/rule_type/effect/application_mode) rather
    than hardcoding an effect — the rule compiler is the source of truth."""
    impact: list[dict[str, Any]] = []
    for rule in global_rules_applied or []:
        if not isinstance(rule, Mapping):
            continue
        impact.append(
            {
                "rule_id": rule.get("rule_id"),
                "rule_type": rule.get("rule_type"),
                "effect": rule.get("effect"),
                "application_mode": rule.get("application_mode"),
                "scope": rule.get("scope"),
                "source": rule.get("source"),
                "table": rule.get("table"),
                "column": rule.get("column"),
                "operator": rule.get("operator"),
                "value": rule.get("value"),
                "reason": rule.get("reason"),
            }
        )
    return impact


def _provenance(
    *,
    tool_name: str,
    source: str,
    source_id: str | None = None,
    source_type: str | None = None,
    fields: Iterable[str] | None = None,
    filters: Any = None,
    user_filters: Any = None,
    default_filters: Any = None,
    rule_filters: Any = None,
    joins: Any = None,
    global_rules_applied: Any = None,
    compiled_sql: str | None = None,
    query_body: Any = None,
    row_count: int = 0,
    citation_mode: str = "claim_support",
    may_support_final_answer: bool = True,
    purpose: Mapping[str, Any] | None = None,
    evidence_kind: str = "atomic",
    metric_resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    boundary = source
    resolved_source_id = source_id or boundary.split(".", 1)[0]
    rules = global_rules_applied or []
    compiled_sql_hash = _query_hash(compiled_sql) if compiled_sql else None
    query_body_hash = _query_hash(query_body) if query_body is not None else None
    payload = {
        "tool_name": tool_name,
        "source": source,
        "semantic_contract_id": _contract_id(),
        "fields": sorted({str(field) for field in (fields or []) if str(field)}),
        "filters": _json_safe(filters or []),
        "joins": _json_safe(joins or []),
        "global_rules_applied": _json_safe(rules),
        "compiled_sql_hash": compiled_sql_hash,
        "query_body_hash": query_body_hash,
        "row_count": row_count,
        "citation_mode": citation_mode,
        "may_support_final_answer": may_support_final_answer,
        "purpose": _json_safe(purpose or {}),
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": evidence_kind,
        "source_ref": _source_ref(resolved_source_id, str(source_type or ""), boundary),
        "filters_by_role": {
            "user": _json_safe(user_filters or []),
            "default": _json_safe(default_filters or []),
            "rule": _json_safe(rule_filters if rule_filters is not None else rules),
        },
        "query_hash": {"compiled_sql_hash": compiled_sql_hash, "query_body_hash": query_body_hash},
        "rule_impact": _rule_impact(rules),
        "contract_hash": _contract_hash_id(),
        "claim_mode": citation_mode,
    }
    if metric_resolution is not None:
        payload["metric_resolution"] = _json_safe(dict(metric_resolution))
    payload["provenance_id"] = _evidence_id("prov", payload)
    payload["evidence_id"] = payload["provenance_id"]  # query-level evidence id
    return payload


def _attach_citations(
    rows: list[dict[str, Any]],
    *,
    provenance: Mapping[str, Any],
    source: str,
    prefix: str,
    identity_fields: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    cited_rows: list[dict[str, Any]] = []
    identities = list(identity_fields or [])
    for index, row in enumerate(rows):
        record_ref = {field: row.get(field) for field in identities if field in row}
        if not record_ref:
            record_ref = {"row_index": index}
        citation_payload = {
            "source": source,
            "record_ref": record_ref,
            "provenance_id": provenance.get("provenance_id"),
            "row_index": index,
        }
        cited = dict(row)
        cited["_citation"] = {
            "evidence_id": _evidence_id(prefix, citation_payload),
            "source": source,
            "semantic_contract_id": provenance.get("semantic_contract_id"),
            "provenance_id": provenance.get("provenance_id"),
            "record_ref": record_ref,
            "may_support_final_answer": bool(provenance.get("may_support_final_answer")),
            "schema_version": SCHEMA_VERSION,
            "evidence_kind": "atomic",
            "source_ref": provenance.get("source_ref"),
            "contract_hash": provenance.get("contract_hash"),
            "claim_mode": provenance.get("claim_mode") or provenance.get("citation_mode"),
        }
        cited_rows.append(cited)
    return cited_rows


def _derived_citation(
    *,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    left_key: str,
    right_key: str,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    left_citation = left.get("_citation") if isinstance(left.get("_citation"), Mapping) else None
    right_citation = right.get("_citation") if isinstance(right.get("_citation"), Mapping) else None
    left_eid = left_citation.get("evidence_id") if left_citation else None
    right_eid = right_citation.get("evidence_id") if right_citation else None
    supporting_ids = [eid for eid in (left_eid, right_eid) if eid]
    supporting_sources = [
        source
        for source in (
            left_citation.get("source") if left_citation else None,
            right_citation.get("source") if right_citation else None,
        )
        if source
    ]
    return {
        "evidence_id": _evidence_id(
            "combine",
            {
                "left": left_eid if left_eid else left.get(left_key),
                "right": right_eid if right_eid else right.get(right_key),
                "left_key": left_key,
                "right_key": right_key,
            },
        ),
        "source": FEDERATION_SOURCE_ID,
        "semantic_contract_id": provenance.get("semantic_contract_id"),
        "provenance_id": provenance.get("provenance_id"),
        "left_evidence_id": left_eid,
        "right_evidence_id": right_eid,
        "supporting_evidence_ids": supporting_ids,
        "supporting_sources": supporting_sources,
        "may_support_final_answer": bool(
            (not left_citation or left_citation.get("may_support_final_answer"))
            and (not right_citation or right_citation.get("may_support_final_answer"))
        ),
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": "derived",
        "source_ref": _source_ref(FEDERATION_SOURCE_ID, FEDERATION_SOURCE_TYPE, FEDERATION_SOURCE_ID),
        "contract_hash": provenance.get("contract_hash"),
        "claim_mode": provenance.get("claim_mode"),
    }
