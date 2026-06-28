from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from recosearch.semantic_layers.context.hash import compute_term_definition_hash
from recosearch.semantic_layers.context.schema import validate_context_kernel
from recosearch.semantic_layers.context.types import (
    ClientGuidance,
    ContextCertification,
    ContextKernel,
    GoldenContextQuestion,
    RelationshipEdge,
    TermBinding,
)
from recosearch.semantic_layers.metrics.loader import MetricKernel


def _tuple_str(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(v) for v in values)


@dataclass(frozen=True, slots=True)
class _ContextKernelBuilder:
    terms: dict[str, TermBinding]
    guidance: dict[str, ClientGuidance]
    relationships: list[RelationshipEdge]
    alias_index: dict[str, list[str]]
    alias_owners: dict[str, str]
    certifications: dict[str, ContextCertification]
    persisted_certification_results: dict[str, dict[str, Any]]

    def build(self) -> ContextKernel:
        frozen_aliases = {
            alias: tuple(sorted(set(term_ids)))
            for alias, term_ids in self.alias_index.items()
        }
        return ContextKernel(
            terms=MappingProxyType(self.terms),
            guidance=MappingProxyType(self.guidance),
            relationships=tuple(self.relationships),
            alias_index=MappingProxyType(frozen_aliases),
            certifications=MappingProxyType(self.certifications),
            persisted_certification_results=MappingProxyType(self.persisted_certification_results),
        )


