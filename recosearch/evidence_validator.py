from __future__ import annotations

from typing import Any, Mapping

from .contract import _contract_hash_id, _contract_id
from .evidence_schema import validate_citation, validate_evidence_envelope


def _source_matches(actual: str, required: str) -> bool:
    return actual == required or actual.startswith(f"{required}.") or required.startswith(f"{actual}.")


def _required_sources_for_claim(claim: Mapping[str, Any]) -> list[str]:
    sources = [str(source) for source in claim.get("required_sources") or []]
    claim_source = claim.get("source")
    if claim_source:
        sources.append(str(claim_source))
    return sorted(set(sources))


def _sources_of(obj: Mapping[str, Any]) -> list[str]:
    source_ref = obj.get("source_ref") if isinstance(obj.get("source_ref"), Mapping) else {}
    out = [str(source_ref.get("source_id") or ""), str(source_ref.get("boundary") or ""), str(obj.get("source") or "")]
    return [value for value in out if value]


def _collect(packet: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Collect provenance envelopes (indexed by provenance_id and evidence_id) and
    row/chunk citations, each tagged with its parent tool-result status so refused
    outputs cannot become claim-supporting evidence."""
    envelopes: dict[str, dict[str, Any]] = {}
    citations: dict[str, dict[str, Any]] = {}
    results = list(packet.get("tool_results") or []) + list(packet.get("evidence") or [])
    for result in results:
        if not isinstance(result, Mapping):
            continue
        claim_ok = str(result.get("status") or "ok") == "ok"
        envelope = result.get("provenance")
        if isinstance(envelope, Mapping):
            for key in (envelope.get("provenance_id"), envelope.get("evidence_id")):
                if key:
                    envelopes[str(key)] = {"obj": envelope, "claim_ok": claim_ok}
        for row in result.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            citation = row.get("_citation")
            if isinstance(citation, Mapping) and citation.get("evidence_id"):
                citations[str(citation["evidence_id"])] = {"obj": citation, "claim_ok": claim_ok}
    return envelopes, citations


def validate_cited_evidence_packet(packet: dict[str, Any], *, allow_contract_drift: bool = False) -> dict[str, Any]:
    """Validate the full evidence closure for a set of final-answer claims.

    claim -> evidence_id -> citation -> provenance_id -> envelope, and for derived
    (federation) citations, -> supporting_evidence_ids -> atomic citations. Every
    cited object is schema-validated, pinned to the current contract, and must come
    from a claim-supporting, non-refused tool output.
    """
    if not isinstance(packet, Mapping):
        return {"status": "refused", "reason": "packet must be an object", "valid": False}
    claims = packet.get("claims")
    if not isinstance(claims, list) or not claims:
        return {"status": "refused", "reason": "packet.claims must be a non-empty array", "valid": False}

    envelopes, citations = _collect(packet)
    current_hash = _contract_hash_id()
    errors: list[dict[str, Any]] = []

    def add(index: int, code: str, **extra: Any) -> None:
        errors.append({"claim_index": index, "reason_code": code, **extra})

    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            add(index, "claim_not_object")
            continue
        evidence_ids = [str(item) for item in claim.get("evidence_ids") or claim.get("evidence") or []]
        if not evidence_ids:
            add(index, "missing_evidence_ids")
            continue

        cited_sources: list[str] = []
        for evidence_id in evidence_ids:
            citation_entry = citations.get(evidence_id)
            envelope_entry = envelopes.get(evidence_id)
            if not citation_entry and not envelope_entry:
                add(index, "unknown_evidence_id", evidence_ids=[evidence_id])
                continue

            if citation_entry is not None:
                citation = citation_entry["obj"]
                if validate_citation(citation):
                    add(index, "citation_malformed", evidence_ids=[evidence_id])
                if not citation_entry["claim_ok"] or not citation.get("may_support_final_answer"):
                    add(index, "evidence_not_claim_supporting", evidence_ids=[evidence_id])
                if not allow_contract_drift and citation.get("contract_hash") != current_hash:
                    add(index, "contract_hash_mismatch", evidence_ids=[evidence_id])

                provenance_id = str(citation.get("provenance_id") or "")
                parent = envelopes.get(provenance_id)
                if not parent:
                    add(index, "dangling_provenance_id", evidence_ids=[evidence_id])
                elif validate_evidence_envelope(parent["obj"]):
                    add(index, "evidence_envelope_malformed", evidence_ids=[evidence_id])

                if citation.get("evidence_kind") == "derived":
                    supporting = [str(item) for item in citation.get("supporting_evidence_ids") or []]
                    if not supporting:
                        add(index, "derived_missing_supporting_ids", evidence_ids=[evidence_id])
                    for support_id in supporting:
                        support = citations.get(support_id)
                        if not support or support["obj"].get("evidence_kind") != "atomic":
                            add(index, "unresolved_supporting_evidence", evidence_ids=[support_id])
                        else:
                            cited_sources.extend(_sources_of(support["obj"]))
                else:
                    cited_sources.extend(_sources_of(citation))
            else:
                envelope = envelope_entry["obj"]
                if validate_evidence_envelope(envelope):
                    add(index, "evidence_envelope_malformed", evidence_ids=[evidence_id])
                if not envelope_entry["claim_ok"] or not envelope.get("may_support_final_answer"):
                    add(index, "evidence_not_claim_supporting", evidence_ids=[evidence_id])
                if not allow_contract_drift and envelope.get("contract_hash") != current_hash:
                    add(index, "contract_hash_mismatch", evidence_ids=[evidence_id])
                cited_sources.extend(_sources_of(envelope))

        required_sources = _required_sources_for_claim(claim)
        missing_sources = [
            required for required in required_sources
            if not any(_source_matches(actual, required) for actual in cited_sources)
        ]
        if missing_sources:
            add(index, "missing_required_source", required_sources=missing_sources, cited_sources=cited_sources)
        if str(claim.get("claim_type") or "") in {"cross_source_verdict", "policy_review_verdict"}:
            if len(required_sources) < 2:
                add(index, "cross_source_claim_missing_required_sources")
            elif missing_sources:
                add(index, "cross_source_claim_not_fully_cited", required_sources=required_sources, cited_sources=cited_sources)

    return {
        "status": "ok" if not errors else "refused",
        "valid": not errors,
        "semantic_contract_id": _contract_id(),
        "contract_hash": current_hash,
        "evidence_count": len(citations),
        "errors": errors,
        "source_boundary": "cited_mcp_tool_outputs_only",
    }
