from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from recosearch.semantic_layers.compiler import _check_identifier
from recosearch.semantic_layers.metrics.types import Entity, FreshnessSLA, Metric
from recosearch.semantic_layers.sql_lint import lint_select_only


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    max_data_date: date | None
    reference_date: date
    age_days: int | None
    is_stale: bool
    max_age_days: int
    hard_sla: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_data_date": self.max_data_date.isoformat() if self.max_data_date else None,
            "reference_date": self.reference_date.isoformat(),
            "age_days": self.age_days,
            "is_stale": self.is_stale,
            "max_age_days": self.max_age_days,
            "hard_sla": self.hard_sla,
        }


def resolve_freshness_sla(
    source_cfg: Mapping[str, Any],
    metric: Metric | None = None,
) -> FreshnessSLA | None:
    if metric is not None and metric.freshness_sla is not None:
        return metric.freshness_sla
    freshness = source_cfg.get("freshness")
    if not isinstance(freshness, dict):
        return None
    max_age = freshness.get("max_age_days")
    if max_age is None:
        return None
    return FreshnessSLA(
        max_age_days=int(max_age),
        hard_sla=bool(freshness.get("hard_sla", False)),
    )


def query_max_time_field(
    adapter: Any,
    connection: Any,
    entity: Entity,
    *,
    dialect: str = "duckdb",
) -> date | None:
    if not entity.time_field:
        return None
    _check_identifier(entity.table, "table")
    _check_identifier(entity.time_field, "column")
    sql = f"SELECT MAX({entity.time_field}) AS max_date FROM {entity.table}"
    safe_sql = lint_select_only(sql, dialect=dialect)
    rows = adapter.run_structured_query(connection, safe_sql, row_limit=1)
    if not rows:
        return None
    raw = rows[0].get("max_date")
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, str):
        return date.fromisoformat(raw[:10])
    return None


def check_freshness(
    *,
    max_data_date: date | None,
    reference_date: date,
    sla: FreshnessSLA,
) -> FreshnessResult:
    if max_data_date is None:
        age_days = None
        is_stale = True
    else:
        age_days = (reference_date - max_data_date).days
        is_stale = age_days > sla.max_age_days
    return FreshnessResult(
        max_data_date=max_data_date,
        reference_date=reference_date,
        age_days=age_days,
        is_stale=is_stale,
        max_age_days=sla.max_age_days,
        hard_sla=sla.hard_sla,
    )


def assess_freshness(
    adapter: Any,
    connection: Any,
    entity: Entity,
    source_cfg: Mapping[str, Any],
    *,
    reference_date: date,
    metric: Metric | None = None,
    dialect: str = "duckdb",
) -> FreshnessResult | None:
    sla = resolve_freshness_sla(source_cfg, metric)
    if sla is None:
        return None
    max_data_date = query_max_time_field(adapter, connection, entity, dialect=dialect)
    return check_freshness(max_data_date=max_data_date, reference_date=reference_date, sla=sla)
