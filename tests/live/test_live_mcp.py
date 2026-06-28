from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Mapping

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from recosearch import mcp_server


def _contract() -> dict[str, Any]:
    return mcp_server.compile_semantic_contract()


def _source_id(source_type: str) -> str:
    ids = [
        source_id
        for source_id, source in _contract()["sources"].items()
        if source["type"] == source_type
    ]
    assert len(ids) == 1
    return ids[0]


def _source_table(source_type: str) -> str:
    contract = _contract()
    source = contract["sources"][_source_id(source_type)]
    table = source.get("index") or source.get("collection")
    if table:
        return str(table)
    tables = sorted(
        {
            field["table"]
            for field in _fields(source_type).values()
        }
    )
    assert tables
    return tables[0]


def _fields(source_type: str, table: str | None = None) -> dict[str, dict[str, Any]]:
    source_id = _source_id(source_type)
    result: dict[str, dict[str, Any]] = {}
    for field_id, field in {**_contract()["dimensions"], **_contract()["measures"]}.items():
        if field["source"] != source_id:
            continue
        if table is not None and field["table"] != table:
            continue
        result[field_id] = {**field, "field_id": field_id}
    return result


def _field_by_column(source_type: str, column_suffix: str, table: str | None = None) -> dict[str, Any]:
    matches = [
        field
        for field in _fields(source_type, table).values()
        if field["column"].endswith(column_suffix)
    ]
    assert matches
    return sorted(matches, key=lambda item: item["field_id"])[0]


def _field_by_description(source_type: str, *needles: str, table: str | None = None) -> dict[str, Any]:
    lowered = [needle.casefold() for needle in needles]
    for field in _fields(source_type, table).values():
        haystack = f"{field['column']} {field.get('description', '')}".casefold()
        if any(needle in haystack for needle in lowered):
            return field
    raise AssertionError(f"no {source_type} field matched {needles}")


def _first_measure(source_type: str, table: str | None = None) -> dict[str, Any]:
    source_id = _source_id(source_type)
    matches = [
        {**field, "field_id": field_id}
        for field_id, field in _contract()["measures"].items()
        if field["source"] == source_id and (table is None or field["table"] == table)
    ]
    assert matches
    return sorted(matches, key=lambda item: item["field_id"])[0]


def _postgres_exclusion() -> dict[str, Any]:
    source_id = _source_id("postgres")
    matches = [
        exclusion
        for exclusion in _contract().get("exclusions", [])
        if exclusion["source"] == source_id
    ]
    assert matches
    return matches[0]


def _opensearch_exclusion() -> dict[str, Any]:
    source_id = _source_id("opensearch")
    matches = [
        exclusion
        for exclusion in _contract().get("exclusions", [])
        if exclusion["source"] == source_id
    ]
    assert matches
    return matches[0]


def _sql_literal(value: Any) -> str:
    return str(value).replace("'", "''")


