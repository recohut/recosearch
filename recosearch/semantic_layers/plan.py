from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from recosearch.semantic_layers.identity import Actor


@dataclass
class QueryPlan:
    """Typed pre-execution plan. SQL is a downstream artifact — placeholder here for slice 1."""

    plan_id: str
    scoped_question: str = ""
    actor: Actor = field(default_factory=Actor)
    selected_sources: list[dict[str, Any]] = field(default_factory=list)
    relation_path: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    estimated_cost: dict[str, Any] = field(default_factory=dict)
    decision: str = "answer"
    # Slice-1-only: caller still supplies SQL directly. Slice 2 renders SQL from this plan.
    sql: str = ""
    capability: str = "structured_query"
    contract_hash: str = ""
    metric_refs: tuple[str, ...] = ()
    grain: str = ""
    fallback_metric_refs: tuple[str, ...] = ()


def build_structured_query_plan(
    sql: str,
    *,
    source_id: str,
    source_type: str,
    contract_hash: str,
    actor: Actor,
    scoped_question: str = "",
) -> QueryPlan:
    import hashlib

    plan_id = "plan-" + hashlib.sha256(f"{contract_hash}:{source_id}:{sql}".encode()).hexdigest()[:12]
    return QueryPlan(
        plan_id=plan_id,
        scoped_question=scoped_question,
        actor=actor,
        contract_hash=contract_hash,
        capability="structured_query",
        sql=sql,
        selected_sources=[{"source_id": source_id, "source_type": source_type, "operation": "structured_query"}],
    )
