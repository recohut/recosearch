from __future__ import annotations

from typing import Any, Mapping

from .adapters import CAPABILITY_CLARIFICATION, capabilities_for
from .contract import compile_semantic_contract
from .metric_resolver import resolve_metric


def validate_analysis_request(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate whether an LLM-planned analysis request is specific enough.

    This tool does not interpret natural language and does not execute source
    access. It only checks structured inputs against the compiled semantic
    contract and returns contract-derived clarification prompts.
    """
    contract = compile_semantic_contract()
    request = dict(request or {})
    capabilities = _analysis_capabilities(contract)
    source_ids = _requested_source_ids(request, contract)
    missing: list[dict[str, Any]] = []

    metric_resolutions: list[dict[str, Any]] = []
    for requested in request.get("metric_ids") or []:
        resolution = resolve_metric(str(requested), contract)
        entry = {"requested": requested, "status": resolution["status"]}
        if resolution.get("stamp"):
            entry["metric_resolution"] = resolution["stamp"]
        metric_resolutions.append(entry)
        if resolution["status"] in {"clarify", "fallback_disabled"}:
            missing.append({
                "input": "metric_focus",
                "reason": f"requested metric {requested!r} is {resolution['status']} (not a customer metric; fallback off/unavailable)",
                "options": capabilities.get("metrics", []),
            })

    if not _has_any(request, "metrics", "metric_ids", "measures", "measure_ids", "metric_focus"):
        missing.append(_missing_metric_focus(capabilities))

    if _date_fields(contract) and not _has_any(request, "time_window", "date_range", "assume_all_time"):
        missing.append(_missing_time_window())

    if not source_ids and len(contract.get("sources", {})) > 1:
        missing.append(_missing_source_scope(capabilities))

    if len(source_ids) > 1 and not _has_any(request, "join_keys", "relation_fields", "join_strategy"):
        missing.append(_missing_cross_source_relation(capabilities, source_ids))

    if bool(request.get("requires_decision")) and not request.get("decision_intent"):
        missing.append(_missing_decision_intent())

    # Capability-driven (NOT source-type business meaning): map each requested
    # source to its intrinsic storage capability and ask the capability-level
    # clarification. No "opensearch => reviews" / "qdrant => policy" branching.
    requested_capabilities: set[str] = set()
    for source_id in source_ids:
        source_type = str(contract.get("sources", {}).get(source_id, {}).get("type") or "")
        requested_capabilities |= capabilities_for(source_type)
    for capability in sorted(requested_capabilities):
        clarification = CAPABILITY_CLARIFICATION.get(capability)
        if not clarification:
            continue
        input_id, accepted_keys = clarification
        if not _has_any(request, *accepted_keys):
            missing.append(_missing_capability_focus(input_id, capability))

    status = "clarification_needed" if missing else "ok"
    return {
        "status": status,
        "semantic_contract_id": contract.get("artifact_id"),
        "source_boundary": "semantic_contract_only",
        "request": _json_safe(request),
        "metric_resolutions": metric_resolutions,
        "missing_inputs": missing,
        "suggested_clarification_questions": [
            _clarification_question(item)
            for item in missing
        ],
        "available_options": capabilities,
        "planner_guidance": {
            "llm_responsibility": "Ask the user for missing inputs or explicitly declare broad defaults before executing source tools.",
            "mcp_responsibility": "Validate structured plans, source boundaries, joins, global rules, and citation-ready evidence; do not infer business intent from natural language.",
            "final_answer_rule": "Do not make final business claims from exploratory rows or from sources that were not cited as claim-supporting evidence.",
        },
    }


def _analysis_capabilities(contract: Mapping[str, Any]) -> dict[str, Any]:
    fields = _field_index(contract)
    return {
        "metrics": [
            {
                "metric_id": metric_id,
                "label": metric.get("label"),
                "definition": metric.get("definition"),
            }
            for metric_id, metric in sorted(contract.get("metrics", {}).items())
            if isinstance(metric, Mapping)
        ],
        "measures": _field_options(contract, "measures"),
        "dimensions": _field_options(contract, "dimensions"),
        "sources": [
            _source_option(source_id, source, contract)
            for source_id, source in sorted(contract.get("sources", {}).items())
            if isinstance(source, Mapping)
        ],
        "declared_relation_fields": [
            _relation_option(relation, fields)
            for relation in contract.get("relations", [])
            if isinstance(relation, Mapping)
        ],
        "global_rules": [
            {"rule_id": rule.get("rule_id"), "text": rule.get("text")}
            for rule in contract.get("rules", [])
            if isinstance(rule, Mapping)
        ],
    }


def _field_options(contract: Mapping[str, Any], section: str) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for field_id, field in sorted(contract.get(section, {}).items()):
        if not isinstance(field, Mapping):
            continue
        option = {
            "field_id": field_id,
            "source": field.get("source"),
            "table": field.get("table"),
            "column": field.get("column"),
            "description": field.get("description"),
        }
        if field.get("default_aggregation"):
            option["default_aggregation"] = field.get("default_aggregation")
        options.append(option)
    return options


def _field_index(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for section in ("dimensions", "measures"):
        for field_id, field in contract.get(section, {}).items():
            if isinstance(field, Mapping):
                fields[str(field_id)] = {
                    "field_id": str(field_id),
                    "semantic_kind": section[:-1],
                    **dict(field),
                }
    return fields


def _source_option(source_id: str, source: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    source_type = str(source.get("type") or "")
    option: dict[str, Any] = {
        "source_id": source_id,
        "source_type": source_type,
        "suggested_tools": _suggested_tools(source_type),
    }
    if source.get("database"):
        option["database"] = source.get("database")
    if source.get("index"):
        option["index"] = source.get("index")
    if source.get("collection"):
        option["collection"] = source.get("collection")
    tables = sorted(
        {
            str(field.get("table"))
            for field in _field_index(contract).values()
            if field.get("source") == source_id and field.get("table")
        }
    )
    if tables:
        option["declared_tables"] = tables
    return option


def _suggested_tools(source_type: str) -> list[str]:
    # Derived from declared storage capabilities, not hardcoded source-type roles.
    from .adapters import suggested_tools_for

    return suggested_tools_for(source_type)


def _relation_option(relation: Mapping[str, Any], fields: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    left_id = str(relation.get("left") or "")
    right_id = str(relation.get("right") or "")
    return {
        "left": _relation_side(left_id, fields),
        "right": _relation_side(right_id, fields),
    }


def _relation_side(field_id: str, fields: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    field = fields.get(field_id, {})
    return {
        "field": field_id,
        "source": field.get("source"),
        "table": field.get("table"),
        "column": field.get("column"),
        "semantic_kind": field.get("semantic_kind"),
    }


def _requested_source_ids(request: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
    raw = request.get("expected_sources") or request.get("source_ids")
    if raw:
        requested = _as_list(raw)
        return [source_id for source_id in requested if source_id in contract.get("sources", {})]
    if str(request.get("source_scope") or "").casefold() in {"all", "all_declared_sources"}:
        return sorted(str(source_id) for source_id in contract.get("sources", {}))
    return []


def _date_fields(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    date_fields: list[dict[str, Any]] = []
    for field_id, field in contract.get("dimensions", {}).items():
        if not isinstance(field, Mapping):
            continue
        haystack = f"{field.get('column', '')} {field.get('description', '')}".casefold()
        if any(token in haystack for token in ("date", "timestamp", "submitted_at", "created_at")):
            date_fields.append({"field_id": field_id, **dict(field)})
    return date_fields


def _missing_metric_focus(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "input": "metric_focus",
        "reason": "No metric, measure, or metric focus was declared.",
        "options": {
            "metrics": capabilities.get("metrics", []),
            "measures": capabilities.get("measures", []),
        },
    }


def _missing_time_window() -> dict[str, Any]:
    return {
        "input": "time_window",
        "reason": "Date or timestamp fields are declared, but the request does not specify a time window or all-time scope.",
        "options": [
            {"value": "all_time", "description": "Use all available declared data."},
            {"value": "explicit_range", "description": "Ask the user for start and end dates."},
            {"value": "latest_available_period", "description": "Use the latest period only if the assistant declares that default."},
        ],
    }


def _missing_source_scope(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "input": "source_scope",
        "reason": "Multiple sources are declared, but the request does not state which sources should support the answer.",
        "options": capabilities.get("sources", []),
    }


def _missing_cross_source_relation(capabilities: Mapping[str, Any], source_ids: list[str]) -> dict[str, Any]:
    relations = [
        relation
        for relation in capabilities.get("declared_relation_fields", [])
        if _relation_mentions_sources(relation, set(source_ids))
    ]
    return {
        "input": "cross_source_relation_fields",
        "reason": "Multiple sources were requested, but no join keys, relation fields, or join strategy were declared.",
        "options": relations,
    }


def _missing_decision_intent() -> dict[str, Any]:
    return {
        "input": "decision_intent",
        "reason": "The request asks for a decision or action, but the intended action is not declared.",
        "options": [
            {"value": "rank", "description": "Rank entities for review or prioritization."},
            {"value": "diagnose", "description": "Explain what is driving a metric or risk."},
            {"value": "compare", "description": "Compare entities, periods, or segments."},
            {"value": "monitor", "description": "Summarize current health and risks."},
        ],
    }


def _missing_capability_focus(input_name: str, capability: str) -> dict[str, Any]:
    return {
        "input": input_name,
        "reason": f"a {capability} source was requested, but no query, filter, or explicit broad-search default was declared.",
        "capability": capability,
        "options": [
            {"value": "specific_query", "description": "Provide the query, topic, or filter to execute against this source."},
            {"value": "structured_filters", "description": "Use declared identifiers or other source fields as filters."},
            {"value": "broad_scan", "description": "Proceed only if the assistant declares a bounded broad exploratory scan."},
        ],
    }


def _missing_text_search_focus(input_name: str, label: str) -> dict[str, Any]:
    return {
        "input": input_name,
        "reason": f"A {label} source was requested, but no query, filter, or explicit broad-search default was declared.",
        "options": [
            {"value": "specific_query", "description": "Ask for the topic, policy area, review theme, or risk signal to search."},
            {"value": "structured_filters", "description": "Use declared identifiers, ratings, tags, or other source fields."},
            {"value": "broad_scan", "description": "Proceed only if the assistant declares a bounded broad exploratory scan."},
        ],
    }


def _clarification_question(missing: Mapping[str, Any]) -> dict[str, Any]:
    input_name = str(missing.get("input") or "missing_input")
    question_by_input = {
        "metric_focus": "Which declared metric or measure should define the analysis?",
        "time_window": "What time window should the analysis use?",
        "source_scope": "Which declared sources should support the answer?",
        "cross_source_relation_fields": "Which declared relation fields should be used to combine sources?",
        "decision_intent": "What decision or action should the analysis support?",
        "text_search_focus": "What text query or filter should the text search use?",
        "vector_query_focus": "What query should the vector search use?",
    }
    return {
        "question_id": input_name,
        "missing_input": input_name,
        "question": question_by_input.get(input_name, "What missing input should the assistant clarify?"),
        "options": missing.get("options", []),
    }


def _relation_mentions_sources(relation: Mapping[str, Any], source_ids: set[str]) -> bool:
    mentioned = {
        str(side.get("source"))
        for side in (relation.get("left"), relation.get("right"))
        if isinstance(side, Mapping) and side.get("source")
    }
    return len(mentioned & source_ids) >= 2


def _has_any(request: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        value = request.get(key)
        if value is None or value is False:
            continue
        if isinstance(value, (list, tuple, set, dict)) and not value:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return []


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value
