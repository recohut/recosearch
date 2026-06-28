import pytest

from recosearch.semantic_layers.metrics.formula import FormulaError, extract_refs, render_formula


def test_extract_refs_sorted_unique():
    formula = "measure:x:b + measure:x:a / metric:x:c"
    assert extract_refs(formula) == ("measure:x:a", "measure:x:b", "metric:x:c")


def test_extract_refs_rejects_function_call():
    with pytest.raises(FormulaError, match="functions"):
        extract_refs("SUM(measure:x:a)")


def test_extract_refs_rejects_subquery():
    with pytest.raises(FormulaError, match="subquer"):
        extract_refs("(SELECT 1) + measure:x:a")


def test_render_formula_substitutes_refs_and_nullif_division():
    formula = "measure:x:a / measure:x:b"
    rendered = render_formula(
        formula,
        lambda ref: {"measure:x:a": "SUM(t0.amount)", "measure:x:b": "COUNT(t0.id)"}[ref],
    )
    assert "SUM(t0.amount)" in rendered
    assert "NULLIF(COUNT(t0.id), 0)" in rendered


def test_render_formula_supports_parentheses_and_literals():
    formula = "(measure:x:a + 1.5) * 2"
    rendered = render_formula(formula, lambda ref: "SUM(t0.amount)")
    assert "SUM(t0.amount)" in rendered
    assert "1.5" in rendered


@pytest.mark.parametrize(
    "formula,error_match",
    [
        ("   ", "must not be empty"),
        ("SUM(measure:x:a)", "functions"),
        ("COALESCE(measure:x:a, 0)", "functions"),
        ("(SELECT 1 FROM t) + measure:x:a", "subquer"),
        ("measure:x:a; DROP TABLE orders", "unsupported formula node"),
        ("measure:x:a + unknown_token", "unknown column ref"),
        ("(measure:x:a + measure:x:b", "invalid formula syntax"),
        ("measure:x:a +)", "invalid formula syntax"),
        ("1 + * 2", "invalid formula syntax"),
    ],
    ids=[
        "whitespace",
        "sum_function",
        "coalesce_function",
        "subquery",
        "sql_injection_semicolon",
        "unknown_identifier",
        "unbalanced_paren_open",
        "unbalanced_paren_close",
        "invalid_operator_sequence",
    ],
)
def test_extract_refs_rejects_adversarial_formula(formula, error_match):
    with pytest.raises(FormulaError, match=error_match):
        extract_refs(formula)


def test_extract_refs_returns_empty_for_blank_formula():
    assert extract_refs("") == ()


@pytest.mark.parametrize(
    "formula,expected_refs",
    [
        ("measure:x:a + measure:x:a", ("measure:x:a",)),
        ("measure:x:a + measure:x:b * 2", ("measure:x:a", "measure:x:b")),
        ("(measure:x:a + measure:x:b) / measure:x:c", ("measure:x:a", "measure:x:b", "measure:x:c")),
        ("measure:x:a - measure:x:b / measure:x:c", ("measure:x:a", "measure:x:b", "measure:x:c")),
    ],
    ids=["repeated_ref", "mixed_ops", "grouped_division", "precedence_chain"],
)
def test_extract_refs_handles_valid_formula_shapes(formula, expected_refs):
    assert extract_refs(formula) == expected_refs


def test_render_formula_wraps_nested_divisions_with_nullif():
    formula = "measure:x:a / measure:x:b / measure:x:c"
    rendered = render_formula(
        formula,
        lambda ref: {
            "measure:x:a": "SUM(t0.a)",
            "measure:x:b": "COUNT(t0.b)",
            "measure:x:c": "COUNT(t0.c)",
        }[ref],
    )
    assert "NULLIF(COUNT(t0.b), 0)" in rendered
    assert "NULLIF(COUNT(t0.c), 0)" in rendered


def test_render_formula_preserves_operator_precedence():
    formula = "measure:x:a + measure:x:b * 2"
    rendered = render_formula(
        formula,
        lambda ref: {"measure:x:a": "SUM(t0.a)", "measure:x:b": "COUNT(t0.b)"}[ref],
    )
    normalized = rendered.replace(" ", "")
    assert normalized == "SUM(t0.a)+COUNT(t0.b)*2"


def test_render_formula_rejects_malformed_before_render():
    with pytest.raises(FormulaError, match="functions"):
        render_formula("ABS(measure:x:a)", lambda ref: "1")
