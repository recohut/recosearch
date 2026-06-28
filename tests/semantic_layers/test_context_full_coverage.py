"""Branch coverage for recosearch/context/* gaps not hit by integration tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.context.catalog import FileCatalogAdapter, apply_catalog_ingest
from recosearch.semantic_layers.context.certify import (
    _ares_confidence_interval,
    _contract_for_certification,
    verify_context_certification_results,
)
from recosearch.semantic_layers.context.eval import pass_k
from recosearch.semantic_layers.context.events import EventBus, MetadataChanged, get_event_bus, subscribe_re_cert
from recosearch.semantic_layers.context.export import validate_osi_export, write_osi_export
from recosearch.semantic_layers.context.facets import _schema_for_refs, build_provenance_facets, discover_join_path_refs
from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.context.probe import probe_term_local
from recosearch.semantic_layers.context.resolve import ContextResolver
from recosearch.semantic_layers.context.trust import _map_evidence_tier, apply_runtime_trust, build_trust_signal
from recosearch.semantic_layers.context.types import (
    ClaimScope,
    ContextCard,
    ContextCertification,
    ContextKernel,
    ContextQuery,
    ContextResolution,
    TermBinding,
    TrustSignal,
)
from recosearch.semantic_layers.envelope import Answer
from recosearch.semantic_layers.metrics.freshness import FreshnessSLA
from recosearch.semantic_layers.metrics.loader import MetricKernel
from recosearch.semantic_layers.metrics.types import Certification, Entity

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def _kernels():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    return metric_kernel, context_kernel


# --- cards.py ---


def test_freshness_sla_included_on_card():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    metrics = dict(metric_kernel.metrics)
    m = metrics["metric:novashop:order_revenue"]
    metrics["metric:novashop:order_revenue"] = replace(
        m, freshness_sla=FreshnessSLA(max_age_days=7, hard_sla=True)
    )
    patched = replace(metric_kernel, metrics=MappingProxyType(metrics))
    card = build_context_card(binding, context_kernel, patched, actor_role="analyst")
    sla = card.operational["freshness_sla"]
    assert sla == [
        {"metric_id": "metric:novashop:order_revenue", "max_age_days": 7, "hard_sla": True}
    ]


# --- catalog/__init__.py ---


def test_catalog_skips_non_dict_entities(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "entities": [
                    "not-a-dict",
                    {
                        "urn": "urn:li:dataset:(urn:li:dataPlatform:db,orders,PROD)",
                        "glossaryTerm": "term:novashop:revenue",
                        "related": ["catalog:novashop:extra"],
                        "owner": "team@example.com",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    adapter = FileCatalogAdapter(catalog_path)
    merged = adapter.merge_related_refs("term:novashop:revenue", ())
    assert "catalog:novashop:extra" in merged
    assert "owner:team@example.com" in merged


def test_catalog_ingest_skips_existing_edges():
    metric_kernel, context_kernel = _kernels()
    adapter = FileCatalogAdapter(ROOT / "examples" / "catalog" / "novashop_export.json")
    once = apply_catalog_ingest(context_kernel, adapter)
    twice = apply_catalog_ingest(once, adapter)
    assert len(twice.relationships) == len(once.relationships)
    binding = context_kernel.terms["term:novashop:revenue"]
    authored = tuple(
        edge.to_id
        for edge in once.relationships
        if edge.from_id == binding.term_id
    )
    merged = adapter.merge_related_refs(binding.term_id, authored)
    assert all(ref in authored for ref in merged)


# --- certify.py ---


def test_contract_for_certification_non_dict_kernel():
    raw = {"context_kernel": "not-a-mapping", "other": 1}
    assert _contract_for_certification(raw) == raw


def test_ares_confidence_interval_zero_total():
    assert _ares_confidence_interval(0, 0) == (0.0, 0.0)


def test_verify_policy_hash_mismatch(monkeypatch):
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    cert = context_kernel.certifications["term:novashop:revenue"]
    monkeypatch.setattr("recosearch.semantic_layers.policy.compute_policy_hash", lambda: "current_policy_hash")
    stale = ContextCertification(
        term_id=cert.term_id,
        definition_hash=binding.definition_hash,
        policy_hash="stale_policy_hash",
        golden_questions=cert.golden_questions,
        certified=True,
        golden_passed=True,
    )
    kernel = ContextKernel(
        terms=context_kernel.terms,
        guidance=context_kernel.guidance,
        relationships=context_kernel.relationships,
        alias_index=context_kernel.alias_index,
        certifications={"term:novashop:revenue": stale},
    )
    failures = verify_context_certification_results(kernel)
    assert any("policy changed" in f for f in failures)


# --- eval.py ---


def test_pass_k_empty_or_invalid_k():
    assert pass_k([], {}) == 0.0
    assert pass_k([{"term": "x", "expected_decision": "answer"}], {}, k=0) == 0.0


# --- events.py ---


def test_publish_unknown_event_kind_raises():
    bus = EventBus()
    with pytest.raises(ValueError, match="unknown event kind"):
        bus.publish(MetadataChanged(kind="not-real", ref="ref"))


def test_subscribe_re_cert_on_global_bus():
    bus = get_event_bus()
    bus.clear()
    seen: list[str] = []

    def handler(event: MetadataChanged) -> None:
        seen.append(event.kind)

    subscribe_re_cert(handler)
    bus.publish(MetadataChanged(kind="catalog-update", ref="term:novashop:revenue"))
    assert seen == ["catalog-update"]
    bus.clear()


# --- export.py ---


def test_validate_osi_export_errors():
    assert "invalid osi_version" in validate_osi_export({"osi_version": "0.0.0"})[0]
    assert "missing glossary or context_cards" in validate_osi_export({"osi_version": "1.0.0"})[0]


def test_write_osi_export(tmp_path):
    metric_kernel, context_kernel = _kernels()
    from recosearch.semantic_layers.context.export import export_context_cards

    payload = export_context_cards(context_kernel, metric_kernel)
    out = write_osi_export(tmp_path / "export.json", payload)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["osi_version"] == "1.0.0"


# --- facets.py ---


def test_schema_for_dimension_ref():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    schemas = _schema_for_refs(metric_kernel, ("dimension:novashop:order_status",))
    assert schemas
    assert schemas[0]["table"]


def test_discover_join_path_skips_unreachable_entities():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    entities = dict(metric_kernel.entities)
    entities["entity:novashop:isolated"] = Entity(
        entity_id="entity:novashop:isolated",
        source_id="novashop",
        table="isolated",
        primary_key="id",
        time_field="",
    )
    patched = replace(metric_kernel, entities=MappingProxyType(entities))
    binding = TermBinding(
        term_id="term:test:one",
        display_name="one",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("entity:novashop:order",),
    )
    refs = discover_join_path_refs(binding, patched, ())
    assert "entity:novashop:isolated" not in refs


# --- loader.py ---


def test_relationship_unknown_from_id_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
relationships:
  - from_id: term:missing:one
    to_id: novashop
    kind: related
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown term"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_duplicate_certification_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "dup.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [novashop]
certifications:
  - term_id: term:test:one
    definition_hash: abc
    golden_questions:
      - term: one
        expected_decision: clarify
        expected_trust_status: trusted
  - term_id: term:test:one
    definition_hash: def
    golden_questions:
      - term: one
        expected_decision: clarify
        expected_trust_status: trusted
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="duplicate certification"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_persisted_certification_non_dict_entry_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "term.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [novashop]
"""
    )
    (context_dir / "_certification_results.yaml").write_text(
        "certification_results:\n  - not-a-mapping\n",
        encoding="utf-8",
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="must be mappings"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_with_certification_results_skips_unknown_term():
    metric_kernel, context_kernel = _kernels()
    patched = ContextKernelLoader.with_certification_results(
        context_kernel,
        {"term:does:not:exist": {"certified": True, "golden_passed": True}},
    )
    assert patched.certifications == context_kernel.certifications


# --- probe.py ---


def test_probe_unknown_metric_ref():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    binding = TermBinding(
        term_id="term:novashop:revenue",
        display_name="revenue",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("metric:novashop:missing_metric",),
    )
    result = probe_term_local(binding, metric_kernel, {})
    assert result == {"passed": False, "reason": "unknown_metric"}


def test_probe_non_answer_decision():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    fake_answer = Answer(decision="clarify", contract_version="v1", evidence_tier="contract-only")
    with patch("recosearch.semantic_layers.context.probe.execute_metric_query", return_value=fake_answer):
        result = probe_term_local(binding, metric_kernel, {})
    assert result["passed"] is False
    assert result["reason"] == "decision_clarify"


# --- resolve.py ---


def test_resolve_industry_scoped_collection(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "retail.yaml").write_text(
        """
terms:
  - id: term:retail:revenue
    display_name: retail revenue
    definition: retail scoped revenue
    collection_id: retail_industry
    primary_refs: [metric:global:revenue]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(tmp_path, metric_kernel=metric_kernel)
    resolver = ContextResolver(context_kernel, metric_kernel)
    resolution = resolver.resolve(
        ContextQuery(term="retail revenue", tenant="other", industry="retail")
    )
    assert resolution.decision == "resolved"
    assert resolution.term_id == "term:retail:revenue"


# --- trust.py ---


def test_map_evidence_tier_golden_passed_only_context_cert():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    cert = ContextCertification(
        term_id="term:t",
        definition_hash="abc",
        policy_hash="",
        golden_questions=(),
        certified=False,
        golden_passed=True,
        evidence_tier=2,
    )
    tier, label, labels = _map_evidence_tier(
        metric_kernel,
        ["metric:novashop:order_revenue"],
        context_cert=cert,
    )
    assert tier >= 2
    assert "fixture-backed" in labels


def test_map_evidence_tier_metric_golden_passed_not_certified():
    metric_kernel, _ = _kernels()
    metrics = dict(metric_kernel.metrics)
    cert_id = "metric:novashop:order_revenue"
    certs = dict(metric_kernel.certifications)
    certs[cert_id] = Certification(
        metric_id=cert_id,
        definition_hash=metrics[cert_id].definition_hash,
        golden_questions=(),
        certified=False,
        golden_passed=True,
    )
    patched = replace(
        metric_kernel,
        metrics=MappingProxyType(metrics),
        certifications=MappingProxyType(certs),
    )
    tier, _, labels = _map_evidence_tier(patched, [cert_id])
    assert tier >= 2
    assert "fixture-backed" in labels


def test_drift_context_cert_definition_hash_mismatch():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    cert = context_kernel.certifications["term:novashop:revenue"]
    stale = ContextCertification(
        term_id=cert.term_id,
        definition_hash="stale_hash",
        policy_hash=cert.policy_hash,
        golden_questions=cert.golden_questions,
        certified=True,
        golden_passed=True,
    )
    stale_kernel = ContextKernel(
        terms=context_kernel.terms,
        guidance=context_kernel.guidance,
        relationships=context_kernel.relationships,
        alias_index=context_kernel.alias_index,
        certifications={"term:novashop:revenue": stale},
    )
    trust = build_trust_signal(
        binding,
        metric_kernel,
        context_kernel=stale_kernel,
        actor_role="analyst",
    )
    assert "definition_hash_mismatch" in trust.expiry_reasons


def test_drift_context_cert_golden_failed():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    cert = context_kernel.certifications["term:novashop:revenue"]
    failed = ContextCertification(
        term_id=cert.term_id,
        definition_hash=binding.definition_hash,
        policy_hash=cert.policy_hash,
        golden_questions=cert.golden_questions,
        certified=True,
        golden_passed=False,
    )
    failed_kernel = ContextKernel(
        terms=context_kernel.terms,
        guidance=context_kernel.guidance,
        relationships=context_kernel.relationships,
        alias_index=context_kernel.alias_index,
        certifications={"term:novashop:revenue": failed},
    )
    trust = build_trust_signal(
        binding,
        metric_kernel,
        context_kernel=failed_kernel,
        actor_role="analyst",
    )
    assert "failed_certification" in trust.expiry_reasons


def test_drift_context_cert_not_certified():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    cert = context_kernel.certifications["term:novashop:revenue"]
    uncert = ContextCertification(
        term_id=cert.term_id,
        definition_hash=binding.definition_hash,
        policy_hash=cert.policy_hash,
        golden_questions=cert.golden_questions,
        certified=False,
        golden_passed=True,
    )
    uncert_kernel = ContextKernel(
        terms=context_kernel.terms,
        guidance=context_kernel.guidance,
        relationships=context_kernel.relationships,
        alias_index=context_kernel.alias_index,
        certifications={"term:novashop:revenue": uncert},
    )
    trust = build_trust_signal(
        binding,
        metric_kernel,
        context_kernel=uncert_kernel,
        actor_role="analyst",
    )
    assert "failed_certification" in trust.expiry_reasons


def test_drift_skips_unknown_metric():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    binding = TermBinding(
        term_id="term:t",
        display_name="t",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("metric:novashop:ghost",),
    )
    trust = build_trust_signal(binding, metric_kernel, actor_role="analyst")
    assert trust.drift_status in ("current", "at_risk", "expired")


def test_drift_missing_certification():
    metric_kernel, _ = _kernels()
    metrics = dict(metric_kernel.metrics)
    m = metrics["metric:novashop:order_revenue"]
    metrics["metric:novashop:order_revenue"] = replace(m, status="certified")
    certs = dict(metric_kernel.certifications)
    certs.pop("metric:novashop:order_revenue", None)
    patched = replace(
        metric_kernel,
        metrics=MappingProxyType(metrics),
        certifications=MappingProxyType(certs),
    )
    binding = TermBinding(
        term_id="term:t",
        display_name="t",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("metric:novashop:order_revenue",),
    )
    trust = build_trust_signal(binding, patched, actor_role="analyst")
    assert "missing_certification" in trust.expiry_reasons


def test_drift_missing_lineage():
    metric_kernel, _ = _kernels()
    metrics = dict(metric_kernel.metrics)
    m = metrics["metric:novashop:order_revenue"]
    metrics["metric:novashop:order_revenue"] = replace(m, status="certified")
    patched = replace(metric_kernel, metrics=MappingProxyType(metrics))
    binding = TermBinding(
        term_id="term:t",
        display_name="t",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("metric:novashop:order_revenue",),
    )
    with patch(
        "recosearch.semantic_layers.context.trust._lineage_for_refs",
        return_value=[],
    ):
        trust = build_trust_signal(binding, patched, actor_role="analyst")
    assert "missing_lineage" in trust.expiry_reasons


def test_apply_runtime_trust_without_context_kernel_term():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    card = build_context_card(binding, context_kernel, metric_kernel, actor_role="analyst")
    answer = Answer(
        decision="answer",
        contract_version="abc",
        evidence_tier="fixture-backed",
        actor_role="analyst",
    )
    updated = apply_runtime_trust(card, answer, metric_kernel, context_kernel=None)
    assert updated.trust.status in ("trusted", "usable_with_caveats", "not_usable")


# --- types.py ---


def test_context_resolution_to_dict_with_candidates_and_card():
    binding = TermBinding(
        term_id="term:a",
        display_name="A",
        definition="d",
        aliases=(),
        collection_id="c",
        primary_refs=(),
    )
    trust = TrustSignal(
        signal_id="trust-x",
        status="trusted",
        evidence_tier=2,
        evidence_label="fixture-backed",
        claim_scope=ClaimScope(sources=(), roles=("*",), metrics=()),
        drift_status="current",
        expiry_reasons=(),
        no_overclaim_labels=(),
        reasons=(),
    )
    card = ContextCard(
        card_id="ctx-1",
        term_id="term:a",
        display_name="A",
        definition="d",
        primary_refs=(),
        related_refs=(),
        technical={},
        semantic={},
        operational={},
        relationships={},
        trust=trust,
        client_guidance={},
        caveats=(),
    )
    resolution = ContextResolution(
        decision="clarify",
        term_id="",
        reason="ambiguous",
        candidates=(("term:a", "A"), ("term:b", "B")),
        card=card,
    )
    payload = resolution.to_dict()
    assert payload["candidates"] == [
        {"term_id": "term:a", "display_name": "A"},
        {"term_id": "term:b", "display_name": "B"},
    ]
    assert payload["card"]["card_id"] == "ctx-1"


def test_context_kernel_post_init_wraps_plain_dicts():
    binding = TermBinding(
        term_id="term:a",
        display_name="A",
        definition="d",
        aliases=(),
        collection_id="c",
        primary_refs=(),
    )
    cert = ContextCertification(
        term_id="term:a",
        definition_hash="h",
        policy_hash="p",
        golden_questions=(),
    )
    kernel = ContextKernel(
        terms={"term:a": binding},
        guidance={},
        relationships=(),
        alias_index={},
        certifications={"term:a": cert},
        persisted_certification_results={"term:a": {"certified": True}},
    )
    assert isinstance(kernel.certifications, MappingProxyType)
    assert isinstance(kernel.persisted_certification_results, MappingProxyType)
