from __future__ import annotations

from recosearch.semantic_layers.evidence.hash import compute_ticket_id
from recosearch.semantic_layers.evidence.types import ReviewTicket


def create_review_ticket(
    *,
    pack_id: str,
    triggers: tuple[str, ...],
    required_role: str = "controller",
) -> ReviewTicket:
    ticket_id = compute_ticket_id(pack_id=pack_id, triggers=triggers)
    return ReviewTicket(
        ticket_id=ticket_id,
        pack_id=pack_id,
        triggers=triggers,
        required_role=required_role,
        status="pending",
    )
