from __future__ import annotations

from typing import Any, Mapping

from .analysis_request import validate_analysis_request
from .citations import _attach_citations, _provenance
from .config import (
    _redact_source_config,
    _ref_by_id,
    _source_refs,
    resolve_source_id,
)
from .contract import (
    _contract_id,
    _field_index,
    _global_rule_filters_for_tables,
    _source_ids_with_capability,
    _table_for_source,
    canonical_contract_json,
    compile_semantic_contract,
    validated_contract,
)
from .evidence_validator import validate_cited_evidence_packet
from .federation import combine_slices
from .field_roles import identity_columns, searchable_columns
from .adapters import adapter_for_type
from .adapters.opensearch import _opensearch_search
from .adapters.postgres import (
    _compile_postgres_semantic_query,
    _fetch_postgres,
    _postgres_purpose_validation,
    _postgres_sql_shape,
    validate_postgres_sql,
)
from .metric_resolver import resolve_and_validate_metric
from .observability import stamp_trace_id, traced_tool
from .adapters.qdrant import _vector_search
from .acl import mask_result
from .rbac import rbac_gate
from .rules import recorded_policies, relevant_recorded_policies
from .settings import EMBEDDING_MODEL, MAX_FEDERATION_ROWS, MAX_SOURCE_ROWS, SEMANTIC_JSON_PATH


def _source_boundary(source_id: str, table: str | None = None) -> str:
    return f"{source_id}.{table}" if table else source_id


def _fields_of(contract: Mapping[str, Any], source_id: str, table: str) -> dict[str, dict[str, Any]]:
    return {
        field_id: field
        for field_id, field in _field_index(contract).items()
        if field.get("source") == source_id and field.get("table") == table
    }


def _field_ids_of(contract: Mapping[str, Any], source_id: str, table: str) -> list[str]:
    return sorted(_fields_of(contract, source_id, table))


def _identity_columns_for_source(contract: Mapping[str, Any], source_id: str) -> list[str]:
    """Identity/join-key columns across all tables of a source — driven by
    resolved field roles, not '_id' name luck. Plus '_id' as a last-resort key."""
    index = {**contract.get("dimensions", {}), **contract.get("measures", {})}
    columns: list[str] = []
    for assignment in contract.get("field_roles", []):
        if (
            isinstance(assignment, Mapping)
            and assignment.get("resolution") == "resolved"
            and assignment.get("source") == source_id
            and assignment.get("field_role") in {"identity", "join_key"}
        ):
            field = index.get(assignment.get("field_id"))
            if isinstance(field, Mapping) and field.get("column"):
                columns.append(str(field["column"]))
    return [*dict.fromkeys(columns), "_id"]


def _exclusions_for_source_table(source_id: str, table: str) -> list[dict[str, Any]]:
    return [
        dict(exclusion)
        for exclusion in compile_semantic_contract().get("exclusions", [])
        if isinstance(exclusion, Mapping)
        and exclusion.get("source") == source_id
        and exclusion.get("table") == table
    ]


def _semantic_filters_from_exclusions(exclusions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "field": exclusion.get("field_id")
            or f"{exclusion.get('source')}.{exclusion.get('table')}.{exclusion.get('column')}",
            "operator": exclusion.get("operator"),
            "value": exclusion.get("value"),
        }
        for exclusion in exclusions
    ]



def _contract_gate() -> dict[str, Any] | None:
    """Refuse governed source execution when the contract is error-invalid."""
    vc = validated_contract()
    if vc.is_valid:
        return None
    return {
        "status": "refused",
        "reason_code": "contract_invalid",
        "issues": [issue.as_dict() for issue in vc.errors],
        "source_boundary": "semantic_contract_only",
        "rows": [],
        "row_count": 0,
    }


def _referenced_tables(sql: str) -> list[str]:
    """Best-effort table-name extraction for routing. Dialect-agnostic enough for
    table names; the real per-source guard runs afterward with the right dialect."""
    try:
        import sqlglot
        from sqlglot import exp

        parsed = sqlglot.parse_one(sql, read="postgres")
        return sorted({table.name for table in parsed.find_all(exp.Table)})
    except Exception:
        return []


