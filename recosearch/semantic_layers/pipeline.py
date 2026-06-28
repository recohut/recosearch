from __future__ import annotations

import hashlib
import time
from datetime import date
from typing import Any

from recosearch.semantic_layers import identity, ledger, plan, policy
from recosearch.semantic_layers.compiler import QuerySpec, compile_query
from recosearch.semantic_layers.envelope import Answer, clarify, refuse
from recosearch.semantic_layers.identity import Actor
from recosearch.semantic_layers.metrics.compile import (
    DimensionNotAllowed,
    FanoutNotAllowed,
    MetricCompiler,
    ReferenceDateRequired,
    TimeGrainNotSupported,
)
from recosearch.semantic_layers.metrics.freshness import assess_freshness
from recosearch.semantic_layers.metrics.lineage import project_metric_lineage
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.resolve import MetricResolver
from recosearch.semantic_layers.metrics.types import ClarifyRequest, MetricQuery, ResolvedMetric
from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.sources import resolve_source
from recosearch.semantic_layers.sql_lint import lint_select_only


def execute_structured_query(
    sql: str,
    *,
    source_key: str,
    contract: dict[str, Any],
    row_limit: int = 100,
    actor: Actor | None = None,
    scoped_question: str = "",
) -> Answer:
    contract_hash = contract.get("contract_hash", "")
    actor = actor or identity.resolve()

    try:
        adapter, connection, cfg = resolve_source(source_key, contract)
    except (KeyError, RuntimeError, FileNotFoundError) as exc:
        ans = refuse(str(exc), contract_hash, actor_role=actor.role)
        ledger.record("refusal", payload={"reason": ans.reason, "actor_role": actor.role})
        return ans

    query_plan = plan.build_structured_query_plan(
        sql,
        source_id=cfg["source_id"],
        source_type=cfg["type"],
        contract_hash=contract_hash,
        actor=actor,
        scoped_question=scoped_question,
    )
    ledger.record(
        "plan",
        source_id=cfg["source_id"],
        payload=_plan_dict(query_plan),
        lineage_edges=[
            ledger.LineageEdge(
                from_id=query_plan.plan_id,
                to_id=f"source:{cfg['source_id']}",
                kind="selects_source",
            )
        ],
    )
    policy_answer = policy.decide(
        Answer(
            decision="answer",
            contract_version=contract_hash,
            evidence_tier="contract-only",
            actor_role=actor.role,
            scoped_question=scoped_question,
            plan_ref=query_plan.plan_id,
            source_role_matrix=[
                {"source_id": cfg["source_id"], "role": actor.role, "operation": "structured_query"}
            ],
        ),
        query_plan,
    )
    if policy_answer.decision == "refuse":
        return policy_answer

    try:
        safe_sql = lint_select_only(sql, dialect=adapter.sql_dialect or "duckdb")
    except ValueError as exc:
        ans = refuse(str(exc), contract_hash, actor_role=actor.role)
        ledger.record(
            "refusal",
            source_id=cfg["source_id"],
            payload={"reason": ans.reason, "plan_id": query_plan.plan_id},
        )
        return ans

    max_rows = int(cfg.get("cost_controls", {}).get("max_rows", row_limit))
    effective_limit = min(row_limit, max_rows)
    query_hash = hashlib.sha256(safe_sql.encode()).hexdigest()[:16]
    rows = adapter.run_structured_query(connection, safe_sql, row_limit=effective_limit, actor=actor)

    citation = {
        "source_id": cfg["source_id"],
        "kind": "query_hash",
        "query": safe_sql,
        "query_hash": query_hash,
        "contract_hash": contract_hash,
        "capability": query_plan.capability,
    }
    for row in rows:
        row["_citation"] = citation

    evidence_artifact_id = ledger.record(
        "query",
        source_id=cfg["source_id"],
        evidence_tier="fixture-backed",
        payload={
            "query_hash": query_hash,
            "sql": safe_sql,
            "row_count": len(rows),
            "plan_id": query_plan.plan_id,
        },
        lineage_edges=[
            ledger.LineageEdge(
                from_id=f"query:{query_hash}",
                to_id=query_plan.plan_id,
                kind="executes_plan",
            ),
            ledger.LineageEdge(
                from_id=f"query:{query_hash}",
                to_id=f"source:{cfg['source_id']}",
                kind="reads_source",
            ),
        ],
    )

    answer = Answer(
        decision="answer",
        result=rows,
        citations=[citation],
        contract_version=contract_hash,
        answer_id="ans-" + query_hash,
        evidence_tier="fixture-backed",
        actor_role=actor.role,
        scoped_question=scoped_question,
        plan_ref=query_plan.plan_id,
        source_role_matrix=[
            {"source_id": cfg["source_id"], "role": actor.role, "operation": "structured_query"}
        ],
        reason_code=policy_answer.reason_code,
        policy_trace=policy_answer.policy_trace,
        replay_refs=[*policy_answer.replay_refs, evidence_artifact_id],
    )
    ledger.record(
        "answer",
        source_id=cfg["source_id"],
        evidence_tier="fixture-backed",
        payload={
            "answer_id": answer.answer_id,
            "decision": answer.decision,
            "plan_id": query_plan.plan_id,
            "query_hash": query_hash,
        },
        lineage_edges=[
            ledger.LineageEdge(
                from_id=answer.answer_id,
                to_id=query_plan.plan_id,
                kind="answers_plan",
            ),
            ledger.LineageEdge(
                from_id=answer.answer_id,
                to_id=f"query:{query_hash}",
                kind="cites_query",
            ),
        ],
    )
    return answer


