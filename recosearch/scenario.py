"""Scenario manifest loader (semantic/scenario_config.yaml).

Reads the ``scenario`` identity block: scenario_id, human name, dataset_id, the
compiled artifact_id, and the MCP server name. The same file also carries
optional governance blocks (roles, access, vocabularies) consumed elsewhere;
this loader only reads identity. Declared, not coded, so the runtime stays
scenario-agnostic. Not a connection authority (source_config.yaml) and not a
business-meaning authority (semantic.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from .errors import SEVERITY_ERROR, ContractIssue
from .settings import SCENARIO_PATH

_REQUIRED_FIELDS = ("scenario_id", "name", "mcp_name")


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    name: str
    dataset_id: str
    artifact_id: str
    mcp_name: str


def _scenario_block(text: str | None) -> dict[str, object]:
    if text is None:
        text = SCENARIO_PATH.read_text(encoding="utf-8") if SCENARIO_PATH.exists() else ""
    data = yaml.safe_load(text) if text.strip() else {}
    block = data.get("scenario") if isinstance(data, dict) else {}
    return block if isinstance(block, dict) else {}


def load_scenario(text: str | None = None) -> Scenario:
    """Load declared identity. dataset_id defaults to scenario_id; artifact_id
    defaults to '<dataset_id>.semantic'. Missing fields resolve to empty strings
    (surfaced by ``validate_scenario``), so callers never crash on a bad file."""
    block = _scenario_block(text)
    scenario_id = str(block.get("scenario_id") or "").strip()
    dataset_id = str(block.get("dataset_id") or scenario_id).strip()
    artifact_id = str(block.get("artifact_id") or (f"{dataset_id}.semantic" if dataset_id else "")).strip()
    return Scenario(
        scenario_id=scenario_id,
        name=str(block.get("name") or "").strip(),
        dataset_id=dataset_id,
        artifact_id=artifact_id,
        mcp_name=str(block.get("mcp_name") or "").strip(),
    )


def validate_scenario(text: str | None = None) -> list[ContractIssue]:
    """Non-raising identity validation. A scenario must not ship anonymous."""
    loc = "scenario_config.yaml"
    if text is None and not SCENARIO_PATH.exists():
        return [ContractIssue("scenario_manifest_missing", SEVERITY_ERROR, loc, "semantic/scenario_config.yaml is missing")]
    block = _scenario_block(text)
    if not block:
        return [ContractIssue("scenario_manifest_missing", SEVERITY_ERROR, loc, "scenario_config.yaml has no non-empty 'scenario' block")]
    return [
        ContractIssue("scenario_identity_incomplete", SEVERITY_ERROR, loc, f"scenario.{field} is required")
        for field in _REQUIRED_FIELDS
        if not str(block.get(field) or "").strip()
    ]