def _owning_structured_sources(contract: Mapping[str, Any], tables: list[str]) -> set[str]:
    """Which declared structured-query sources own the referenced tables."""
    structured = set(_source_ids_with_capability(contract, "structured_query"))
    owners: set[str] = set()
    for table in tables:
        info = contract.get("tables", {}).get(table)
        if isinstance(info, Mapping) and info.get("source") in structured:
            owners.add(str(info["source"]))
    return owners


def _choose_structured_source(owners: set[str], source_id: str | None) -> tuple[str | None, dict[str, Any] | None]:
    """Pick which structured source to run against. Honors an explicit source_id;
    otherwise routes by which source owns the referenced tables; asks only when
    genuinely ambiguous, and refuses a single query that spans two sources."""
    contract = compile_semantic_contract()
    candidates = _source_ids_with_capability(contract, "structured_query")
    if source_id is not None:
        if source_id in candidates:
            return source_id, None
        return None, {"status": "refused", "reason_code": "source_not_found_for_capability",
                      "capability": "structured_query", "requested": source_id,
                      "candidates": candidates, "rows": [], "row_count": 0}
    if not candidates:
        return None, {"status": "refused", "reason_code": "no_source_for_capability",
                      "capability": "structured_query", "rows": [], "row_count": 0}
    if len(candidates) == 1:
        return candidates[0], None
    owners = owners & set(candidates)
    if len(owners) == 1:
        return next(iter(owners)), None
    if len(owners) > 1:
        return None, {"status": "refused", "reason_code": "single_query_spans_sources",
                      "sources": sorted(owners), "hint": "query each source separately, then combine_slices to federate",
                      "rows": [], "row_count": 0}
    return None, {"status": "refused", "reason_code": "source_selection_required",
                  "capability": "structured_query", "candidates": candidates, "rows": [], "row_count": 0}


def _plan_field_sources(plan: Mapping[str, Any]) -> set[str]:
    """Structured sources referenced by a semantic plan's field ids ('source.table.column')."""
    sources: set[str] = set()
    for key in ("select", "group_by", "order_by", "filters"):
        for item in plan.get(key) or []:
            field_id = item.get("field") if isinstance(item, Mapping) else item
            if isinstance(field_id, str) and "." in field_id:
                sources.add(field_id.split(".")[0])
    return sources


def check_semantic_json_fresh() -> dict[str, Any]:
    """Compare on-disk semantic.json against a fresh canonical compile."""
    expected = canonical_contract_json(compile_semantic_contract())
    try:
        actual = SEMANTIC_JSON_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"fresh": False, "reason": "semantic.json is missing", "path": str(SEMANTIC_JSON_PATH)}
    fresh = actual == expected
    return {
        "fresh": fresh,
        "reason": "in sync with declared inputs" if fresh else "semantic.json does not match the compiled contract; run --write-semantic-json",
        "path": str(SEMANTIC_JSON_PATH),
    }


def list_sources() -> dict[str, Any]:
    """List only the live sources declared in source_config.yaml."""
    refs = _source_refs()
    return {
        "status": "ok",
        "source_boundary": "source_config.yaml",
        "sources": {source_id: _redact_source_config(ref) for source_id, ref in refs.items()},
    }


def get_semantic_contract() -> dict[str, Any]:
    """Return the structured semantic contract, with validation issues surfaced."""
    vc = validated_contract()
    contract = dict(vc.contract)
    contract["validation"] = {
        "is_valid": vc.is_valid,
        "issues": [issue.as_dict() for issue in vc.issues],
    }
    contract["recorded_policy_context"] = recorded_policies(vc.contract)
    return contract


def generate_semantic_json(write: bool = False) -> dict[str, Any]:
    """Compile semantic.md into structured semantic JSON; optionally write semantic.json."""
    vc = validated_contract()
    contract = vc.contract
    if write:
        SEMANTIC_JSON_PATH.write_text(canonical_contract_json(contract), encoding="utf-8")
    return {
        "status": "ok",
        "written": bool(write),
        "path": str(SEMANTIC_JSON_PATH),
        "is_valid": vc.is_valid,
        "issues": [issue.as_dict() for issue in vc.issues],
        "contract": contract,
    }


