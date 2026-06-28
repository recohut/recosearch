from __future__ import annotations

import sqlglot
from sqlglot import exp


def lint_select_only(sql: str, dialect: str = "duckdb") -> str:
    """Read-only lint. Compile-time identity predicate injection comes in slice 2 (governed compiler)."""
    tree = sqlglot.parse_one(sql, read=dialect)
    if not isinstance(tree, exp.Select):
        raise ValueError("only SELECT allowed")
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("only one statement allowed")
    return sql.strip()
