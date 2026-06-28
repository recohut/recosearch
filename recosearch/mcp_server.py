"""RecoSearch governed MCP server.

Authority files:
  semantic/scenario_config.yaml  — scenario identity and governance
  semantic/source_config.yaml    — source connections and credentials
  semantic/semantic.md           — business meaning (metrics, rules, dimensions)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from mcp.server.fastmcp import FastMCP

from recosearch.contract import compile_semantic_contract, validated_contract
from recosearch.evidence_validator import validate_cited_evidence_packet
from recosearch.errors import BoundaryError
from recosearch.federation import combine_slices
from recosearch.observability import init_tracing
from recosearch.adapters.postgres import validate_postgres_sql
from recosearch.scenario import load_scenario
from recosearch.tools import (
    check_semantic_json_fresh,
    execute_postgres_semantic_query,
    generate_semantic_json,
    get_semantic_contract,
    health_check_sources,
    list_sources,
    register_tools,
    run_guarded_postgres_sql,
    search_text,
    search_vector,
    validate_analysis_request,
)

mcp = FastMCP(load_scenario().mcp_name or "recosearch-mcp")
register_tools(mcp)

# ---------------------------------------------------------------------------
# Depth tools (L1–L3 only; L4/L5 decision tools are experimental).
# Imported ADDITIVELY and GUARDED so a depth-import failure cannot break
# the server boot path.
# ---------------------------------------------------------------------------
try:
    from recosearch.semantic_layers import mcp_tools as _depth

    @mcp.tool()
    def depth_metric_query(params: dict) -> dict:
        """L1 governed metric query via the DuckDB certified semantic layers."""
        return _depth.handle_metric_query(params)

    @mcp.tool()
    def depth_list_metrics(params: dict | None = None) -> dict:
        """L1 list all certified metrics from the semantic layers kernel."""
        return _depth.handle_list_metrics()

    @mcp.tool()
    def depth_describe_metric(metric_id: str) -> dict:
        """L1 describe a single metric from the semantic layers kernel."""
        return _depth.handle_describe_metric(metric_id)

    @mcp.tool()
    def depth_resolve_context(params: dict) -> dict:
        """L2 resolve business context (dimensions, segments, facets)."""
        return _depth.handle_resolve_context(params)

    @mcp.tool()
    def depth_describe_context(context_id: str) -> dict:
        """L2 describe a business context object."""
        return _depth.handle_describe_context(context_id)

    @mcp.tool()
    def depth_list_terms(params: dict | None = None) -> dict:
        """L2 list all ontology terms in the semantic layers."""
        return _depth.handle_list_terms(params or {})

    @mcp.tool()
    def depth_validate_claim(params: dict) -> dict:
        """L3 validate a claim against certified SHACL constraints."""
        return _depth.handle_validate_claim(params)

    @mcp.tool()
    def depth_describe_constraints(params: dict | None = None) -> dict:
        """L3 describe active SHACL constraint shapes."""
        return _depth.handle_describe_constraints(params or {})

    @mcp.tool()
    def depth_list_shapes(params: dict | None = None) -> dict:
        """L3 list all SHACL shapes in the ontology kernel."""
        return _depth.handle_list_shapes(params or {})

except Exception as _depth_import_err:  # pragma: no cover
    import sys
    print(
        f"[recosearch] WARNING: depth semantic-layers tools could not be loaded: "
        f"{_depth_import_err}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Experimental L4/L5 decision & calibration tools (OFF by default).
# Enable with RECOSEARCH_EXPERIMENTAL=1 (or true/yes/on).
#
# NOTE: the decision ledger is per-process (in-memory). Audit entries are
# not persisted across server restarts. These tools are experimental and
# subject to change without notice.
# ---------------------------------------------------------------------------
_EXPERIMENTAL_ON = os.environ.get("RECOSEARCH_EXPERIMENTAL", "").strip().lower() in (
    "1", "true", "yes", "on"
)

if _EXPERIMENTAL_ON:
    try:
        from recosearch.semantic_layers import mcp_tools as _depth_exp

        @mcp.tool()
        def experimental_compose_evidence_pack(params: dict) -> dict:
            """[EXPERIMENTAL] L4 compose a governed evidence pack for a claim set."""
            return _depth_exp.handle_compose_evidence_pack(params)

        @mcp.tool()
        def experimental_record_decision(params: dict) -> dict:
            """[EXPERIMENTAL] L4 record a governed decision in the per-process ledger."""
            return _depth_exp.handle_record_decision(params)

        @mcp.tool()
        def experimental_replay_decision(params: dict) -> dict:
            """[EXPERIMENTAL] L4 replay a recorded decision for audit or counterfactual."""
            return _depth_exp.handle_replay_decision(params)

        @mcp.tool()
        def experimental_record_outcome(params: dict) -> dict:
            """[EXPERIMENTAL] L4 record a real-world outcome against a prior decision."""
            return _depth_exp.handle_record_outcome(params)

        @mcp.tool()
        def experimental_generate_calibration_signal(params: dict) -> dict:
            """[EXPERIMENTAL] L5 generate a calibration signal from a decision and its outcome."""
            return _depth_exp.handle_generate_calibration_signal(params)

        @mcp.tool()
        def experimental_aggregate_calibration(params: dict | None = None) -> dict:
            """[EXPERIMENTAL] L5 aggregate calibration signals into a trust-prior report."""
            return _depth_exp.handle_aggregate_calibration(params or {})

        @mcp.tool()
        def experimental_counterfactual_replay(params: dict) -> dict:
            """[EXPERIMENTAL] L5 replay a decision under a counterfactual evidence scenario."""
            return _depth_exp.handle_counterfactual_replay(params)

        @mcp.tool()
        def experimental_propose_trust_prior(params: dict | None = None) -> dict:
            """[EXPERIMENTAL] L5 propose a new trust prior from aggregated calibration data."""
            return _depth_exp.handle_propose_trust_prior(params or {})

        @mcp.tool()
        def experimental_approve_trust_prior_proposal(params: dict) -> dict:
            """[EXPERIMENTAL] L5 approve a pending trust-prior proposal."""
            return _depth_exp.handle_approve_trust_prior_proposal(params)

        @mcp.tool()
        def experimental_reject_trust_prior_proposal(params: dict) -> dict:
            """[EXPERIMENTAL] L5 reject a pending trust-prior proposal."""
            return _depth_exp.handle_reject_trust_prior_proposal(params)

    except Exception as _exp_import_err:  # pragma: no cover
        import sys
        print(
            f"[recosearch] WARNING: experimental L4/L5 tools could not be loaded: "
            f"{_exp_import_err}",
            file=sys.stderr,
        )


def _print_issues(issues) -> None:
    for issue in issues:
        print(json.dumps(issue.as_dict(), sort_keys=True), file=sys.stderr)


def _enforcement_mode() -> str:
    return os.environ.get("RECOSEARCH_CONTRACT_ENFORCEMENT", "warn").strip().casefold()


def _boot_guard() -> None:
    vc = validated_contract()
    fresh = check_semantic_json_fresh()
    strict = _enforcement_mode() == "strict"
    if not vc.is_valid:
        print(f"[contract] {len(vc.errors)} error-severity issue(s):", file=sys.stderr)
        _print_issues(vc.issues)
        if strict:
            print("[contract] strict mode: refusing to start.", file=sys.stderr)
            raise SystemExit(2)
        print("[contract] warn mode: starting, governed tools will refuse until fixed.", file=sys.stderr)
    if not fresh["fresh"]:
        print(f"[contract] semantic.json is stale: {fresh['reason']}", file=sys.stderr)
        if strict:
            raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RecoSearch MCP server.")
    parser.add_argument("--write-semantic-json", action="store_true", help="Compile and write semantic.json, then exit.")
    parser.add_argument("--health-check", action="store_true", help="Probe declared sources, then exit.")
    parser.add_argument("--validate", action="store_true", help="Validate declared inputs; exit non-zero on errors.")
    parser.add_argument("--check-semantic-json", action="store_true", help="Verify semantic.json matches compiled contract; exit non-zero if stale.")
    args = parser.parse_args()

    if args.write_semantic_json:
        payload = generate_semantic_json(write=True)
        print(json.dumps({"status": payload["status"], "path": payload["path"], "is_valid": payload["is_valid"]}, indent=2))
        return
    if args.health_check:
        print(json.dumps(health_check_sources(), indent=2, sort_keys=True))
        return
    if args.validate:
        vc = validated_contract()
        _print_issues(vc.issues)
        print(json.dumps({"is_valid": vc.is_valid, "error_count": len(vc.errors), "issue_count": len(vc.issues)}, indent=2))
        raise SystemExit(0 if vc.is_valid else 2)
    if args.check_semantic_json:
        fresh = check_semantic_json_fresh()
        print(json.dumps(fresh, indent=2, sort_keys=True))
        raise SystemExit(0 if fresh["fresh"] else 2)

    _boot_guard()
    init_tracing()
    mcp.run()


if __name__ == "__main__":
    main()
