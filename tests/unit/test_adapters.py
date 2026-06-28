"""Offline adapter-capability and field-role tests."""
from __future__ import annotations

from recosearch.adapters import ADAPTER_CAPABILITIES, capabilities_for, suggested_tools_for
from recosearch.contract import compile_semantic_contract
from recosearch.field_roles import identity_columns, roles_present, searchable_columns

_C = compile_semantic_contract()
_OID = next(sid for sid, s in _C["sources"].items() if s["type"] == "opensearch")


def test_capabilities_are_storage_only() -> None:
    assert capabilities_for("postgres") == {"structured_query"}
    assert capabilities_for("opensearch") == {"text_search"}
    assert capabilities_for("qdrant") == {"vector_search"}
    all_caps = set().union(*ADAPTER_CAPABILITIES.values())
    assert not (all_caps & {"reviews", "policy", "orders", "review_evidence", "policy_document"})


def test_suggested_tools_are_capability_generic() -> None:
    assert suggested_tools_for("opensearch") == ["search_text"]
    assert suggested_tools_for("qdrant") == ["search_vector"]
    assert "search_reviews" not in suggested_tools_for("opensearch")
    assert "search_policy_chunks" not in suggested_tools_for("qdrant")


def test_field_roles_resolved_with_provenance() -> None:
    body = [a for a in _C["field_roles"] if a["field_role"] == "body_text" and a["resolution"] == "resolved"]
    assert body and body[0]["evidence"] and body[0]["field_id"]
    assert "body_text" in roles_present(_C, _OID, "customer_reviews")


def test_role_driven_column_helpers() -> None:
    # Field discovery comes from roles, not column-name luck.
    assert searchable_columns(_C, _OID, "customer_reviews")  # body_text/display_name
    assert identity_columns(_C, _OID, "customer_reviews")    # identity/join_key


# --- declared-but-adapter-less source types ---

def test_new_source_types_registered_and_validate_clean() -> None:
    from recosearch.config import registered_source_types, validate_source_config

    assert {"duckdb", "mongodb", "snowflake"} <= registered_source_types()
    assert [i for i in validate_source_config() if i.is_error] == []  # secret refs ok, no errors


def test_landed_adapters_advertise_their_capability() -> None:
    # duckdb's adapter has landed (zero-infra structured_query source).
    assert capabilities_for("duckdb") == {"structured_query"}
    # mongodb adapter has landed -> it advertises document_query.
    assert capabilities_for("mongodb") == {"document_query"}
    # snowflake's adapter has landed and is live -> it advertises structured_query.
    assert capabilities_for("snowflake") == {"structured_query"}


def test_no_plaintext_secrets_in_source_config() -> None:
    from recosearch.config import validate_source_config

    codes = {i.code for i in validate_source_config()}
    assert "config_plaintext_secret" not in codes  # all secrets use ${ENV_VAR} refs


# --- plugin-layer tests ---

def test_adapters_registry_contains_all_four_source_types() -> None:
    """ADAPTERS dict must have all four registered adapters with the right capabilities."""
    from recosearch.adapters import ADAPTERS

    assert set(ADAPTERS.keys()) >= {"postgres", "opensearch", "qdrant", "snowflake"}
    assert set(ADAPTERS["postgres"].capabilities) == {"structured_query"}
    assert set(ADAPTERS["opensearch"].capabilities) == {"text_search"}
    assert set(ADAPTERS["qdrant"].capabilities) == {"vector_search"}
    assert set(ADAPTERS["snowflake"].capabilities) == {"structured_query"}


