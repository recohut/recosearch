from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from recosearch.semantic_layers.contract import ROOT, SEMANTIC_DIR, compile_contract
from recosearch.semantic_layers.context.certify import (
    apply_context_certification_results,
    persist_context_certification_results,
    run_context_certifications,
    verify_context_certification_results,
)
# ontology.* imports are deferred into the ontology subcommands (see _require_ontology);
# they pull pyshacl/rdflib, which only ship in the optional `recosearch[ontology]` extra.
from recosearch.semantic_layers.context.export import export_context_cards, write_osi_export
from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.metrics.certify import (
    apply_certification_results,
    persist_certification_results,
    run_certifications,
    verify_certification_results,
)
from recosearch.semantic_layers.evidence.certify import (
    persist_evidence_certification_results,
    run_evidence_certifications,
    validate_evidence_registry,
    verify_evidence_certification_results,
)
from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal
from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration
from recosearch.semantic_layers.decisions.apply_proposal import approve_trust_prior_proposal, reject_trust_prior_proposal
from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger
from recosearch.semantic_layers.decisions.certify import (
    persist_decision_certification_results,
    run_decision_certifications,
    validate_decisions_registry,
    verify_decision_certification_results,
)
from recosearch.semantic_layers.decisions.loader import load_counterfactuals_from_contract
from recosearch.semantic_layers.decisions.outcomes import record_outcome
from recosearch.semantic_layers.decisions.record import DecisionRecordError, record_decision
from recosearch.semantic_layers.decisions.replay import counterfactual_replay, replay_decision
from recosearch.semantic_layers.metrics.loader import MetricKernel


def _default_metrics_dir() -> Path:
    return SEMANTIC_DIR / "metrics"


def _load_contract(semantic_dir: Path) -> dict:
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return compile_contract(semantic_dir)


def _default_context_dir() -> Path:
    return SEMANTIC_DIR / "context"


def _load_context_kernel(context_dir: Path, semantic_dir: Path) -> tuple[Any, Any, dict]:
    from recosearch.semantic_layers.metrics.loader import MetricKernel

    metric_kernel = MetricKernel.from_dir(semantic_dir / "metrics")
    context_kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    contract = _load_contract(semantic_dir)
    return context_kernel, metric_kernel, contract


def cmd_context_certify(args: argparse.Namespace) -> int:
    context_dir = Path(args.context_dir)
    semantic_dir = Path(args.semantic_dir)
    context_kernel, metric_kernel, contract = _load_context_kernel(context_dir, semantic_dir)
    results = run_context_certifications(context_kernel, metric_kernel, contract)
    persist_context_certification_results(context_dir, results)
    context_kernel = apply_context_certification_results(context_kernel, results)
    failures = verify_context_certification_results(context_kernel)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"context-certified {len(results)} term(s); wrote {context_dir / '_certification_results.yaml'}")
    return 0


def cmd_context_verify(args: argparse.Namespace) -> int:
    context_dir = Path(args.context_dir)
    semantic_dir = Path(args.semantic_dir)
    from recosearch.semantic_layers.metrics.loader import MetricKernel

    metric_kernel = MetricKernel.from_dir(semantic_dir / "metrics")
    context_kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    failures = verify_context_certification_results(context_kernel)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"verified {len(context_kernel.certifications)} context certification(s)")
    return 0


def cmd_context_export(args: argparse.Namespace) -> int:
    context_dir = Path(args.context_dir)
    semantic_dir = Path(args.semantic_dir)
    context_kernel, metric_kernel, contract = _load_context_kernel(context_dir, semantic_dir)
    payload = export_context_cards(
        context_kernel,
        metric_kernel,
        contract_hash=contract.get("contract_hash", ""),
    )
    out = write_osi_export(args.out, payload)
    print(f"exported {len(payload['context_cards'])} card(s) to {out}")
    return 0


def _default_ontology_dir() -> Path:
    return SEMANTIC_DIR / "ontology"


def _require_ontology() -> None:
    """Fail clearly if the optional ontology extra (pyshacl/rdflib) is missing."""
    try:
        import pyshacl  # noqa: F401
        import rdflib  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "ontology subcommands need the optional ontology dependencies. "
            "Install them with: pip install 'recosearch[ontology]'"
        ) from exc


