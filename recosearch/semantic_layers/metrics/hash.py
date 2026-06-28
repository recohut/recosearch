from __future__ import annotations

import hashlib
import json
from typing import Any


def metric_definition_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(item.get("kind", "measure")),
        "measure_id": str(item.get("measure_id", "")),
        "formula": str(item.get("formula", "")),
        "grain": str(item["grain"]),
        "filter_rules": sorted(str(r) for r in item.get("filter_rules", [])),
        "allowed_dimension_ids": sorted(str(d) for d in item.get("allowed_dimension_ids", [])),
    }


def compute_definition_hash(item: dict[str, Any]) -> str:
    payload = json.dumps(metric_definition_payload(item), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
