from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from recosearch.semantic_layers.context.types import ContextKernel
from recosearch.semantic_layers.ontology.hash import compute_ontology_hash
from recosearch.semantic_layers.ontology.types import (
    DEFAULT_REASONER_MODE,
    GoldenConstraintCase,
    OntologyCertification,
    OntologyKernel,
    SUPPORTED_REASONER_MODES,
    TermMapping,
)


class OntologyKernelLoader:
    @classmethod
    def from_dir(
        cls,
        dir_path: Path | str,
        *,
        context_kernel: ContextKernel | None = None,
        reasoner_mode: str = DEFAULT_REASONER_MODE,
    ) -> OntologyKernel:
        path = Path(dir_path)
        if not path.exists():
            raise FileNotFoundError(f"missing ontology registry directory: {path}")

        ontology_path = path / "_ontology.ttl"
        shapes_path = path / "_shapes.ttl"
        mappings_path = path / "_claim_mappings.yaml"
        for required in (ontology_path, shapes_path, mappings_path):
            if not required.exists():
                raise FileNotFoundError(f"missing ontology artifact: {required}")

        ontology_ttl = ontology_path.read_text(encoding="utf-8")
        shapes_ttl = shapes_path.read_text(encoding="utf-8")
        raw_mappings = yaml.safe_load(mappings_path.read_text(encoding="utf-8")) or {}
        namespace = str(raw_mappings.get("namespace", "https://recosearch.example/ontology/ns#"))
        mappings = cls._parse_mappings(raw_mappings)

        if context_kernel is not None:
            cls._assert_terms_exist(mappings, context_kernel)

        mode = reasoner_mode if reasoner_mode in SUPPORTED_REASONER_MODES else DEFAULT_REASONER_MODE
        onto_hash = compute_ontology_hash(
            ontology_ttl=ontology_ttl,
            shapes_ttl=shapes_ttl,
            mappings={k: _mapping_dict(v) for k, v in mappings.items()},
            reasoner_mode=mode,
        )

        certifications: dict[str, OntologyCertification] = {}
        persisted: dict[str, dict[str, Any]] = {}
        cert_path = path / "_certification.yaml"
        if cert_path.exists():
            certifications = cls._parse_certifications(
                yaml.safe_load(cert_path.read_text(encoding="utf-8")) or {},
                onto_hash=onto_hash,
            )
        results_path = path / "_certification_results.yaml"
        if results_path.exists():
            raw_results = yaml.safe_load(results_path.read_text(encoding="utf-8")) or {}
            for item in raw_results.get("certification_results", []):
                key = str(item.get("ontology_hash", onto_hash))
                persisted[key] = item

        return OntologyKernel(
            namespace=namespace,
            ontology_ttl=ontology_ttl,
            shapes_ttl=shapes_ttl,
            mappings=MappingProxyType(mappings),
            ontology_hash=onto_hash,
            reasoner_mode=mode,
            certifications=MappingProxyType(certifications),
            persisted_certification_results=MappingProxyType(persisted),
        )

    @classmethod
    def from_contract(
        cls,
        contract: Mapping[str, Any],
        *,
        context_kernel: ContextKernel | None = None,
    ) -> OntologyKernel:
        raw = contract.get("ontology_kernel")
        if raw is None:
            raise ValueError("contract missing ontology_kernel")
        if not isinstance(raw, dict):
            raise ValueError("ontology_kernel must be a mapping")

        mappings = {
            term_id: TermMapping(
                term_id=str(term_id),
                revenue_type=str(item["revenue_type"]),
                claim_class=str(item.get("claim_class", "RevenueClaim")),
            )
            for term_id, item in raw.get("mappings", {}).items()
        }
        mode = str(raw.get("reasoner_mode", DEFAULT_REASONER_MODE))
        if context_kernel is not None:
            cls._assert_terms_exist(mappings, context_kernel)

        return OntologyKernel(
            namespace=str(raw.get("namespace", "https://recosearch.example/ontology/ns#")),
            ontology_ttl=str(raw["ontology_ttl"]),
            shapes_ttl=str(raw["shapes_ttl"]),
            mappings=MappingProxyType(mappings),
            ontology_hash=str(raw.get("ontology_hash", "")),
            reasoner_mode=mode,
            certifications=MappingProxyType(
                {
                    k: OntologyCertification(
                        ontology_hash=str(v["ontology_hash"]),
                        reasoner_mode=str(v.get("reasoner_mode", DEFAULT_REASONER_MODE)),
                        golden_cases=tuple(
                            GoldenConstraintCase(
                                term_id=str(gc["term_id"]),
                                tenant=str(gc.get("tenant", "novashop")),
                                actor_role=str(gc.get("actor_role", "analyst")),
                                claim_qualifiers=tuple(
                                    tuple(pair) for pair in gc.get("claim_qualifiers", [])
                                ),
                                expected_decision=str(gc["expected_decision"]),
                                expected_reason_code=str(gc.get("expected_reason_code", "")),
                            )
                            for gc in v.get("golden_cases", [])
                        ),
                        certified=v.get("certified"),
                        golden_passed=v.get("golden_passed"),
                    )
                    for k, v in raw.get("certifications", {}).items()
                }
            ),
            persisted_certification_results=MappingProxyType(
                dict(raw.get("persisted_certification_results", {}))
            ),
        )

    @classmethod
    def to_dict(cls, kernel: OntologyKernel) -> dict[str, Any]:
        return {
            "namespace": kernel.namespace,
            "ontology_ttl": kernel.ontology_ttl,
            "shapes_ttl": kernel.shapes_ttl,
            "ontology_hash": kernel.ontology_hash,
            "reasoner_mode": kernel.reasoner_mode,
            "mappings": {
                term_id: _mapping_dict(mapping) for term_id, mapping in kernel.mappings.items()
            },
            "certifications": {
                key: {
                    "ontology_hash": cert.ontology_hash,
                    "reasoner_mode": cert.reasoner_mode,
                    "golden_cases": [
                        {
                            "term_id": gc.term_id,
                            "tenant": gc.tenant,
                            "actor_role": gc.actor_role,
                            "claim_qualifiers": [list(pair) for pair in gc.claim_qualifiers],
                            "expected_decision": gc.expected_decision,
                            "expected_reason_code": gc.expected_reason_code,
                        }
                        for gc in cert.golden_cases
                    ],
                    "certified": cert.certified,
                    "golden_passed": cert.golden_passed,
                }
                for key, cert in kernel.certifications.items()
            },
            "persisted_certification_results": dict(kernel.persisted_certification_results),
        }

    @staticmethod
    def _parse_mappings(raw: dict[str, Any]) -> dict[str, TermMapping]:
        mappings: dict[str, TermMapping] = {}
        for item in raw.get("mappings", []):
            term_id = str(item["term_id"])
            mappings[term_id] = TermMapping(
                term_id=term_id,
                revenue_type=str(item["revenue_type"]),
                claim_class=str(item.get("claim_class", "RevenueClaim")),
            )
        return mappings

    @staticmethod
    def _parse_certifications(
        raw: dict[str, Any],
        *,
        onto_hash: str = "",
    ) -> dict[str, OntologyCertification]:
        certs: dict[str, OntologyCertification] = {}
        for item in raw.get("certifications", []):
            declared_hash = str(item.get("ontology_hash", ""))
            cert_hash = onto_hash if declared_hash == "placeholder" else declared_hash
            certs[cert_hash] = OntologyCertification(
                ontology_hash=cert_hash,
                reasoner_mode=str(item.get("reasoner_mode", DEFAULT_REASONER_MODE)),
                golden_cases=tuple(
                    GoldenConstraintCase(
                        term_id=str(gc["term_id"]),
                        tenant=str(gc.get("tenant", "novashop")),
                        actor_role=str(gc.get("actor_role", "analyst")),
                        claim_qualifiers=tuple(
                            (str(a), str(b)) for a, b in gc.get("claim_qualifiers", [])
                        ),
                        expected_decision=str(gc["expected_decision"]),
                        expected_reason_code=str(gc.get("expected_reason_code", "")),
                    )
                    for gc in item.get("golden_cases", [])
                ),
            )
        return certs

    @staticmethod
    def _assert_terms_exist(mappings: Mapping[str, TermMapping], context_kernel: ContextKernel) -> None:
        for term_id in mappings:
            if term_id not in context_kernel.terms:
                raise ValueError(
                    f"ontology mapping references unknown L2 term: {term_id}"
                )


def load_ontology_kernel(
    semantic_dir: Path | str,
    *,
    context_kernel: ContextKernel | None = None,
    reasoner_mode: str = DEFAULT_REASONER_MODE,
) -> OntologyKernel:
    ontology_dir = Path(semantic_dir) / "ontology"
    if not ontology_dir.exists():
        raise FileNotFoundError(f"missing ontology directory: {ontology_dir}")
    return OntologyKernelLoader.from_dir(
        ontology_dir,
        context_kernel=context_kernel,
        reasoner_mode=reasoner_mode,
    )


def _mapping_dict(mapping: TermMapping) -> dict[str, str]:
    return {
        "term_id": mapping.term_id,
        "revenue_type": mapping.revenue_type,
        "claim_class": mapping.claim_class,
    }
