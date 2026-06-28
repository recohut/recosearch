from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

import sqlglot
from sqlglot import exp

from ..config import _postgres_ref
from ..contract import (
    _declared_relation_pairs,
    _field_index,
    _global_rule_filters_for_tables,
    _postgres_field,
    _source_ids_with_capability,
    compile_semantic_contract,
)
from ..errors import BoundaryError
from ..json_utils import _json_safe
from ..settings import MAX_FEDERATION_ROWS, MAX_SOURCE_ROWS

# Server-side functions refused by the read-only guard: file read/write, DoS
# (sleep), and outbound/admin calls. These run independently of the table/column
# allowlists, so they must be blocked by name (DB-user privilege is the backstop).
_FORBIDDEN_SQL_FUNCTIONS = frozenset({
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_read_server_files", "pg_logdir_ls",
    "lo_import", "lo_export",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "dblink", "dblink_exec", "dblink_connect",
    "set_config", "pg_terminate_backend", "pg_cancel_backend",
    "query_to_xml", "copy",
})

def _postgres_connection(ref: Any | None = None):
    # Lazy import so the package (and validate_postgres_sql, which is sqlglot-only)
    # imports even when the optional psycopg2 driver is absent — e.g. a zero-infra
    # install that only pulls the duckdb extra.
    import psycopg2  # noqa: PLC0415

    cfg = (ref or _postgres_ref()).config
    return psycopg2.connect(
        host=cfg.get("host"),
        port=int(cfg.get("port")),
        dbname=cfg.get("database"),
        user=cfg.get("user"),
        password=cfg.get("password"),
    )

def _fetch_postgres(sql: str, params: Iterable[Any] = (), *, limit: int = MAX_SOURCE_ROWS, ref: Any | None = None) -> list[dict[str, Any]]:
    params = list(params)
    guard = validate_postgres_sql(sql, allow_parameterized_exclusions=bool(params))
    if guard["decision"] != "allow":
        raise BoundaryError(f"postgres SQL refused: {guard['reason_code']}")
    bounded_limit = max(1, min(int(limit), MAX_SOURCE_ROWS))
    cleaned = sql.strip().rstrip(";")
    with _postgres_connection(ref) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM ({cleaned}) AS guarded_query LIMIT %s", [*params, bounded_limit])
            columns = [desc[0] for desc in cur.description]
            return [_json_safe(dict(zip(columns, row))) for row in cur.fetchall()]

def _sql_contains_exclusion(
    sql: str,
    exclusion: Mapping[str, Any],
    *,
    allow_parameterized: bool = False,
) -> bool:
    column = re.escape(str(exclusion.get("column") or ""))
    value = re.escape(str(exclusion.get("value") or "").casefold())
    operator = str(exclusion.get("operator") or "")
    lowered = sql.casefold()
    if not column or not value:
        return False
    if operator == "!=":
        parameterized_match = allow_parameterized and bool(
            re.search(rf"\b{column}\b\s*(?:!=|<>)\s*%s", lowered)
            or re.search(rf"%s\s*(?:!=|<>)\s*\b{column}\b", lowered)
        )
        return bool(
            parameterized_match
            or re.search(rf"\b{column}\b\s*(?:!=|<>)\s*'?{value}'?", lowered)
            or re.search(rf"'?{value}'?\s*(?:!=|<>)\s*\b{column}\b", lowered)
        )
    return False

def _suggested_tools_for_source_type(source_type: str | None) -> list[str]:
    # Derived from declared storage capabilities, not source-type business roles.
    from .. import adapters as _adapters_pkg
    return _adapters_pkg.suggested_tools_for(str(source_type or ""))

def _field_context(contract: Mapping[str, Any], field_id: str) -> dict[str, Any]:
    field = _field_index(contract).get(field_id, {})
    source_id = str(field.get("source") or "")
    source = contract.get("sources", {}).get(source_id, {})
    return {
        "field": field_id,
        "source": source_id or None,
        "source_type": source.get("type") if isinstance(source, Mapping) else None,
        "table": field.get("table"),
        "column": field.get("column"),
    }

