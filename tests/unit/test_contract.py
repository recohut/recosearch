"""Offline contract-hardening tests.

Run without live Postgres/OpenSearch/Qdrant: exercise the compile, validation,
freshness, and runtime-gating logic against declared inputs and injected broken inputs.
"""
from __future__ import annotations

from recosearch import federation, tools
from recosearch.config import _source_refs, validate_source_config
from recosearch.contract import (
    ValidatedContract,
    compile_semantic_contract,
    compile_with_issues,
    validated_contract,
)
from recosearch.errors import SEVERITY_ERROR, ContractIssue
from recosearch.scenario import load_scenario, validate_scenario


def _semantic_codes(semantic_text: str) -> set[str]:
    _contract, issues = compile_with_issues(semantic_text=semantic_text, source_refs=_source_refs())
    return {issue.code for issue in issues}


def _config_codes(config_text: str) -> set[str]:
    return {issue.code for issue in validate_source_config(config_text)}


# --- positive baseline -------------------------------------------------------

def test_declared_inputs_compile_clean() -> None:
    vc = validated_contract()
    assert vc.is_valid
    assert vc.errors == []
    assert vc.contract["version"] == "1.0"
    assert vc.contract["contract_hash"].startswith("sha256:")
    assert vc.contract.get("exclusions")


def test_contract_hash_is_deterministic() -> None:
    a = compile_semantic_contract()["contract_hash"]
    b = compile_semantic_contract()["contract_hash"]
    assert a == b


# --- scenario manifest -------------------------------------------------------

def test_declared_scenario_is_clean() -> None:
    assert [issue for issue in validate_scenario() if issue.is_error] == []


def test_scenario_identity_comes_from_manifest() -> None:
    custom = "scenario:\n  scenario_id: demo_x\n  name: Demo X\n  mcp_name: demo-x\n"
    scenario = load_scenario(custom)
    assert scenario.dataset_id == "demo_x"
    assert scenario.artifact_id == "demo_x.semantic"  # derived default
    contract, _issues = compile_with_issues(
        semantic_text="# dimensions\n- novamart_postgres.orders.order_id: x\n",
        source_refs=_source_refs(),
        scenario_text=custom,
    )
    assert contract["artifact_id"] == "demo_x.semantic"
    assert contract["dataset_id"] == "demo_x"
    assert contract["name"] == "Demo X"


def test_incomplete_scenario_identity_is_error() -> None:
    codes = {issue.code for issue in validate_scenario("scenario:\n  name: X only\n")}
    assert "scenario_identity_incomplete" in codes


def test_missing_scenario_block_is_error() -> None:
    assert "scenario_manifest_missing" in {issue.code for issue in validate_scenario("foo: bar\n")}


# --- semantic.md negative cases (one per issue code) -------------------------

def test_unknown_section_is_error() -> None:
    assert "unknown_section" in _semantic_codes("# dimensons\n- novamart_postgres.orders.order_id: x\n")


def test_bullet_outside_section_is_error() -> None:
    assert "bullet_ignored" in _semantic_codes("- orphan bullet before any section\n")


def test_malformed_field_token_is_error() -> None:
    assert "malformed_field_token" in _semantic_codes("# dimensions\n- not_a_triple: desc\n")


def test_malformed_metric_is_error() -> None:
    assert "malformed_metric" in _semantic_codes("# metrics\n- revenue without a colon separator\n")


def test_malformed_relation_is_error() -> None:
    assert "malformed_relation" in _semantic_codes("# relations\n- novamart_postgres.orders.order_id\n")


def test_unknown_source_is_error() -> None:
    assert "unknown_source" in _semantic_codes("# dimensions\n- rs99_unknown.orders.order_id: x\n")


def test_duplicate_field_id_is_error() -> None:
    text = "# dimensions\n- novamart_postgres.orders.order_id: a\n- novamart_postgres.orders.order_id: b\n"
    assert "duplicate_field_id" in _semantic_codes(text)


def test_metric_id_collision_is_error() -> None:
    assert "metric_id_collision" in _semantic_codes("# metrics\n- Net Revenue: a\n- net revenue: b\n")


