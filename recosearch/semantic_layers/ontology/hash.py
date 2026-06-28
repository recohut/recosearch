from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_ontology_hash(
    *,
    ontology_ttl: str,
    shapes_ttl: str,
    mappings: dict[str, Any],
    reasoner_mode: str,
) -> str:
    payload = {
        "ontology_ttl": ontology_ttl,
        "shapes_ttl": shapes_ttl,
        "mappings": mappings,
        "reasoner_mode": reasoner_mode,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"onto-{digest}"


def compute_claim_hash(claim_payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(claim_payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"claim-{digest}"
