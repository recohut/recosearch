from __future__ import annotations

from typing import Any, Callable

from recosearch.semantic_layers.context.types import ContextQuery
from recosearch.semantic_layers.mcp_tools import handle_resolve_context
from recosearch.semantic_layers.pipeline import execute_context_query


def pass_k(
    questions: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    k: int = 2,
    runner: Callable[..., Any] | None = None,
) -> float:
    """Compute pass^k consistency across k retries per golden question."""
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
    if question.get("tool") == "resolve_context":
        return handle_resolve_context(
            {"term": question["term"], "tenant": question.get("tenant", "novashop")},
            contract=contract,
        )
    return execute_context_query(
        ContextQuery(term=question["term"], tenant=question.get("tenant", "novashop")),
        contract=contract,
    )


def _decision(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("decision", ""))
    return str(getattr(result, "decision", ""))


def golden_context_suite() -> list[dict[str, Any]]:
    return [
        {
            "tool": "resolve_context",
            "term": "revenue",
            "tenant": "novashop",
            "expected_decision": "resolved",
        },
        {"term": "revenue", "tenant": "novashop", "expected_decision": "answer"},
        {"term": "customer", "tenant": "novashop", "expected_decision": "clarify"},
        {"term": "nonexistent", "tenant": "novashop", "expected_decision": "clarify"},
    ]
