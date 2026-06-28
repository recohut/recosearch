import pytest

from recosearch.semantic_layers.compiler import QuerySpec, compile_query


def test_compile_query_spec():
    sql = compile_query(
        QuerySpec(
            source_key="novashop",
            table="orders",
            columns=["order_id", "total_amount"],
            filters={"status": "delivered"},
            limit=10,
        ),
        max_limit=100,
    )
    assert sql == "SELECT order_id, total_amount FROM orders WHERE status = 'delivered' LIMIT 10"


def test_compile_query_caps_limit():
    sql = compile_query(QuerySpec(source_key="novashop", table="orders", columns=["order_id"], limit=500), max_limit=100)
    assert sql.endswith("LIMIT 100")


def test_compile_query_rejects_bad_identifier():
    with pytest.raises(ValueError):
        compile_query(QuerySpec(source_key="novashop", table="orders; DROP TABLE orders", columns=["order_id"]))
