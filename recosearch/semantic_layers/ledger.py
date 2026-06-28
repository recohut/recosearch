from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PERSIST_DIR: Path | None = None
_ARTIFACT_STORE: dict[str, dict[str, Any]] = {}


@dataclass
class LineageEdge:
    from_id: str
    to_id: str
    kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "kind": self.kind,
        }


@dataclass
class EvidenceArtifact:
    artifact_type: str  # query | plan | decision | answer | citation | refusal | evidence_pack | review_ticket | review_clearance | decision_record | outcome_record | calibration_signal | replay_result | calibration_report | trust_prior_proposal | counterfactual_result
    source_id: str = ""
    evidence_tier: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    lineage_edges: list[LineageEdge] = field(default_factory=list)
    recorded_at: float = 0.0
    artifact_id: str = ""
    contract_hash: str = ""

    def __post_init__(self) -> None:
        if not self.recorded_at:
            self.recorded_at = time.time()
        if not self.artifact_id:
            content_parts: dict[str, Any] = {
                "type": self.artifact_type,
                "source_id": self.source_id,
                "payload": self.payload,
            }
            if self.lineage_edges:
                content_parts["lineage_edges"] = [
                    edge.to_dict() for edge in self.lineage_edges
                ]
            content = json.dumps(content_parts, sort_keys=True)
            self.artifact_id = "art-" + hashlib.sha256(content.encode()).hexdigest()[:16]


_EVENTS: list[EvidenceArtifact] = []


def configure_persist_dir(path: Path | str | None) -> None:
    global _PERSIST_DIR
    if path is None:
        _PERSIST_DIR = None
        return
    _PERSIST_DIR = Path(path)
    _PERSIST_DIR.mkdir(parents=True, exist_ok=True)


def _persist_artifact(artifact: EvidenceArtifact) -> None:
    if _PERSIST_DIR is None:
        return
    out = _PERSIST_DIR / f"{artifact.artifact_id}.json"
    data = {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "source_id": artifact.source_id,
        "evidence_tier": artifact.evidence_tier,
        "recorded_at": artifact.recorded_at,
        "contract_hash": artifact.contract_hash,
        "payload": artifact.payload,
        "lineage_edges": [edge.to_dict() for edge in artifact.lineage_edges],
    }
    out.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    _ARTIFACT_STORE[artifact.artifact_id] = data


def record(
    artifact_type: str,
    *,
    source_id: str = "",
    evidence_tier: str = "",
    payload: dict[str, Any] | None = None,
    lineage_edges: list[LineageEdge] | None = None,
    contract_hash: str = "",
) -> str:
    payload = dict(payload or {})
    if contract_hash:
        payload.setdefault("contract_hash", contract_hash)
    elif "contract_hash" in payload:
        contract_hash = str(payload["contract_hash"])
    artifact = EvidenceArtifact(
        artifact_type=artifact_type,
        source_id=source_id,
        evidence_tier=evidence_tier,
        payload=payload,
        lineage_edges=lineage_edges or [],
        contract_hash=contract_hash,
    )
    _EVENTS.append(artifact)
    _ARTIFACT_STORE[artifact.artifact_id] = {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "source_id": artifact.source_id,
        "evidence_tier": artifact.evidence_tier,
        "recorded_at": artifact.recorded_at,
        "contract_hash": artifact.contract_hash,
        "payload": artifact.payload,
        "lineage_edges": [edge.to_dict() for edge in artifact.lineage_edges],
    }
    _persist_artifact(artifact)
    return artifact.artifact_id


def load_by_id(artifact_id: str) -> dict[str, Any] | None:
    if artifact_id in _ARTIFACT_STORE:
        return dict(_ARTIFACT_STORE[artifact_id])
    if _PERSIST_DIR is not None:
        path = _PERSIST_DIR / f"{artifact_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            _ARTIFACT_STORE[artifact_id] = data
            return data
    for event in _EVENTS:
        if event.artifact_id == artifact_id:
            return {
                "artifact_id": event.artifact_id,
                "artifact_type": event.artifact_type,
                "source_id": event.source_id,
                "evidence_tier": event.evidence_tier,
                "recorded_at": event.recorded_at,
                "contract_hash": event.contract_hash,
                "payload": dict(event.payload),
                "lineage_edges": [edge.to_dict() for edge in event.lineage_edges],
            }
    return None


def is_expired(artifact_id: str, *, contract_hash: str) -> bool:
    artifact = load_by_id(artifact_id)
    if artifact is None:
        return True
    stored = str(artifact.get("contract_hash") or artifact.get("payload", {}).get("contract_hash", ""))
    if stored and stored != contract_hash:
        return True
    return False


def events() -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": e.artifact_id,
            "artifact_type": e.artifact_type,
            "source_id": e.source_id,
            "evidence_tier": e.evidence_tier,
            "recorded_at": e.recorded_at,
            "contract_hash": e.contract_hash,
            "payload": e.payload,
            "lineage_edges": [edge.to_dict() for edge in e.lineage_edges],
        }
        for e in _EVENTS
    ]


def lineage_edges() -> list[LineageEdge]:
    return [edge for event in _EVENTS for edge in event.lineage_edges]


def clear() -> None:
    _EVENTS.clear()
    _ARTIFACT_STORE.clear()
