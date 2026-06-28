from __future__ import annotations

import json

from recosearch.semantic_layers import ledger


def test_configure_persist_dir_writes_artifact_files(tmp_path):
    ledger.configure_persist_dir(tmp_path)
    artifact_id = ledger.record(
        "evidence_pack",
        evidence_tier="local-equivalent",
        payload={"pack_id": "pack-test"},
        contract_hash="hash-v1",
    )
    path = tmp_path / f"{artifact_id}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["artifact_type"] == "evidence_pack"
    assert data["contract_hash"] == "hash-v1"


def test_load_by_id_from_memory_and_disk(tmp_path):
    ledger.configure_persist_dir(tmp_path)
    artifact_id = ledger.record(
        "review_ticket",
        payload={"ticket_id": "ticket-test"},
        contract_hash="hash-v1",
    )
    loaded = ledger.load_by_id(artifact_id)
    assert loaded is not None
    assert loaded["artifact_id"] == artifact_id
    assert loaded["payload"]["ticket_id"] == "ticket-test"

    ledger.clear()
    reloaded = ledger.load_by_id(artifact_id)
    assert reloaded is not None
    assert reloaded["payload"]["ticket_id"] == "ticket-test"


def test_load_by_id_missing_returns_none():
    assert ledger.load_by_id("art-does-not-exist") is None


def test_is_expired_on_contract_hash_mismatch():
    artifact_id = ledger.record(
        "evidence_pack",
        payload={"pack_id": "pack-test"},
        contract_hash="hash-v1",
    )
    assert ledger.is_expired(artifact_id, contract_hash="hash-v1") is False
    assert ledger.is_expired(artifact_id, contract_hash="hash-v2") is True
    assert ledger.is_expired("art-missing", contract_hash="hash-v1") is True


def test_clear_removes_events():
    ledger.record("evidence_pack", payload={"pack_id": "pack-test"})
    assert ledger.events()
    ledger.clear()
    assert ledger.events() == []
