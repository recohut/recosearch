"""Offline tests for recosearch/adapters/postgres.py validate_postgres_sql.

No DB connection needed — validate_postgres_sql only parses SQL + checks the
compiled semantic contract (static semantic.json).

Tests:
- SELECT on declared postgres tables -> decision allow
- INSERT/UPDATE/DELETE -> mutating_sql
- Non-select (CREATE/DROP) -> mutating_sql
- Undeclared table -> table_not_allowed
- Undeclared column on a declared table -> column_not_allowed
- Missing global exclusion -> missing_global_exclusion
- Parameterized exclusion accepted
- dialect param accepted (postgres / snowflake)
"""
from __future__ import annotations

import pytest

from recosearch.adapters.postgres import validate_postgres_sql


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allow(result: dict) -> None:
    assert result["decision"] == "allow", (
        f"Expected allow, got {result['decision']!r} (reason={result.get('reason_code')!r})"
    )
    assert result["execution_allowed"] is True


def _refuse(result: dict, reason_code: str) -> None:
    assert result["decision"] == "refuse", (
        f"Expected refuse, got {result['decision']!r}"
    )
    assert result["reason_code"] == reason_code, (
        f"Expected reason_code={reason_code!r}, got {result.get('reason_code')!r}"
    )
    assert result["execution_allowed"] is False


# ---------------------------------------------------------------------------
# Happy path — SELECT on declared postgres tables
# ---------------------------------------------------------------------------

def test_select_on_sellers_allowed() -> None:
    """sellers has no exclusion requirement so a plain SELECT is allowed."""
    result = validate_postgres_sql("SELECT seller_id FROM sellers")
    _allow(result)
    assert "sellers" in result["tables"]


def test_select_on_orders_with_required_exclusion_allowed() -> None:
    """orders requires the product_id != 'P003' exclusion from global rules."""
    result = validate_postgres_sql("SELECT order_id FROM orders WHERE product_id != 'P003'")
    _allow(result)


def test_select_on_products_with_required_exclusion_allowed() -> None:
    result = validate_postgres_sql("SELECT product_id FROM products WHERE product_id != 'P003'")
    _allow(result)


def test_select_star_on_sellers_allowed() -> None:
    result = validate_postgres_sql("SELECT * FROM sellers")
    _allow(result)


# ---------------------------------------------------------------------------
# Mutating SQL — INSERT / UPDATE / DELETE
# ---------------------------------------------------------------------------

def test_insert_refused() -> None:
    result = validate_postgres_sql("INSERT INTO sellers (seller_id) VALUES ('S999')")
    _refuse(result, "mutating_sql")


def test_update_refused() -> None:
    result = validate_postgres_sql("UPDATE sellers SET active_status = 'inactive'")
    _refuse(result, "mutating_sql")


def test_delete_refused() -> None:
    result = validate_postgres_sql("DELETE FROM sellers WHERE seller_id = 'S1'")
    _refuse(result, "mutating_sql")


def test_drop_refused() -> None:
    result = validate_postgres_sql("DROP TABLE sellers")
    _refuse(result, "mutating_sql")


def test_truncate_refused() -> None:
    result = validate_postgres_sql("TRUNCATE TABLE sellers")
    _refuse(result, "mutating_sql")


# ---------------------------------------------------------------------------
# Non-select that isn't a mutating keyword — not_read_only_select
# ---------------------------------------------------------------------------

def test_non_select_create_not_read_only() -> None:
    # CREATE is caught by the mutating_sql regex first (it includes 'create')
    result = validate_postgres_sql("CREATE TABLE foo (id INT)")
    # Either mutating_sql or not_read_only_select is acceptable — both refuse execution
    assert result["decision"] == "refuse"
    assert result["execution_allowed"] is False


def test_call_statement_not_read_only() -> None:
    # CALL is not a SELECT and doesn't start with SELECT/WITH
    result = validate_postgres_sql("CALL some_procedure()")
    assert result["decision"] == "refuse"
    assert result["execution_allowed"] is False


# ---------------------------------------------------------------------------
# Undeclared table
# ---------------------------------------------------------------------------

def test_undeclared_table_refused() -> None:
    result = validate_postgres_sql("SELECT id FROM unknown_table")
    _refuse(result, "table_not_allowed")
    assert "unknown_table" in result["bad_tables"]