def _relation_between(left_type: str, right_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fields = {
        field["field_id"]: field
        for field in [*_fields(left_type).values(), *_fields(right_type).values()]
    }
    left_source = _source_id(left_type)
    right_source = _source_id(right_type)
    for relation in _contract()["relations"]:
        left = fields.get(relation["left"])
        right = fields.get(relation["right"])
        if not left or not right:
            continue
        if left["source"] == left_source and right["source"] == right_source:
            return left, right
        if left["source"] == right_source and right["source"] == left_source:
            return right, left
    raise AssertionError(f"no declared relation between {left_type} and {right_type}")


def test_compiles_contract_from_declared_sources() -> None:
    contract = _contract()
    listed_sources = mcp_server.list_sources()["sources"]

    assert set(contract["sources"]) == set(listed_sources)
    # Every declared source type must be in the adapter registry.
    from recosearch.config import registered_source_types
    assert all(source["type"] in registered_source_types() for source in contract["sources"].values())
    assert contract.get("metrics")
    assert "purpose_definitions" not in contract
    assert contract.get("exclusions")


def test_analysis_request_returns_contract_driven_clarifications() -> None:
    result = mcp_server.validate_analysis_request(
        {
            "analysis_goal": "broad_business_health_check",
            "source_scope": "all_declared_sources",
            "requires_decision": True,
        }
    )
    missing_inputs = {item["input"] for item in result["missing_inputs"]}
    questions = {item["question_id"] for item in result["suggested_clarification_questions"]}

    assert result["status"] == "clarification_needed"
    assert result["source_boundary"] == "semantic_contract_only"
    assert "metric_focus" in missing_inputs
    assert "time_window" in missing_inputs
    assert "cross_source_relation_fields" in missing_inputs
    assert "decision_intent" in missing_inputs
    assert questions == missing_inputs
    assert {source["source_id"] for source in result["available_options"]["sources"]} == set(_contract()["sources"])
    assert {
        metric["metric_id"]
        for metric in result["available_options"]["metrics"]
    } == set(_contract()["metrics"])
    assert result["available_options"]["declared_relation_fields"]


def test_analysis_request_allows_specific_single_source_plan() -> None:
    contract = _contract()
    postgres_source = _source_id("postgres")
    metric_id = sorted(contract["metrics"])[0]

    result = mcp_server.validate_analysis_request(
        {
            "analysis_goal": "specific_metric_check",
            "metric_ids": [metric_id],
            "expected_sources": [postgres_source],
            "time_window": {"mode": "all_time"},
        }
    )

    assert result["status"] == "ok"
    assert result["missing_inputs"] == []


def test_analysis_request_requires_text_focus_for_document_sources() -> None:
    qdrant_source = _source_id("qdrant")
    metric_id = sorted(_contract()["metrics"])[0]

    result = mcp_server.validate_analysis_request(
        {
            "analysis_goal": "policy_supported_metric_check",
            "metric_ids": [metric_id],
            "expected_sources": [qdrant_source],
            "time_window": {"mode": "all_time"},
        }
    )

    # Capability-driven: a vector_search source asks for clarification at the
    # capability level, NOT based on a hardcoded source name.
    assert result["status"] == "clarification_needed"
    assert {item["input"] for item in result["missing_inputs"]} == {"vector_query_focus"}


def test_live_sources_are_reachable() -> None:
    # Check only the live subset; declared sources without live connections are skipped.
    health = mcp_server.health_check_sources()
    live = {_source_id("postgres"), _source_id("opensearch"), _source_id("qdrant")}

    # The three local sources must be reachable. Snowflake is live too now,
    # but needs real credentials + network, so we don't require the overall status
    # to be "ok" here — only the core subset.
    assert live.issubset(set(health["results"]))
    assert all(health["results"][source_id]["status"] == "ok" for source_id in live)


def test_semantic_query_applies_compiled_global_exclusion() -> None:
    exclusion = _postgres_exclusion()
    measure = _first_measure("postgres", exclusion["table"])
    result = mcp_server.execute_postgres_semantic_query(
        {
            "select": [
                {"field": measure["field_id"], "aggregation": "sum", "alias": "metric_value"},
            ],
            "apply_global_rules": True,
            "limit": 10,
        }
    )

    assert result["status"] == "ok"
    assert result["metadata"]["global_rule_filters"]
    assert result["rows"][0]["_citation"]["may_support_final_answer"] is True


def test_sql_guard_refuses_missing_compiled_exclusion() -> None:
    exclusion = _postgres_exclusion()
    measure = _first_measure("postgres", exclusion["table"])
    result = mcp_server.run_guarded_postgres_sql(
        f"SELECT SUM({measure['column']}) AS metric_value FROM {exclusion['table']}"
    )

    assert result["status"] == "refused"
    assert result["guard"]["reason_code"] == "missing_global_exclusion"


def test_sql_guard_refuses_direct_excluded_value_read() -> None:
    exclusion = _postgres_exclusion()
    result = mcp_server.run_guarded_postgres_sql(
        f"SELECT {exclusion['column']} FROM {exclusion['table']} "
        f"WHERE {exclusion['column']} = '{_sql_literal(exclusion['value'])}'"
    )

    assert result["status"] == "refused"
    assert result["guard"]["reason_code"] == "missing_global_exclusion"


def test_sql_guard_explains_cross_source_table_refusal() -> None:
    postgres_table = _source_table("postgres")
    opensearch_table = _source_table("opensearch")
    result = mcp_server.run_guarded_postgres_sql(
        f"SELECT * FROM {postgres_table} JOIN {opensearch_table} ON 1 = 1"
    )
    guard = result["guard"]

    assert result["status"] == "refused"
    assert guard["reason_code"] == "table_not_allowed"
    assert postgres_table in guard["allowed_postgres_tables"]
    assert guard["rejected_tables"] == [
        {
            "table": opensearch_table,
            "source": _source_id("opensearch"),
            "source_type": "opensearch",
            "suggested_tools": ["search_text"],
        }
    ]
    assert guard["declared_cross_source_relations"]
    assert any(
        side["table"] == opensearch_table and side["source"] == _source_id("opensearch")
        for relation in guard["declared_cross_source_relations"]
        for side in (relation["left"], relation["right"])
    )


def test_semantic_query_cannot_disable_compiled_global_exclusion() -> None:
    exclusion = _postgres_exclusion()
    result = mcp_server.execute_postgres_semantic_query(
        {
            "select": [
                {"field": exclusion["field_id"], "alias": "excluded_dimension"},
            ],
            "apply_global_rules": False,
            "limit": 10,
        }
    )

    assert result["status"] == "refused"
    assert "missing_global_exclusion" in result["error"]


def test_raw_sql_exploratory_rows_are_not_final_answer_evidence() -> None:
    exclusion = _postgres_exclusion()
    result = mcp_server.run_guarded_postgres_sql(
        f"SELECT {exclusion['column']} FROM {exclusion['table']} "
        f"WHERE {exclusion['column']} != '{_sql_literal(exclusion['value'])}' LIMIT 1"
    )

    assert result["status"] == "ok"
    assert result["citation_mode"] == "exploratory"
    assert result["rows"][0]["_citation"]["may_support_final_answer"] is False

    validation = mcp_server.validate_cited_evidence_packet(
        {
            "claims": [
                {
                    "claim": "An exploratory row is being used as a business finding.",
                    "claim_type": "custom",
                    "required_sources": [_source_id("postgres")],
                    "evidence_ids": [result["rows"][0]["_citation"]["evidence_id"]],
                }
            ],
            "tool_results": [result],
        }
    )

    assert validation["valid"] is False
    assert validation["errors"][0]["reason_code"] == "evidence_not_claim_supporting"


def test_raw_sql_claim_support_records_intent_and_returns_citations() -> None:
    exclusion = _postgres_exclusion()
    result = mcp_server.run_guarded_postgres_sql(
        f"""
        SELECT {exclusion['column']}, COUNT(*) AS row_count
        FROM {exclusion['table']}
        WHERE {exclusion['column']} != '{_sql_literal(exclusion['value'])}'
        GROUP BY {exclusion['column']}
        LIMIT 1
        """,
        citation_mode="claim_support",
        purpose={
            "claim_type": "row_count",
            "business_terms": ["row count"],
            "expected_sources": [_source_id("postgres")],
            "expected_fields": [exclusion["field_id"]],
            "required_filters": [
                {
                    "field": exclusion["field_id"],
                    "operator": "!=",
                    "value": exclusion["value"],
                }
            ],
        },
    )

    assert result["status"] == "ok"
    assert result["may_support_final_answer"] is True
    assert result["provenance"]["source"] == _source_id("postgres")
    assert result["rows"][0]["_citation"]["may_support_final_answer"] is True


def test_postgres_semantic_ranking_uses_declared_fields() -> None:
    exclusion = _postgres_exclusion()
    measure = _first_measure("postgres", exclusion["table"])
    result = mcp_server.execute_postgres_semantic_query(
        {
            "select": [
                {"field": exclusion["field_id"], "alias": "dimension_value"},
                {"field": measure["field_id"], "aggregation": "sum", "alias": "metric_value"},
            ],
            "group_by": [exclusion["field_id"]],
            "order_by": [{"field": "metric_value", "direction": "desc"}],
            "apply_global_rules": True,
            "limit": 10,
        }
    )

    assert result["status"] == "ok"
    assert result["rows"]
    assert all(row["dimension_value"] != exclusion["value"] for row in result["rows"])


def test_qdrant_ranked_policy_search_uses_declared_collection() -> None:
    result = mcp_server.search_vector("policy", limit=2)
    source = f"{_source_id('qdrant')}.{_source_table('qdrant')}"

    assert result["status"] == "ok"
    assert result["source_boundary"] == source
    assert result["rows"]
    assert result["rows"][0]["_citation"]["source"] == source
    if len(result["rows"]) > 1:
        assert result["rows"][0]["score"] >= result["rows"][1]["score"]


def test_text_search_applies_compiled_exclusion() -> None:
    exclusion = _opensearch_exclusion()
    direct = mcp_server.search_text(filters={exclusion["column"]: [exclusion["value"]]}, limit=20)
    broad = mcp_server.search_text(limit=50)

    assert direct["status"] == "ok"
    assert direct["rows"] == []
    assert direct["provenance"]["filters"][0]["operator"] == exclusion["operator"]
    assert broad["status"] == "ok"
    assert all(row[exclusion["column"]] != exclusion["value"] for row in broad["rows"])


def test_postgres_opensearch_federation_uses_declared_relation() -> None:
    postgres_field, opensearch_field = _relation_between("postgres", "opensearch")
    postgres_slice = mcp_server.execute_postgres_semantic_query(
        {
            "select": [
                {"field": postgres_field["field_id"], "alias": "join_key"},
            ],
            "apply_global_rules": True,
            "limit": 50,
        }
    )
    values = [row["join_key"] for row in postgres_slice["rows"]]
    opensearch_slice = mcp_server.search_text(
        filters={opensearch_field["column"]: values},
        limit=50,
    )
    combined = mcp_server.combine_slices(
        postgres_slice["rows"],
        opensearch_slice["rows"],
        left_key="join_key",
        right_key=opensearch_field["column"],
        limit=50,
    )

    assert postgres_slice["status"] == "ok"
    assert opensearch_slice["status"] == "ok"
    assert combined["status"] == "ok"
    assert combined["rows"]
    assert combined["rows"][0]["_citation"]["supporting_evidence_ids"]


def test_cross_source_evidence_packet_validates_declared_sources() -> None:
    postgres_field, opensearch_field = _relation_between("postgres", "opensearch")
    postgres_slice = mcp_server.execute_postgres_semantic_query(
        {
            "select": [{"field": postgres_field["field_id"], "alias": "join_key"}],
            "apply_global_rules": True,
            "limit": 50,
        }
    )
    opensearch_slice = mcp_server.search_text(
        filters={opensearch_field["column"]: [row["join_key"] for row in postgres_slice["rows"]]},
        limit=50,
    )
    policy_slice = mcp_server.search_vector("policy", limit=2)
    combined = mcp_server.combine_slices(
        postgres_slice["rows"],
        opensearch_slice["rows"],
        left_key="join_key",
        right_key=opensearch_field["column"],
        limit=20,
    )

    validation = mcp_server.validate_cited_evidence_packet(
        {
            "claims": [
                {
                    "claim": "A cross-source verdict is based on structured data, review evidence, and policy evidence.",
                    "claim_type": "cross_source_verdict",
                    "required_sources": [
                        _source_id("postgres"),
                        f"{_source_id('opensearch')}.{_source_table('opensearch')}",
                        f"{_source_id('qdrant')}.{_source_table('qdrant')}",
                    ],
                    "evidence_ids": [
                        combined["rows"][0]["_citation"]["evidence_id"],
                        policy_slice["rows"][0]["_citation"]["evidence_id"],
                    ],
                }
            ],
            "tool_results": [postgres_slice, opensearch_slice, policy_slice, combined],
        }
    )

    assert validation["valid"] is True


def test_mcp_stdio_smoke_lists_and_calls_live_tools() -> None:
    exclusion = _postgres_exclusion()
    measure = _first_measure("postgres", exclusion["table"])

    async def _run() -> None:
        params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "answer_business_question" not in tool_names
                assert "search_reviews" not in tool_names  # business-role tool names not exposed
                assert "search_policy_chunks" not in tool_names
                assert "execute_postgres_semantic_query" in tool_names
                assert "search_text" in tool_names
                assert "search_vector" in tool_names
                assert "validate_analysis_request" in tool_names
                assert "validate_cited_evidence_packet" in tool_names

                answer = await session.call_tool(
                    "execute_postgres_semantic_query",
                    {
                        "plan": {
                            "select": [
                                {"field": measure["field_id"], "aggregation": "sum", "alias": "metric_value"}
                            ],
                            "apply_global_rules": True,
                            "limit": 10,
                        }
                    },
                )
                payload = json.loads(answer.content[0].text)
                assert payload["status"] == "ok"
                assert payload["rows"][0]["_citation"]["may_support_final_answer"] is True

    asyncio.run(_run())
