from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
from recosearch.semantic_layers.evidence.schema import validate_evidence_certifications, validate_evidence_gates
from recosearch.semantic_layers.evidence.types import ClaimSet, Subclaim

TOOL_VERSION = "0.1.0"
CERTIFICATION_FILENAME = "_certification.yaml"
CERTIFICATION_RESULTS_FILENAME = "_certification_results.yaml"


def _subclaim_from_dict(raw: dict[str, Any]) -> Subclaim:
    qualifiers = tuple(tuple(str(part) for part in pair) for pair in raw.get("claim_qualifiers", []) or [])
    return Subclaim(
        term=str(raw["term"]),
        tenant=str(raw.get("tenant", "novashop")),
        industry=raw.get("industry"),
        actor_role=str(raw.get("actor_role", "analyst")),
        claim_qualifiers=qualifiers,
        comparable_group=str(raw.get("comparable_group", "")),
        reference_date=str(raw.get("reference_date", "")),
        time_period=str(raw.get("time_period", "")),
        scoped_question=str(raw.get("scoped_question", "")),
    )


def load_evidence_certifications(evidence_dir: Path | str) -> list[dict[str, Any]]:
    path = Path(evidence_dir) / CERTIFICATION_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"missing {CERTIFICATION_FILENAME}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_evidence_certifications(raw)
    cases = raw.get("certifications", []) or []
    return [dict(case) for case in cases]


def run_evidence_certifications(
    contract: dict[str, Any],
    *,
    evidence_dir: Path | str,
) -> dict[str, dict[str, Any]]:
    contract_hash = str(contract.get("contract_hash", ""))
    results: dict[str, dict[str, Any]] = {}
    for case in load_evidence_certifications(evidence_dir):
        case_id = str(case["case_id"])
        subclaims = tuple(_subclaim_from_dict(item) for item in case["subclaims"])
        claim_set = ClaimSet(
            subclaims=subclaims,
            pack_label=str(case.get("pack_label", "board_pack")),
        )
        expected_decision = str(case["expected_decision"])
        pack, answer = compose_evidence_pack(claim_set, contract=contract)
        results[case_id] = {
            "passed": answer.decision == expected_decision,
            "expected_decision": expected_decision,
            "actual_decision": answer.decision,
            "pack_id": pack.pack_id,
            "contract_hash": contract_hash,
        }
    return results


def persist_evidence_certification_results(
    evidence_dir: Path | str,
    results: dict[str, dict[str, Any]],
    *,
    tool_version: str = TOOL_VERSION,
) -> Path:
    run_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entries = []
    for case_id in sorted(results):
        result = results[case_id]
        entries.append(
            {
                "case_id": case_id,
                "passed": bool(result.get("passed")),
                "expected_decision": result.get("expected_decision"),
                "actual_decision": result.get("actual_decision"),
                "pack_id": result.get("pack_id", ""),
                "contract_hash": result.get("contract_hash", ""),
                "run_at": run_at,
                "tool_version": tool_version,
            }
        )
    payload = {"certification_results": entries}
    out_path = Path(evidence_dir) / CERTIFICATION_RESULTS_FILENAME
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out_path


def verify_evidence_certification_results(
    evidence_dir: Path | str,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    path = Path(evidence_dir) / CERTIFICATION_RESULTS_FILENAME
    if not path.exists():
        return ["missing certification results"]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return ["certification results must be a mapping"]
    expected_hash = str((contract or {}).get("contract_hash", ""))
    failures: list[str] = []
    for item in raw.get("certification_results", []) or []:
        if not isinstance(item, dict):
            failures.append("invalid certification entry")
            continue
        case_id = str(item.get("case_id", "unknown"))
        if not item.get("passed"):
            failures.append(f"{case_id}: certification failed")
            continue
        if expected_hash and str(item.get("contract_hash", "")) != expected_hash:
            failures.append(f"{case_id}: stale evidence certification (hash mismatch)")
    return failures


def validate_evidence_registry(evidence_dir: Path | str) -> list[str]:
    failures: list[str] = []
    gates_path = Path(evidence_dir) / "_gates.yaml"
    if not gates_path.exists():
        failures.append("missing _gates.yaml")
    else:
        raw = yaml.safe_load(gates_path.read_text(encoding="utf-8")) or {}
        try:
            validate_evidence_gates(raw)
        except Exception as exc:
            failures.append(str(exc))

    cert_path = Path(evidence_dir) / CERTIFICATION_FILENAME
    if not cert_path.exists():
        failures.append(f"missing {CERTIFICATION_FILENAME}")
    else:
        raw = yaml.safe_load(cert_path.read_text(encoding="utf-8")) or {}
        try:
            validate_evidence_certifications(raw)
        except Exception as exc:
            failures.append(str(exc))
    return failures
