from recosearch.semantic_layers.adapters.duckdb import ADAPTER
from recosearch.semantic_layers import capabilities as cap
from recosearch.semantic_layers.adapters import ADAPTERS, adapter_for, capabilities_for


def test_duckdb_adapter_registered():
    assert "duckdb" in ADAPTERS
    adapter = adapter_for("duckdb")
    assert adapter is not None
    assert cap.STRUCTURED_QUERY in adapter.capabilities
    assert adapter.sql_dialect == "duckdb"
    assert adapter.source_mode == "runtime"
    assert "query_hash" in adapter.citation_kinds


def test_capabilities_for_unknown_type():
    assert capabilities_for("nonexistent") == set()
