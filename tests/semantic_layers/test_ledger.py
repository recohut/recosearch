from recosearch.semantic_layers import ledger


def test_record_returns_content_addressed_id():
    ledger.clear()
    id1 = ledger.record("query", source_id="x", payload={"q": "SELECT 1"})
    id2 = ledger.record("query", source_id="x", payload={"q": "SELECT 1"})
    assert id1 == id2
    assert id1.startswith("art-")


def test_distinct_payloads_distinct_ids():
    ledger.clear()
    id1 = ledger.record("query", source_id="x", payload={"q": "SELECT 1"})
    id2 = ledger.record("query", source_id="x", payload={"q": "SELECT 2"})
    assert id1 != id2


def test_events_serializable():
    import json

    ledger.clear()
    ledger.record("query", source_id="x", payload={"q": "SELECT 1"})
    json.dumps(ledger.events())


def test_events_serialize_lineage_edges():
    ledger.clear()
    edge = ledger.LineageEdge(from_id="query-1", to_id="decision-1", kind="supports")

    ledger.record("decision", source_id="x", lineage_edges=[edge])

    assert ledger.events()[0]["lineage_edges"] == [
        {"from_id": "query-1", "to_id": "decision-1", "kind": "supports"}
    ]


def test_lineage_edges_projects_recorded_edges():
    ledger.clear()
    edge1 = ledger.LineageEdge(from_id="query-1", to_id="plan-1", kind="feeds")
    edge2 = ledger.LineageEdge(from_id="plan-1", to_id="decision-1", kind="supports")

    ledger.record("plan", source_id="x", lineage_edges=[edge1])
    ledger.record("decision", source_id="x", lineage_edges=[edge2])

    assert ledger.lineage_edges() == [edge1, edge2]


def test_lineage_edges_contribute_to_content_addressed_id():
    ledger.clear()
    edge = ledger.LineageEdge(from_id="query-1", to_id="decision-1", kind="supports")
    other_edge = ledger.LineageEdge(from_id="query-1", to_id="decision-1", kind="refutes")

    without_edge = ledger.record("decision", source_id="x", payload={"answer": "yes"})
    with_edge = ledger.record(
        "decision", source_id="x", payload={"answer": "yes"}, lineage_edges=[edge]
    )
    with_same_edge = ledger.record(
        "decision", source_id="x", payload={"answer": "yes"}, lineage_edges=[edge]
    )
    with_other_edge = ledger.record(
        "decision", source_id="x", payload={"answer": "yes"}, lineage_edges=[other_edge]
    )

    assert without_edge != with_edge
    assert with_edge == with_same_edge
    assert with_edge != with_other_edge
