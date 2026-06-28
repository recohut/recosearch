"""Portability proof: the runtime must work with a different business schema
and different field names, with no code changes. Uses the real tool code; only the
low-level executor and source resolution are stubbed for offline running.
"""
from __future__ import annotations

from types import SimpleNamespace

from recosearch import config, tools
from recosearch.field_roles import identity_columns, resolve_field_roles, searchable_columns


def _events_contract():
    """Synthetic contract: OpenSearch source with analytics events and distinct field names."""
    contract = {
        "sources": {"os_events": {"type": "opensearch", "index": "events"}},
        "measures": {},
        "dimensions": {
            "os_events.events.event_id": {"source": "os_events", "table": "events", "column": "event_id", "description": "unique identifier of each analytics event"},
            "os_events.events.seller_name": {"source": "os_events", "table": "events", "column": "seller_name", "description": "display name of the seller"},
            "os_events.events.event_blob": {"source": "os_events", "table": "events", "column": "event_blob", "description": "full free-text body of the event payload"},
            "os_events.events.event_ts": {"source": "os_events", "table": "events", "column": "event_ts", "description": "timestamp when the event occurred"},
        },
        "relations": [],
        "exclusions": [],
    }
    contract["field_roles"] = resolve_field_roles(contract)
    return contract


def test_field_roles_resolve_for_a_different_schema() -> None:
    contract = _events_contract()
    cols = searchable_columns(contract, "os_events", "events")
    assert "event_blob" in cols  # body_text role, despite the unfamiliar name
    assert "event_id" in identity_columns(contract, "os_events", "events")


def test_search_text_is_role_driven_for_a_new_business(monkeypatch) -> None:
    contract = _events_contract()
    captured: dict = {}

    def _fake_search(body, *, url, index):
        captured["body"], captured["index"], captured["url"] = body, index, url
        return [{"event_id": "E1", "seller_name": "Acme", "event_blob": "big sale", "_id": "x", "_score": 1.0}]

    monkeypatch.setattr(tools, "compile_semantic_contract", lambda *a, **k: contract)
    monkeypatch.setattr(tools, "resolve_source_id", lambda capability, source_id=None: ("os_events", None))
    monkeypatch.setattr(tools, "_ref_by_id", lambda sid: SimpleNamespace(source_type="opensearch", config={"url": "http://x", "index": "events"}))
    monkeypatch.setattr(tools, "adapter_for_type", lambda source_type: SimpleNamespace(run_query=_fake_search))

    result = tools.search_text(query="sale")
    assert result["status"] == "ok"
    # Full-text runs over body_text/display_name roles on the NEW schema — never
    # any order_id / rating / "review" assumption.
    multi_match_fields = captured["body"]["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert "event_blob" in multi_match_fields and "seller_name" in multi_match_fields
    # Citations use the resolved identity role (event_id), not '_id' luck.
    assert result["rows"][0]["_citation"]["record_ref"].get("event_id") == "E1"


def test_search_text_accepts_field_id_filters(monkeypatch) -> None:
    contract = _events_contract()
    captured: dict = {}

    def _fake_search(body, *, url, index):
        captured["body"] = body
        return []

    monkeypatch.setattr(tools, "compile_semantic_contract", lambda *a, **k: contract)
    monkeypatch.setattr(tools, "resolve_source_id", lambda capability, source_id=None: ("os_events", None))
    monkeypatch.setattr(tools, "_ref_by_id", lambda sid: SimpleNamespace(source_type="opensearch", config={"url": "http://x", "index": "events"}))
    monkeypatch.setattr(tools, "adapter_for_type", lambda source_type: SimpleNamespace(run_query=_fake_search))

    # filter keyed by declared field_id resolves to the column in the query.
    tools.search_text(filters={"os_events.events.event_id": "E1"})
    terms = captured["body"]["query"]["bool"]["filter"]
    assert any(clause.get("term", {}).get("event_id") == "E1" for clause in terms)


def test_search_text_refuses_when_no_searchable_roles(monkeypatch) -> None:
    contract = {
        "sources": {"os_x": {"type": "opensearch", "index": "x"}},
        "measures": {},
        "dimensions": {"os_x.x.row_key": {"source": "os_x", "table": "x", "column": "row_key", "description": "unique identifier of the row"}},
        "relations": [], "exclusions": [],
    }
    contract["field_roles"] = resolve_field_roles(contract)
    monkeypatch.setattr(tools, "compile_semantic_contract", lambda *a, **k: contract)
    monkeypatch.setattr(tools, "resolve_source_id", lambda capability, source_id=None: ("os_x", None))
    monkeypatch.setattr(tools, "_ref_by_id", lambda sid: SimpleNamespace(source_type="opensearch", config={"url": "http://x", "index": "x"}))
    result = tools.search_text(query="anything")
    assert result["status"] == "refused" and result["reason_code"] == "text_search_fields_unresolved"


def test_multiple_sources_of_a_type_require_source_id(monkeypatch) -> None:
    refs = {
        "os1": config.SourceRef("os1", "opensearch", "opensearch", {"url": "http://a", "index": "i1"}),
        "os2": config.SourceRef("os2", "opensearch", "opensearch", {"url": "http://b", "index": "i2"}),
    }
    monkeypatch.setattr(config, "_source_refs", lambda: refs)

    sid, refusal = config.resolve_source_id("text_search")
    assert sid is None and refusal["reason_code"] == "source_selection_required"
    assert set(refusal["candidates"]) == {"os1", "os2"}

    sid2, refusal2 = config.resolve_source_id("text_search", "os2")
    assert sid2 == "os2" and refusal2 is None
