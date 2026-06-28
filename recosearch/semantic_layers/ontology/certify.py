from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers import identity
from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader, load_ontology_kernel
from recosearch.semantic_layers.ontology.types import GoldenConstraintCase, OntologyCertification
from recosearch.semantic_layers.ontology.validate import validate_claim
from recosearch.semantic_layers.pipeline import execute_context_query

TOOL_VERSION = "0.1.0"
CERTIFICATION_RESULTS_FILENAME = "_certification_results.yaml"


def _resolve_cert_hash(kernel: Any) -> str:
    if kernel.certifications:
        first = next(iter(kernel.certifications.values()))
        if first.ontology_hash != "placeholder":
            return first.ontology_hash
    return kernel.ontology_hash


def run_ontology_certifications(
    ontology_kernel: Any,
    context_kernel: Any,
    contract: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    cert_hash = _resolve_cert_hash(ontology_kernel)
    cert = ontology_kernel.certifications.get(cert_hash)
    if cert is None and ontology_kernel.certifications:
        cert = next(iter(ontology_kernel.certifications.values()))
    golden_cases = cert.golden_cases if cert else ()

    case_results: list[dict[str, Any]] = []
    all_passed = True
    for case in golden_cases:
        binding = context_kernel.terms[case.term_id]
        metric_refs = [r for r in binding.primary_refs if r.startswith("metric:")]
        metric_id = metric_refs[0] if metric_refs else ""
        decision = validate_claim(
            binding,
            metric_id,
            ontology_kernel,
            claim_qualifiers=case.claim_qualifiers,
        )
        passed = (
            decision.decision == case.expected_decision
            and (
                not case.expected_reason_code
                or decision.reason_code == case.expected_reason_code
            )
        )
        if not passed:
            all_passed = False
        case_results.append(
            {
                "term_id": case.term_id,
                "passed": passed,
                "expected_decision": case.expected_decision,
                "actual_decision": decision.decision,
                "expected_reason_code": case.expected_reason_code,
                "actual_reason_code": decision.reason_code,
            }
        )

    results[cert_hash] = {
        "ontology_hash": ontology_kernel.ontology_hash,
        "reasoner_mode": ontology_kernel.reasoner_mode,
        "certified": all_passed,
        "golden_passed": all_passed,
        "golden_cases": case_results,
        "tool_version": TOOL_VERSION,
        "certified_at": datetime.now(UTC).isoformat(),
    }
    return results


def persist_ontology_certification_results(
    ontology_dir: Path | str,
    results: dict[str, dict[str, Any]],
) -> Path:
    path = Path(ontology_dir) / CERTIFICATION_RESULTS_FILENAME
    payload = {"certification_results": list(results.values())}
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def verify_ontology_certification_results(ontology_kernel: Any) -> list[str]:
    failures: list[str] = []
    for stored in ontology_kernel.persisted_certification_results.values():
        if stored.get("ontology_hash") != ontology_kernel.ontology_hash:
            failures.append(
                f"ontology hash drift: stored={stored.get('ontology_hash')} "
                f"current={ontology_kernel.ontology_hash}"
            )
        if not stored.get("certified"):
            failures.append("ontology certification not passed")
    if ontology_kernel.certifications and not ontology_kernel.persisted_certification_results:
        failures.append("missing persisted ontology certification results")
    return failures


def apply_ontology_certification_results(
    ontology_kernel: Any,
    results: dict[str, dict[str, Any]],
) -> Any:
    from types import MappingProxyType

    from recosearch.semantic_layers.ontology.types import OntologyKernel

    updated_certs = dict(ontology_kernel.certifications)
    for cert_hash, result in results.items():
        existing = updated_certs.get(cert_hash)
        if existing is None:
            continue
        updated_certs[cert_hash] = OntologyCertification(
            ontology_hash=existing.ontology_hash,
            reasoner_mode=existing.reasoner_mode,
            golden_cases=existing.golden_cases,
            certified=bool(result.get("certified")),
            golden_passed=bool(result.get("golden_passed")),
        )
    return OntologyKernel(
        namespace=ontology_kernel.namespace,
        ontology_ttl=ontology_kernel.ontology_ttl,
        shapes_ttl=ontology_kernel.shapes_ttl,
        mappings=ontology_kernel.mappings,
        ontology_hash=ontology_kernel.ontology_hash,
        reasoner_mode=ontology_kernel.reasoner_mode,
        certifications=MappingProxyType(updated_certs),
        persisted_certification_results=MappingProxyType(results),
    )


def run_pipeline_golden_case(
    case: GoldenConstraintCase,
    contract: dict[str, Any],
) -> Any:
    actor = identity.resolve(role=case.actor_role or "analyst")
    return execute_context_query(
        ContextQuery(
            term=case.term_id.split(":")[-1].replace("_", " "),
            tenant=case.tenant,
            claim_qualifiers=case.claim_qualifiers,
        ),
        contract=contract,
        actor=actor,
    )
