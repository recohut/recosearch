from pathlib import Path

import pytest

from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.context.trust import apply_runtime_trust, build_trust_signal
from recosearch.semantic_layers.context.types import TermBinding
from recosearch.semantic_layers.envelope import Answer
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def _kernels():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    return metric_kernel, context_kernel


def test_drift_definition_hash_mismatch(tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(SEMANTIC / "metrics", metrics_dir)
    order_path = metrics_dir / "order_revenue.yaml"
    order_path.write_text(
        order_path.read_text(encoding="utf-8").replace("grain: order", "grain: transaction"),
        encoding="utf-8",
    )
    metric_kernel = MetricKernel.from_dir(metrics_dir)
    binding = TermBinding(
        term_id="term:test:one",
        display_name="one",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("metric:novashop:order_revenue",),
    )
    trust = build_trust_signal(binding, metric_kernel, actor_role="analyst")
    assert trust.drift_status == "expired"
    assert "definition_hash_mismatch" in trust.expiry_reasons
    assert trust.status == "not_usable"


def test_drift_missing_freshness_sla_at_risk():
    metric_kernel, _ = _kernels()
    binding = TermBinding(
        term_id="term:novashop:revenue",
        display_name="revenue",
        definition="d",
        aliases=(),
        collection_id="novashop_custom",
        primary_refs=("metric:novashop:order_revenue",),
    )
    trust = build_trust_signal(binding, metric_kernel, actor_role="analyst")
    if "missing_freshness_sla" in trust.expiry_reasons:
        assert trust.drift_status == "at_risk"
        assert trust.status == "usable_with_caveats"


def test_drift_failed_certification_expired(tmp_path):
    import shutil

    metrics_dir = tmp_path / "metrics"
    shutil.copytree(SEMANTIC / "metrics", metrics_dir)
    cert_path = metrics_dir / "_certifications.yaml"
    cert_path.write_text(
        cert_path.read_text(encoding="utf-8").replace("metric_value: 109.97", "metric_value: 0"),
        encoding="utf-8",
    )
    metric_kernel = MetricKernel.from_dir(metrics_dir)
    from recosearch.semantic_layers.metrics.certify import apply_certification_results, run_certifications
    from recosearch.semantic_layers.contract import compile_contract

    results = run_certifications(metric_kernel, compile_contract())
    metric_kernel = apply_certification_results(metric_kernel, results)
    binding = TermBinding(
        term_id="term:t",
        display_name="t",
        definition="d",
        aliases=(),
        collection_id="global",
        primary_refs=("metric:novashop:order_revenue",),
    )
    trust = build_trust_signal(binding, metric_kernel, actor_role="analyst")
    assert "failed_certification" in trust.expiry_reasons
    assert trust.drift_status == "expired"


def test_policy_changed_drift_expired(monkeypatch):
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    cert = context_kernel.certifications["term:novashop:revenue"]
    monkeypatch.setattr(
        "recosearch.semantic_layers.policy.compute_policy_hash",
        lambda: "deadbeef00000000",
    )
    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role="analyst",
        context_kernel=context_kernel,
    )
    assert "policy_changed" in trust.expiry_reasons
    assert trust.drift_status == "expired"


def test_runtime_trust_stale_data_caveat():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    card = build_context_card(binding, context_kernel, metric_kernel, actor_role="analyst")
    answer = Answer(
        decision="answer",
        contract_version="abc",
        evidence_tier="fixture-backed",
        actor_role="analyst",
        caveats=["stale_data"],
    )
    updated = apply_runtime_trust(card, answer, metric_kernel, context_kernel=context_kernel)
    assert "stale_data" in updated.caveats
    assert updated.trust.drift_status == "at_risk"


def test_runtime_trust_policy_refuse_expired():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    card = build_context_card(binding, context_kernel, metric_kernel, actor_role="analyst")
    answer = Answer(
        decision="refuse",
        contract_version="abc",
        evidence_tier="contract-only",
        actor_role="analyst",
    )
    updated = apply_runtime_trust(card, answer, metric_kernel, context_kernel=context_kernel)
    assert "policy_refuse" in updated.trust.expiry_reasons
    assert updated.trust.drift_status == "expired"


def test_deprecated_metric_usable_with_caveats():
    metric_kernel, context_kernel = _kernels()
    metrics = dict(metric_kernel.metrics)
    m = metrics["metric:novashop:order_revenue"]
    from recosearch.semantic_layers.metrics.types import Metric

    metrics["metric:novashop:order_revenue"] = Metric(
        metric_id=m.metric_id,
        display_name=m.display_name,
        collection_id=m.collection_id,
        grain=m.grain,
        filter_rules=m.filter_rules,
        allowed_dimension_ids=m.allowed_dimension_ids,
        measure_id=m.measure_id,
        deprecated=True,
        definition_hash=m.definition_hash,
        status=m.status,
    )
    from types import MappingProxyType
    from dataclasses import replace

    patched = replace(metric_kernel, metrics=MappingProxyType(metrics))
    binding = context_kernel.terms["term:novashop:revenue"]
    trust = build_trust_signal(binding, patched, actor_role="analyst", context_kernel=context_kernel)
    assert "deprecated_metric" in trust.reasons
    assert trust.status == "usable_with_caveats"


def test_context_cert_boosts_evidence_tier():
    metric_kernel, context_kernel = _kernels()
    from recosearch.semantic_layers.context.loader import ContextKernelLoader

    results = {
        "term:novashop:revenue": {
            "certified": True,
            "golden_passed": True,
            "evidence_tier": 3,
            "ares_confidence_interval": [1.0, 1.0],
        }
    }
    patched_ctx = ContextKernelLoader.with_certification_results(context_kernel, results)
    binding = patched_ctx.terms["term:novashop:revenue"]
    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role="analyst",
        context_kernel=patched_ctx,
    )
    assert trust.evidence_tier >= 3
    assert "not_cloud_proven" in trust.no_overclaim_labels
    assert "ares_ci=1.00-1.00" in trust.no_overclaim_labels