def _load_ontology_stack(ontology_dir: Path, semantic_dir: Path) -> tuple[Any, Any, Any, dict]:
    from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader

    metric_kernel = MetricKernel.from_dir(semantic_dir / "metrics")
    context_kernel = ContextKernelLoader.from_dir(semantic_dir / "context", metric_kernel=metric_kernel)
    ontology_kernel = OntologyKernelLoader.from_dir(
        ontology_dir,
        context_kernel=context_kernel,
    )
    contract = _load_contract(semantic_dir)
    return ontology_kernel, context_kernel, metric_kernel, contract


def cmd_ontology_validate(args: argparse.Namespace) -> int:
    _require_ontology()
    ontology_dir = Path(args.ontology_dir)
    semantic_dir = Path(args.semantic_dir)
    ontology_kernel, context_kernel, _, _ = _load_ontology_stack(ontology_dir, semantic_dir)
    print(
        f"ontology valid: hash={ontology_kernel.ontology_hash} "
        f"mappings={len(ontology_kernel.mappings)} reasoner={ontology_kernel.reasoner_mode}"
    )
    unknown = [tid for tid in ontology_kernel.mappings if tid not in context_kernel.terms]
    if unknown:
        print(f"unknown L2 terms: {unknown}", file=sys.stderr)
        return 1
    return 0


def cmd_ontology_certify(args: argparse.Namespace) -> int:
    _require_ontology()
    from recosearch.semantic_layers.ontology.certify import (
        apply_ontology_certification_results,
        persist_ontology_certification_results,
        run_ontology_certifications,
        verify_ontology_certification_results,
    )

    ontology_dir = Path(args.ontology_dir)
    semantic_dir = Path(args.semantic_dir)
    ontology_kernel, context_kernel, _, contract = _load_ontology_stack(ontology_dir, semantic_dir)
    results = run_ontology_certifications(ontology_kernel, context_kernel, contract)
    persist_ontology_certification_results(ontology_dir, results)
    ontology_kernel = apply_ontology_certification_results(ontology_kernel, results)
    failures = verify_ontology_certification_results(ontology_kernel)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(
        f"ontology-certified {len(results)} bundle(s); "
        f"wrote {ontology_dir / '_certification_results.yaml'}"
    )
    return 0


def cmd_ontology_verify(args: argparse.Namespace) -> int:
    _require_ontology()
    from recosearch.semantic_layers.ontology.certify import verify_ontology_certification_results
    from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader

    ontology_dir = Path(args.ontology_dir)
    semantic_dir = Path(args.semantic_dir)
    metric_kernel = MetricKernel.from_dir(semantic_dir / "metrics")
    context_kernel = ContextKernelLoader.from_dir(semantic_dir / "context", metric_kernel=metric_kernel)
    ontology_kernel = OntologyKernelLoader.from_dir(
        ontology_dir,
        context_kernel=context_kernel,
    )
    failures = verify_ontology_certification_results(ontology_kernel)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"verified {len(ontology_kernel.persisted_certification_results)} ontology certification(s)")
    return 0


def cmd_ontology_export(args: argparse.Namespace) -> int:
    _require_ontology()
    from recosearch.semantic_layers.ontology.export import export_validation_report, write_ontology_export

    ontology_dir = Path(args.ontology_dir)
    semantic_dir = Path(args.semantic_dir)
    ontology_kernel, context_kernel, _, _ = _load_ontology_stack(ontology_dir, semantic_dir)
    binding = context_kernel.terms[args.term_id]
    metric_refs = [ref for ref in binding.primary_refs if ref.startswith("metric:")]
    if not metric_refs:
        print(f"term {args.term_id} has no metric ref", file=sys.stderr)
        return 1
    qualifiers = tuple(tuple(pair.split("=", 1)) for pair in args.qualifier) if args.qualifier else ()
    payload = export_validation_report(
        binding,
        metric_refs[0],
        ontology_kernel,
        claim_qualifiers=qualifiers,
    )
    out = write_ontology_export(args.out, payload)
    print(f"exported ontology validation bundle to {out}")
    return 0


