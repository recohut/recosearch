from __future__ import annotations

import time
from typing import Any, Callable

from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.ontology.validate import clear_validation_cache, validate_claim
from recosearch.semantic_layers.pipeline import execute_context_query

DEFAULT_LATENCY_BUDGET_MS = 250.0


def pass_k(
    questions: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    k: int = 2,
    runner: Callable[..., Any] | None = None,
) -> float:
    if k < 1 or not questions:
        return 0.0

    run = runner or _default_runner
    scores: list[float] = []
    for question in questions:
        outcomes: list[bool] = []
        for _ in range(k):
            result = run(question, contract)
            outcomes.append(_decision(result) == question["expected_decision"])
        scores.append(1.0 if all(outcomes) else 0.0)
    return sum(scores) / len(scores)


def _default_runner(question: dict[str, Any], contract: dict[str, Any]) -> Any:
    from datetime import date

    qualifiers = tuple(tuple(pair) for pair in question.get("claim_qualifiers", []))
    ref = question.get("reference_date")
    reference_date = date.fromisoformat(ref) if ref else None
    return execute_context_query(
        ContextQuery(
            term=question["term"],
            tenant=question.get("tenant", "novashop"),
            claim_qualifiers=qualifiers,
        ),
        contract=contract,
        reference_date=reference_date,
    )


def _decision(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("decision", ""))
    return str(getattr(result, "decision", ""))


def golden_constraint_suite() -> list[dict[str, Any]]:
    return [
        {
            "term": "revenue",
            "tenant": "novashop",
            "expected_decision": "answer",
            "reference_date": "2026-01-31",
        },
        {
            "term": "gross revenue",
            "tenant": "novashop",
            "claim_qualifiers": [["reported_as", "NetRevenue"], ["period", "2026-01"]],
            "expected_decision": "refuse",
        },
        {
            "term": "deferred revenue",
            "tenant": "novashop",
            "claim_qualifiers": [
                ["recognition_status", "recognized"],
                ["reported_as", "NetRevenue"],
                ["refund_treatment", "after_refunds"],
                ["period", "2026-01"],
            ],
            "expected_decision": "refuse",
        },
        {
            "term": "net revenue",
            "tenant": "novashop",
            "claim_qualifiers": [["period", "2026-01"]],
            "expected_decision": "clarify",
        },
    ]


def assert_latency_budget(
    runner: Callable[[], Any],
    *,
    budget_ms: float = DEFAULT_LATENCY_BUDGET_MS,
    repeats: int = 3,
    warmup: int = 1,
) -> float:
    clear_validation_cache()
    for _ in range(warmup):
        runner()
    durations: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        runner()
        durations.append((time.perf_counter() - start) * 1000.0)
    return max(durations)
