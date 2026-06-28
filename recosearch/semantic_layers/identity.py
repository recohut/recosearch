from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    agent_id: str = "anonymous"
    role: str = "analyst"
    tenant: str = "default"
    purpose: str = "analytics"


def resolve(
    agent_id: str = "anonymous",
    role: str = "analyst",
    tenant: str = "default",
    purpose: str = "analytics",
) -> Actor:
    """Caller identity bound at the edge (Snowflake-style passthrough later)."""
    return Actor(agent_id=agent_id, role=role, tenant=tenant, purpose=purpose)
