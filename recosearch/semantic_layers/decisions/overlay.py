from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def _merge_tier_bars(base: list[Any], overlay: list[Any]) -> list[Any]:
    merged = copy.deepcopy(base)
    by_pattern = {str(item.get("pattern")): item for item in merged if isinstance(item, dict)}
    for item in overlay:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern", ""))
        if pattern in by_pattern:
            by_pattern[pattern] = {**by_pattern[pattern], **item}
        else:
            by_pattern[pattern] = dict(item)
    return list(by_pattern.values())


def deep_merge_contract(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key == "contract_hash":
            continue
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_contract(result[key], value)
        elif (
            key in result
            and isinstance(result[key], list)
            and isinstance(value, list)
            and key == "evidence_tier_bars"
        ):
            result[key] = _merge_tier_bars(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def recompute_contract_hash(contract: dict[str, Any]) -> dict[str, Any]:
    payload_contract = {k: v for k, v in contract.items() if k != "contract_hash"}
    payload = json.dumps(payload_contract, sort_keys=True)
    contract = dict(contract)
    contract["contract_hash"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return contract


def apply_contract_overlay(contract: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deep_merge_contract(contract, overlay)
    return recompute_contract_hash(merged)
