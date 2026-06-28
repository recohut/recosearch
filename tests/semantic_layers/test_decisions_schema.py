from __future__ import annotations

import pytest

from recosearch.semantic_layers.decisions.schema import (
    DecisionSchemaError,
    validate_decision_certifications,
    validate_decisions_config,
)
from recosearch.semantic_layers.decisions.types import ReplayResult


def test_replay_result_to_dict():
    result = ReplayResult(
        decision_id="decision-abc",
        original_contract_hash="hash1",
        replayed_contract_hash="hash2",
        original_decision="answer",
        replayed_decision="review_required",
        drift=True,
        drift_reasons=("contract_hash_changed",),
    )
    data = result.to_dict()
    assert data["drift"] is True
    assert data["drift_reasons"] == ["contract_hash_changed"]


def test_validate_decision_certifications_unknown_delta():
    with pytest.raises(DecisionSchemaError, match="unknown calibration delta"):
        validate_decision_certifications(
            {
                "certifications": [
                    {
                        "case_id": "x",
                        "expected_replay_drift": False,
                        "expected_calibration_delta": "unknown",
                        "subclaims": [{"term": "revenue"}],
                    }
                ]
            }
        )


def test_validate_decision_certifications_unknown_pack_decision():
    with pytest.raises(DecisionSchemaError, match="unknown pack decision"):
        validate_decision_certifications(
            {
                "certifications": [
                    {
                        "case_id": "x",
                        "expected_replay_drift": False,
                        "expected_pack_decision": "bogus",
                        "subclaims": [{"term": "revenue"}],
                    }
                ]
            }
        )


def test_validate_decisions_config_schema_error():
    with pytest.raises(DecisionSchemaError):
        validate_decisions_config({"calibration_match_rules": [{"match_mode": "exact"}]})
