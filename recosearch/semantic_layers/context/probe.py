from __future__ import annotations

from typing import Any

from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.types import MetricQuery
from recosearch.semantic_layers.pipeline import execute_metric_query


def probe_term_local(
    binding: TermBinding,
    metric_kernel: MetricKernel,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Read-only local probe against DuckDB fixture (tier-3 evidence)."""
    metric_refs = [ref for ref in binding.primary_refs if ref.startswith("metric:")]
    if not metric_refs:
        return {"passed": False, "reason": "no_metric_ref"}

    metric_id = metric_refs[0]
    if metric_id not in metric_kernel.metrics:
        return {"passed": False, "reason": "unknown_metric"}

    tenant = binding.term_id.split(":")[1] if binding.term_id.startswith("term:") else "default"
    answer = execute_metric_query(
        MetricQuery(term=metric_id, tenant=tenant),
        contract=contract,
    )
    if answer.decision != "answer":
        return {"passed": False, "reason": f"decision_{answer.decision}"}

    row_count = len(answer.result or [])
    columns = list(answer.result[0].keys()) if answer.result else []
    return {
        "passed": row_count >= 1 and bool(columns),
        "row_count": row_count,
        "columns": columns,
        "evidence_tier": 3,
        "label": "local-equivalent",
    }