def _relations_for_rejected_tables(
    contract: Mapping[str, Any],
    bad_tables: Iterable[str],
) -> list[dict[str, Any]]:
    bad_table_set = set(bad_tables)
    relations: list[dict[str, Any]] = []
    for relation in contract.get("relations", []):
        if not isinstance(relation, Mapping):
            continue
        left = _field_context(contract, str(relation.get("left") or ""))
        right = _field_context(contract, str(relation.get("right") or ""))
        if left.get("table") in bad_table_set or right.get("table") in bad_table_set:
            relations.append({"left": left, "right": right})
    return relations

def _rejected_table_context(contract: Mapping[str, Any], table: str) -> dict[str, Any]:
    table_info = contract.get("tables", {}).get(table)
    source_id = table_info.get("source") if isinstance(table_info, Mapping) else None
    source = contract.get("sources", {}).get(str(source_id), {}) if source_id else {}
    source_type = source.get("type") if isinstance(source, Mapping) else None
    return {
        "table": table,
        "source": source_id,
        "source_type": source_type,
        "suggested_tools": _suggested_tools_for_source_type(str(source_type) if source_type else None),
    }

def validate_postgres_sql(sql: str, *, allow_parameterized_exclusions: bool = False, dialect: str = "postgres") -> dict[str, Any]:
    contract = compile_semantic_contract()
    postgres_source_ids = set(_source_ids_with_capability(contract, "structured_query"))
    postgres_tables = {
        table: set(info["column_names"])
        for table, info in contract["tables"].items()
        if info["source"] in postgres_source_ids
    }
    lowered = sql.casefold()
    if re.search(r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy)\b", lowered):
        return {"decision": "refuse", "reason_code": "mutating_sql", "execution_allowed": False}
    if not re.match(r"^\s*(select|with)\b", lowered):
        return {"decision": "refuse", "reason_code": "not_read_only_select", "execution_allowed": False}
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except Exception as exc:
        return {
            "decision": "refuse",
            "reason_code": "sql_parse_failed",
            "execution_allowed": False,
            "error": str(exc),
        }

    tables = sorted({table.name for table in parsed.find_all(exp.Table)})

    # Server-side functions that read files, sleep (DoS), or reach out can run
    # even with a valid FROM, bypassing the table/column allowlists. Refuse them
    # anywhere in the statement (incl. inside CTEs/subqueries). DB-user privilege
    # is the backstop, but the guard must not depend on it.
    called_functions = {
        fn.name.casefold()
        for fn in parsed.find_all(exp.Anonymous)
        if fn.name
    }
    forbidden = sorted(called_functions & _FORBIDDEN_SQL_FUNCTIONS)
    if forbidden:
        return {
            "decision": "refuse",
            "reason_code": "forbidden_function",
            "execution_allowed": False,
            "forbidden_functions": forbidden,
        }

    # A governed data query must read from at least one declared table. A SELECT
    # with no table source (e.g. `SELECT pg_read_file(...)`, `SELECT version()`,
    # `SELECT current_user`) is not a data read and dodges the table/column
    # allowlists, so it is refused.
    if not tables:
        return {
            "decision": "refuse",
            "reason_code": "no_table_source",
            "execution_allowed": False,
        }

    bad_tables = [table for table in tables if table not in postgres_tables]
    if bad_tables:
        return {
            "decision": "refuse",
            "reason_code": "table_not_allowed",
            "execution_allowed": False,
            "bad_tables": bad_tables,
            "allowed_postgres_tables": sorted(postgres_tables),
            "rejected_tables": [_rejected_table_context(contract, table) for table in bad_tables],
            "declared_cross_source_relations": _relations_for_rejected_tables(contract, bad_tables),
        }

    alias_to_table = {
        table.alias_or_name: table.name
        for table in parsed.find_all(exp.Table)
        if table.name in postgres_tables
    }
    select_aliases = {
        alias.alias
        for alias in parsed.find_all(exp.Alias)
        if alias.alias
    }
    all_columns = set().union(*postgres_tables.values()) if postgres_tables else set()
    bad_columns: list[str] = []
    for column in parsed.find_all(exp.Column):
        if column.name == "*":
            continue
        table_name = alias_to_table.get(column.table, column.table) if column.table else None
        if table_name:
            if table_name in postgres_tables and column.name not in postgres_tables[table_name]:
                bad_columns.append(f"{table_name}.{column.name}")
        elif column.name not in all_columns and column.name not in select_aliases:
            bad_columns.append(column.name)
    if bad_columns:
        return {
            "decision": "refuse",
            "reason_code": "column_not_allowed",
            "execution_allowed": False,
            "bad_columns": sorted(set(bad_columns)),
        }

    missing_exclusions = [
        exclusion
        for exclusion in contract.get("exclusions", [])
        if isinstance(exclusion, Mapping)
        and exclusion.get("source") in postgres_source_ids
        and exclusion.get("table") in tables
        and not _sql_contains_exclusion(
            sql,
            exclusion,
            allow_parameterized=allow_parameterized_exclusions,
        )
    ]
    if missing_exclusions:
        return {
            "decision": "refuse",
            "reason_code": "missing_global_exclusion",
            "execution_allowed": False,
            "required_exclusions": _json_safe(missing_exclusions),
        }

    return {
        "decision": "allow",
        "reason_code": None,
        "execution_allowed": True,
        "tables": tables,
    }

