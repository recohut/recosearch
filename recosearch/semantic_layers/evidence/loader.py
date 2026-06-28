from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from recosearch.semantic_layers.evidence.schema import validate_evidence_gates
from recosearch.semantic_layers.evidence.types import (
    ComparableGroupRule,
    EvidenceGateKernel,
    EvidenceTierBar,
    ReviewTrigger,
    TIER_LABEL_TO_RANK,
)


def _tier_rank(label: str) -> int:
    if label not in TIER_LABEL_TO_RANK:
        raise ValueError(f"unknown evidence tier label: {label}")
    return TIER_LABEL_TO_RANK[label]


def _build_kernel(raw: dict[str, Any]) -> EvidenceGateKernel:
    tier_bars: dict[str, EvidenceTierBar] = {}
    for item in raw.get("evidence_tier_bars", []) or []:
        pattern = str(item["pattern"])
        label = str(item["min_tier_label"])
        tier_bars[pattern] = EvidenceTierBar(
            pattern=pattern,
            min_tier_label=label,
            min_tier_rank=_tier_rank(label),
        )

    review_triggers: dict[str, ReviewTrigger] = {}
    for item in raw.get("review_triggers", []) or []:
        pattern = str(item["pattern"])
        review_triggers[pattern] = ReviewTrigger(
            pattern=pattern,
            required_role=str(item.get("required_role", "controller")),
        )

    comparable_groups: dict[str, ComparableGroupRule] = {}
    for item in raw.get("comparable_groups", []) or []:
        group_id = str(item["group_id"])
        comparable_groups[group_id] = ComparableGroupRule(
            group_id=group_id,
            description=str(item.get("description", "")),
        )

    default_label = str(raw.get("default_min_tier_label", "fixture-backed"))
    return EvidenceGateKernel(
        tier_bars=tier_bars,
        review_triggers=review_triggers,
        comparable_groups=comparable_groups,
        default_min_tier_label=default_label,
        default_min_tier_rank=_tier_rank(default_label),
    )


def load_evidence_gates(dir_path: Path | str) -> EvidenceGateKernel:
    path = Path(dir_path) / "_gates.yaml"
    if not path.exists():
        return EvidenceGateKernel(
            tier_bars={},
            review_triggers={},
            comparable_groups={},
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    validate_evidence_gates(raw)
    return _build_kernel(raw)


def load_evidence_gates_from_contract(contract: dict[str, Any]) -> EvidenceGateKernel:
    raw = contract.get("evidence_gates")
    if not raw:
        return EvidenceGateKernel(tier_bars={}, review_triggers={}, comparable_groups={})
    if not isinstance(raw, dict):
        raise ValueError("evidence_gates must be a mapping")
    validate_evidence_gates(raw)
    return _build_kernel(raw)


def gates_to_dict(kernel: EvidenceGateKernel) -> dict[str, Any]:
    return {
        "default_min_tier_label": kernel.default_min_tier_label,
        "evidence_tier_bars": [
            {"pattern": bar.pattern, "min_tier_label": bar.min_tier_label}
            for bar in kernel.tier_bars.values()
        ],
        "review_triggers": [
            {"pattern": t.pattern, "required_role": t.required_role}
            for t in kernel.review_triggers.values()
        ],
        "comparable_groups": [
            {"group_id": g.group_id, "description": g.description}
            for g in kernel.comparable_groups.values()
        ],
    }


def pattern_matches(pattern: str, value: str) -> bool:
    if pattern == value:
        return True
    if "*" in pattern or "?" in pattern:
        return fnmatch.fnmatchcase(value, pattern)
    if pattern.endswith(":") and value.startswith(pattern):
        return True
    return False
