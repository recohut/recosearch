from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import sqlglot

from recosearch.semantic_layers.compiler import _check_identifier, _literal
from recosearch.semantic_layers.identity import Actor
from recosearch.semantic_layers.metrics.formula import render_formula
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.relations import path_has_additive_fanout, plan_relation_path
from recosearch.semantic_layers.metrics.types import CompiledMetricQuery, ResolvedMetric, TimeSpine
from recosearch.semantic_layers.plan import build_structured_query_plan


class DimensionNotAllowed(Exception):
    def __init__(self, metric_id: str, requested: str, allowed: tuple[str, ...]) -> None:
        self.metric_id = metric_id
        self.requested = requested
        self.allowed = allowed
        super().__init__(f"{requested} not allowed for {metric_id}; allowed: {allowed}")


class FanoutNotAllowed(Exception):
    def __init__(self, metric_id: str, relation_id: str, cardinality: str) -> None:
        self.metric_id = metric_id
        self.relation_id = relation_id
        self.cardinality = cardinality
        super().__init__(f"fanout join {relation_id} ({cardinality}) blocked for {metric_id}")


class TimeGrainNotSupported(Exception):
    def __init__(self, grain: str, supported: tuple[str, ...]) -> None:
        self.grain = grain
        self.supported = supported
        super().__init__(f"time grain {grain} not supported; supported: {supported}")


class ReferenceDateRequired(Exception):
    def __init__(self, period: str) -> None:
        self.period = period
        super().__init__(f"reference_date is required for time period {period}")


