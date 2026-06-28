from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class QuerySpec:
    source_key: str
    table: str
    columns: list[str]
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int | None = None
    scoped_question: str = ""


def compile_query(spec: QuerySpec, *, max_limit: int = 100) -> str:
    """Render a small typed request into SQL.

    This is the first compiler seam. It keeps raw SQL out of normal callers while
    staying simple enough for the DuckDB slice.
    """
    _check_identifier(spec.table, "table")
    if not spec.columns:
        raise ValueError("at least one column required")
    for col in spec.columns:
        _check_identifier(col, "column")
    for col in spec.filters:
        _check_identifier(col, "filter")

    columns = ", ".join(spec.columns)
    sql = f"SELECT {columns} FROM {spec.table}"
    if spec.filters:
        clauses = [f"{col} = {_literal(value)}" for col, value in sorted(spec.filters.items())]
        sql += " WHERE " + " AND ".join(clauses)

    limit = spec.limit if spec.limit is not None else max_limit
    sql += f" LIMIT {min(limit, max_limit)}"
    return sql


def _check_identifier(value: str, kind: str) -> None:
    if not _IDENTIFIER.match(value):
        raise ValueError(f"invalid {kind}: {value!r}")


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"