def execute_query_spec(
    spec: QuerySpec,
    *,
    contract: dict[str, Any],
    actor: Actor | None = None,
) -> Answer:
    source = contract.get("sources", {}).get(spec.source_key, {})
    max_rows = int(source.get("cost_controls", {}).get("max_rows", 100))
    try:
        sql = compile_query(spec, max_limit=max_rows)
    except ValueError as exc:
        return refuse(str(exc), contract.get("contract_hash", ""), actor_role=(actor or identity.resolve()).role)
    return execute_structured_query(
        sql,
        source_key=spec.source_key,
        contract=contract,
        row_limit=max_rows,
        actor=actor,
        scoped_question=spec.scoped_question,
    )


def execute_metric_query(
    query: MetricQuery,
    *,
    contract: dict[str, Any],
    actor: Actor | None = None,
    scoped_question: str = "",
) -> Answer:
    contract_hash = contract.get("contract_hash", "")
    actor = actor or identity.resolve()

    if "metric_kernel" not in contract:
        return clarify("metric kernel not loaded in contract", contract_hash, actor_role=actor.role)

    kernel = MetricKernel.from_contract(contract)
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(query)
    if isinstance(resolved, ClarifyRequest):
        reason = resolved.reason
        if resolved.candidates:
            names = ", ".join(f"{mid} ({name})" for mid, name in resolved.candidates)
            reason = f"{reason}: {names}"
        return clarify(reason, contract_hash, actor_role=actor.role)

    measure = kernel.measures[resolved.measure_id]
    entity = kernel.entities[measure.entity_id]
    source_key = entity.source_id
    source_cfg = contract.get("sources", {}).get(source_key, {})
    max_rows = int(source_cfg.get("cost_controls", {}).get("max_rows", 100))

    compiler = MetricCompiler(kernel)
    try:
        compiled = compiler.compile(
            resolved,
            query.dimensions,
            query.filters,
            contract_hash=contract_hash,
            actor=actor,
            scoped_question=scoped_question or query.term,
            max_limit=max_rows,
            time_grain=query.time_grain,
            time_period=query.time_period,
            reference_date=query.reference_date,
        )
    except DimensionNotAllowed as exc:
        return clarify(str(exc), contract_hash, actor_role=actor.role)
    except TimeGrainNotSupported as exc:
        return clarify(str(exc), contract_hash, actor_role=actor.role)
    except ReferenceDateRequired as exc:
        return clarify(str(exc), contract_hash, actor_role=actor.role)
    except FanoutNotAllowed as exc:
        ans = refuse(str(exc), contract_hash, actor_role=actor.role)
        ans.reason_code = "METRIC_FANOUT_BLOCKED"
        return ans

    column_edges = project_metric_lineage(
        kernel, resolved, compiled.column_lineage, join_plan=compiled.plan.relation_path
    )
    query_plan = compiled.plan
    ledger.record(
        "plan",
        source_id=source_key,
        payload=_plan_dict(query_plan),
        lineage_edges=[
            ledger.LineageEdge(
                from_id=resolved.metric_id,
                to_id=query_plan.plan_id,
                kind="defines_plan",
            ),
            ledger.LineageEdge(
                from_id=query_plan.plan_id,
                to_id=f"source:{source_key}",
                kind="selects_source",
            ),
            *column_edges,
        ],
    )

    policy_answer = policy.decide(
        Answer(
            decision="answer",
            contract_version=contract_hash,
            evidence_tier="contract-only",
            actor_role=actor.role,
            scoped_question=scoped_question or query.term,
            plan_ref=query_plan.plan_id,
            source_role_matrix=[
                {"source_id": source_key, "role": actor.role, "operation": "structured_query"}
            ],
        ),
        query_plan,
        metric_id=resolved.metric_id,
    )
    if policy_answer.decision == "refuse":
        ledger.record(
            "refusal",
            source_id=source_key,
            payload={
                "reason": policy_answer.reason,
                "plan_id": query_plan.plan_id,
                "metric_id": resolved.metric_id,
            },
            lineage_edges=[
                ledger.LineageEdge(
                    from_id=resolved.metric_id,
                    to_id=query_plan.plan_id,
                    kind="attempted_plan",
                )
            ],
        )
        policy_answer.metric_resolution = _metric_resolution_tuple(query, resolved)
        if resolved.caveat_codes:
            policy_answer.caveats = list(resolved.caveat_codes)
        return policy_answer

    try:
        adapter, connection, cfg = resolve_source(source_key, contract)
    except (KeyError, RuntimeError, FileNotFoundError) as exc:
        ans = refuse(str(exc), contract_hash, actor_role=actor.role)
        ledger.record("refusal", payload={"reason": ans.reason, "actor_role": actor.role})
        return ans

    metric = kernel.metrics[resolved.metric_id]
    reference_date = query.reference_date or date.today()
    freshness_result = assess_freshness(
        adapter,
        connection,
        entity,
        cfg,
        reference_date=reference_date,
        metric=metric,
        dialect=adapter.sql_dialect or "duckdb",
    )
    if freshness_result is not None and freshness_result.is_stale:
        freshness_payload = freshness_result.to_dict()
        if freshness_result.hard_sla:
            ans = refuse(
                f"metric data stale: max date {freshness_result.max_data_date} exceeds SLA",
                contract_hash,
                actor_role=actor.role,
            )
            ans.reason_code = "METRIC_DATA_STALE"
            ans.caveats = ["stale_data"]
            ledger.record(
                "refusal",
                source_id=cfg["source_id"],
                payload={
                    "reason": ans.reason,
                    "plan_id": query_plan.plan_id,
                    "metric_id": resolved.metric_id,
                    "freshness": freshness_payload,
                },
            )
            return ans

    try:
        safe_sql = lint_select_only(compiled.sql, dialect=adapter.sql_dialect or "duckdb")
    except ValueError as exc:
        ans = refuse(str(exc), contract_hash, actor_role=actor.role)
        ledger.record(
            "refusal",
            source_id=cfg["source_id"],
            payload={"reason": ans.reason, "plan_id": query_plan.plan_id, "metric_id": resolved.metric_id},
        )
        return ans

    query_hash = hashlib.sha256(safe_sql.encode()).hexdigest()[:16]
    rows = adapter.run_structured_query(connection, safe_sql, row_limit=max_rows, actor=actor)

    citation = {
        "source_id": cfg["source_id"],
        "kind": "metric_query",
        "query": safe_sql,
        "query_hash": query_hash,
        "contract_hash": contract_hash,
        "metric_id": resolved.metric_id,
        "metric_version": resolved.version,
        "definition_hash": resolved.definition_hash,
        "collection_id": resolved.collection.collection_id,
        "fallback_used": resolved.fallback_used,
    }
    if freshness_result is not None:
        citation["freshness"] = freshness_result.to_dict()

    evidence_artifact_id = ledger.record(
        "query",
        source_id=cfg["source_id"],
        evidence_tier="fixture-backed",
        payload={
            "query_hash": query_hash,
            "sql": safe_sql,
            "row_count": len(rows),
            "plan_id": query_plan.plan_id,
            "metric_id": resolved.metric_id,
            **(
                {"freshness": freshness_result.to_dict()}
                if freshness_result is not None
                else {}
            ),
        },
        lineage_edges=[
            ledger.LineageEdge(
                from_id=f"query:{query_hash}",
                to_id=query_plan.plan_id,
                kind="executes_plan",
            ),
            ledger.LineageEdge(
                from_id=f"query:{query_hash}",
                to_id=resolved.metric_id,
                kind="answers_metric",
            ),
        ],
    )

    caveat_codes = list(resolved.caveat_codes)
    if freshness_result is not None and freshness_result.is_stale:
        caveat_codes.append("stale_data")
    answer = Answer(
        decision="answer",
        result=rows,
        citations=[citation],
        contract_version=contract_hash,
        answer_id="ans-" + query_hash,
        evidence_tier="fixture-backed",
        actor_role=actor.role,
        scoped_question=scoped_question or query.term,
        plan_ref=query_plan.plan_id,
        source_role_matrix=[
            {"source_id": cfg["source_id"], "role": actor.role, "operation": "structured_query"}
        ],
        reason_code=policy_answer.reason_code,
        policy_trace=policy_answer.policy_trace,
        caveats=caveat_codes,
        replay_refs=[*policy_answer.replay_refs, evidence_artifact_id],
        metric_resolution=_metric_resolution_tuple(query, resolved),
    )
    ledger.record(
        "answer",
        source_id=cfg["source_id"],
        evidence_tier="fixture-backed",
        payload={
            "answer_id": answer.answer_id,
            "decision": answer.decision,
            "plan_id": query_plan.plan_id,
            "query_hash": query_hash,
            "metric_id": resolved.metric_id,
        },
        lineage_edges=[
            ledger.LineageEdge(
                from_id=answer.answer_id,
                to_id=query_plan.plan_id,
                kind="answers_plan",
            ),
            ledger.LineageEdge(
                from_id=answer.answer_id,
                to_id=f"query:{query_hash}",
                kind="cites_query",
            ),
        ],
    )
    return answer


