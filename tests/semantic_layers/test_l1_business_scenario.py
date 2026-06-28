"""L1-only business scenario: additive fan-out / wrong-grain trap (Novashop).

A text-to-SQL agent joins orders to line items and double-counts revenue on a
one-to-many path. L1 governed compile refuses the unsafe dimension drill via
FanoutNotAllowed; the safe product-category path still matches DuckDB oracle.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pytest

from recosearch.semantic_layers import ledger
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import (
    FanoutNotAllowed,
    MetricCompiler,
    MetricKernel,
    MetricQuery,
    MetricResolver,
)
from recosearch.semantic_layers.metrics.relations import path_has_additive_fanout, plan_relation_path
from recosearch.semantic_layers.pipeline import execute_metric_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
NOVASHOP_DB = ROOT / "examples" / "novashop" / "shop.duckdb"
METRICS_DIR = ROOT / "semantic" / "metrics"
JANUARY_REFERENCE = date(2026, 1, 31)
TERM_ORDER_REVENUE = "order revenue"
DIM_PRODUCT_CATEGORY = "dimension:novashop:product_category"
DIM_LINE_SKU = "dimension:novashop:line_sku"
RELATION_ORDER_LINES = "relation:novashop:order_to_lines"
METRIC_FANOUT_TRAP = "metric:novashop:fanout_trap_revenue"

FANOUT_EXTENSION_YAML = """
entities:
  - id: entity:novashop:order_line
    source_id: novashop
    table: order_items
    primary_key: line_id
    time_field: ""
relations:
  - id: relation:novashop:order_to_lines
    from_entity_id: entity:novashop:order
    to_entity_id: entity:novashop:order_line
    join_key: order_id
    cardinality: one_to_many
dimensions:
  - id: dimension:novashop:line_sku
    entity_id: entity:novashop:order_line
    field: sku
    type: categorical
metrics:
  - id: metric:novashop:fanout_trap_revenue
    display_name: fanout trap revenue
    synonyms:
      - line revenue
    collection_id: novashop_custom
    measure_id: measure:novashop:total_amount
    grain: order
    filter_rules:
      - active
    allowed_dimension_ids:
      - dimension:novashop:line_sku
"""


@pytest.fixture(autouse=True)
def _clear_ledger():
    ledger.clear()
    yield
    ledger.clear()


def ensure_novashop_db() -> Path:
    if not NOVASHOP_DB.exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
        return NOVASHOP_DB
    con = duckdb.connect(str(NOVASHOP_DB), read_only=True)
    try:
        (has_items,) = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = 'order_items'
            """
        ).fetchone()
    finally:
        con.close()
    if not has_items:
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return NOVASHOP_DB


def raw_duckdb_correct_january_revenue(*, status: str = "delivered") -> float:
    """Independent oracle: sum order totals at order grain (no fan-out join)."""
    db_path = ensure_novashop_db()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        (total,) = con.execute(
            """
            SELECT COALESCE(SUM(total_amount), 0)
            FROM orders
            WHERE status = ?
              AND order_date >= DATE '2026-01-01'
              AND order_date < DATE '2026-02-01'
            """,
            [status],
        ).fetchone()
    finally:
        con.close()
    return float(total)


def raw_duckdb_naive_line_item_fanout_total(*, status: str = "delivered") -> float:
    """Text-to-SQL trap: join orders→order_items and SUM order totals (double-counts)."""
    db_path = ensure_novashop_db()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        (total,) = con.execute(
            """
            SELECT COALESCE(SUM(o.total_amount), 0)
            FROM orders o
            JOIN order_items li ON o.order_id = li.order_id
            WHERE o.status = ?
              AND o.order_date >= DATE '2026-01-01'
              AND o.order_date < DATE '2026-02-01'
            """,
            [status],
        ).fetchone()
    finally:
        con.close()
    return float(total)


