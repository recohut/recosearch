"""MCP tool handlers for governed metric queries."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from recosearch.semantic_layers import identity
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics import MetricKernel, MetricQuery
from recosearch.semantic_layers.context import ContextKernelLoader, ContextQuery, ContextResolver
from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.pipeline import execute_metric_query


def handle_metric_query(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    actor: identity.Actor | None = None,
) -> dict[str, Any]:
    contract = contract or compile_contract()
    query = MetricQuery(
        term=str(params.get("term", "")),
        dimensions=tuple(params.get("dimensions", ())),
        filters=tuple(tuple(item) for item in params.get("filters", ())),
        tenant=str(params.get("tenant", "default")),
        industry=params.get("industry"),
        time_grain=params.get("time_grain"),
        time_period=params.get("time_period"),
        reference_date=_parse_date(params.get("reference_date")),
    )
    answer = execute_metric_query(
        query,
        contract=contract,
        actor=actor or identity.resolve(role=str(params.get("actor_role", identity.resolve().role))),
        scoped_question=str(params.get("scoped_question", "")),
    )
    return answer.to_dict()


def handle_list_metrics(*, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or compile_contract()
    kernel = MetricKernel.from_contract(contract)
    metrics = []
    for metric in sorted(kernel.metrics.values(), key=lambda item: item.metric_id):
        metrics.append(
            {
                "metric_id": metric.metric_id,
                "display_name": metric.display_name,
                "collection_id": metric.collection_id,
                "kind": metric.kind,
                "grain": metric.grain,
                "status": metric.status,
                "version": metric.version,
                "synonyms": list(metric.synonyms),
            }
        )
    return {"metrics": metrics}


def handle_describe_metric(
    metric_id: str,
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or compile_contract()
    kernel = MetricKernel.from_contract(contract)
    if metric_id not in kernel.metrics:
        return {"error": f"unknown metric: {metric_id}"}
    metric = kernel.metrics[metric_id]
    cert = kernel.certifications.get(metric_id)
    return {
        "metric_id": metric.metric_id,
        "display_name": metric.display_name,
        "collection_id": metric.collection_id,
        "kind": metric.kind,
        "grain": metric.grain,
        "status": metric.status,
        "version": metric.version,
        "definition_hash": metric.definition_hash,
        "measure_id": metric.measure_id,
        "formula": metric.formula,
        "filter_rules": list(metric.filter_rules),
        "allowed_dimension_ids": list(metric.allowed_dimension_ids),
        "synonyms": list(metric.synonyms),
        "owners": list(metric.owners),
        "certification": (
            {
                "definition_hash": cert.definition_hash,
                "certified": cert.certified,
                "golden_passed": cert.golden_passed,
            }
            if cert is not None
            else None
        ),
        "freshness_sla": (
            {
                "max_age_days": metric.freshness_sla.max_age_days,
                "hard_sla": metric.freshness_sla.hard_sla,
            }
            if metric.freshness_sla is not None
            else None
        ),
    }


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def handle_resolve_context(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    actor: identity.Actor | None = None,
) -> dict[str, Any]:
    contract = contract or compile_contract()
    actor = actor or identity.resolve(role=str(params.get("actor_role", identity.resolve().role)))
    metric_kernel = MetricKernel.from_contract(contract)
    context_kernel = ContextKernelLoader.from_contract(contract, metric_kernel=metric_kernel)
    query = ContextQuery(
        term=str(params.get("term", "")),
        tenant=str(params.get("tenant", "default")),
        industry=params.get("industry"),
        actor_role=actor.role,
    )
    resolution = ContextResolver(context_kernel, metric_kernel).resolve(query)
    out = resolution.to_dict()
    if resolution.binding is not None:
        card = build_context_card(
            resolution.binding,
            context_kernel,
            metric_kernel,
            actor_role=actor.role,
            contract_hash=contract.get("contract_hash", ""),
        )
        out["card"] = card.to_dict()
    return out


def handle_describe_context(
    term_or_id: str,
    *,
    tenant: str = "default",
    industry: str | None = None,
    contract: dict[str, Any] | None = None,
    actor: identity.Actor | None = None,
) -> dict[str, Any]:
    return handle_resolve_context(
        {"term": term_or_id, "tenant": tenant, "industry": industry},
        contract=contract,
        actor=actor,
    )


def handle_list_terms(
    *,
    tenant: str = "default",
    industry: str | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or compile_contract()
    metric_kernel = MetricKernel.from_contract(contract)
    context_kernel = ContextKernelLoader.from_contract(contract, metric_kernel=metric_kernel)
    query = ContextQuery(term="", tenant=tenant, industry=industry)
    applicable_collections = ContextResolver(context_kernel, metric_kernel)._applicable_collections(query)
    collection_ids = {c.collection_id for c in applicable_collections}
    terms = []
    for term in sorted(context_kernel.terms.values(), key=lambda t: t.term_id):
        if term.collection_id in collection_ids:
            terms.append(
                {
                    "term_id": term.term_id,
                    "display_name": term.display_name,
                    "collection_id": term.collection_id,
                    "aliases": list(term.aliases),
                }
            )
    return {"terms": terms}


def handle_validate_claim(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader
    from recosearch.semantic_layers.ontology.validate import validate_claim

    contract = contract or compile_contract()
    if "ontology_kernel" not in contract:
        return {"error": "ontology kernel not loaded in contract"}

    metric_kernel = MetricKernel.from_contract(contract)
    context_kernel = ContextKernelLoader.from_contract(contract, metric_kernel=metric_kernel)
    ontology_kernel = OntologyKernelLoader.from_contract(
        contract, context_kernel=context_kernel
    )

    term_id = str(params.get("term_id", ""))
    if not term_id:
        term = str(params.get("term", ""))
        resolution = ContextResolver(context_kernel, metric_kernel).resolve(
            ContextQuery(term=term, tenant=str(params.get("tenant", "default")))
        )
        if resolution.binding is None:
            return {"error": f"could not resolve term: {term}"}
        binding = resolution.binding
    else:
        if term_id not in context_kernel.terms:
            return {"error": f"unknown term_id: {term_id}"}
        binding = context_kernel.terms[term_id]

    metric_id = str(params.get("metric_id", ""))
    if not metric_id:
        metric_refs = [ref for ref in binding.primary_refs if ref.startswith("metric:")]
        if not metric_refs:
            return {"error": f"term {binding.term_id} has no metric ref"}
        metric_id = metric_refs[0]

    qualifiers = tuple(
        (str(k), str(v)) for k, v in params.get("claim_qualifiers", {}).items()
    )
    decision = validate_claim(
        binding,
        metric_id,
        ontology_kernel,
        claim_qualifiers=qualifiers,
        reference_date=_parse_date(params.get("reference_date")),
    )
    return decision.to_dict()


def handle_describe_constraints(
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader

    contract = contract or compile_contract()
    if "ontology_kernel" not in contract:
        return {"error": "ontology kernel not loaded in contract"}

    metric_kernel = MetricKernel.from_contract(contract)
    context_kernel = ContextKernelLoader.from_contract(contract, metric_kernel=metric_kernel)
    ontology_kernel = OntologyKernelLoader.from_contract(
        contract, context_kernel=context_kernel
    )
    return {
        "ontology_hash": ontology_kernel.ontology_hash,
        "reasoner_mode": ontology_kernel.reasoner_mode,
        "namespace": ontology_kernel.namespace,
        "mappings": {
            term_id: {
                "revenue_type": mapping.revenue_type,
                "claim_class": mapping.claim_class,
            }
            for term_id, mapping in ontology_kernel.mappings.items()
        },
        "shapes": handle_list_shapes(contract=contract).get("shapes", []),
    }


def handle_list_shapes(
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from rdflib import Graph
    from rdflib.namespace import RDF, SH

    contract = contract or compile_contract()
    raw = contract.get("ontology_kernel")
    if raw is None:
        return {"shapes": []}

    shapes_graph = Graph()
    shapes_graph.parse(data=str(raw["shapes_ttl"]), format="turtle")
    shapes: list[dict[str, str]] = []
    for shape in shapes_graph.subjects(RDF.type, SH.NodeShape):
        shapes.append({"shape_id": str(shape), "kind": "NodeShape"})
    return {"shapes": shapes}


def _parse_subclaim(item: dict[str, Any]) -> Subclaim:
    from recosearch.semantic_layers.evidence.types import Subclaim

    qualifiers = tuple(tuple(q) for q in item.get("claim_qualifiers", ()))
    return Subclaim(
        term=str(item.get("term", "")),
        tenant=str(item.get("tenant", "novashop")),
        industry=item.get("industry"),
        actor_role=str(item.get("actor_role", "analyst")),
        claim_qualifiers=qualifiers,
        comparable_group=str(item.get("comparable_group", "")),
        reference_date=str(item.get("reference_date", "")),
        time_period=str(item.get("time_period", "")),
        scoped_question=str(item.get("scoped_question", "")),
    )


def handle_compose_evidence_pack(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.evidence.compose import compose_evidence_pack
    from recosearch.semantic_layers.evidence.types import ClaimSet

    contract = contract or compile_contract()
    subclaims = tuple(_parse_subclaim(item) for item in params.get("subclaims", ()))
    claim_set = ClaimSet(
        subclaims=subclaims,
        pack_label=str(params.get("pack_label", "board_pack")),
        min_tier_label=str(params.get("min_tier_label", "")),
    )
    pack, answer = compose_evidence_pack(claim_set, contract=contract)
    return {"pack": pack.to_dict(), "answer": answer.to_dict()}


def handle_record_decision(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.record import record_decision

    contract = contract or compile_contract()
    record = record_decision(
        str(params["pack_id"]),
        actor=str(params.get("actor", "controller")),
        decision_payload=dict(params.get("decision_payload", {}) or {}),
        expected_outcome=dict(params.get("expected_outcome", {}) or {}),
        outcome_due_date=str(params.get("outcome_due_date", "")),
        contract=contract,
    )
    return {"decision": record.to_dict()}


def handle_replay_decision(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.replay import replay_decision

    contract = contract or compile_contract()
    result = replay_decision(
        str(params["decision_id"]),
        contract=contract,
        target_contract_hash=params.get("target_contract_hash"),
    )
    return {"replay": result.to_dict()}


def handle_record_outcome(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.outcomes import record_outcome

    contract = contract or compile_contract()
    outcome = record_outcome(
        str(params["decision_id"]),
        actual_outcome=dict(params.get("actual_outcome", {}) or {}),
        contract_hash=str(contract.get("contract_hash", "")),
    )
    return {"outcome": outcome.to_dict()}


def handle_generate_calibration_signal(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.calibrate import generate_calibration_signal

    contract = contract or compile_contract()
    signal = generate_calibration_signal(str(params["decision_id"]), contract=contract)
    return {"calibration_signal": signal.to_dict()}


def handle_aggregate_calibration(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.aggregate import aggregate_calibration

    contract = contract or compile_contract()
    report = aggregate_calibration(
        contract=contract,
        decision_class=params.get("decision_class"),
        term=params.get("term"),
    )
    return {"calibration_report": report.to_dict()}


def handle_counterfactual_replay(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.loader import load_counterfactuals_from_contract
    from recosearch.semantic_layers.decisions.replay import counterfactual_replay

    contract = contract or compile_contract()
    scenario = str(params.get("scenario", "") or "")
    if scenario:
        scenarios = load_counterfactuals_from_contract(contract)
        if scenario not in scenarios:
            raise ValueError(f"unknown counterfactual scenario: {scenario}")
        item = scenarios[scenario]
        result = counterfactual_replay(
            str(params["decision_id"]),
            contract=contract,
            overrides=item.overlay,
            scenario_label=item.label,
        )
    else:
        result = counterfactual_replay(
            str(params["decision_id"]),
            contract=contract,
            overrides=dict(params.get("overrides") or {}),
            scenario_label=str(params.get("scenario_label", "custom")),
        )
    return {"counterfactual_result": result.to_dict()}


def handle_propose_trust_prior(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.propose import propose_trust_prior_from_ledger

    contract = contract or compile_contract()
    proposal = propose_trust_prior_from_ledger(
        contract=contract,
        decision_class=params.get("decision_class"),
        term=params.get("term"),
    )
    return {"trust_prior_proposal": proposal.to_dict() if proposal else None}


def handle_approve_trust_prior_proposal(
    params: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from recosearch.semantic_layers.contract import ROOT
    from recosearch.semantic_layers.decisions.apply_proposal import approve_trust_prior_proposal

    context_dir = Path(str(params.get("context_dir", ROOT / "semantic" / "context")))
    path = approve_trust_prior_proposal(
        str(params["proposal_id"]),
        context_dir=context_dir,
        operator=str(params.get("operator", "cert-operator")),
    )
    return {"trust_overrides_path": str(path)}


def handle_reject_trust_prior_proposal(params: dict[str, Any]) -> dict[str, Any]:
    from recosearch.semantic_layers.decisions.apply_proposal import reject_trust_prior_proposal

    proposal = reject_trust_prior_proposal(
        str(params["proposal_id"]),
        operator=str(params.get("operator", "cert-operator")),
    )
    return {"trust_prior_proposal": proposal.to_dict()}
