from recosearch.semantic_layers.envelope import Answer, DECISIONS, refuse


def test_answer_requires_known_decision():
    import pytest

    with pytest.raises(ValueError):
        Answer(decision="bogus")


def test_refuse_carries_actor_role():
    a = refuse("no", actor_role="analyst")
    assert a.decision == "refuse"
    assert a.actor_role == "analyst"


def test_answer_serializes_optional_fields():
    a = Answer(decision="answer", result=[{"x": 1}], scoped_question="how much?")
    d = a.to_dict()
    assert d["decision"] == "answer"
    assert d["result"] == [{"x": 1}]
    assert d["scoped_question"] == "how much?"
    assert "caveats" in d


def test_decisions_enum_complete():
    assert DECISIONS == frozenset(
        {"answer", "answer_with_caveats", "clarify", "review_required", "refuse"}
    )