def cmd_certify(args: argparse.Namespace) -> int:
    metrics_dir = Path(args.metrics_dir)
    semantic_dir = Path(args.semantic_dir)
    kernel = MetricKernel.from_dir(metrics_dir)
    contract = _load_contract(semantic_dir)
    results = run_certifications(kernel, contract)
    persist_certification_results(metrics_dir, results)
    kernel = apply_certification_results(kernel, results)
    failures = verify_certification_results(kernel)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"certified {len(results)} metric(s); wrote {metrics_dir / '_certification_results.yaml'}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    metrics_dir = Path(args.metrics_dir)
    kernel = MetricKernel.from_dir(metrics_dir)
    failures = verify_certification_results(kernel)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"verified {len(kernel.certifications)} certification(s)")
    return 0


def _default_evidence_dir() -> Path:
    return SEMANTIC_DIR / "evidence"


def cmd_evidence_certify(args: argparse.Namespace) -> int:
    evidence_dir = Path(args.evidence_dir)
    semantic_dir = Path(args.semantic_dir)
    failures = validate_evidence_registry(evidence_dir)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    contract = _load_contract(semantic_dir)
    results = run_evidence_certifications(contract, evidence_dir=evidence_dir)
    persist_evidence_certification_results(evidence_dir, results)
    verify_failures = verify_evidence_certification_results(evidence_dir, contract)
    if verify_failures:
        for failure in verify_failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"evidence-certified {len(results)} case(s); wrote {evidence_dir / '_certification_results.yaml'}")
    return 0


def cmd_evidence_verify(args: argparse.Namespace) -> int:
    evidence_dir = Path(args.evidence_dir)
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    failures = validate_evidence_registry(evidence_dir)
    failures.extend(verify_evidence_certification_results(evidence_dir, contract))
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"verified evidence certifications in {evidence_dir}")
    return 0


def _default_decisions_dir() -> Path:
    return SEMANTIC_DIR / "decisions"