def test_declared_os_table_refused_for_postgres() -> None:
    """customer_reviews belongs to opensearch, not postgres — must be refused."""
    result = validate_postgres_sql("SELECT review_id FROM customer_reviews")
    _refuse(result, "table_not_allowed")


# ---------------------------------------------------------------------------
# Undeclared column on a declared table
# ---------------------------------------------------------------------------

def test_undeclared_column_refused() -> None:
    result = validate_postgres_sql(
        "SELECT nonexistent_col FROM sellers"
    )
    _refuse(result, "column_not_allowed")


def test_undeclared_column_on_orders_refused() -> None:
    result = validate_postgres_sql(
        "SELECT fake_column FROM orders WHERE product_id != 'P003'"
    )
    _refuse(result, "column_not_allowed")


# ---------------------------------------------------------------------------
# Missing global exclusion
# ---------------------------------------------------------------------------

def test_missing_exclusion_refused_for_orders() -> None:
    """orders requires product_id != 'P003' — omitting it must be refused."""
    result = validate_postgres_sql("SELECT order_id FROM orders")
    _refuse(result, "missing_global_exclusion")


def test_missing_exclusion_refused_for_products() -> None:
    result = validate_postgres_sql("SELECT product_id FROM products")
    _refuse(result, "missing_global_exclusion")


# ---------------------------------------------------------------------------
# Parameterized exclusion accepted
# ---------------------------------------------------------------------------

def test_parameterized_exclusion_accepted() -> None:
    """product_id != %s with allow_parameterized_exclusions=True -> allow."""
    result = validate_postgres_sql(
        "SELECT order_id FROM orders WHERE product_id != %s",
        allow_parameterized_exclusions=True,
    )
    _allow(result)


def test_parameterized_exclusion_not_accepted_by_default() -> None:
    """Without the flag, %s placeholder is not recognised as the exclusion."""
    result = validate_postgres_sql(
        "SELECT order_id FROM orders WHERE product_id != %s",
        allow_parameterized_exclusions=False,
    )
    _refuse(result, "missing_global_exclusion")


# ---------------------------------------------------------------------------
# dialect param accepted
# ---------------------------------------------------------------------------

def test_postgres_dialect_accepted() -> None:
    result = validate_postgres_sql("SELECT seller_id FROM sellers", dialect="postgres")
    _allow(result)


def test_snowflake_dialect_accepted() -> None:
    """snowflake dialect parses the same SQL correctly."""
    result = validate_postgres_sql("SELECT seller_id FROM sellers", dialect="snowflake")
    _allow(result)


def test_snowflake_dialect_still_refuses_undeclared_table() -> None:
    result = validate_postgres_sql("SELECT foo FROM no_such_table", dialect="snowflake")
    _refuse(result, "table_not_allowed")


# ---------------------------------------------------------------------------
# Regression: no-FROM function calls and dangerous server-side functions must
# NOT slip past the table/column allowlists (security regression fix).
# ---------------------------------------------------------------------------

def test_pg_read_file_no_from_refused() -> None:
    _refuse(validate_postgres_sql("SELECT pg_read_file('/etc/passwd')"), "forbidden_function")


def test_pg_sleep_no_from_refused() -> None:
    _refuse(validate_postgres_sql("SELECT pg_sleep(10)"), "forbidden_function")


def test_version_no_from_refused() -> None:
    _refuse(validate_postgres_sql("SELECT version()"), "no_table_source")


def test_current_user_no_from_refused() -> None:
    _refuse(validate_postgres_sql("SELECT current_user"), "no_table_source")


def test_constant_select_no_table_refused() -> None:
    _refuse(validate_postgres_sql("SELECT 1"), "no_table_source")


def test_dangerous_function_with_valid_from_refused() -> None:
    # A valid FROM must NOT let a file-read function through.
    _refuse(
        validate_postgres_sql("SELECT pg_read_file('/etc/passwd') FROM sellers"),
        "forbidden_function",
    )


def test_dangerous_function_in_subquery_refused() -> None:
    _refuse(
        validate_postgres_sql(
            "SELECT seller_id FROM sellers WHERE seller_id = (SELECT pg_read_file('/x'))"
        ),
        "forbidden_function",
    )
