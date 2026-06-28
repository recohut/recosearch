from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from recosearch.semantic_layers.metrics.formula import extract_refs
from recosearch.semantic_layers.metrics.hash import compute_definition_hash
from recosearch.semantic_layers.metrics.schema import validate_certification_results, validate_metric_kernel
from recosearch.semantic_layers.metrics.types import (
    METRIC_KINDS,
    METRIC_STATUSES,
    Certification,
    Collection,
    Dimension,
    Entity,
    FreshnessSLA,
    GoldenQuestion,
    Measure,
    Metric,
    Relation,
    TimeSpine,
)

def _scope_pairs(scope: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not scope:
        return ()
    return tuple(sorted(scope.items()))


def _tuple_str(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(v) for v in values)


def _detect_cycles(metrics: dict[str, dict[str, Any]]) -> None:
    graph: dict[str, list[str]] = {}
    for metric_id, item in metrics.items():
        if item.get("kind", "measure") != "derived":
            continue
        refs = []
        for ref in extract_refs(str(item.get("formula", ""))):
            if ref.startswith("metric:"):
                refs.append(ref)
        graph[metric_id] = refs

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> None:
        if node in visiting:
            raise ValueError(f"derived metric cycle detected at {node}")
        if node in visited:
            return
        visiting.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in metrics:
                raise ValueError(f"derived metric {node} references unknown metric {neighbor}")
            dfs(neighbor)
        visiting.remove(node)
        visited.add(node)

    for metric_id in graph:
        dfs(metric_id)


@dataclass(frozen=True, slots=True)
class MetricKernel:
    collections: Mapping[str, Collection]
    rule_definitions: Mapping[str, Mapping[str, Any]]
    entities: Mapping[str, Entity]
    measures: Mapping[str, Measure]
    dimensions: Mapping[str, Dimension]
    relations: Mapping[str, Relation]
    time_spine: TimeSpine | None
    certifications: Mapping[str, Certification]
    metrics: Mapping[str, Metric]
    persisted_certification_results: Mapping[str, Mapping[str, Any]]

    @classmethod
    def from_dir(cls, dir_path: Path | str) -> MetricKernel:
        merged: dict[str, Any] = {
            "version": 1,
            "metric_collections": [],
            "rule_definitions": {},
            "entities": [],
            "measures": [],
            "dimensions": [],
            "relations": [],
            "metrics": [],
            "certifications": [],
            "time_spine": None,
        }
        list_sections = (
            "metric_collections",
            "entities",
            "measures",
            "dimensions",
            "relations",
            "metrics",
            "certifications",
        )
        rule_definitions = merged["rule_definitions"]
        assert isinstance(rule_definitions, dict)

        for path in sorted(Path(dir_path).glob("*.yaml")):
            if path.name == "_certification_results.yaml":
                continue
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{path} must be a mapping")
            for section in list_sections:
                values = raw.get(section, [])
                if values is None:
                    continue
                if not isinstance(values, list):
                    raise ValueError(f"{path}:{section} must be a list")
                merged[section].extend(values)
            rules = raw.get("rule_definitions", {})
            if rules is None:
                continue
            if not isinstance(rules, dict):
                raise ValueError(f"{path}:rule_definitions must be a mapping")
            for rule_id, definition in rules.items():
                rule_id = str(rule_id)
                if rule_id in rule_definitions:
                    raise ValueError(f"duplicate rule id {rule_id}")
                rule_definitions[rule_id] = definition
            if raw.get("time_spine") is not None:
                if merged["time_spine"] is not None:
                    raise ValueError("duplicate time_spine definition")
                merged["time_spine"] = raw["time_spine"]
        kernel = cls._from_raw(merged)
        cert_results_path = Path(dir_path) / "_certification_results.yaml"
        if cert_results_path.exists():
            raw_results = yaml.safe_load(cert_results_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw_results, dict):
                raise ValueError(f"{cert_results_path} must be a mapping")
            validate_certification_results(raw_results)
            kernel = kernel._apply_persisted_certification_results(raw_results.get("certification_results", []))
        return kernel

    @classmethod
    def from_contract(cls, contract: Mapping[str, Any]) -> MetricKernel:
        kernel = contract.get("metric_kernel")
        if kernel is None:
            raise ValueError("contract missing metric_kernel")
        if not isinstance(kernel, dict):
            raise ValueError("metric_kernel must be a mapping")
        return cls._from_raw(kernel)

    @classmethod
    def _from_raw(cls, raw: dict[str, Any]) -> MetricKernel:
        validate_metric_kernel(raw)
        collections: dict[str, Collection] = {}
        for item in raw.get("metric_collections", []):
            collection_id = item["id"]
            if collection_id in collections:
                raise ValueError(f"duplicate collection id {collection_id}")
            collections[collection_id] = Collection(
                collection_id=collection_id,
                priority=int(item["priority"]),
                scope=_scope_pairs(item.get("scope")),
            )

        rule_definitions: dict[str, dict[str, Any]] = {}
        for rule_id, definition in (raw.get("rule_definitions") or {}).items():
            if not isinstance(definition, dict):
                raise ValueError(f"rule_definitions.{rule_id} must be a mapping")
            rule_definitions[str(rule_id)] = dict(definition)

        entities: dict[str, Entity] = {}
        for item in raw.get("entities", []):
            entity_id = item["id"]
            if entity_id in entities:
                raise ValueError(f"duplicate entity id {entity_id}")
            entities[entity_id] = Entity(
                entity_id=entity_id,
                source_id=item["source_id"],
                table=item["table"],
                primary_key=item["primary_key"],
                time_field=str(item.get("time_field", "")),
                external_ref=str(item.get("external_ref", "")),
            )

        measures: dict[str, Measure] = {}
        for item in raw.get("measures", []):
            measure_id = item["id"]
            if measure_id in measures:
                raise ValueError(f"duplicate measure id {measure_id}")
            measures[measure_id] = Measure(
                measure_id=measure_id,
                entity_id=item["entity_id"],
                field=item["field"],
                aggregation=item["aggregation"],
                external_ref=str(item.get("external_ref", "")),
            )

        dimensions: dict[str, Dimension] = {}
        for item in raw.get("dimensions", []):
            dimension_id = item["id"]
            if dimension_id in dimensions:
                raise ValueError(f"duplicate dimension id {dimension_id}")
            dimensions[dimension_id] = Dimension(
                dimension_id=dimension_id,
                entity_id=item["entity_id"],
                field=item["field"],
                type=item["type"],
            )

        relations: dict[str, Relation] = {}
        for item in raw.get("relations", []):
            relation_id = item["id"]
            if relation_id in relations:
                raise ValueError(f"duplicate relation id {relation_id}")
            relations[relation_id] = Relation(
                relation_id=relation_id,
                from_entity_id=item["from_entity_id"],
                to_entity_id=item["to_entity_id"],
                join_key=item["join_key"],
                cardinality=item["cardinality"],
            )

        time_spine = _parse_time_spine(raw.get("time_spine"))

        raw_metrics: dict[str, dict[str, Any]] = {}
        for item in raw.get("metrics", []):
            metric_id = item["id"]
            if metric_id in raw_metrics:
                raise ValueError(f"duplicate metric id {metric_id}")
            raw_metrics[metric_id] = dict(item)

        _detect_cycles(raw_metrics)

        metrics: dict[str, Metric] = {}
        for metric_id, item in raw_metrics.items():
            collection_id = item["collection_id"]
            kind = str(item.get("kind", "measure"))
            if kind not in METRIC_KINDS:
                raise ValueError(f"metric {metric_id} has invalid kind {kind}")
            status = str(item.get("status", "draft"))
            if status not in METRIC_STATUSES - {"uncertified"}:
                raise ValueError(f"metric {metric_id} has invalid status {status}")
            deprecated = bool(item.get("deprecated", False))
            if deprecated and not str(item.get("superseded_by", "")):
                raise ValueError(f"deprecated metric {metric_id} must specify superseded_by")

            measure_id = str(item.get("measure_id", ""))
            formula = str(item.get("formula", ""))
            if kind == "measure":
                if not measure_id:
                    raise ValueError(f"measure metric {metric_id} requires measure_id")
            else:
                if not formula:
                    raise ValueError(f"derived metric {metric_id} requires formula")
                formula_refs = extract_refs(formula)
                for ref in formula_refs:
                    if ref.startswith("measure:") and ref not in measures:
                        raise ValueError(f"metric {metric_id} references unknown measure {ref}")
                    if ref.startswith("metric:") and ref not in raw_metrics:
                        raise ValueError(f"metric {metric_id} references unknown metric {ref}")

            if collection_id not in collections:
                raise ValueError(f"metric {metric_id} references unknown collection {collection_id}")
            if measure_id and measure_id not in measures:
                raise ValueError(f"metric {metric_id} references unknown measure {measure_id}")
            for dimension_id in item.get("allowed_dimension_ids", []):
                if dimension_id not in dimensions:
                    raise ValueError(f"metric {metric_id} references unknown dimension {dimension_id}")
            for rule_name in item.get("filter_rules", []):
                if str(rule_name) not in rule_definitions:
                    raise ValueError(f"metric {metric_id} references unknown rule {rule_name}")

            grain = str(item["grain"])
            if kind == "derived":
                for ref in extract_refs(formula):
                    if ref.startswith("metric:"):
                        ref_metric = raw_metrics[ref]
                        if str(ref_metric.get("grain", "")) != grain:
                            raise ValueError(
                                f"metric {metric_id} grain {grain} incompatible with {ref} grain {ref_metric.get('grain')}"
                            )

            definition_hash = compute_definition_hash(item)
            metrics[metric_id] = Metric(
                metric_id=metric_id,
                display_name=item["display_name"],
                collection_id=collection_id,
                measure_id=measure_id,
                kind=kind,
                formula=formula,
                formula_refs=extract_refs(formula),
                grain=grain,
                filter_rules=_tuple_str(item.get("filter_rules")),
                allowed_dimension_ids=_tuple_str(item.get("allowed_dimension_ids")),
                synonyms=_tuple_str(item.get("synonyms")),
                external_ref=str(item.get("external_ref", "")),
                owners=_tuple_str(item.get("owners")),
                version=str(item.get("version", "1.0.0")),
                status=status,
                certification_tier=str(item.get("certification_tier", "")),
                deprecated=deprecated,
                superseded_by=str(item.get("superseded_by", "")),
                definition_hash=definition_hash,
                freshness_sla=_parse_freshness_sla(item.get("freshness_sla")),
            )

        for measure in measures.values():
            if measure.entity_id not in entities:
                raise ValueError(f"measure {measure.measure_id} references unknown entity {measure.entity_id}")

        for dimension in dimensions.values():
            if dimension.entity_id not in entities:
                raise ValueError(f"dimension {dimension.dimension_id} references unknown entity {dimension.entity_id}")

        for relation in relations.values():
            if relation.from_entity_id not in entities:
                raise ValueError(f"relation {relation.relation_id} references unknown from_entity {relation.from_entity_id}")
            if relation.to_entity_id not in entities:
                raise ValueError(f"relation {relation.relation_id} references unknown to_entity {relation.to_entity_id}")

        certifications: dict[str, Certification] = {}
        for item in raw.get("certifications", []):
            metric_id = item["metric_id"]
            if metric_id in certifications:
                raise ValueError(f"duplicate certification for {metric_id}")
            if metric_id not in metrics:
                raise ValueError(f"certification references unknown metric {metric_id}")
            golden_questions: list[GoldenQuestion] = []
            for gq in item.get("golden_questions", []):
                expected = gq.get("expected", {})
                if not isinstance(expected, dict):
                    raise ValueError(f"golden question expected must be a mapping for {metric_id}")
                golden_questions.append(
                    GoldenQuestion(
                        term=str(gq["term"]),
                        tenant=str(gq.get("tenant", "default")),
                        dimensions=_tuple_str(gq.get("dimensions")),
                        expected=tuple(sorted(expected.items())),
                    )
                )
            certifications[metric_id] = Certification(
                metric_id=metric_id,
                definition_hash=str(item["definition_hash"]),
                golden_questions=tuple(golden_questions),
                certified=item.get("certified"),
                golden_passed=item.get("golden_passed"),
            )

        frozen_rules = {rule_id: MappingProxyType(definition) for rule_id, definition in rule_definitions.items()}
        return cls(
            collections=MappingProxyType(collections),
            rule_definitions=MappingProxyType(frozen_rules),
            entities=MappingProxyType(entities),
            measures=MappingProxyType(measures),
            dimensions=MappingProxyType(dimensions),
            relations=MappingProxyType(relations),
            time_spine=time_spine,
            certifications=MappingProxyType(certifications),
            metrics=MappingProxyType(metrics),
            persisted_certification_results=MappingProxyType({}),
        )

    def to_dict(self) -> dict[str, Any]:
        collections = [
            {
                "id": collection.collection_id,
                "priority": collection.priority,
                "scope": dict(collection.scope),
            }
            for collection in sorted(self.collections.values(), key=lambda c: (-c.priority, c.collection_id))
        ]

        entities = [
            {
                "id": entity.entity_id,
                "source_id": entity.source_id,
                "table": entity.table,
                "primary_key": entity.primary_key,
                "time_field": entity.time_field,
                **({"external_ref": entity.external_ref} if entity.external_ref else {}),
            }
            for entity in sorted(self.entities.values(), key=lambda e: e.entity_id)
        ]

        measures = [
            {
                "id": measure.measure_id,
                "entity_id": measure.entity_id,
                "field": measure.field,
                "aggregation": measure.aggregation,
                **({"external_ref": measure.external_ref} if measure.external_ref else {}),
            }
            for measure in sorted(self.measures.values(), key=lambda m: m.measure_id)
        ]

        dimensions = [
            {
                "id": dimension.dimension_id,
                "entity_id": dimension.entity_id,
                "field": dimension.field,
                "type": dimension.type,
            }
            for dimension in sorted(self.dimensions.values(), key=lambda d: d.dimension_id)
        ]

        relations = [
            {
                "id": relation.relation_id,
                "from_entity_id": relation.from_entity_id,
                "to_entity_id": relation.to_entity_id,
                "join_key": relation.join_key,
                "cardinality": relation.cardinality,
            }
            for relation in sorted(self.relations.values(), key=lambda r: r.relation_id)
        ]

        metrics = []
        for metric in sorted(self.metrics.values(), key=lambda m: m.metric_id):
            entry: dict[str, Any] = {
                "id": metric.metric_id,
                "display_name": metric.display_name,
                "collection_id": metric.collection_id,
                "grain": metric.grain,
                "filter_rules": list(metric.filter_rules),
                "allowed_dimension_ids": list(metric.allowed_dimension_ids),
                "kind": metric.kind,
                "version": metric.version,
                "status": metric.status,
                "definition_hash": metric.definition_hash,
            }
            if metric.measure_id:
                entry["measure_id"] = metric.measure_id
            if metric.formula:
                entry["formula"] = metric.formula
            if metric.synonyms:
                entry["synonyms"] = list(metric.synonyms)
            if metric.external_ref:
                entry["external_ref"] = metric.external_ref
            if metric.owners:
                entry["owners"] = list(metric.owners)
            if metric.certification_tier:
                entry["certification_tier"] = metric.certification_tier
            if metric.deprecated:
                entry["deprecated"] = True
                entry["superseded_by"] = metric.superseded_by
            if metric.freshness_sla is not None:
                entry["freshness_sla"] = {
                    "max_age_days": metric.freshness_sla.max_age_days,
                    **(
                        {"hard_sla": True}
                        if metric.freshness_sla.hard_sla
                        else {}
                    ),
                }
            metrics.append(entry)

        rule_definitions = {
            rule_id: dict(definition) for rule_id, definition in self.rule_definitions.items()
        }

        certifications = [
            {
                "metric_id": cert.metric_id,
                "definition_hash": cert.definition_hash,
                "golden_questions": [
                    {
                        "term": gq.term,
                        "tenant": gq.tenant,
                        "dimensions": list(gq.dimensions),
                        "expected": dict(gq.expected),
                    }
                    for gq in cert.golden_questions
                ],
                **(
                    {"certified": cert.certified}
                    if cert.certified is not None
                    else {}
                ),
                **(
                    {"golden_passed": cert.golden_passed}
                    if cert.golden_passed is not None
                    else {}
                ),
            }
            for cert in sorted(self.certifications.values(), key=lambda c: c.metric_id)
        ]

        out: dict[str, Any] = {
            "version": 2,
            "metric_collections": collections,
            "rule_definitions": rule_definitions,
            "entities": entities,
            "measures": measures,
            "dimensions": dimensions,
            "relations": relations,
            "metrics": metrics,
            "certifications": certifications,
        }
        if self.time_spine is not None:
            out["time_spine"] = {
                "timezone": self.time_spine.timezone,
                "min_grain": self.time_spine.min_grain,
                "supported_grains": list(self.time_spine.supported_grains),
                "period_macros": {k: dict(v) for k, v in self.time_spine.period_macros},
            }
        return out

    def _apply_persisted_certification_results(self, entries: list[Any]) -> MetricKernel:
        results: dict[str, dict[str, Any]] = {}
        persisted: dict[str, Mapping[str, Any]] = {}
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("certification_results entries must be mappings")
            metric_id = str(item["metric_id"])
            persisted[metric_id] = MappingProxyType(dict(item))
            metric = self.metrics.get(metric_id)
            hash_match = metric is not None and str(item.get("definition_hash", "")) == metric.definition_hash
            results[metric_id] = {
                "certified": bool(item.get("certified")) and hash_match,
                "golden_passed": bool(item.get("golden_passed")) and hash_match,
            }
        kernel = self.with_certification_results(results)
        return MetricKernel(
            collections=kernel.collections,
            rule_definitions=kernel.rule_definitions,
            entities=kernel.entities,
            measures=kernel.measures,
            dimensions=kernel.dimensions,
            relations=kernel.relations,
            time_spine=kernel.time_spine,
            certifications=kernel.certifications,
            metrics=kernel.metrics,
            persisted_certification_results=MappingProxyType(persisted),
        )

    def with_certification_results(self, results: Mapping[str, Mapping[str, Any]]) -> MetricKernel:
        certifications = dict(self.certifications)
        for metric_id, result in results.items():
            cert = certifications.get(metric_id)
            if cert is None:
                continue
            golden_questions = result.get("golden_questions", [])
            golden_passed = result.get("golden_passed")
            if golden_passed is None and golden_questions:
                golden_passed = all(bool(gq.get("passed")) for gq in golden_questions)
            certifications[metric_id] = Certification(
                metric_id=cert.metric_id,
                definition_hash=cert.definition_hash,
                golden_questions=cert.golden_questions,
                certified=result.get("certified"),
                golden_passed=golden_passed,
            )
        return MetricKernel(
            collections=self.collections,
            rule_definitions=self.rule_definitions,
            entities=self.entities,
            measures=self.measures,
            dimensions=self.dimensions,
            relations=self.relations,
            time_spine=self.time_spine,
            certifications=MappingProxyType(certifications),
            metrics=self.metrics,
            persisted_certification_results=self.persisted_certification_results,
        )


def _parse_freshness_sla(raw: Any) -> FreshnessSLA | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("freshness_sla must be a mapping")
    max_age = raw.get("max_age_days")
    if max_age is None:
        raise ValueError("freshness_sla requires max_age_days")
    return FreshnessSLA(
        max_age_days=int(max_age),
        hard_sla=bool(raw.get("hard_sla", False)),
    )


def _parse_time_spine(raw: Any) -> TimeSpine | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("time_spine must be a mapping")
    supported = _tuple_str(raw.get("supported_grains", []))
    macros_raw = raw.get("period_macros", {})
    if not isinstance(macros_raw, dict):
        raise ValueError("time_spine.period_macros must be a mapping")
    macros = tuple(sorted((str(k), dict(v)) for k, v in macros_raw.items()))
    return TimeSpine(
        timezone=str(raw.get("timezone", "UTC")),
        min_grain=str(raw.get("min_grain", "day")),
        supported_grains=supported,
        period_macros=macros,
    )
