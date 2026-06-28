from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from recosearch.semantic_layers.plan import QueryPlan

METRIC_STATUSES = frozenset({"draft", "certified", "deprecated", "uncertified"})
METRIC_KINDS = frozenset({"measure", "derived"})


@dataclass(frozen=True, slots=True)
class FreshnessSLA:
    max_age_days: int
    hard_sla: bool = False


@dataclass(frozen=True, slots=True)
class MetricQuery:
    term: str
    dimensions: tuple[str, ...] = ()
    filters: tuple[tuple[str, Any], ...] = ()
    tenant: str = "default"
    industry: str | None = None
    time_grain: str | None = None
    time_period: str | None = None
    reference_date: date | None = None


@dataclass(frozen=True, slots=True)
class Collection:
    collection_id: str
    priority: int
    scope: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: str
    source_id: str
    table: str
    primary_key: str
    time_field: str
    external_ref: str = ""


@dataclass(frozen=True, slots=True)
class Measure:
    measure_id: str
    entity_id: str
    field: str
    aggregation: str
    external_ref: str = ""


@dataclass(frozen=True, slots=True)
class Dimension:
    dimension_id: str
    entity_id: str
    field: str
    type: str


@dataclass(frozen=True, slots=True)
class Relation:
    relation_id: str
    from_entity_id: str
    to_entity_id: str
    join_key: str
    cardinality: str


@dataclass(frozen=True, slots=True)
class TimeSpine:
    timezone: str
    min_grain: str
    supported_grains: tuple[str, ...]
    period_macros: tuple[tuple[str, dict[str, Any]], ...]


@dataclass(frozen=True, slots=True)
class GoldenQuestion:
    term: str
    tenant: str
    dimensions: tuple[str, ...]
    expected: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Certification:
    metric_id: str
    definition_hash: str
    golden_questions: tuple[GoldenQuestion, ...]
    certified: bool | None = None
    golden_passed: bool | None = None


@dataclass(frozen=True, slots=True)
class Metric:
    metric_id: str
    display_name: str
    collection_id: str
    grain: str
    filter_rules: tuple[str, ...]
    allowed_dimension_ids: tuple[str, ...]
    measure_id: str = ""
    kind: str = "measure"
    formula: str = ""
    formula_refs: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    external_ref: str = ""
    owners: tuple[str, ...] = ()
    version: str = "1.0.0"
    status: str = "draft"
    certification_tier: str = ""
    deprecated: bool = False
    superseded_by: str = ""
    definition_hash: str = ""
    freshness_sla: FreshnessSLA | None = None


@dataclass(frozen=True, slots=True)
class ResolvedMetric:
    metric_id: str
    display_name: str
    collection: Collection
    fallback_used: bool
    measure_id: str
    grain: str
    filter_rules: tuple[str, ...]
    allowed_dimension_ids: tuple[str, ...]
    caveat_codes: tuple[str, ...]
    version: str = ""
    definition_hash: str = ""
    status: str = ""
    kind: str = "measure"
    formula: str = ""
    formula_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClarifyRequest:
    reason: str
    requested_term: str
    available_metrics: tuple[str, ...] = ()
    candidates: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledMetricQuery:
    sql: str
    plan: QueryPlan
    metric_refs: tuple[str, ...]
    grain: str
    fallback_metric_refs: tuple[str, ...]
    column_lineage: tuple[tuple[str, str, str], ...] = ()
