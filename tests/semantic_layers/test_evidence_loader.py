from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from recosearch.semantic_layers.evidence.loader import (
    gates_to_dict,
    load_evidence_gates,
    load_evidence_gates_from_contract,
    pattern_matches,
)
from recosearch.semantic_layers.evidence.schema import EvidenceSchemaError, validate_evidence_gates

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_load_evidence_gates_from_semantic_dir():
    kernel = load_evidence_gates(SEMANTIC / "evidence")
    assert kernel.default_min_tier_label == "local-equivalent"
    assert "board_pack" in kernel.tier_bars
    assert any(
        t.pattern == "term:novashop:deferred_revenue"
        for t in kernel.review_triggers.values()
    )
    assert "january_close_totals" in kernel.comparable_groups


def test_load_evidence_gates_missing_file_returns_empty_kernel(tmp_path):
    kernel = load_evidence_gates(tmp_path)
    assert kernel.tier_bars == {}
    assert kernel.review_triggers == {}
    assert kernel.comparable_groups == {}


def test_load_evidence_gates_rejects_non_mapping(tmp_path):
    gates_path = tmp_path / "_gates.yaml"
    gates_path.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_evidence_gates(tmp_path)


def test_validate_evidence_gates_schema_errors():
    with pytest.raises(EvidenceSchemaError) as exc:
        validate_evidence_gates({"evidence_tier_bars": [{"pattern": "x"}]})
    assert exc.value.path
    assert exc.value.reason


def test_load_evidence_gates_from_contract():
    kernel = load_evidence_gates(SEMANTIC / "evidence")
    contract = {"evidence_gates": gates_to_dict(kernel)}
    restored = load_evidence_gates_from_contract(contract)
    assert restored.default_min_tier_label == kernel.default_min_tier_label
    assert restored.tier_bars.keys() == kernel.tier_bars.keys()


def test_load_evidence_gates_from_contract_missing_returns_empty():
    kernel = load_evidence_gates_from_contract({})
    assert kernel.tier_bars == {}


def test_load_evidence_gates_from_contract_non_mapping():
    with pytest.raises(ValueError, match="must be a mapping"):
        load_evidence_gates_from_contract({"evidence_gates": "bad"})


def test_gates_to_dict_roundtrip():
    kernel = load_evidence_gates(SEMANTIC / "evidence")
    payload = gates_to_dict(kernel)
    assert payload["default_min_tier_label"] == "local-equivalent"
    assert payload["evidence_tier_bars"]
    assert payload["review_triggers"]
    assert payload["comparable_groups"]


def test_tier_rank_rejects_unknown_label():
    from recosearch.semantic_layers.evidence.loader import _tier_rank

    with pytest.raises(ValueError, match="unknown evidence tier label"):
        _tier_rank("not-a-tier")


def test_pattern_matches():
    assert pattern_matches("board_pack", "board_pack")
    assert pattern_matches("term:*:deferred_revenue", "term:novashop:deferred_revenue")
    assert pattern_matches("term:novashop:", "term:novashop:revenue")
    assert not pattern_matches("board_pack", "finance_close")
    assert not pattern_matches("term:other:", "term:novashop:revenue")


def test_validate_evidence_gates_rejects_unknown_default_tier_label():
    with pytest.raises(EvidenceSchemaError, match="unknown tier label"):
        validate_evidence_gates({"default_min_tier_label": "not-a-tier"})


def test_validate_evidence_gates_rejects_unknown_tier_in_bar():
    with pytest.raises(EvidenceSchemaError, match="unknown tier label"):
        validate_evidence_gates(
            {
                "evidence_tier_bars": [{"pattern": "board_pack", "min_tier_label": "not-a-tier"}],
            }
        )


def test_load_evidence_gates_invalid_schema_in_dir(tmp_path):
    evidence_dir = tmp_path / "evidence"
    shutil.copytree(SEMANTIC / "evidence", evidence_dir)
    raw = yaml.safe_load((evidence_dir / "_gates.yaml").read_text(encoding="utf-8"))
    raw["evidence_tier_bars"] = [{"pattern": "x"}]
    (evidence_dir / "_gates.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(EvidenceSchemaError):
        load_evidence_gates(evidence_dir)