def _parse_json_arg(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON payload must be an object")
    return parsed


def cmd_decision_record(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    try:
        record = record_decision(
            args.pack_id,
            actor=args.actor,
            decision_payload=_parse_json_arg(args.decision_payload),
            expected_outcome=_parse_json_arg(args.expected_outcome),
            outcome_due_date=args.outcome_due_date,
            contract=contract,
        )
    except (DecisionRecordError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(record.to_dict(), sort_keys=True))
    return 0


def cmd_decision_replay(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    try:
        result = replay_decision(
            args.decision_id,
            contract=contract,
            target_contract_hash=getattr(args, "target_contract_hash", "") or None,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


def cmd_decision_outcome(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    try:
        outcome = record_outcome(
            args.decision_id,
            actual_outcome=_parse_json_arg(args.actual_outcome),
            contract_hash=str(contract.get("contract_hash", "")),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(outcome.to_dict(), sort_keys=True))
    return 0


def cmd_decision_calibrate(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    try:
        signal = generate_calibration_signal(args.decision_id, contract=contract)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(signal.to_dict(), sort_keys=True))
    return 0


def cmd_decision_certify(args: argparse.Namespace) -> int:
    decisions_dir = Path(getattr(args, "decisions_dir", str(_default_decisions_dir())))
    semantic_dir = Path(args.semantic_dir)
    failures = validate_decisions_registry(decisions_dir)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    contract = _load_contract(semantic_dir)
    results = run_decision_certifications(contract, decisions_dir=decisions_dir)
    persist_decision_certification_results(decisions_dir, results)
    verify_failures = verify_decision_certification_results(decisions_dir, contract)
    if verify_failures:
        for failure in verify_failures:
            print(failure, file=sys.stderr)
        return 1
    print(
        f"decision-certified {len(results)} case(s); "
        f"wrote {decisions_dir / '_decision_certification_results.yaml'}"
    )
    return 0


def cmd_decision_verify(args: argparse.Namespace) -> int:
    decisions_dir = Path(getattr(args, "decisions_dir", str(_default_decisions_dir())))
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    failures = validate_decisions_registry(decisions_dir)
    failures.extend(verify_decision_certification_results(decisions_dir, contract))
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"verified decision certifications in {decisions_dir}")
    return 0


def cmd_decision_aggregate(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    try:
        report = aggregate_calibration(
            contract=contract,
            decision_class=getattr(args, "decision_class", None) or None,
            term=getattr(args, "term", None) or None,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0


def cmd_decision_counterfactual(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    scenario = str(getattr(args, "scenario", "") or "")
    try:
        if scenario:
            scenarios = load_counterfactuals_from_contract(contract)
            if scenario not in scenarios:
                raise ValueError(f"unknown counterfactual scenario: {scenario}")
            cf = counterfactual_replay(
                args.decision_id,
                contract=contract,
                overrides=scenarios[scenario].overlay,
                scenario_label=scenarios[scenario].label,
            )
        else:
            overrides = _parse_json_arg(getattr(args, "overrides", "{}"))
            cf = counterfactual_replay(
                args.decision_id,
                contract=contract,
                overrides=overrides,
                scenario_label=str(getattr(args, "scenario_label", "custom")),
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(cf.to_dict(), sort_keys=True))
    return 0


def cmd_decision_propose(args: argparse.Namespace) -> int:
    semantic_dir = Path(args.semantic_dir)
    contract = _load_contract(semantic_dir)
    try:
        proposal = propose_trust_prior_from_ledger(
            contract=contract,
            decision_class=getattr(args, "decision_class", None) or None,
            term=getattr(args, "term", None) or None,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if proposal is None:
        print("null")
        return 0
    print(json.dumps(proposal.to_dict(), sort_keys=True))
    return 0


def cmd_proposal_approve(args: argparse.Namespace) -> int:
    context_dir = Path(getattr(args, "context_dir", str(_default_context_dir())))
    try:
        path = approve_trust_prior_proposal(
            args.proposal_id,
            context_dir=context_dir,
            operator=str(getattr(args, "operator", "cert-operator")),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(str(path))
    return 0


def cmd_proposal_reject(args: argparse.Namespace) -> int:
    try:
        proposal = reject_trust_prior_proposal(
            args.proposal_id,
            operator=str(getattr(args, "operator", "cert-operator")),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(proposal.to_dict(), sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recosearch-certify")
    subparsers = parser.add_subparsers(dest="command", required=True)

    certify_parser = subparsers.add_parser("certify", help="run golden certifications and persist results")
    certify_parser.add_argument("--metrics-dir", default=str(_default_metrics_dir()))
    certify_parser.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    certify_parser.set_defaults(func=cmd_certify)

    verify_parser = subparsers.add_parser("verify", help="verify persisted certification results")
    verify_parser.add_argument("--metrics-dir", default=str(_default_metrics_dir()))
    verify_parser.set_defaults(func=cmd_verify)

    ctx_certify = subparsers.add_parser("context-certify", help="run context golden certifications")
    ctx_certify.add_argument("--context-dir", default=str(_default_context_dir()))
    ctx_certify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    ctx_certify.set_defaults(func=cmd_context_certify)

    ctx_verify = subparsers.add_parser("context-verify", help="verify persisted context certifications")
    ctx_verify.add_argument("--context-dir", default=str(_default_context_dir()))
    ctx_verify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    ctx_verify.set_defaults(func=cmd_context_verify)

    ctx_export = subparsers.add_parser("context-export", help="export OSI interchange JSON")
    ctx_export.add_argument("--context-dir", default=str(_default_context_dir()))
    ctx_export.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    ctx_export.add_argument("--out", required=True)
    ctx_export.set_defaults(func=cmd_context_export)

    onto_validate = subparsers.add_parser("ontology-validate", help="validate ontology registry")
    onto_validate.add_argument("--ontology-dir", default=str(_default_ontology_dir()))
    onto_validate.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    onto_validate.set_defaults(func=cmd_ontology_validate)

    onto_certify = subparsers.add_parser("ontology-certify", help="run ontology golden certifications")
    onto_certify.add_argument("--ontology-dir", default=str(_default_ontology_dir()))
    onto_certify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    onto_certify.set_defaults(func=cmd_ontology_certify)

    onto_verify = subparsers.add_parser("ontology-verify", help="verify persisted ontology certifications")
    onto_verify.add_argument("--ontology-dir", default=str(_default_ontology_dir()))
    onto_verify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    onto_verify.set_defaults(func=cmd_ontology_verify)

    onto_export = subparsers.add_parser("ontology-export", help="export RDF/SHACL validation bundle")
    onto_export.add_argument("--ontology-dir", default=str(_default_ontology_dir()))
    onto_export.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    onto_export.add_argument("--term-id", default="term:novashop:revenue")
    onto_export.add_argument("--qualifier", action="append", default=[])
    onto_export.add_argument("--out", required=True)
    onto_export.set_defaults(func=cmd_ontology_export)

    ev_certify = subparsers.add_parser("evidence-certify", help="run evidence pack golden certifications")
    ev_certify.add_argument("--evidence-dir", default=str(_default_evidence_dir()))
    ev_certify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    ev_certify.set_defaults(func=cmd_evidence_certify)

    ev_verify = subparsers.add_parser("evidence-verify", help="verify persisted evidence certifications")
    ev_verify.add_argument("--evidence-dir", default=str(_default_evidence_dir()))
    ev_verify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    ev_verify.set_defaults(func=cmd_evidence_verify)

    dec_record = subparsers.add_parser("decision-record", help="record a governed decision against an evidence pack")
    dec_record.add_argument("pack_id")
    dec_record.add_argument("--actor", default="controller")
    dec_record.add_argument("--decision-payload", required=True)
    dec_record.add_argument("--expected-outcome", required=True)
    dec_record.add_argument("--outcome-due-date", required=True)
    dec_record.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_record.set_defaults(func=cmd_decision_record)

    dec_replay = subparsers.add_parser("decision-replay", help="replay a decision under current or target contract")
    dec_replay.add_argument("decision_id")
    dec_replay.add_argument("--target-contract-hash", default="")
    dec_replay.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_replay.set_defaults(func=cmd_decision_replay)

    dec_outcome = subparsers.add_parser("decision-outcome", help="record realized outcome for a decision")
    dec_outcome.add_argument("decision_id")
    dec_outcome.add_argument("--actual-outcome", required=True)
    dec_outcome.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_outcome.set_defaults(func=cmd_decision_outcome)

    dec_calibrate = subparsers.add_parser("decision-calibrate", help="generate advisory calibration signal")
    dec_calibrate.add_argument("decision_id")
    dec_calibrate.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_calibrate.set_defaults(func=cmd_decision_calibrate)

    dec_certify = subparsers.add_parser("decision-certify", help="run decision golden certifications")
    dec_certify.add_argument("--decisions-dir", default=str(_default_decisions_dir()))
    dec_certify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_certify.set_defaults(func=cmd_decision_certify)

    dec_verify = subparsers.add_parser("decision-verify", help="verify persisted decision certifications")
    dec_verify.add_argument("--decisions-dir", default=str(_default_decisions_dir()))
    dec_verify.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_verify.set_defaults(func=cmd_decision_verify)

    dec_aggregate = subparsers.add_parser("decision-aggregate", help="aggregate calibration signals into Wilson CI report")
    dec_aggregate.add_argument("--decision-class", default="")
    dec_aggregate.add_argument("--term", default="")
    dec_aggregate.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_aggregate.set_defaults(func=cmd_decision_aggregate)

    dec_counterfactual = subparsers.add_parser("decision-counterfactual", help="counterfactual replay with contract overlay")
    dec_counterfactual.add_argument("decision_id")
    dec_counterfactual.add_argument("--scenario", default="")
    dec_counterfactual.add_argument("--scenario-label", default="custom")
    dec_counterfactual.add_argument("--overrides", default="{}")
    dec_counterfactual.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_counterfactual.set_defaults(func=cmd_decision_counterfactual)

    dec_propose = subparsers.add_parser("decision-propose", help="propose gated trust-prior update from calibration aggregate")
    dec_propose.add_argument("--decision-class", default="")
    dec_propose.add_argument("--term", default="")
    dec_propose.add_argument("--semantic-dir", default=str(SEMANTIC_DIR))
    dec_propose.set_defaults(func=cmd_decision_propose)

    proposal_approve = subparsers.add_parser("proposal-approve", help="approve trust-prior proposal into L2 override file")
    proposal_approve.add_argument("proposal_id")
    proposal_approve.add_argument("--context-dir", default=str(_default_context_dir()))
    proposal_approve.add_argument("--operator", default="cert-operator")
    proposal_approve.set_defaults(func=cmd_proposal_approve)

    proposal_reject = subparsers.add_parser("proposal-reject", help="reject trust-prior proposal (no L2 mutation)")
    proposal_reject.add_argument("proposal_id")
    proposal_reject.add_argument("--operator", default="cert-operator")
    proposal_reject.set_defaults(func=cmd_proposal_reject)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