def _metric_resolution_tuple(query: MetricQuery, resolved: ResolvedMetric) -> tuple[tuple[str, Any], ...]:
    return (
        ("requested_term", query.term),
        ("resolved_metric_id", resolved.metric_id),
        ("collection_id", resolved.collection.collection_id),
        ("collection_priority", resolved.collection.priority),
        ("fallback_used", resolved.fallback_used),
        ("caveat_codes", list(resolved.caveat_codes)),
        ("grain", resolved.grain),
        ("metric_version", resolved.version),
        ("definition_hash", resolved.definition_hash),
        ("status", resolved.status),
        ("time_grain", query.time_grain or ""),
        ("time_period", query.time_period or ""),
    )


def execute_context_query(
    query: ContextQuery,
    *,
    contract: dict[str, Any],
    actor: Actor | None = None,
    scoped_question: str = "",
    reference_date: date | None = None,
) -> Answer:
    from recosearch.semantic_layers.context.cards import build_context_card
    from recosearch.semantic_layers.context.loader import ContextKernelLoader
    from recosearch.semantic_layers.context.resolve import ContextResolver
    from recosearch.semantic_layers.context.trust import apply_runtime_trust

    contract_hash = contract.get("contract_hash", "")
    actor = actor or identity.resolve()
    ctx_query = ContextQuery(
        term=query.term,
        tenant=query.tenant,
        industry=query.industry,
        actor_role=actor.role,
        claim_qualifiers=query.claim_qualifiers,
    )

    if "context_kernel" not in contract:
        return clarify("context kernel not loaded in contract", contract_hash, actor_role=actor.role)

    metric_kernel = MetricKernel.from_contract(contract)
    context_kernel = ContextKernelLoader.from_contract(contract, metric_kernel=metric_kernel)
    resolver = ContextResolver(context_kernel, metric_kernel)
    resolution = resolver.resolve(ctx_query)

    if resolution.decision == "unknown":
        return clarify(resolution.reason, contract_hash, actor_role=actor.role)
    if resolution.decision == "clarify":
        reason = resolution.reason
        if resolution.candidates:
            names = ", ".join(f"{tid} ({name})" for tid, name in resolution.candidates)
            reason = f"{reason}: {names}"
        ans = clarify(reason, contract_hash, actor_role=actor.role)
        ans.context_resolution = _context_resolution_tuple(resolution)
        return ans

    binding = resolution.binding
    assert binding is not None
    card = build_context_card(
        binding,
        context_kernel,
        metric_kernel,
        actor_role=actor.role,
        contract_hash=contract_hash,
    )
    ledger.record(
        "context",
        payload={"term_id": binding.term_id, "card_id": card.card_id},
        lineage_edges=[
            ledger.LineageEdge(from_id=binding.term_id, to_id=ref, kind="context_ref")
            for ref in binding.primary_refs
        ],
    )

    metric_refs = [ref for ref in binding.primary_refs if ref.startswith("metric:")]
    if not metric_refs:
        ans = clarify(
            f"term {binding.term_id} is not directly executable; see context card for guidance",
            contract_hash,
            actor_role=actor.role,
        )
        ans.context_resolution = _context_resolution_tuple(resolution, card=card)
        return ans

    if card.trust.status == "not_usable":
        ans = refuse(
            f"context term not usable: {', '.join(card.trust.reasons) or card.trust.status}",
            contract_hash,
            actor_role=actor.role,
        )
        if "policy_denied" in card.trust.reasons:
            ans.reason_code = "POLICY"
        else:
            ans.reason_code = "CONTEXT_NOT_USABLE"
        ans.context_resolution = _context_resolution_tuple(resolution, card=card)
        ans.caveats = list(card.caveats)
        return ans

    metric_id = metric_refs[0]
    constraint = None

    if "ontology_kernel" in contract:
        from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader
        from recosearch.semantic_layers.ontology.validate import validate_claim

        ontology_kernel = OntologyKernelLoader.from_contract(
            contract, context_kernel=context_kernel
        )
        lineage_context = tuple(
            (f"lineage_{edge.kind}", f"{edge.from_id}->{edge.to_id}")
            for edge in context_kernel.relationships
            if edge.from_id == binding.term_id or edge.to_id == binding.term_id
        )
        constraint = validate_claim(
            binding,
            metric_id,
            ontology_kernel,
            claim_qualifiers=ctx_query.claim_qualifiers,
            reference_date=reference_date,
            lineage_context=lineage_context,
            plan_context=(("metric_id", metric_id), ("term_id", binding.term_id)),
        )
        if constraint.decision == "refuse":
            ans = refuse(
                constraint.reason,
                contract_hash,
                actor_role=actor.role,
            )
            ans.reason_code = constraint.reason_code or "CONSTRAINT_VIOLATION"
            ans.constraint_decision = constraint.to_tuple()
            ans.context_resolution = _context_resolution_tuple(resolution, card=card)
            ledger.record(
                "constraint",
                payload={
                    "term_id": binding.term_id,
                    "metric_id": metric_id,
                    "decision": constraint.decision,
                    "reason": constraint.reason,
                    "claim_hash": constraint.claim_hash,
                },
                lineage_edges=[
                    ledger.LineageEdge(
                        from_id=binding.term_id,
                        to_id=v.shape or "shape:unknown",
                        kind="constraint_violation",
                    )
                    for v in constraint.violations
                ],
            )
            return ans
        if constraint.decision == "clarify":
            ans = clarify(constraint.reason, contract_hash, actor_role=actor.role)
            ans.reason_code = constraint.reason_code or "CONSTRAINT_CLARIFY"
            ans.constraint_decision = constraint.to_tuple()
            ans.context_resolution = _context_resolution_tuple(resolution, card=card)
            return ans

    metric_query = MetricQuery(
        term=metric_id,
        tenant=ctx_query.tenant,
        industry=ctx_query.industry,
        reference_date=reference_date,
    )
    answer = execute_metric_query(
        metric_query,
        contract=contract,
        actor=actor,
        scoped_question=scoped_question or ctx_query.term,
    )

    if constraint is not None:
        answer.constraint_decision = constraint.to_tuple()

    runtime_card = apply_runtime_trust(
        card, answer, metric_kernel, context_kernel=context_kernel
    )
    if runtime_card.trust.evidence_label:
        answer.evidence_tier = runtime_card.trust.evidence_label
    answer.context_resolution = _context_resolution_tuple(resolution, card=runtime_card)
    return answer


def _context_resolution_tuple(
    resolution: Any,
    *,
    card: Any | None = None,
) -> tuple[tuple[str, Any], ...]:
    out: list[tuple[str, Any]] = [
        ("decision", resolution.decision),
        ("term_id", resolution.term_id),
        ("reason", resolution.reason),
    ]
    if resolution.candidates:
        out.append(("candidates", list(resolution.candidates)))
    if card is not None:
        out.append(("card_id", card.card_id))
        out.append(("trust_status", card.trust.status))
        out.append(("evidence_tier", card.trust.evidence_tier))
        out.append(("drift_status", card.trust.drift_status))
    return tuple(out)


def _plan_dict(query_plan: plan.QueryPlan) -> dict[str, Any]:
    return {
        "plan_id": query_plan.plan_id,
        "source_id": (query_plan.selected_sources[0]["source_id"] if query_plan.selected_sources else ""),
        "capability": query_plan.capability,
        "contract_hash": query_plan.contract_hash,
    }