def raw_duckdb_revenue_by_product_category() -> dict[str, float]:
    db_path = ensure_novashop_db()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT p.category, COALESCE(SUM(o.total_amount), 0)
            FROM orders o
            JOIN products p ON o.product_id = p.product_id
            WHERE o.status = 'delivered'
              AND o.order_date >= DATE '2026-01-01'
              AND o.order_date < DATE '2026-02-01'
            GROUP BY p.category
            ORDER BY p.category
            """
        ).fetchall()
    finally:
        con.close()
    return {category: float(amount) for category, amount in rows}


@pytest.fixture(scope="module")
def contract():
    ensure_novashop_db()
    return compile_contract()


@pytest.fixture(scope="module")
def fanout_contract():
    ensure_novashop_db()
    tmp = Path(tempfile.mkdtemp(prefix="recosearch_fanout_metrics_"))
    metrics_dir = tmp / "metrics"
    shutil.copytree(METRICS_DIR, metrics_dir)
    (metrics_dir / "fanout_trap.yaml").write_text(FANOUT_EXTENSION_YAML, encoding="utf-8")
    base = compile_contract()
    merged = dict(base)
    merged["metric_kernel"] = MetricKernel.from_dir(metrics_dir).to_dict()
    return merged


class TestL1FanoutWrongGrainWedge:
    """Prove L1 fan-out protection beats naive additive SQL on Novashop DuckDB."""

    def test_oracle_naive_join_overcounts_order_grain_revenue(self):
        correct = raw_duckdb_correct_january_revenue()
        naive = raw_duckdb_naive_line_item_fanout_total()
        assert naive > correct
        assert correct == pytest.approx(109.97)
        assert naive == pytest.approx(169.95)

    def test_relation_path_detects_additive_fanout(self, fanout_contract):
        kernel = MetricKernel.from_contract(fanout_contract)
        path = plan_relation_path(
            kernel.relations,
            "entity:novashop:order",
            "entity:novashop:order_line",
        )
        fanout_step = path_has_additive_fanout(path, "sum")
        assert fanout_step is not None
        assert fanout_step.relation_id == RELATION_ORDER_LINES
        assert fanout_step.cardinality == "one_to_many"

    def test_l1_governed_compile_refuses_unsafe_line_sku_drill(self, fanout_contract):
        answer = execute_metric_query(
            MetricQuery(
                term="line revenue",
                tenant="novashop",
                dimensions=(DIM_LINE_SKU,),
                reference_date=JANUARY_REFERENCE,
            ),
            contract=fanout_contract,
        )
        assert answer.decision == "refuse"
        assert answer.reason_code == "METRIC_FANOUT_BLOCKED"
        assert RELATION_ORDER_LINES in answer.reason
        assert answer.result is None

    def test_l1_compiler_raises_fanout_not_allowed_directly(self, fanout_contract):
        kernel = MetricKernel.from_contract(fanout_contract)
        resolved = MetricResolver(kernel).resolve(
            MetricQuery(term="line revenue", tenant="novashop")
        )
        compiler = MetricCompiler(kernel)
        with pytest.raises(FanoutNotAllowed) as exc:
            compiler.compile(resolved, (DIM_LINE_SKU,))
        assert exc.value.relation_id == RELATION_ORDER_LINES
        assert exc.value.metric_id == METRIC_FANOUT_TRAP

    def test_l1_safe_product_category_path_matches_duckdb_oracle(self, contract):
        expected_total = raw_duckdb_correct_january_revenue()
        expected_by_category = raw_duckdb_revenue_by_product_category()

        total_answer = execute_metric_query(
            MetricQuery(
                term=TERM_ORDER_REVENUE,
                tenant="novashop",
                reference_date=JANUARY_REFERENCE,
            ),
            contract=contract,
        )
        drill_answer = execute_metric_query(
            MetricQuery(
                term=TERM_ORDER_REVENUE,
                tenant="novashop",
                dimensions=(DIM_PRODUCT_CATEGORY,),
                reference_date=JANUARY_REFERENCE,
            ),
            contract=contract,
        )

        assert total_answer.decision == "answer"
        assert total_answer.result[0]["metric_value"] == expected_total
        assert drill_answer.decision == "answer"
        drill_totals = {row["category"]: row["metric_value"] for row in drill_answer.result}
        assert drill_totals == expected_by_category
        assert sum(drill_totals.values()) == pytest.approx(expected_total)