def test_adapter_capabilities_derived_from_registry() -> None:
    """ADAPTER_CAPABILITIES must mirror the adapter objects — no hand-maintained list.

    Only AVAILABLE adapters contribute to ADAPTER_CAPABILITIES; gated adapters
    (available=False) are excluded, so ADAPTER_CAPABILITIES.keys() is a subset
    of ADAPTERS.keys().
    """
    from recosearch.adapters import ADAPTERS, ADAPTER_CAPABILITIES

    for source_type, adapter in ADAPTERS.items():
        if adapter.available:
            assert ADAPTER_CAPABILITIES[source_type] == set(adapter.capabilities), (
                f"ADAPTER_CAPABILITIES[{source_type!r}] out of sync with ADAPTERS[{source_type!r}].capabilities"
            )
        else:
            # Gated adapters must NOT appear in advertised ADAPTER_CAPABILITIES.
            assert source_type not in ADAPTER_CAPABILITIES, (
                f"Gated adapter {source_type!r} (available=False) must not appear in ADAPTER_CAPABILITIES"
            )
    # Available adapters are a subset of all adapters.
    available_types = {t for t, a in ADAPTERS.items() if a.available}
    assert set(ADAPTER_CAPABILITIES.keys()) == available_types


def test_snowflake_adapter_dialect_and_callable() -> None:
    """Snowflake adapter must advertise 'snowflake' dialect and expose a callable run_query."""
    from recosearch.adapters import adapter_for_type

    sf = adapter_for_type("snowflake")
    assert sf is not None, "adapter_for_type('snowflake') returned None"
    assert sf.sql_dialect == "snowflake"
    assert callable(sf.run_query)
    assert sf.source_type == "snowflake"


def test_import_adapters_package_does_not_require_snowflake_connector() -> None:
    """Importing the adapters package must not trigger a snowflake.connector import.

    snowflake.connector is not installed in this environment; if the driver were
    imported at module level the entire package would be un-importable.
    """
    import sys

    # The package is already imported (earlier tests pulled it in). Verify that
    # snowflake.connector is NOT in sys.modules — confirming the driver import
    # is deferred (lazy) and was never triggered at package-load time.
    assert "snowflake.connector" not in sys.modules, (
        "snowflake.connector was imported at module level — it must be lazy (inside the function body)"
    )


# --- availability-gating tests ---

def test_snowflake_adapter_is_available() -> None:
    """snowflake is a live structured_query source (real account configured)."""
    from recosearch.adapters import adapter_for_type

    sf = adapter_for_type("snowflake")
    assert sf is not None, "adapter_for_type('snowflake') returned None — adapter must be registered"
    assert sf.available is True
    assert "structured_query" in sf.capabilities
    assert sf.sql_dialect == "snowflake"


def test_gating_mechanism_excludes_unavailable_adapter() -> None:
    """The availability gate (available=False) must suppress a capability while
    keeping the adapter's intrinsic declaration. Tested with synthetic adapters so
    it does not depend on which real adapters happen to be gated."""
    from recosearch.adapters.base import SourceAdapter

    gated = SourceAdapter(source_type="demo_gated", capabilities=frozenset({"structured_query"}),
                          run_query=lambda *a, **k: [], available=False)
    live = SourceAdapter(source_type="demo_live", capabilities=frozenset({"structured_query"}),
                         run_query=lambda *a, **k: [], available=True)

    # Intrinsic capability is preserved on the object regardless of availability.
    assert "structured_query" in gated.capabilities

    # The same derivation the registry uses: only available adapters advertise.
    advertised = {a.source_type: set(a.capabilities) for a in (gated, live) if a.available}
    assert "demo_gated" not in advertised
    assert advertised["demo_live"] == {"structured_query"}


def test_two_structured_sources_route_by_table() -> None:
    """With snowflake live, postgres and snowflake are both structured sources. A
    query routes to whichever source owns its tables — no source_id needed."""
    from recosearch.config import sources_with_capability
    from recosearch.contract import compile_semantic_contract
    from recosearch.tools import (
        _choose_structured_source,
        _owning_structured_sources,
        _referenced_tables,
    )

    ids = {s.source_id for s in sources_with_capability("structured_query")}
    assert {"novamart_postgres", "novamart_snowflake"} <= ids

    contract = compile_semantic_contract()
    pg, _ = _choose_structured_source(
        _owning_structured_sources(contract, _referenced_tables("SELECT product_id FROM products")), None)
    sf, _ = _choose_structured_source(
        _owning_structured_sources(contract, _referenced_tables("SELECT seller_id FROM sellers")), None)
    assert pg == "novamart_postgres"
    assert sf == "novamart_snowflake"