def health_check_sources() -> dict[str, Any]:
    """Probe declared live sources. Limited mode when the contract is error-invalid.
    Registry-driven: iterates all declared sources via _source_refs() and delegates
    to each adapter's health_check callable. Unavailable (placeholder) adapters are
    reported as 'unavailable' and do NOT count toward overall health."""
    contract_valid = validated_contract().is_valid
    results: dict[str, Any] = {}
    counted_ids: list[str] = []  # source ids whose status matters for overall health

    for source_id, ref in _source_refs().items():
        adapter = adapter_for_type(ref.source_type)
        if adapter is None:
            results[source_id] = {"status": "no_adapter"}
            # not counted
        elif not adapter.available:
            results[source_id] = {
                "status": "unavailable",
                "reason": "adapter declared but not enabled (placeholder)",
            }
            # not counted
        else:
            counted_ids.append(source_id)
            try:
                results[source_id] = {"status": "ok", **adapter.health_check(ref)}
            except Exception as exc:
                results[source_id] = {"status": "failed", "error": str(exc)}

    overall = "ok" if all(results[sid]["status"] == "ok" for sid in counted_ids) else "failed"
    return {
        "status": overall,
        "contract_status": "valid" if contract_valid else "invalid",
        "source_boundary": "source_config.yaml",
        "results": results,
    }


def run_guarded_postgres_sql(
    sql: str,
    limit: int = 50,
    purpose: dict[str, Any] | None = None,
    citation_mode: str = "exploratory",
    source_id: str | None = None,
) -> dict[str, Any]:
    """Run read-only structured SQL after semantic allowlist validation."""
    gate = _contract_gate()
    if gate is not None:
        return gate
    # Route by the tables the SQL touches: orders/products -> Postgres, sellers ->
    # Snowflake, etc. No source_id needed unless genuinely ambiguous.
    owners = _owning_structured_sources(compile_semantic_contract(), _referenced_tables(sql))
    pg_id, refusal = _choose_structured_source(owners, source_id)
    if refusal is not None:
        return refusal
    _sq_ref = _ref_by_id(pg_id)
    _sq_adapter = adapter_for_type(_sq_ref.source_type)
    _sq_dialect = (_sq_adapter.sql_dialect if _sq_adapter is not None else None) or "postgres"
    guard = validate_postgres_sql(sql, dialect=_sq_dialect)
    if guard["decision"] != "allow":
        return {"status": "refused", "guard": guard, "rows": [], "source_boundary": pg_id}
    purpose_guard = _postgres_purpose_validation(sql, purpose, citation_mode, dialect=_sq_dialect)
    if purpose_guard["decision"] != "allow":
        return {"status": "refused", "guard": guard, "purpose_guard": purpose_guard, "rows": [], "row_count": 0, "source_boundary": pg_id}
    try:
        rows = _sq_adapter.run_query(sql, limit=limit, ref=_sq_ref) if _sq_adapter is not None else _fetch_postgres(sql, limit=limit, ref=_sq_ref)
    except Exception as exc:
        return {
            "status": "refused",
            "reason_code": "source_execution_failed",
            "capability": "structured_query",
            "source_boundary": pg_id,
            "error": str(exc),
            "rows": [],
            "row_count": 0,
        }
    shape = purpose_guard.get("shape") or _postgres_sql_shape(sql, dialect=_sq_dialect)
    contract = compile_semantic_contract()
    rule_filters = _global_rule_filters_for_tables(shape.get("tables", []))
    provenance = _provenance(
        tool_name="run_guarded_postgres_sql",
        source=pg_id,
        source_id=pg_id,
        source_type=_ref_by_id(pg_id).source_type,
        fields=shape.get("field_ids", []),
        filters=(purpose or {}).get("required_filters", []),
        user_filters=(purpose or {}).get("required_filters", []),
        rule_filters=rule_filters,
        joins=shape.get("joins", []),
        global_rules_applied=rule_filters,
        compiled_sql=sql,
        row_count=len(rows),
        citation_mode=str(citation_mode or "exploratory"),
        may_support_final_answer=bool(purpose_guard.get("may_support_final_answer")),
        purpose=purpose,
    )
    return {
        "status": "ok",
        "guard": guard,
        "purpose_guard": purpose_guard,
        "citation_mode": str(citation_mode or "exploratory"),
        "may_support_final_answer": bool(purpose_guard.get("may_support_final_answer")),
        "provenance": provenance,
        "rows": _attach_citations(rows, provenance=provenance, source=pg_id, prefix="pg",
                                  identity_fields=_identity_columns_for_source(contract, pg_id)),
        "row_count": len(rows),
        "recorded_policy_context": relevant_recorded_policies(contract, source_id=pg_id, field_ids=set(shape.get("field_ids", []))),
        "source_boundary": pg_id,
    }


