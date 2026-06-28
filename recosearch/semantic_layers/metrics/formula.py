from __future__ import annotations

import re
from typing import Callable

import sqlglot
import sqlglot.expressions as exp

_REF_PATTERN = re.compile(r"(metric|measure):[a-zA-Z0-9_:]+")
class FormulaError(ValueError):
    pass


def extract_refs(formula: str) -> tuple[str, ...]:
    if not formula:
        return ()
    _parse_formula_ast(formula)
    return tuple(sorted({m.group(0) for m in _REF_PATTERN.finditer(formula)}))


def _tokenize_refs(formula: str) -> tuple[str, dict[str, str]]:
    refs: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        token = f"__ref_{len(refs)}__"
        refs[token] = match.group(0)
        return token

    return _REF_PATTERN.sub(repl, formula), refs


def _parse_formula_ast(formula: str) -> exp.Expression:
    if not formula.strip():
        raise FormulaError("formula must not be empty")
    tokenized, refs = _tokenize_refs(formula)
    try:
        ast = sqlglot.parse_one(tokenized, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise FormulaError(f"invalid formula syntax: {exc}") from exc
    _validate_ast(ast, refs)
    return ast


def _validate_ast(node: exp.Expression, refs: dict[str, str]) -> None:
    if isinstance(node, exp.Identifier):
        name = node.name
        if name not in refs:
            raise FormulaError(f"unknown identifier {name!r}; refs must be metric: or measure: tokens")
        return
    if isinstance(node, exp.Column):
        col = node.name
        if col not in refs:
            raise FormulaError(f"unknown column ref {col!r}")
        return
    if isinstance(node, exp.Literal):
        return
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul, exp.Div)):
        _validate_ast(node.left, refs)
        _validate_ast(node.right, refs)
        return
    if isinstance(node, exp.Paren):
        _validate_ast(node.this, refs)
        return
    if isinstance(node, exp.Subquery):
        raise FormulaError("subqueries are not allowed in metric formulas")
    if isinstance(node, exp.Func):
        raise FormulaError(f"functions are not allowed in metric formulas: {node.sql()}")
    raise FormulaError(f"unsupported formula node: {type(node).__name__}")


def _wrap_divisions(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Div):
        left = _wrap_divisions(node.left)
        right = _wrap_divisions(node.right)
        nullif = exp.Nullif(this=right.copy(), expression=exp.Literal.number(0))
        return exp.Div(this=left, expression=nullif)
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul)):
        return type(node)(this=_wrap_divisions(node.left), expression=_wrap_divisions(node.right))
    if isinstance(node, exp.Paren):
        return exp.Paren(this=_wrap_divisions(node.this))
    return node


def render_formula(
    formula: str,
    ref_to_sql: Callable[[str], str],
    *,
    dialect: str = "duckdb",
) -> str:
    ast = _parse_formula_ast(formula)
    ast = _wrap_divisions(ast)
    _, refs = _tokenize_refs(formula)

    def identifier_transform(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Identifier):
            ref = refs.get(node.name)
            if ref is not None:
                return sqlglot.parse_one(ref_to_sql(ref), dialect=dialect)
        return node

    rendered = ast.transform(identifier_transform)
    return rendered.sql(dialect=dialect)
