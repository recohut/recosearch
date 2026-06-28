from __future__ import annotations

import hashlib
import json
from typing import Any


def card_payload(card: dict[str, Any]) -> dict[str, Any]:
    trust = card.get("trust", {})
    scope = trust.get("claim_scope", {})
    return {
        "term_id": card["term_id"],
        "display_name": card["display_name"],
        "definition": card["definition"],
        "primary_refs": sorted(card.get("primary_refs", [])),
        "related_refs": sorted(card.get("related_refs", [])),
        "trust_status": trust.get("status", ""),
        "evidence_tier": trust.get("evidence_tier", 0),
        "drift_status": trust.get("drift_status", ""),
        "expiry_reasons": sorted(trust.get("expiry_reasons", [])),
        "claim_scope_sources": sorted(scope.get("sources", [])),
        "claim_scope_roles": sorted(scope.get("roles", [])),
        "claim_scope_metrics": sorted(scope.get("metrics", [])),
    }


def compute_card_id(card: dict[str, Any]) -> str:
    payload = json.dumps(card_payload(card), sort_keys=True)
    return "ctx-" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def trust_payload(trust: dict[str, Any]) -> dict[str, Any]:
    scope = trust.get("claim_scope", {})
    return {
        "status": trust.get("status", ""),
        "evidence_tier": trust.get("evidence_tier", 0),
        "drift_status": trust.get("drift_status", ""),
        "expiry_reasons": sorted(trust.get("expiry_reasons", [])),
        "sources": sorted(scope.get("sources", [])),
        "roles": sorted(scope.get("roles", [])),
        "metrics": sorted(scope.get("metrics", [])),
    }


def compute_trust_id(trust: dict[str, Any]) -> str:
    payload = json.dumps(trust_payload(trust), sort_keys=True)
    return "trust-" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def term_definition_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "display_name": str(item["display_name"]),
        "definition": str(item["definition"]),
        "aliases": sorted(str(a) for a in item.get("aliases", [])),
        "collection_id": str(item["collection_id"]),
        "primary_refs": sorted(str(r) for r in item["primary_refs"]),
    }


def compute_term_definition_hash(item: dict[str, Any]) -> str:
    payload = json.dumps(term_definition_payload(item), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