def execute_postgres_semantic_query(plan: dict[str, Any], metric_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
    """Execute a structured query plan; validates declared fields/joins/aggregations.
    With metric_id, the plan is validated against the resolved metric and stamped."""
    gate = _contract_gate()
    if gate is not None:
        return gate
    contract = compile_semantic_contract()
    metric_resolution = None
    if metric_id:
        decision = resolve_and_validate_metric(metric_id, plan, contract)
        if decision.get("refused"):
            return {
                "status": "refused",
                "reason_code": decision["refused"],
                "metric_id": metric_id,
                "details": {key: value for key, value in decision.items() if key != "refused"},
                "rows": [],
                "row_count": 0,
            }
        metric_resolution = decision["stamp"]
    # Route by the sources named in the plan's field ids (source.table.column).
    pg_id, refusal = _choose_structured_source(_plan_field_sources(plan), source_id)
    if refusal is not None:
        return refusal
    try:
        _esq_ref = _ref_by_id(pg_id)
        _esq_adapter = adapter_for_type(_esq_ref.source_type)
        _esq_dialect = (_esq_adapter.sql_dialect if _esq_adapter is not None else None) or "postgres"
        sql, params, metadata = _compile_postgres_semantic_query(plan, dialect=_esq_dialect)
    except Exception as exc:
        return {"status": "refused", "reason_code": "plan_compile_failed", "reason": str(exc), "source_boundary": pg_id, "rows": [], "row_count": 0}
    try:
        _esq_runner = _esq_adapter.run_query if _esq_adapter is not None else _fetch_postgres
        rows = _esq_runner(sql, params, limit=int(metadata["limit"]), ref=_esq_ref)
    except Exception as exc:
        return {
            "status": "refused",
            "reason_code": "source_execution_failed",
            "capability": "structured_query",
            "source_boundary": pg_id,
            "error": str(exc),
            "rows": [],
            "row_count": 0,
        }
    selected_fields = metadata.get("selected_fields", [])
    fields = set(selected_fields) | set(metadata.get("filter_fields", [])) | set(metadata.get("group_by", []))
    for join in metadata.get("joins", []):
        if isinstance(join, Mapping):
            fields.add(str(join.get("left") or ""))
            fields.add(str(join.get("right") or ""))
    provenance = _provenance(
        tool_name="execute_postgres_semantic_query",
        source=pg_id,
        source_id=pg_id,
        source_type=_ref_by_id(pg_id).source_type,
        fields=fields,
        filters=plan.get("filters", []),
        user_filters=plan.get("filters", []),
        rule_filters=metadata.get("global_rule_filters", []),
        joins=plan.get("joins", []),
        global_rules_applied=metadata.get("global_rule_filters", []),
        compiled_sql=sql,
        row_count=len(rows),
        citation_mode="claim_support",
        may_support_final_answer=True,
        purpose={
            "claim_type": "semantic_plan",
            "business_terms": [],
            "expected_sources": [pg_id],
            "expected_fields": sorted(fields),
            "required_filters": plan.get("filters", []),
        },
        metric_resolution=metric_resolution,
    )
    return {
        "status": "ok",
        "source_boundary": pg_id,
        "semantic_contract_id": _contract_id(),
        "plan": plan,
        "metric_resolution": metric_resolution,
        "compiled_sql": sql,
        "provenance": provenance,
        "metadata": metadata,
        "rows": _attach_citations(rows, provenance=provenance, source=pg_id, prefix="pg",
                                  identity_fields=_identity_columns_for_source(contract, pg_id)),
        "row_count": len(rows),
        "recorded_policy_context": relevant_recorded_policies(contract, source_id=pg_id, field_ids=set(fields)),
    }


def search_text(
    source_id: str | None = None,
    query: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Text-search capability tool over a declared text_search source.

    Full-text runs over resolved body_text/display_name field roles; `filters` is
    keyed by declared field_id (a bare column name is accepted as a back-compat
    alias); record citations use resolved identity/join roles. No business-role
    assumptions.
    """
    gate = _contract_gate()
    if gate is not None:
        return gate
    sid, refusal = resolve_source_id("text_search", source_id)
    if refusal is not None:
        return refusal
    contract = compile_semantic_contract()
    ref = _ref_by_id(sid)
    index = _table_for_source(contract, sid)
    source = _source_boundary(sid, index)
    fields_by_id = _fields_of(contract, sid, index)
    column_by_field_id = {field_id: str(field["column"]) for field_id, field in fields_by_id.items()}
    allowed_columns = set(column_by_field_id.values())
    searchable = searchable_columns(contract, sid, index)
    exclusions = _exclusions_for_source_table(sid, index)

    if query and not searchable:
        return {"status": "refused", "reason_code": "text_search_fields_unresolved",
                "reason": "no body_text/display_name field roles resolved for this source; cannot run a full-text query",
                "source_boundary": source, "rows": [], "row_count": 0}

    def _resolve_filter_key(key: str) -> str | None:
        if key in column_by_field_id:  # declared field_id (preferred)
            return column_by_field_id[key]
        if key in allowed_columns:  # bare column alias (back-compat)
            return key
        return None

    filter_clauses: list[dict[str, Any]] = []
    for exclusion in exclusions:
        if exclusion.get("operator") == "!=":
            filter_clauses.append({"bool": {"must_not": [{"term": {str(exclusion.get("column")): exclusion.get("value")}}]}})

    def _empty_result(query_body: dict[str, Any]) -> dict[str, Any]:
        provenance = _provenance(
            tool_name="search_text", source=source, source_id=sid, source_type=ref.source_type,
            fields=_field_ids_of(contract, sid, index), filters=_semantic_filters_from_exclusions(exclusions),
            rule_filters=_semantic_filters_from_exclusions(exclusions), joins=[], global_rules_applied=exclusions,
            query_body=query_body, row_count=0,
        )
        return {"status": "ok", "source_boundary": source, "semantic_contract_id": _contract_id(),
                "provenance": provenance, "rows": [], "row_count": 0}

    applied: list[tuple[str, Any]] = []  # (column, value) for provenance
    for key, value in (filters or {}).items():
        column = _resolve_filter_key(key)
        if column is None:
            return {"status": "refused", "reason": f"filter key {key!r} is not a declared field_id or column for {source}",
                    "source_boundary": source, "rows": [], "row_count": 0}
        excluded_values = {
            exclusion.get("value") for exclusion in exclusions
            if exclusion.get("column") == column and exclusion.get("operator") == "!="
        }
        if isinstance(value, list):
            values = [item for item in value[:MAX_FEDERATION_ROWS] if item not in excluded_values]
            if not values and value:
                return _empty_result({"excluded_filter_values": {column: value}, "requested_filters": filters or {}})
            filter_clauses.append({"terms": {column: values}})
        else:
            if value in excluded_values:
                return _empty_result({"excluded_filter_values": {column: value}, "requested_filters": filters or {}})
            filter_clauses.append({"term": {column: value}})
        applied.append((column, value))

    must: list[dict[str, Any]] = []
    if query:
        must.append({"multi_match": {"query": query, "fields": searchable}})
    body = {"size": max(1, min(int(limit), MAX_SOURCE_ROWS)), "query": {"bool": {"filter": filter_clauses, "must": must or [{"match_all": {}}]}}}
    _adapter = adapter_for_type(ref.source_type)
    rows = (_adapter.run_query if _adapter is not None else _opensearch_search)(
        body, url=str(ref.config.get("url")), index=index
    )
    fields = _field_ids_of(contract, sid, index)
    semantic_filters = [
        {"field": f"{sid}.{index}.{column}", "operator": "in" if isinstance(value, list) else "=", "value": value}
        for column, value in applied
    ]
    provenance = _provenance(
        tool_name="search_text", source=source, source_id=sid, source_type=ref.source_type, fields=fields,
        filters=[*_semantic_filters_from_exclusions(exclusions), *semantic_filters], user_filters=semantic_filters,
        rule_filters=_semantic_filters_from_exclusions(exclusions), joins=[], global_rules_applied=exclusions,
        query_body=body, row_count=len(rows),
    )
    return {
        "status": "ok",
        "source_boundary": source,
        "semantic_contract_id": _contract_id(),
        "provenance": provenance,
        "rows": _attach_citations(rows, provenance=provenance, source=source, prefix="os",
                                  identity_fields=identity_columns(contract, sid, index) or ["_id"]),
        "row_count": len(rows),
        "recorded_policy_context": relevant_recorded_policies(contract, source_id=sid, table=index, field_ids=set(fields)),
    }


def search_vector(query: str, source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    """Vector-search capability tool over a declared vector_search source. No
    business meaning ('policy'/'reviews') is assumed about the vectors."""
    gate = _contract_gate()
    if gate is not None:
        return gate
    sid, refusal = resolve_source_id("vector_search", source_id)
    if refusal is not None:
        return refusal
    contract = compile_semantic_contract()
    ref = _ref_by_id(sid)
    collection = _table_for_source(contract, sid)
    source = _source_boundary(sid, collection)
    _adapter = adapter_for_type(ref.source_type)
    rows = (_adapter.run_query if _adapter is not None else _vector_search)(
        query, url=str(ref.config.get("url")), collection=collection, limit=limit
    )
    fields = _field_ids_of(contract, sid, collection)
    provenance = _provenance(
        tool_name="search_vector", source=source, source_id=sid, source_type=ref.source_type, fields=fields,
        filters=[{"field": "vector_query", "operator": "similarity", "value": query}],
        user_filters=[{"field": "vector_query", "operator": "similarity", "value": query}],
        joins=[], global_rules_applied=[],
        query_body={"query": query, "limit": limit, "embedding_model": EMBEDDING_MODEL}, row_count=len(rows),
    )
    return {
        "status": "ok",
        "source_boundary": source,
        "semantic_contract_id": _contract_id(),
        "embedding_model": EMBEDDING_MODEL,
        "provenance": provenance,
        "rows": _attach_citations(rows, provenance=provenance, source=source, prefix="qd",
                                  identity_fields=identity_columns(contract, sid, collection) or ["id", "_id"]),
        "row_count": len(rows),
    }


_MONGO_ALLOWED_OPERATORS = {"eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists"}
_MONGO_OPERATOR_MAP = {
    "eq": "$eq",
    "ne": "$ne",
    "in": "$in",
    "nin": "$nin",
    "gt": "$gt",
    "gte": "$gte",
    "lt": "$lt",
    "lte": "$lte",
    "exists": "$exists",
}


def query_documents(
    source_id: str | None = None,
    filter: dict | None = None,
    projection: list | None = None,
    sort: list | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Document-query capability tool over a declared MongoDB document_query source.

    `filter` is keyed by declared field_id (bare column name accepted as alias);
    operators are constrained to safe read-only set. Global rule exclusions are
    applied automatically. Record citations use resolved identity/join roles.
    """
    gate = _contract_gate()
    if gate is not None:
        return gate
    sid, refusal = resolve_source_id("document_query", source_id)
    if refusal is not None:
        return refusal
    contract = compile_semantic_contract()
    ref = _ref_by_id(sid)
    collection = _table_for_source(contract, sid)
    source = _source_boundary(sid, collection)

    fields_by_id = _fields_of(contract, sid, collection)
    column_by_field_id = {field_id: str(field["column"]) for field_id, field in fields_by_id.items()}
    allowed_columns = set(column_by_field_id.values())

    def _resolve_filter_key(key: str) -> str | None:
        if key in column_by_field_id:  # declared field_id (preferred)
            return column_by_field_id[key]
        if key in allowed_columns:  # bare column alias (back-compat)
            return key
        return None

    def _refused(reason_code: str) -> dict[str, Any]:
        return {
            "status": "refused",
            "reason_code": reason_code,
            "source_boundary": source,
            "rows": [],
            "row_count": 0,
        }

    # --- GUARD: validate filter keys and operators --------------------------
    for key, value in (filter or {}).items():
        # No Mongo special keys starting with "$"
        if key.startswith("$"):
            return _refused("not_read_only")
        if _resolve_filter_key(key) is None:
            return _refused("field_not_allowed")
        if isinstance(value, dict):
            for op_key, op_val in value.items():
                if op_key.startswith("$"):
                    return _refused("not_read_only")
                if op_key not in _MONGO_ALLOWED_OPERATORS:
                    return _refused("operator_not_allowed")

    # --- GUARD: validate projection fields ---------------------------------
    for field in (projection or []):
        if _resolve_filter_key(str(field)) is None:
            return _refused("field_not_allowed")

    # --- GUARD: validate sort fields ---------------------------------------
    for sort_item in (sort or []):
        sort_field = sort_item[0] if isinstance(sort_item, (list, tuple)) else str(sort_item)
        if _resolve_filter_key(str(sort_field)) is None:
            return _refused("field_not_allowed")

    # --- Apply global rule exclusions (read-only enforcement of blacklist) -
    exclusions = _exclusions_for_source_table(sid, collection)
    # Collect every filter clause separately, then combine with $and, so a user
    # filter can NEVER overwrite a rule exclusion on the same column (blacklist
    # bypass). Each clause is a single-column dict.
    clauses: list[dict[str, Any]] = []
    used_columns: set[str] = set()
    global_rules_applied: list[dict[str, Any]] = []
    for exclusion in exclusions:
        if exclusion.get("operator") == "!=":
            col = str(exclusion.get("column", ""))
            clauses.append({col: {"$ne": exclusion.get("value")}})
            used_columns.add(col)
            global_rules_applied.append(exclusion)

    # --- Translate user filter to real Mongo filter clauses ----------------
    user_filter_clauses: list[dict[str, Any]] = []
    for key, value in (filter or {}).items():
        column = _resolve_filter_key(key)
        used_columns.add(str(column))
        if isinstance(value, dict):
            translated: dict[str, Any] = {}
            for op_key, op_val in value.items():
                mongo_op = _MONGO_OPERATOR_MAP.get(op_key, f"${op_key}")
                translated[mongo_op] = op_val
            clauses.append({column: translated})
            user_filter_clauses.append({"field": f"{sid}.{collection}.{column}", "operator": list(value.keys())[0] if value else "eq", "value": value})
        else:
            clauses.append({column: value})
            user_filter_clauses.append({"field": f"{sid}.{collection}.{column}", "operator": "eq", "value": value})

    # Combine: $and preserves every clause (exclusions cannot be dropped).
    mongo_filter: dict[str, Any] = {"$and": clauses} if len(clauses) > 1 else (clauses[0] if clauses else {})

    # --- Translate projection and sort -------------------------------------
    mongo_projection: dict[str, int] | None = None
    if projection:
        mongo_projection = {_resolve_filter_key(str(f)) or str(f): 1 for f in projection}

    mongo_sort: list[list[Any]] | None = None
    if sort:
        mongo_sort = []
        for sort_item in sort:
            if isinstance(sort_item, (list, tuple)) and len(sort_item) >= 2:
                sf = _resolve_filter_key(str(sort_item[0])) or str(sort_item[0])
                direction = int(sort_item[1])
            else:
                sf = _resolve_filter_key(str(sort_item)) or str(sort_item)
                direction = 1
            mongo_sort.append([sf, direction])

    # --- Execute query via adapter -----------------------------------------
    effective_limit = min(int(limit), MAX_SOURCE_ROWS)
    rows = adapter_for_type(ref.source_type).run_query(
        {
            "collection": collection,
            "filter": mongo_filter,
            "projection": mongo_projection,
            "sort": mongo_sort,
        },
        ref=ref,
        limit=effective_limit,
    )

    # --- Build provenance and return ---------------------------------------
    used_field_ids = sorted(
        {
            field_id
            for field_id, field in fields_by_id.items()
            if str(field.get("column", "")) in used_columns or str(field.get("column", "")) in (mongo_projection or {})
        }
    )
    exclusion_semantic_filters = _semantic_filters_from_exclusions(exclusions)
    all_filters = [*exclusion_semantic_filters, *user_filter_clauses]

    provenance = _provenance(
        tool_name="query_documents",
        source=source,
        source_id=sid,
        source_type=ref.source_type,
        fields=sorted(used_field_ids),
        filters=all_filters,
        user_filters=user_filter_clauses,
        rule_filters=exclusion_semantic_filters,
        joins=[],
        global_rules_applied=global_rules_applied,
        query_body={
            "collection": collection,
            "filter": mongo_filter,
            "projection": projection,
            "limit": effective_limit,
        },
        row_count=len(rows),
    )
    return {
        "status": "ok",
        "source_boundary": source,
        "semantic_contract_id": _contract_id(),
        "provenance": provenance,
        "rows": _attach_citations(
            rows,
            provenance=provenance,
            source=source,
            prefix="mg",
            identity_fields=identity_columns(contract, sid, collection) or ["_id"],
        ),
        "row_count": len(rows),
    }


def execute_semantic_query(plan: dict[str, Any], metric_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
    """Generic alias for execute_postgres_semantic_query.

    Routing is capability-based (structured_query), so this works against any
    structured source (Postgres, Snowflake, ...), not just Postgres.
    """
    return execute_postgres_semantic_query(plan, metric_id=metric_id, source_id=source_id)


def run_guarded_sql(
    sql: str,
    limit: int = 50,
    purpose: dict[str, Any] | None = None,
    citation_mode: str = "exploratory",
    source_id: str | None = None,
) -> dict[str, Any]:
    """Generic alias for run_guarded_postgres_sql (structured_query capability)."""
    return run_guarded_postgres_sql(sql, limit=limit, purpose=purpose, citation_mode=citation_mode, source_id=source_id)


def register_tools(mcp: Any) -> None:
    """Register the governed, capability-generic MCP tool surface.

    The ``*_postgres_*`` tool names are retained as compatibility aliases of the
    generic structured-query tools; both dispatch to the same routing.
    """
    for tool in (
        list_sources,
        get_semantic_contract,
        generate_semantic_json,
        health_check_sources,
        run_guarded_sql,
        run_guarded_postgres_sql,
        execute_semantic_query,
        execute_postgres_semantic_query,
        search_text,
        search_vector,
        query_documents,
        combine_slices,
        validate_analysis_request,
        validate_cited_evidence_packet,
    ):
        # Dispatch chain (innermost -> outermost):
        #   rbac_gate    enforce the configured role (no-op unless RECOSEARCH_ROLE)
        #   mask_result  mask sensitive/PII columns for the role (no-op unless ACL applies)
        #   traced_tool  record one span w/ role + session.id (no-op unless tracing)
        #   stamp_trace_id  add trace_id to the response envelope (always on)
        # mask is inside tracing so spans record MASKED rows (PII doesn't leak to
        # traces); gate is innermost so denials are captured; stamp is outermost.
        mcp.tool()(stamp_trace_id(traced_tool(mask_result(rbac_gate(tool)))))
