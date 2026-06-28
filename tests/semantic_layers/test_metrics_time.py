from datetime import date
from pathlib import Path

import pytest

from recosearch.semantic_layers.metrics import MetricCompiler, MetricKernel, MetricQuery, MetricResolver, ReferenceDateRequired, TimeGrainNotSupported
from recosearch.semantic_layers.pipeline import execute_metric_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
METRICS_DIR = ROOT / "semantic" / "metrics"


@pytest.fixture(scope="module")
def kernel() -> MetricKernel:
    return MetricKernel.from_dir(METRICS_DIR)


@pytest.fixture(scope="module")
def compiler(kernel: MetricKernel) -> MetricCompiler:
    return MetricCompiler(kernel)


@pytest.fixture(scope="module")
def contract():
    from recosearch.semantic_layers.contract import compile_contract

    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


@pytest.fixture(scope="module")
def order_revenue(kernel: MetricKernel):
    resolver = MetricResolver(kernel)
    return resolver.resolve(MetricQuery(term="metric:novashop:order_revenue", tenant="novashop"))


def test_compile_month_grain_group_by(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_grain="month",
        reference_date=date(2026, 1, 31),
    )
    assert "DATE_TRUNC('MONTH', t0.order_date) AS time_bucket" in compiled.sql
    assert "GROUP BY DATE_TRUNC('MONTH', t0.order_date)" in compiled.sql


def test_compile_ytd_period_filter(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_period="ytd",
        reference_date=date(2026, 1, 31),
    )
    assert "t0.order_date >= '2026-01-01'" in compiled.sql
    assert "t0.order_date <= '2026-01-31'" in compiled.sql


def test_compile_period_requires_reference_date(compiler: MetricCompiler, order_revenue):
    with pytest.raises(ReferenceDateRequired):
        compiler.compile(order_revenue, (), time_period="ytd")


def test_compile_unsupported_grain_clarifies(compiler: MetricCompiler, order_revenue):
    with pytest.raises(TimeGrainNotSupported):
        compiler.compile(order_revenue, (), time_grain="quarter")


def test_pipeline_metric_query_uses_reference_date():
    from recosearch.semantic_layers.contract import compile_contract

    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    contract = compile_contract()
    answer = execute_metric_query(
        MetricQuery(
            term="order revenue",
            tenant="novashop",
            time_period="ytd",
            reference_date=date(2025, 6, 15),
        ),
        contract=contract,
    )
    assert answer.decision == "answer"
    citation = answer.citations[0]
    assert "t0.order_date >= '2025-01-01'" in citation["query"]
    assert "t0.order_date <= '2025-06-15'" in citation["query"]


def test_pipeline_period_without_reference_date_clarifies():
    from recosearch.semantic_layers.contract import compile_contract

    contract = compile_contract()
    answer = execute_metric_query(
        MetricQuery(term="order revenue", tenant="novashop", time_period="ytd"),
        contract=contract,
    )
    assert answer.decision == "clarify"
    assert "reference_date is required" in answer.reason


def test_compile_last_30_days_period_filter(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_period="last_30_days",
        reference_date=date(2026, 1, 31),
    )
    assert "t0.order_date >= '2026-01-02'" in compiled.sql
    assert "t0.order_date <= '2026-01-31'" in compiled.sql


def test_compile_prior_period_january_reference(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_period="prior_period",
        reference_date=date(2026, 1, 15),
    )
    assert "t0.order_date >= '2025-12-01'" in compiled.sql
    assert "t0.order_date <= '2025-12-31'" in compiled.sql


def test_compile_prior_period_march_reference(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_period="prior_period",
        reference_date=date(2026, 3, 10),
    )
    assert "t0.order_date >= '2026-02-01'" in compiled.sql
    assert "t0.order_date <= '2026-02-28'" in compiled.sql


def test_compile_day_grain_group_by(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_grain="day",
        reference_date=date(2026, 1, 31),
    )
    assert "DATE_TRUNC('DAY', t0.order_date) AS time_bucket" in compiled.sql
    assert "GROUP BY DATE_TRUNC('DAY', t0.order_date)" in compiled.sql


def test_compile_week_grain_group_by(compiler: MetricCompiler, order_revenue):
    compiled = compiler.compile(
        order_revenue,
        (),
        time_grain="week",
        reference_date=date(2026, 1, 31),
    )
    assert "DATE_TRUNC('WEEK', t0.order_date) AS time_bucket" in compiled.sql
    assert "GROUP BY DATE_TRUNC('WEEK', t0.order_date)" in compiled.sql


def test_pipeline_last_30_days_executes(contract):
    answer = execute_metric_query(
        MetricQuery(
            term="order revenue",
            tenant="novashop",
            time_period="last_30_days",
            reference_date=date(2026, 1, 31),
        ),
        contract=contract,
    )
    assert answer.decision == "answer"
    citation = answer.citations[0]
    assert "t0.order_date >= '2026-01-02'" in citation["query"]
    assert "t0.order_date <= '2026-01-31'" in citation["query"]

