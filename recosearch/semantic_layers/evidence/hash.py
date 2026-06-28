from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_pack_id(*, claim_set_payload: dict[str, Any], contract_hash: str) -> str:
    content = json.dumps(
        {"claims": claim_set_payload, "contract_hash": contract_hash},
        sort_keys=True,
    )
    return "pack-" + hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_ticket_id(*, pack_id: str, triggers: tuple[str, ...]) -> str:
    content = json.dumps({"pack_id": pack_id, "triggers": list(triggers)}, sort_keys=True)
    return "ticket-" + hashlib.sha256(content.encode()).hexdigest()[:16]