def test_relation_references_undeclared_field_is_error() -> None:
    text = (
        "# dimensions\n- novamart_postgres.orders.order_id: a\n"
        "# relations\n- novamart_postgres.orders.order_id = novamart_postgres.products.does_not_exist\n"
    )
    assert "relation_references_undeclared_field" in _semantic_codes(text)


def test_table_in_multiple_sources_is_error() -> None:
    text = "# dimensions\n- novamart_postgres.shared.a: x\n- novamart_opensearch.shared.b: y\n"
    assert "table_in_multiple_sources" in _semantic_codes(text)


def test_enforceable_rule_not_compiled_is_error() -> None:
    assert "enforceable_rule_not_compiled" in _semantic_codes("# rules\n- Ignore widget WIDG from all calculations\n")


def test_presence_errors_for_missing_sections() -> None:
    codes = _semantic_codes("# metrics\n- delivered revenue: sum of total\n")
    assert "no_dimensions" in codes
    assert "no_measures" in codes
    # 3 sources are declared, so missing relations is an error here.
    assert "no_relations" in codes


# --- source_config.yaml negative cases ---------------------------------------

def test_config_duplicate_yaml_key_is_error() -> None:
    text = "sources:\n  postgres:\n    id: a\n    id: b\n    host: h\n    port: 5\n    database: d\n"
    assert "config_duplicate_yaml_key" in _config_codes(text)


def test_config_unknown_source_type_is_error() -> None:
    assert "config_unknown_source_type" in _config_codes("sources:\n  mongo:\n    id: m\n")


def test_config_missing_required_key_is_error() -> None:
    assert "config_missing_required_key" in _config_codes("sources:\n  postgres:\n    id: p\n")


def test_config_malformed_port_is_error() -> None:
    text = "sources:\n  postgres:\n    id: p\n    host: localhost\n    port: notaport\n    database: db\n"
    assert "config_malformed_port" in _config_codes(text)


def test_config_malformed_url_is_error() -> None:
    text = "sources:\n  opensearch:\n    id: o\n    url: not a url\n    index: idx\n"
    assert "config_malformed_url" in _config_codes(text)


def test_config_empty_source_id_is_error() -> None:
    text = "sources:\n  postgres:\n    host: localhost\n    port: 5432\n    database: db\n"
    assert "config_empty_source_id" in _config_codes(text)


def test_config_no_sources_is_error() -> None:
    assert "config_no_sources" in _config_codes("foo: bar\n")


def test_declared_source_config_is_clean() -> None:
    assert [i for i in validate_source_config() if i.is_error] == []


# --- freshness ---------------------------------------------------------------

def test_semantic_json_is_fresh() -> None:
    assert tools.check_semantic_json_fresh()["fresh"] is True


def test_freshness_detects_drift(monkeypatch) -> None:
    drifted = {**compile_semantic_contract(), "injected_drift": True}
    monkeypatch.setattr(tools, "compile_semantic_contract", lambda: drifted)
    result = tools.check_semantic_json_fresh()
    assert result["fresh"] is False


# --- runtime gating ----------------------------------------------------------

def _invalid_contract() -> ValidatedContract:
    return ValidatedContract(contract={}, issues=[ContractIssue("forced", SEVERITY_ERROR, "test", "forced invalid")])


def test_governed_postgres_tools_refuse_on_invalid_contract(monkeypatch) -> None:
    monkeypatch.setattr(tools, "validated_contract", _invalid_contract)
    for result in (
        tools.run_guarded_postgres_sql("SELECT 1"),
        tools.execute_postgres_semantic_query({"select": []}),
        tools.search_text(),
        tools.search_vector("anything"),
    ):
        assert result["status"] == "refused"
        assert result["reason_code"] == "contract_invalid"


def test_combine_slices_refuses_on_invalid_contract(monkeypatch) -> None:
    monkeypatch.setattr(federation, "validated_contract", _invalid_contract)
    result = federation.combine_slices([], [], left_key="a", right_key="b")
    assert result["status"] == "refused"
    assert result["reason_code"] == "contract_invalid"
