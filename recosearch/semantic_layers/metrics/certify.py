from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.types import MetricQuery
from recosearch.semantic_layers.pipeline import execute_metric_query

TOOL_VERSION = "0.1.0"
CERTIFICATION_RESULTS_FILENAME = "_certification_results.yaml"


def run_certifications(
    kernel: MetricKernel,
    contract: dict[str, Any],
    *,
    reference_date: date | None = None,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for cert in kernel.certifications.values():
        metric = kernel.metrics[cert.metric_id]
        hash_match = cert.definition_hash == metric.definition_hash
        question_results: list[dict[str, Any]] = []
        all_passed = hash_match

        for gq in cert.golden_questions:
            query_kwargs: dict[str, Any] = {
                "term": gq.term,
                "tenant": gq.tenant,
                "dimensions": gq.dimensions,
            }
            if reference_date is not None:
                query_kwargs["reference_date"] = reference_date
            answer = execute_metric_query(
                MetricQuery(**query_kwargs),
                contract=contract,
            )
            expected = dict(gq.expected)
            passed = False
            if answer.decision == "answer" and answer.result:
                row = answer.result[0]
                passed = all(row.get(k) == v for k, v in expected.items())
            if not passed:
                all_passed = False
            question_results.append(
                {
                    "term": gq.term,
                    "passed": passed,
                    "expected": expected,
                    "actual": answer.result[0] if answer.result else None,
                    "decision": answer.decision,
                }
            )

        golden_passed = all(bool(gq.get("passed")) for gq in question_results) if question_results else hash_match
        results[cert.metric_id] = {
            "hash_match": hash_match,
            "certified": all_passed and hash_match,
            "golden_passed": golden_passed and hash_match,
            "definition_hash": metric.definition_hash,
            "signed_hash": cert.definition_hash,
            "golden_questions": question_results,
        }
    return results


def apply_certification_results(
    kernel: MetricKernel,
    results: dict[str, dict[str, Any]],
) -> MetricKernel:
    return kernel.with_certification_results(results)


def persist_certification_results(
    metrics_dir: Path | str,
    results: dict[str, dict[str, Any]],
    *,
    tool_version: str = TOOL_VERSION,
) -> Path:
    run_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entries = []
    for metric_id in sorted(results):
        result = results[metric_id]
        entries.append(
            {
                "metric_id": metric_id,
                "definition_hash": result["definition_hash"],
                "certified": bool(result.get("certified")),
                "golden_passed": bool(result.get("golden_passed")),
                "run_at": run_at,
                "tool_version": tool_version,
            }
        )
    payload = {"certification_results": entries}
    out_path = Path(metrics_dir) / CERTIFICATION_RESULTS_FILENAME
    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out_path


def verify_certification_results(kernel: MetricKernel) -> list[str]:
    failures: list[str] = []
    for cert in kernel.certifications.values():
        metric = kernel.metrics[cert.metric_id]
        if cert.definition_hash != metric.definition_hash:
            failures.append(f"{cert.metric_id}: stale certification (hash mismatch)")
            continue
        persisted = kernel.persisted_certification_results.get(cert.metric_id)
        if persisted is not None and str(persisted.get("definition_hash", "")) != metric.definition_hash:
            failures.append(f"{cert.metric_id}: stale certification (persisted hash mismatch)")
            continue
        if cert.certified is False or cert.golden_passed is False:
            failures.append(f"{cert.metric_id}: certification failed")
    return failures
