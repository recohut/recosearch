from pathlib import Path

import pytest

from recosearch.semantic_layers.context.eval import golden_context_suite, pass_k
from recosearch.semantic_layers.contract import compile_contract

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


@pytest.fixture(scope="module")
def contract():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract()


def test_pass_k_deterministic(contract):
    score = pass_k(golden_context_suite(), contract, k=2)
    assert score >= 0.66


def test_pass_k_fails_on_nondeterministic_runner(contract):
    class FakeAnswer:
        def __init__(self, decision: str):
            self.decision = decision

    calls = {"n": 0}

    def flaky_runner(question, _contract):
        calls["n"] += 1
        decision = "answer" if calls["n"] % 2 == 1 else "clarify"
        return FakeAnswer(decision)

    score = pass_k(
        [{"term": "revenue", "tenant": "novashop", "expected_decision": "answer"}],
        contract,
        k=2,
        runner=flaky_runner,
    )
    assert score == 0.0
