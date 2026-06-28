from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.pipeline import execute_structured_query

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
DB = ROOT / "examples" / "novashop" / "shop.duckdb"


@pytest.fixture(scope="module")
def contract():
    if not DB.exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_select_returns_cited_rows(contract):
    answer = execute_structured_query(
        "SELECT order_id, total_amount FROM orders WHERE status = 'delivered'",
        source_key="novashop",
        contract=contract,
    )
    assert answer.decision == "answer"
    assert len(answer.result) == 2
    assert answer.result[0]["_citation"]["contract_hash"] == contract["contract_hash"]


def test_insert_refused(contract):
    answer = execute_structured_query(
        "INSERT INTO orders VALUES ('x','2026-01-01','P001','delivered',1,1)",
        source_key="novashop",
        contract=contract,
    )
    assert answer.decision == "refuse"