class MetricCompiler:
    def __init__(self, kernel: MetricKernel) -> None:
        self._kernel = kernel

    def compile(
        self,
        resolved: ResolvedMetric,
        requested_dims: tuple[str, ...],
        user_filters: tuple[tuple[str, Any], ...] = (),
        *,
        contract_hash: str = "",
        actor: Actor | None = None,
        scoped_question: str = "",
        max_limit: int = 100,
        time_grain: str | None = None,
        time_period: str | None = None,
        reference_date: date | None = None,
    ) -> CompiledMetricQuery:
        metric = self._kernel.metrics[resolved.metric_id]
        allowed = set(resolved.allowed_dimension_ids)
        for dimension_id in requested_dims:
            if dimension_id not in allowed:
                raise DimensionNotAllowed(resolved.metric_id, dimension_id, resolved.allowed_dimension_ids)

        if time_grain and self._kernel.time_spine is not None:
            if time_grain not in self._kernel.time_spine.supported_grains:
                raise TimeGrainNotSupported(time_grain, self._kernel.time_spine.supported_grains)

        if metric.kind == "derived":
            return self._compile_derived(
                resolved,
                metric,
                requested_dims,
                user_filters,
                contract_hash=contract_hash,
                actor=actor,
                scoped_question=scoped_question,
                max_limit=max_limit,
                time_grain=time_grain,
                time_period=time_period,
                reference_date=reference_date,
            )

        measure = self._kernel.measures[resolved.measure_id]
        entity = self._kernel.entities[measure.entity_id]
        return self._compile_measure_metric(
            resolved,
            metric,
            measure,
            entity,
            requested_dims,
            user_filters,
            contract_hash=contract_hash,
            actor=actor,
            scoped_question=scoped_question,
            max_limit=max_limit,
            time_grain=time_grain,
            time_period=time_period,
            reference_date=reference_date,
        )

    def _compile_measure_metric(
        self,
        resolved: ResolvedMetric,
        metric,
        measure,
        entity,
        requested_dims: tuple[str, ...],
        user_filters: tuple[tuple[str, Any], ...],
        *,
        contract_hash: str,
        actor: Actor | None,
        scoped_question: str,
        max_limit: int,
        time_grain: str | None,
        time_period: str | None,
        reference_date: date | None,
    ) -> CompiledMetricQuery:
        _check_identifier(entity.table, "table")
        _check_identifier(measure.field, "column")

        join_plan, table_aliases = self._plan_joins(
            entity, requested_dims, measure.aggregation, resolved.metric_id
        )
        primary_alias = table_aliases[entity.entity_id]

        select_parts: list[str] = []
        group_by_parts: list[str] = []
        lineage: list[tuple[str, str, str]] = [
            (resolved.metric_id, measure.measure_id, f"{entity.source_id}.{entity.table}.{measure.field}"),
        ]

        for dimension_id in requested_dims:
            dimension = self._kernel.dimensions[dimension_id]
            dim_entity = self._kernel.entities[dimension.entity_id]
            alias = table_aliases[dimension.entity_id]
            _check_identifier(dimension.field, "column")
            qualified = f"{alias}.{dimension.field}"
            select_parts.append(qualified)
            group_by_parts.append(qualified)
            lineage.append(
                (dimension_id, dim_entity.table, f"{dim_entity.source_id}.{dim_entity.table}.{dimension.field}")
            )

        if time_grain and entity.time_field:
            time_expr = self._time_grain_expr(primary_alias, entity.time_field, time_grain)
            select_parts.append(f"{time_expr} AS time_bucket")
            group_by_parts.append(time_expr)
            lineage.append(
                (resolved.metric_id, entity.time_field, f"{entity.source_id}.{entity.table}.{entity.time_field}")
            )

        agg = measure.aggregation.upper().replace("-", "_")
        select_parts.append(f"{_agg_expr(agg, primary_alias, measure.field)} AS metric_value")

        where_clauses = self._build_where(
            resolved,
            user_filters,
            primary_alias,
            entity,
            time_period=time_period,
            reference_date=reference_date,
        )

        from_clause = self._build_from(entity, join_plan, table_aliases)
        sql = f"SELECT {', '.join(select_parts)} FROM {from_clause}"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        if group_by_parts:
            sql += " GROUP BY " + ", ".join(group_by_parts)
        sql += f" LIMIT {max_limit}"

        return self._finalize(
            resolved,
            sql,
            entity,
            join_plan,
            lineage,
            contract_hash=contract_hash,
            actor=actor,
            scoped_question=scoped_question,
        )

    def _compile_derived(
        self,
        resolved: ResolvedMetric,
        metric,
        requested_dims: tuple[str, ...],
        user_filters: tuple[tuple[str, Any], ...],
        *,
        contract_hash: str,
        actor: Actor | None,
        scoped_question: str,
        max_limit: int,
        time_grain: str | None,
        time_period: str | None,
        reference_date: date | None,
    ) -> CompiledMetricQuery:
        lineage: list[tuple[str, str, str]] = []
        base_entity = None
        base_measure = None

        for ref in metric.formula_refs:
            if ref.startswith("measure:"):
                measure = self._kernel.measures[ref]
                entity = self._kernel.entities[measure.entity_id]
                if base_entity is None:
                    base_entity = entity
                    base_measure = measure
                lineage.append((resolved.metric_id, ref, f"{entity.source_id}.{entity.table}.{measure.field}"))
            elif ref.startswith("metric:"):
                ref_metric = self._kernel.metrics[ref]
                if ref_metric.kind == "derived":
                    for nested_ref in ref_metric.formula_refs:
                        if nested_ref.startswith("measure:"):
                            measure = self._kernel.measures[nested_ref]
                            entity = self._kernel.entities[measure.entity_id]
                            if base_entity is None:
                                base_entity = entity
                                base_measure = measure
                            lineage.append(
                                (resolved.metric_id, nested_ref, f"{entity.source_id}.{entity.table}.{measure.field}")
                            )
                        elif nested_ref.startswith("metric:"):
                            nested_metric = self._kernel.metrics[nested_ref]
                            if nested_metric.measure_id:
                                measure = self._kernel.measures[nested_metric.measure_id]
                                entity = self._kernel.entities[measure.entity_id]
                                if base_entity is None:
                                    base_entity = entity
                                    base_measure = measure
                                lineage.append(
                                    (
                                        resolved.metric_id,
                                        nested_metric.measure_id,
                                        f"{entity.source_id}.{entity.table}.{measure.field}",
                                    )
                                )
                elif ref_metric.measure_id:
                    measure = self._kernel.measures[ref_metric.measure_id]
                    entity = self._kernel.entities[measure.entity_id]
                    if base_entity is None:
                        base_entity = entity
                        base_measure = measure
                    lineage.append(
                        (resolved.metric_id, ref_metric.measure_id, f"{entity.source_id}.{entity.table}.{measure.field}")
                    )

        if base_entity is None or base_measure is None:
            raise ValueError(f"derived metric {metric.metric_id} has no resolvable base entity")

        entity = base_entity
        measure = base_measure
        _check_identifier(entity.table, "table")

        join_plan, table_aliases = self._plan_joins(entity, requested_dims, "sum", resolved.metric_id)
        primary_alias = table_aliases[entity.entity_id]

        select_parts: list[str] = []
        group_by_parts: list[str] = []

        for dimension_id in requested_dims:
            dimension = self._kernel.dimensions[dimension_id]
            dim_entity = self._kernel.entities[dimension.entity_id]
            alias = table_aliases[dimension.entity_id]
            _check_identifier(dimension.field, "column")
            qualified = f"{alias}.{dimension.field}"
            select_parts.append(qualified)
            group_by_parts.append(qualified)
            lineage.append(
                (dimension_id, dim_entity.table, f"{dim_entity.source_id}.{dim_entity.table}.{dimension.field}")
            )

        if time_grain and entity.time_field:
            time_expr = self._time_grain_expr(primary_alias, entity.time_field, time_grain)
            select_parts.append(f"{time_expr} AS time_bucket")
            group_by_parts.append(time_expr)

        formula_sql = render_formula(metric.formula, lambda ref: self._ref_to_sql(ref, primary_alias))

        select_parts.append(f"({formula_sql}) AS metric_value")

        where_clauses = self._build_where(
            resolved,
            user_filters,
            primary_alias,
            entity,
            time_period=time_period,
            reference_date=reference_date,
        )

        from_clause = self._build_from(entity, join_plan, table_aliases)
        sql = f"SELECT {', '.join(select_parts)} FROM {from_clause}"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        if group_by_parts:
            sql += " GROUP BY " + ", ".join(group_by_parts)
        sql += f" LIMIT {max_limit}"

        return self._finalize(
            resolved,
            sql,
            entity,
            join_plan,
            lineage,
            contract_hash=contract_hash,
            actor=actor,
            scoped_question=scoped_question,
        )

    def _plan_joins(
        self,
        base_entity,
        requested_dims: tuple[str, ...],
        aggregation: str,
        metric_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        aliases: dict[str, str] = {base_entity.entity_id: "t0"}
        join_plan: list[dict[str, Any]] = []
        alias_idx = 1

        needed_entities: set[str] = set()
        for dimension_id in requested_dims:
            dimension = self._kernel.dimensions[dimension_id]
            if dimension.entity_id != base_entity.entity_id:
                needed_entities.add(dimension.entity_id)

        for target_entity_id in sorted(needed_entities):
            path = plan_relation_path(self._kernel.relations, base_entity.entity_id, target_entity_id)
            fanout_step = path_has_additive_fanout(path, aggregation)
            if fanout_step is not None:
                raise FanoutNotAllowed(metric_id, fanout_step.relation_id, fanout_step.cardinality)
            for step in path:
                if step.to_entity_id in aliases:
                    continue
                alias = f"t{alias_idx}"
                alias_idx += 1
                aliases[step.to_entity_id] = alias
                from_alias = aliases[step.from_entity_id]
                to_entity = self._kernel.entities[step.to_entity_id]
                _check_identifier(step.join_key, "column")
                join_plan.append(
                    {
                        "relation_id": step.relation_id,
                        "from_entity_id": step.from_entity_id,
                        "to_entity_id": step.to_entity_id,
                        "join_key": step.join_key,
                        "cardinality": step.cardinality,
                        "from_alias": from_alias,
                        "to_alias": alias,
                        "to_table": to_entity.table,
                    }
                )
        return join_plan, aliases

    def _build_from(self, entity, join_plan: list[dict[str, Any]], aliases: dict[str, str]) -> str:
        from_clause = f"{entity.table} AS {aliases[entity.entity_id]}"
        for join in join_plan:
            from_clause += (
                f" JOIN {join['to_table']} AS {join['to_alias']}"
                f" ON {join['from_alias']}.{join['join_key']} = {join['to_alias']}.{join['join_key']}"
            )
        return from_clause

    def _build_where(
        self,
        resolved: ResolvedMetric,
        user_filters: tuple[tuple[str, Any], ...],
        primary_alias: str,
        entity,
        *,
        time_period: str | None,
        reference_date: date | None,
    ) -> list[str]:
        where_values: dict[str, Any] = {}
        for rule_name in resolved.filter_rules:
            rule = self._kernel.rule_definitions[rule_name]
            rule_filter = rule.get("filter", {})
            if not isinstance(rule_filter, dict):
                raise ValueError(f"rule {rule_name} filter must be a mapping")
            where_values.update(rule_filter)

        for field, value in user_filters:
            _check_identifier(field, "filter")
            where_values[field] = value

        if time_period and entity.time_field and self._kernel.time_spine is not None:
            if reference_date is None:
                raise ReferenceDateRequired(time_period)
            start, end = self._period_bounds(time_period, reference_date)
            where_values[f"__time_start__{entity.time_field}"] = start
            where_values[f"__time_end__{entity.time_field}"] = end

        clauses: list[str] = []
        for col, value in sorted(where_values.items()):
            if col.startswith("__time_start__"):
                field = col.replace("__time_start__", "")
                clauses.append(f"{primary_alias}.{field} >= {_literal(value)}")
            elif col.startswith("__time_end__"):
                field = col.replace("__time_end__", "")
                clauses.append(f"{primary_alias}.{field} <= {_literal(value)}")
            else:
                clauses.append(f"{primary_alias}.{col} = {_literal(value)}")
        return clauses

    def _time_grain_expr(self, alias: str, time_field: str, grain: str) -> str:
        _check_identifier(time_field, "column")
        qualified = f"{alias}.{time_field}"
        if grain == "day":
            return f"DATE_TRUNC('day', {qualified})"
        if grain == "week":
            return f"DATE_TRUNC('week', {qualified})"
        if grain == "month":
            return f"DATE_TRUNC('month', {qualified})"
        raise TimeGrainNotSupported(grain, self._kernel.time_spine.supported_grains if self._kernel.time_spine else ())

    def _ref_to_sql(self, ref: str, primary_alias: str) -> str:
        if ref.startswith("measure:"):
            measure = self._kernel.measures[ref]
            agg = measure.aggregation.upper().replace("-", "_")
            _check_identifier(measure.field, "column")
            return _agg_expr(agg, primary_alias, measure.field)
        if ref.startswith("metric:"):
            ref_metric = self._kernel.metrics[ref]
            if ref_metric.kind == "derived" and ref_metric.formula:
                nested = render_formula(
                    ref_metric.formula,
                    lambda nested_ref: self._ref_to_sql(nested_ref, primary_alias),
                )
                return f"({nested})"
            if not ref_metric.measure_id:
                raise ValueError(f"derived ref {ref} has no measure")
            measure = self._kernel.measures[ref_metric.measure_id]
            agg = measure.aggregation.upper().replace("-", "_")
            _check_identifier(measure.field, "column")
            return _agg_expr(agg, primary_alias, measure.field)
        raise ValueError(f"unknown formula ref {ref}")

    def _period_bounds(self, period: str, reference_date: date) -> tuple[date, date]:
        spine = self._kernel.time_spine
        if spine is None:
            raise ValueError("time spine not configured")
        macros = dict(spine.period_macros)
        if period not in macros:
            raise ValueError(f"unknown time period {period}")
        macro = macros[period]
        if period == "last_30_days":
            days = int(macro.get("days", 30))
            return reference_date - timedelta(days=days - 1), reference_date
        if period == "ytd":
            return date(reference_date.year, 1, 1), reference_date
        if period == "prior_period":
            if reference_date.month == 1:
                start = date(reference_date.year - 1, 12, 1)
                end = date(reference_date.year - 1, 12, 31)
            else:
                start = date(reference_date.year, reference_date.month - 1, 1)
                end = date(reference_date.year, reference_date.month, 1) - timedelta(days=1)
            return start, end
        raise ValueError(f"unsupported period macro {period}")

    def _finalize(
        self,
        resolved: ResolvedMetric,
        sql: str,
        entity,
        join_plan: list[dict[str, Any]],
        lineage: list[tuple[str, str, str]],
        *,
        contract_hash: str,
        actor: Actor | None,
        scoped_question: str,
    ) -> CompiledMetricQuery:
        actor = actor or Actor()
        plan = build_structured_query_plan(
            sql,
            source_id=entity.source_id,
            source_type="duckdb",
            contract_hash=contract_hash,
            actor=actor,
            scoped_question=scoped_question or resolved.display_name,
        )

        fallback_metric_refs = (resolved.metric_id,) if resolved.fallback_used else ()
        plan.metric_refs = (resolved.metric_id,)
        plan.grain = resolved.grain
        plan.fallback_metric_refs = fallback_metric_refs
        plan.relation_path = join_plan

        return CompiledMetricQuery(
            sql=render_sql(sql),
            plan=plan,
            metric_refs=(resolved.metric_id,),
            grain=resolved.grain,
            fallback_metric_refs=fallback_metric_refs,
            column_lineage=tuple(lineage),
        )


def _agg_expr(agg: str, alias: str, field: str) -> str:
    _check_identifier(field, "column")
    if agg == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {alias}.{field})"
    if agg in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
        return f"{agg}({alias}.{field})"
    raise ValueError(f"unsupported aggregation: {agg}")


def render_sql(sql: str, *, dialect: str = "duckdb") -> str:
    return sqlglot.parse_one(sql, read=dialect).sql(dialect=dialect)