class ContextKernelLoader:
    @classmethod
    def from_dir(cls, dir_path: Path | str, *, metric_kernel: MetricKernel | None = None) -> ContextKernel:
        merged: dict[str, Any] = {
            "version": 1,
            "terms": [],
            "guidance": [],
            "relationships": [],
            "certifications": [],
        }
        path = Path(dir_path)
        if not path.exists():
            raise FileNotFoundError(f"missing context registry directory: {path}")

        persisted_results: list[Any] = []
        trust_overrides_raw: dict[str, Any] | None = None
        for yaml_path in sorted(path.glob("*.yaml")):
            if yaml_path.name == "_certification_results.yaml":
                raw_results = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
                persisted_results = raw_results.get("certification_results", [])
                continue
            if yaml_path.name == "_trust_overrides.yaml":
                trust_overrides_raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
                continue
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{yaml_path} must be a mapping")
            if "terms" in raw:
                merged["terms"].extend(raw["terms"])
            if "guidance" in raw:
                merged["guidance"].extend(raw["guidance"])
            if "relationships" in raw:
                merged["relationships"].extend(raw["relationships"])
            if "certifications" in raw:
                merged["certifications"].extend(raw["certifications"])

        kernel = cls._from_raw(merged, metric_kernel=metric_kernel)
        if persisted_results:
            kernel = cls._apply_persisted_certification_results(kernel, persisted_results)
        if trust_overrides_raw:
            kernel = cls._apply_trust_overrides(kernel, trust_overrides_raw)
        return kernel

    @classmethod
    def from_contract(
        cls,
        contract: Mapping[str, Any],
        *,
        metric_kernel: MetricKernel | None = None,
    ) -> ContextKernel:
        kernel = contract.get("context_kernel")
        if kernel is None:
            raise ValueError("contract missing context_kernel")
        if not isinstance(kernel, dict):
            raise ValueError("context_kernel must be a mapping")
        mk = metric_kernel or MetricKernel.from_contract(contract)
        built = cls._from_raw(kernel, metric_kernel=mk)
        trust_overrides = contract.get("trust_overrides")
        if trust_overrides:
            built = cls._apply_trust_overrides(built, trust_overrides)
        return built

    @classmethod
    def _from_raw(cls, raw: dict[str, Any], *, metric_kernel: MetricKernel | None = None) -> ContextKernel:
        validate_context_kernel(raw)
        builder = _ContextKernelBuilder(
            terms={},
            guidance={},
            relationships=[],
            alias_index={},
            alias_owners={},
            certifications={},
            persisted_certification_results={},
        )

        for item in raw.get("terms", []):
            term_id = str(item["id"])
            if term_id in builder.terms:
                raise ValueError(f"duplicate term id {term_id}")
            definition_hash = compute_term_definition_hash(item)
            binding = TermBinding(
                term_id=term_id,
                display_name=str(item["display_name"]),
                definition=str(item["definition"]),
                aliases=_tuple_str(item.get("aliases", [])),
                collection_id=str(item["collection_id"]),
                primary_refs=_tuple_str(item["primary_refs"]),
                definition_hash=definition_hash,
            )
            builder.terms[term_id] = binding
            normalized_name = binding.display_name.strip().casefold()
            builder.alias_index.setdefault(normalized_name, []).append(term_id)
            seen_aliases: set[str] = set()
            for alias in binding.aliases:
                normalized_alias = alias.strip().casefold()
                if normalized_alias in seen_aliases:
                    raise ValueError(
                        f"term {term_id} has duplicate alias {alias!r}"
                    )
                seen_aliases.add(normalized_alias)
                owner = builder.alias_owners.get(normalized_alias)
                if owner is not None and owner != term_id:
                    raise ValueError(
                        f"duplicate alias {alias!r} on terms {owner} and {term_id}"
                    )
                builder.alias_owners[normalized_alias] = term_id
                builder.alias_index.setdefault(normalized_alias, []).append(term_id)

        for item in raw.get("guidance", []):
            term_id = str(item["term_id"])
            if term_id not in builder.terms:
                raise ValueError(f"guidance references unknown term {term_id}")
            if term_id in builder.guidance:
                raise ValueError(f"duplicate guidance for {term_id}")
            builder.guidance[term_id] = ClientGuidance(
                term_id=term_id,
                when_to_use=str(item["when_to_use"]),
                when_to_clarify=str(item["when_to_clarify"]),
                when_to_refuse=str(item["when_to_refuse"]),
            )

        for item in raw.get("relationships", []):
            from_id = str(item["from_id"])
            to_id = str(item["to_id"])
            if from_id not in builder.terms:
                raise ValueError(f"relationship from_id references unknown term {from_id}")
            cls._validate_relationship_target(to_id, builder.terms, metric_kernel)
            builder.relationships.append(
                RelationshipEdge(from_id=from_id, to_id=to_id, kind=str(item["kind"]))
            )

        for item in raw.get("certifications", []):
            term_id = str(item["term_id"])
            if term_id not in builder.terms:
                raise ValueError(f"certification references unknown term {term_id}")
            if term_id in builder.certifications:
                raise ValueError(f"duplicate certification for {term_id}")
            golden_questions: list[GoldenContextQuestion] = []
            for gq in item.get("golden_questions", []):
                expected_raw = gq.get("expected", {}) or {}
                golden_questions.append(
                    GoldenContextQuestion(
                        term=str(gq["term"]),
                        tenant=str(gq.get("tenant", "default")),
                        actor_role=str(gq.get("actor_role", "analyst")),
                        expected_decision=str(gq["expected_decision"]),
                        expected_trust_status=str(gq["expected_trust_status"]),
                        expected_evidence_tier=int(gq.get("expected_evidence_tier", 2)),
                        expected=tuple((str(k), v) for k, v in expected_raw.items()),
                    )
                )
            builder.certifications[term_id] = ContextCertification(
                term_id=term_id,
                definition_hash=str(item["definition_hash"]),
                policy_hash=str(item.get("policy_hash", "")),
                golden_questions=tuple(golden_questions),
                certified=item.get("certified"),
                golden_passed=item.get("golden_passed"),
                evidence_tier=(
                    int(item["evidence_tier"]) if item.get("evidence_tier") is not None else None
                ),
                ares_confidence_interval=(
                    tuple(float(v) for v in item["ares_confidence_interval"])
                    if item.get("ares_confidence_interval") is not None
                    else None
                ),
            )

        if metric_kernel is not None:
            cls._validate_refs(builder.terms, metric_kernel)

        return builder.build()

    @staticmethod
    def _validate_relationship_target(
        to_id: str,
        terms: Mapping[str, TermBinding],
        metric_kernel: MetricKernel | None,
    ) -> None:
        if to_id in terms:
            return
        if metric_kernel is None:
            raise ValueError(
                f"relationship to_id references unknown target {to_id}"
            )
        if to_id in metric_kernel.metrics:
            return
        if to_id in metric_kernel.entities:
            return
        if to_id in metric_kernel.dimensions:
            return
        if to_id in metric_kernel.measures:
            return
        if to_id in metric_kernel.relations:
            return
        known_sources = {entity.source_id for entity in metric_kernel.entities.values()}
        if ":" not in to_id and to_id in known_sources:
            return
        raise ValueError(f"relationship to_id references unknown target {to_id}")

    @staticmethod
    def _validate_refs(terms: Mapping[str, TermBinding], metric_kernel: MetricKernel) -> None:
        known_sources = {entity.source_id for entity in metric_kernel.entities.values()}
        for binding in terms.values():
            for ref in binding.primary_refs:
                if ref.startswith("metric:"):
                    if ref not in metric_kernel.metrics:
                        raise ValueError(f"term {binding.term_id} references unknown metric {ref}")
                elif ref.startswith("entity:"):
                    if ref not in metric_kernel.entities:
                        raise ValueError(f"term {binding.term_id} references unknown entity {ref}")
                elif ref.startswith("dimension:"):
                    if ref not in metric_kernel.dimensions:
                        raise ValueError(f"term {binding.term_id} references unknown dimension {ref}")
                elif ref.startswith("measure:"):
                    if ref not in metric_kernel.measures:
                        raise ValueError(f"term {binding.term_id} references unknown measure {ref}")
                elif ":" not in ref:
                    if ref not in known_sources:
                        raise ValueError(f"term {binding.term_id} references unknown source {ref}")
                else:
                    raise ValueError(f"term {binding.term_id} has unsupported ref prefix: {ref}")

    @classmethod
    def _apply_persisted_certification_results(
        cls,
        kernel: ContextKernel,
        entries: list[Any],
    ) -> ContextKernel:
        results: dict[str, dict[str, Any]] = {}
        persisted: dict[str, dict[str, Any]] = {}
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("certification_results entries must be mappings")
            term_id = str(item["term_id"])
            term = kernel.terms.get(term_id)
            hash_match = term is not None and str(item.get("definition_hash", "")) == term.definition_hash
            results[term_id] = {
                "definition_hash": str(item.get("definition_hash", "")),
                "policy_hash": str(item.get("policy_hash", "")),
                "certified": bool(item.get("certified")) and hash_match,
                "golden_passed": bool(item.get("golden_passed")) and hash_match,
                "evidence_tier": int(item.get("evidence_tier", 2)) if hash_match else 1,
                "ares_confidence_interval": item.get("ares_confidence_interval"),
            }
            persisted[term_id] = dict(item)
        return cls.with_certification_results(kernel, results, persisted=persisted)

    @classmethod
    def _apply_trust_overrides(
        cls,
        kernel: ContextKernel,
        raw: Mapping[str, Any],
    ) -> ContextKernel:
        overrides = raw.get("overrides") or []
        if not overrides:
            return kernel
        results: dict[str, dict[str, Any]] = {}
        for item in overrides:
            if not isinstance(item, dict):
                continue
            term_id = str(item.get("term_id", ""))
            if not term_id:
                continue
            cert = kernel.certifications.get(term_id)
            if cert is None:
                continue
            ci = item.get("ares_confidence_interval")
            if ci is None:
                continue
            results[term_id] = {
                "definition_hash": cert.definition_hash,
                "policy_hash": cert.policy_hash,
                "certified": cert.certified,
                "golden_passed": cert.golden_passed,
                "evidence_tier": cert.evidence_tier or 2,
                "ares_confidence_interval": ci,
            }
        if not results:
            return kernel
        return cls.with_certification_results(kernel, results)

    @classmethod
    def with_certification_results(
        cls,
        kernel: ContextKernel,
        results: Mapping[str, Mapping[str, Any]],
        *,
        persisted: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ContextKernel:
        certifications = dict(kernel.certifications)
        for term_id, result in results.items():
            cert = certifications.get(term_id)
            if cert is None:
                continue
            certifications[term_id] = ContextCertification(
                term_id=cert.term_id,
                definition_hash=cert.definition_hash,
                policy_hash=str(result.get("policy_hash", cert.policy_hash)),
                golden_questions=cert.golden_questions,
                certified=bool(result.get("certified")),
                golden_passed=bool(result.get("golden_passed")),
                evidence_tier=int(result.get("evidence_tier", cert.evidence_tier or 2)),
                ares_confidence_interval=(
                    tuple(float(v) for v in result["ares_confidence_interval"])
                    if result.get("ares_confidence_interval") is not None
                    else cert.ares_confidence_interval
                ),
            )
        persisted_results = dict(kernel.persisted_certification_results)
        if persisted:
            persisted_results.update(dict(persisted))
        return ContextKernel(
            terms=kernel.terms,
            guidance=kernel.guidance,
            relationships=kernel.relationships,
            alias_index=kernel.alias_index,
            certifications=MappingProxyType(certifications),
            persisted_certification_results=MappingProxyType(persisted_results),
        )

    @staticmethod
    def to_dict(kernel: ContextKernel) -> dict[str, Any]:
        return {
            "version": 1,
            "terms": [
                {
                    "id": term.term_id,
                    "display_name": term.display_name,
                    "definition": term.definition,
                    "aliases": list(term.aliases),
                    "collection_id": term.collection_id,
                    "primary_refs": list(term.primary_refs),
                }
                for term in sorted(kernel.terms.values(), key=lambda t: t.term_id)
            ],
            "guidance": [
                {
                    "term_id": g.term_id,
                    "when_to_use": g.when_to_use,
                    "when_to_clarify": g.when_to_clarify,
                    "when_to_refuse": g.when_to_refuse,
                }
                for g in sorted(kernel.guidance.values(), key=lambda g: g.term_id)
            ],
            "relationships": [
                {"from_id": e.from_id, "to_id": e.to_id, "kind": e.kind}
                for e in kernel.relationships
            ],
            "certifications": [
                _cert_to_dict(cert)
                for cert in sorted(kernel.certifications.values(), key=lambda c: c.term_id)
            ],
        }


def _cert_to_dict(cert: ContextCertification) -> dict[str, Any]:
    out: dict[str, Any] = {
        "term_id": cert.term_id,
        "definition_hash": cert.definition_hash,
        "policy_hash": cert.policy_hash,
        "golden_questions": [
            {
                "term": gq.term,
                "tenant": gq.tenant,
                "actor_role": gq.actor_role,
                "expected_decision": gq.expected_decision,
                "expected_trust_status": gq.expected_trust_status,
                "expected_evidence_tier": gq.expected_evidence_tier,
                "expected": dict(gq.expected),
            }
            for gq in cert.golden_questions
        ],
    }
    if cert.certified is not None:
        out["certified"] = cert.certified
    if cert.golden_passed is not None:
        out["golden_passed"] = cert.golden_passed
    if cert.evidence_tier is not None:
        out["evidence_tier"] = cert.evidence_tier
    if cert.ares_confidence_interval is not None:
        out["ares_confidence_interval"] = list(cert.ares_confidence_interval)
    return out


def load_context_kernel(
    semantic_dir: Path,
    *,
    metric_kernel: MetricKernel | None = None,
) -> ContextKernel:
    context_dir = semantic_dir / "context"
    mk = metric_kernel
    if mk is None and (semantic_dir / "metrics").exists():
        mk = MetricKernel.from_dir(semantic_dir / "metrics")
    return ContextKernelLoader.from_dir(context_dir, metric_kernel=mk)
