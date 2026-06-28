from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers import identity, policy
from recosearch.semantic_layers.context.loader import ContextKernelLoader
from recosearch.semantic_layers.context.probe import probe_term_local
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.pipeline import execute_context_query

TOOL_VERSION = "0.1.0"
CERTIFICATION_RESULTS_FILENAME = "_certification_results.yaml"
DEFAULT_REFERENCE_DATE = date(2026, 1, 31)


def _contract_for_certification(contract: dict[str, Any]) -> dict[str, Any]:
    """Strip persisted certification outcomes so golden runs are not self-blocked."""
    clean = copy.deepcopy(contract)
    context_kernel = clean.get("context_kernel")
    if not isinstance(context_kernel, dict):
        return clean
    ck = dict(context_kernel)
    ck.pop("persisted_certification_results", None)
    certifications = ck.get("certifications", [])
    if isinstance(certifications, list):
        cleaned: list[dict[str, Any]] = []
        for cert in certifications:
            item = dict(cert)
            item.pop("certified", None)
            item.pop("golden_passed", None)
            cleaned.append(item)
        ck["certifications"] = cleaned
    elif isinstance(certifications, dict):
        cleaned_dict: dict[str, Any] = {}
        for term_id, cert in certifications.items():
            item = dict(cert)
            item.pop("certified", None)
            item.pop("golden_passed", None)
            cleaned_dict[term_id] = item
        ck["certifications"] = cleaned_dict
    clean["context_kernel"] = ck
    return clean


def _ares_confidence_interval(passed: int, total: int) -> tuple[float, float]:
    """Simple normal-approx interval from pass rate (ARES-inspired reporting shape)."""
    if total <= 0:
        return 0.0, 0.0
    rate = passed / total
    margin = 1.96 * ((rate * (1 - rate)) / total) ** 0.5
    return max(0.0, rate - margin), min(1.0, rate + margin)


def run_context_certifications(
    context_kernel: Any,
    metric_kernel: MetricKernel,
    contract: dict[str, Any],
    *,
    reference_date: date | None = None,
    run_probe: bool = True,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    current_policy_hash = policy.compute_policy_hash()
    effective_reference_date = reference_date or DEFAULT_REFERENCE_DATE
    cert_contract = _contract_for_certification(contract)

    for cert in context_kernel.certifications.values():
        term = context_kernel.terms[cert.term_id]
        hash_match = cert.definition_hash == term.definition_hash
        policy_match = not cert.policy_hash or cert.policy_hash == current_policy_hash
        question_results: list[dict[str, Any]] = []
        all_passed = hash_match and policy_match
        passed_count = 0

        for gq in cert.golden_questions:
            actor = identity.resolve(role=gq.actor_role or "analyst")
            answer = execute_context_query(
                ContextQuery(term=gq.term, tenant=gq.tenant),
                contract=cert_contract,
                actor=actor,
                reference_date=effective_reference_date,
            )
            trust_status = ""
            evidence_tier = 0
            if answer.context_resolution:
                ctx = dict(answer.context_resolution)
                trust_status = str(ctx.get("trust_status", ""))
                evidence_tier = int(ctx.get("evidence_tier", 0))

            passed = (
                answer.decision == gq.expected_decision
                and trust_status == gq.expected_trust_status
                and evidence_tier >= gq.expected_evidence_tier
            )
            if gq.expected and answer.decision == "answer" and answer.result:
                row = answer.result[0]
                passed = passed and all(row.get(k) == v for k, v in gq.expected)
            if not passed:
                all_passed = False
            else:
                passed_count += 1
            question_results.append(
                {
                    "term": gq.term,
                    "passed": passed,
                    "expected_decision": gq.expected_decision,
                    "actual_decision": answer.decision,
                    "expected_trust_status": gq.expected_trust_status,
                    "actual_trust_status": trust_status,
                    "expected": dict(gq.expected),
                    "actual": answer.result[0] if answer.result else None,
                }
            )

        golden_passed = (
            all(bool(gq.get("passed")) for gq in question_results) if question_results else hash_match
        )
        evidence_tier = 2 if golden_passed and hash_match else 1
        probe_result: dict[str, Any] | None = None
        if run_probe and golden_passed and hash_match:
            probe_result = probe_term_local(term, metric_kernel, contract)
            if probe_result.get("passed"):
                evidence_tier = 3

        total_q = len(question_results) or 1
        ci_low, ci_high = _ares_confidence_interval(passed_count, total_q)

        results[cert.term_id] = {
            "hash_match": hash_match,
            "policy_match": policy_match,
            "certified": all_passed and hash_match and policy_match,
            "golden_passed": golden_passed and hash_match and policy_match,
            "definition_hash": term.definition_hash,
            "signed_hash": cert.definition_hash,
            "policy_hash": current_policy_hash,
            "evidence_tier": evidence_tier,
            "golden_questions": question_results,
            "probe": probe_result,
            "ares_confidence_interval": [ci_low, ci_high],
        }
    return results


def apply_context_certification_results(
    context_kernel: Any,
    results: dict[str, dict[str, Any]],
) -> Any:
    return ContextKernelLoader.with_certification_results(context_kernel, results)


def persist_context_certification_results(
    context_dir: Path | str,
    results: dict[str, dict[str, Any]],
    *,
    tool_version: str = TOOL_VERSION,
) -> Path:
    run_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entries = []
    for term_id in sorted(results):
        result = results[term_id]
        entries.append(
            {
                "term_id": term_id,
                "definition_hash": result["definition_hash"],
                "policy_hash": result.get("policy_hash", ""),
                "certified": bool(result.get("certified")),
                "golden_passed": bool(result.get("golden_passed")),
                "evidence_tier": int(result.get("evidence_tier", 2)),
                "run_at": run_at,
                "tool_version": tool_version,
                "ares_confidence_interval": result.get("ares_confidence_interval", [0.0, 1.0]),
            }
        )
    payload = {"certification_results": entries}
    out_path = Path(context_dir) / CERTIFICATION_RESULTS_FILENAME
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out_path


def verify_context_certification_results(context_kernel: Any) -> list[str]:
    failures: list[str] = []
    current_policy = policy.compute_policy_hash()
    for cert in context_kernel.certifications.values():
        term = context_kernel.terms.get(cert.term_id)
        if term is None:
            failures.append(f"{cert.term_id}: unknown term")
            continue
        if cert.definition_hash != term.definition_hash:
            failures.append(f"{cert.term_id}: stale certification (hash mismatch)")
            continue
        if cert.policy_hash and cert.policy_hash != current_policy:
            failures.append(f"{cert.term_id}: stale certification (policy changed)")
            continue
        persisted = context_kernel.persisted_certification_results.get(cert.term_id)
        if persisted is not None and str(persisted.get("definition_hash", "")) != term.definition_hash:
            failures.append(f"{cert.term_id}: stale certification (persisted hash mismatch)")
            continue
        if cert.certified is False or cert.golden_passed is False:
            failures.append(f"{cert.term_id}: certification failed")
    return failures