def _postgres_sql_shape(sql: str, dialect: str = "postgres") -> dict[str, Any]:
    contract = compile_semantic_contract()
    postgres_source_ids = set(_source_ids_with_capability(contract, "structured_query"))
    postgres_tables = {
        table: info
        for table, info in contract["tables"].items()
        if info["source"] in postgres_source_ids
    }
    parsed = sqlglot.parse_one(sql, read=dialect)
    tables = sorted({table.name for table in parsed.find_all(exp.Table)})
    alias_to_table = {
        table.alias_or_name: table.name
        for table in parsed.find_all(exp.Table)
        if table.name in postgres_tables
    }
    field_ids: set[str] = set()
    column_refs: set[str] = set()
    for column in parsed.find_all(exp.Column):
        if column.name == "*":
            continue
        table_name = alias_to_table.get(column.table, column.table) if column.table else None
        if table_name:
            column_refs.add(f"{table_name}.{column.name}")
            if table_name in postgres_tables and column.name in postgres_tables[table_name]["columns"]:
                field_ids.add(f"{postgres_tables[table_name]['source']}.{table_name}.{column.name}")
        else:
            for table, info in postgres_tables.items():
                if table in tables and column.name in info["columns"]:
                    column_refs.add(f"{table}.{column.name}")
                    field_ids.add(f"{info['source']}.{table}.{column.name}")

    joins: list[str] = []
    for join in parsed.find_all(exp.Join):
        joins.append(join.sql(dialect=dialect))
    where = parsed.find(exp.Where)
    where_sql = where.sql(dialect=dialect) if where else ""
    lowered = sql.casefold()
    aggregate_functions = sorted(set(re.findall(r"\b(sum|avg|count|min|max)\s*\(", lowered)))
    return {
        "tables": tables,
        "field_ids": sorted(field_ids),
        "column_refs": sorted(column_refs),
        "joins": joins,
        "where_sql": where_sql,
        "aggregate_functions": aggregate_functions,
    }

def _postgres_purpose_validation(
    sql: str,
    purpose: Mapping[str, Any] | None,
    citation_mode: str,
    dialect: str = "postgres",
) -> dict[str, Any]:
    normalized_mode = str(citation_mode or "exploratory")
    if normalized_mode not in {"exploratory", "claim_support"}:
        return {
            "decision": "refuse",
            "reason_code": "unsupported_citation_mode",
            "execution_allowed": False,
            "may_support_final_answer": False,
        }
    if normalized_mode == "exploratory":
        return {
            "decision": "allow",
            "reason_code": None,
            "execution_allowed": True,
            "semantic_purpose_valid": False,
            "may_support_final_answer": False,
            "shape": _postgres_sql_shape(sql, dialect=dialect),
        }
    if not isinstance(purpose, Mapping):
        return {
            "decision": "refuse",
            "reason_code": "missing_claim_support_purpose",
            "execution_allowed": False,
            "may_support_final_answer": False,
        }

    shape = _postgres_sql_shape(sql, dialect=dialect)
    return {
        "decision": "allow",
        "reason_code": None,
        "execution_allowed": True,
        "semantic_purpose_valid": None,
        "intent_recorded": True,
        "intent_verification": "not_governed_by_mcp",
        "declared_purpose": _json_safe(dict(purpose)),
        "may_support_final_answer": True,
        "shape": shape,
    }

