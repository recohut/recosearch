from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import MetricKernel, MetricQuery, MetricResolver
from recosearch.semantic_layers.metrics.types import ClarifyRequest
from recosearch.semantic_layers.pipeline import execute_metric_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"

SCENARIOS = [
    ("gross revenue", 109.97),
    ("net revenue", 104.97),
    ("order count", 2),
    ("unique customers", 1),
    ("revenue per customer", 104.97),
]


@pytest.fixture(autouse=True)
def _clear_ledger():
    ledger.clear()
    yield
    ledger.clear()


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


@pytest.fixture(scope="module")
def kernel():
    return MetricKernel.from_dir(METRICS_DIR)


@pytest.mark.parametrize("term,expected_value", SCENARIOS)
def test_metric_scenario_resolves_and_executes(contract, kernel, term, expected_value):
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(MetricQuery(term=term, tenant="novashop"))
    assert not isinstance(resolved, ClarifyRequest)

    answer = execute_metric_query(
        MetricQuery(term=term, tenant="novashop", reference_date=date(2026, 1, 31)),
        contract=contract,
    )
    assert answer.decision == "answer"
    assert answer.result is not None
    assert answer.result[0]["metric_value"] == expected_value


def test_revenue_per_customer_supports_customer_dimension(contract, kernel):
    resolver = MetricResolver(kernel)
    resolved = resolver.resolve(
        MetricQuery(
            term="revenue per customer",
            tenant="novashop",
            dimensions=("dimension:novashop:customer_name",),
        )
    )
    assert resolved.metric_id == "metric:novashop:revenue_per_customer"

    answer = execute_metric_query(
        MetricQuery(
            term="revenue per customer",
            tenant="novashop",
            dimensions=("dimension:novashop:customer_name",),
            reference_date=date(2026, 1, 31),
        ),
        contract=contract,
    )
    assert answer.decision == "answer"
    rows = {row["customer_name"]: row["metric_value"] for row in answer.result}
    assert rows == {"Alice": 104.97}
