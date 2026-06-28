from __future__ import annotations

from pathlib import Path

import pytest

from recosearch.semantic_layers.contract import ROOT
from recosearch.semantic_layers.decisions.loader import (
    config_to_dict,
    load_decisions_config,
    load_decisions_config_from_contract,
)
from recosearch.semantic_layers.decisions.schema import DecisionSchemaError, validate_decisions_config

DECISIONS_DIR = ROOT / "semantic" / "decisions"


def test_load_decisions_config():
    kernel = load_decisions_config(DECISIONS_DIR)
    assert kernel.calibration_match_rules
    assert kernel.advisory_target_rules


def test_load_decisions_config_from_contract(compile_contract):
    kernel = load_decisions_config_from_contract(compile_contract)
    assert kernel.calibration_match_rules


def test_config_to_dict_roundtrip():
    kernel = load_decisions_config(DECISIONS_DIR)
    data = config_to_dict(kernel)
    assert data["calibration_match_rules"]


def test_load_decisions_config_missing_dir(tmp_path):
    kernel = load_decisions_config(tmp_path)
    assert kernel.calibration_match_rules == ()


def test_load_decisions_config_invalid_file(tmp_path):
    path = tmp_path / "_decisions.yaml"
    path.write_text("not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_decisions_config(tmp_path)


def test_load_decisions_config_from_contract_invalid():
    with pytest.raises(ValueError, match="decisions_config must be a mapping"):
        load_decisions_config_from_contract({"decisions_config": "bad"})


def test_validate_decisions_config_unknown_match_mode():
    with pytest.raises(DecisionSchemaError, match="unknown match mode"):
        validate_decisions_config(
            {
                "calibration_match_rules": [{"field": "status", "match_mode": "fuzzy"}],
            }
        )