def _sql_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise BoundaryError(f"unsafe SQL identifier {value!r}")
    return value

def _field_sql(field_id: str, aliases: Mapping[str, str], contract: Mapping[str, Any]) -> str:
    field = _postgres_field(field_id, contract)
    table = str(field["table"])
    column = str(field["column"])
    return f"{aliases[table]}.{_sql_identifier(column)}"

def _normalize_plan_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise BoundaryError("plan list fields must be arrays")

def _compile_postgres_semantic_query(plan: Mapping[str, Any], dialect: str = "postgres") -> tuple[str, list[Any], dict[str, Any]]:
    if not isinstance(plan, Mapping):
        raise BoundaryError("plan must be an object")
    contract = compile_semantic_contract()
    fields = _field_index(contract)
    selected = _normalize_plan_list(plan.get("select"))
    if not selected:
        raise BoundaryError("plan.select must contain at least one field")

    joins = _normalize_plan_list(plan.get("joins"))
    filters = _normalize_plan_list(plan.get("filters"))
    group_by = [str(item) for item in _normalize_plan_list(plan.get("group_by"))]
    order_by = _normalize_plan_list(plan.get("order_by"))
    apply_global_rules = plan.get("apply_global_rules") is not False

    referenced_fields: set[str] = set(group_by)
    for item in selected:
        if not isinstance(item, Mapping):
            raise BoundaryError("select entries must be objects")
        referenced_fields.add(str(item.get("field") or ""))
    for item in joins:
        if not isinstance(item, Mapping):
            raise BoundaryError("join entries must be objects")
        referenced_fields.add(str(item.get("left") or ""))
        referenced_fields.add(str(item.get("right") or ""))
    for item in filters:
        if not isinstance(item, Mapping):
            raise BoundaryError("filter entries must be objects")
        referenced_fields.add(str(item.get("field") or ""))

    referenced_fields.discard("")
    for field_id in referenced_fields:
        _postgres_field(field_id, contract)

    tables = sorted({str(fields[field_id]["table"]) for field_id in referenced_fields})
    if not tables:
        raise BoundaryError("no Postgres tables referenced")
    aliases = {table: f"t_{index}" for index, table in enumerate(tables)}

    select_sql: list[str] = []
    aggregate_present = False
    select_aliases: set[str] = set()
    for item in selected:
        field_id = str(item.get("field") or "")
        expr_sql = _field_sql(field_id, aliases, contract)
        aggregation = str(item.get("aggregation") or "").lower()
        if aggregation:
            if aggregation not in {"sum", "avg", "count", "min", "max"}:
                raise BoundaryError(f"unsupported aggregation {aggregation!r}")
            aggregate_present = True
            expr_sql = f"{aggregation.upper()}({expr_sql})"
        alias = str(item.get("alias") or fields[field_id]["column"])
        alias = _sql_identifier(alias)
        select_aliases.add(alias)
        select_sql.append(f"{expr_sql} AS {alias}")

    relation_pairs = _declared_relation_pairs(contract)
    join_clauses: list[str] = []
    joined_tables = {tables[0]}
    for join in joins:
        left = str(join.get("left") or "")
        right = str(join.get("right") or "")
        if (left, right) not in relation_pairs:
            raise BoundaryError(f"join {left} = {right} is not declared in semantic.md")
        left_field = _postgres_field(left, contract)
        right_field = _postgres_field(right, contract)
        left_table = str(left_field["table"])
        right_table = str(right_field["table"])
        if left_table == right_table:
            continue
        if left_table in joined_tables and right_table not in joined_tables:
            join_table = right_table
        elif right_table in joined_tables and left_table not in joined_tables:
            join_table = left_table
        else:
            join_table = right_table
        join_clauses.append(
            f"JOIN {_sql_identifier(join_table)} {aliases[join_table]} "
            f"ON {_field_sql(left, aliases, contract)} = {_field_sql(right, aliases, contract)}"
        )
        joined_tables.add(join_table)

    if len(tables) > 1 and len(joined_tables) != len(tables):
        raise BoundaryError("all referenced Postgres tables must be connected by declared joins")

    where_sql: list[str] = []
    params: list[Any] = []
    if apply_global_rules:
        for exclusion in contract.get("exclusions", []):
            if not isinstance(exclusion, dict) or exclusion.get("source") not in _source_ids_with_capability(contract, "structured_query"):
                continue
            table = str(exclusion.get("table") or "")
            column = str(exclusion.get("column") or "")
            if table in aliases and exclusion.get("operator") == "!=":
                where_sql.append(f"{aliases[table]}.{_sql_identifier(column)} != %s")
                params.append(str(exclusion.get("value")))

    for item in filters:
        field_id = str(item.get("field") or "")
        operator = str(item.get("operator") or "=").lower()
        field_expr = _field_sql(field_id, aliases, contract)
        if operator in {"=", "!=", ">", ">=", "<", "<="}:
            where_sql.append(f"{field_expr} {operator} %s")
            params.append(item.get("value"))
        elif operator == "in":
            values = item.get("value")
            if not isinstance(values, list) or not values:
                raise BoundaryError("in filters require a non-empty array value")
            where_sql.append(f"{field_expr} = ANY(%s)")
            params.append(values[:MAX_FEDERATION_ROWS])
        else:
            raise BoundaryError(f"unsupported filter operator {operator!r}")

    group_sql = ""
    if group_by:
        group_exprs = [_field_sql(field_id, aliases, contract) for field_id in group_by]
        group_sql = "GROUP BY " + ", ".join(group_exprs)
    elif aggregate_present:
        non_aggregate_fields = [
            str(item.get("field") or "")
            for item in selected
            if isinstance(item, Mapping) and not item.get("aggregation")
        ]
        if non_aggregate_fields:
            raise BoundaryError("aggregate queries with non-aggregate fields require group_by")

    order_sql = ""
    if order_by:
        clauses: list[str] = []
        for item in order_by:
            if not isinstance(item, Mapping):
                raise BoundaryError("order_by entries must be objects")
            direction = str(item.get("direction") or "asc").lower()
            if direction not in {"asc", "desc"}:
                raise BoundaryError(f"unsupported order direction {direction!r}")
            order_field = str(item.get("field") or "")
            if order_field in select_aliases:
                order_expr = order_field
            else:
                order_expr = _field_sql(order_field, aliases, contract)
            clauses.append(f"{order_expr} {direction.upper()}")
        order_sql = "ORDER BY " + ", ".join(clauses)

    limit = max(1, min(int(plan.get("limit") or MAX_SOURCE_ROWS), MAX_SOURCE_ROWS))
    from_sql = f"FROM {_sql_identifier(tables[0])} {aliases[tables[0]]}"
    where_clause = "WHERE " + " AND ".join(where_sql) if where_sql else ""
    sql = "\n".join(
        part
        for part in [
            "SELECT " + ", ".join(select_sql),
            from_sql,
            *join_clauses,
            where_clause,
            group_sql,
            order_sql,
            f"LIMIT {limit}",
        ]
        if part
    )
    metadata = {
        "tables": tables,
        "aliases": aliases,
        "selected_fields": [str(item.get("field") or "") for item in selected if isinstance(item, Mapping)],
        "filter_fields": [str(item.get("field") or "") for item in filters if isinstance(item, Mapping)],
        "group_by": group_by,
        "order_by": _json_safe(order_by),
        "joins": _json_safe(joins),
        "global_rules_applied": apply_global_rules,
        "global_rule_filters": _global_rule_filters_for_tables(tables) if apply_global_rules else [],
        "limit": limit,
    }
    return sql, params, metadata


def _postgres_health_check(ref: Any | None = None) -> dict[str, Any]:
    """Minimal reachability probe: run 'SELECT 1 AS ok' and return the first row."""
    with _postgres_connection(ref) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
            columns = [desc[0] for desc in cur.description]
            return {"status": "ok", "sample": dict(zip(columns, row))}


from .base import SourceAdapter  # noqa: E402 — after all functions are defined

ADAPTER = SourceAdapter(
    source_type="postgres",
    capabilities=frozenset({"structured_query"}),
    run_query=_fetch_postgres,
    sql_dialect="postgres",
    health_check=_postgres_health_check,
    available=True,
    config_schema={
        "required": ["host", "port", "database"],
        "identifiers": ["database"],
        "allowed": ["id", "host", "port", "database", "user", "password"],
    },
)
