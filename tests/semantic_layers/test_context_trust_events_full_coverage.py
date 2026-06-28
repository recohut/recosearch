from pathlib import Path

from recosearch.semantic_layers.context.events import EventBus, MetadataChanged
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.context.trust import apply_runtime_trust, build_trust_signal
from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.envelope import Answer
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def _kernels():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    return metric_kernel, context_kernel


def test_policy_change_on_term_expires_trust():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    bus = EventBus()
    bus.publish(MetadataChanged(kind="policy-change", ref="term:novashop:revenue"))

    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role="analyst",
        context_kernel=context_kernel,
        event_bus=bus,
    )
    assert "policy_changed" in trust.expiry_reasons
    assert trust.drift_status == "expired"
    assert trust.status == "not_usable"
    assert "drift_expired" in trust.reasons


def test_schema_change_on_metric_ref_expires_trust():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    bus = EventBus()
    bus.publish(
        MetadataChanged(kind="schema-change", ref="metric:novashop:order_revenue")
    )

    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role="analyst",
        context_kernel=context_kernel,
        event_bus=bus,
    )
    assert "schema_changed" in trust.expiry_reasons
    assert trust.drift_status == "expired"
    assert trust.status == "not_usable"


def test_freshness_breach_at_risk():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    bus = EventBus()
    bus.publish(MetadataChanged(kind="freshness-breach", ref="term:novashop:revenue"))

    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role="analyst",
        context_kernel=context_kernel,
        event_bus=bus,
    )
    assert "stale_data" in trust.expiry_reasons
    assert trust.drift_status == "at_risk"
    assert trust.status == "usable_with_caveats"
    assert "drift_at_risk" in trust.reasons


def test_catalog_update_at_risk():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    bus = EventBus()
    bus.publish(MetadataChanged(kind="catalog-update", ref="term:novashop:revenue"))

    trust = build_trust_signal(
        binding,
        metric_kernel,
        actor_role="analyst",
        context_kernel=context_kernel,
        event_bus=bus,
    )
    assert "catalog_updated" in trust.expiry_reasons
    assert trust.drift_status == "at_risk"
    assert trust.status == "usable_with_caveats"


def test_apply_runtime_trust_passes_event_bus():
    metric_kernel, context_kernel = _kernels()
    binding = context_kernel.terms["term:novashop:revenue"]
    card = build_context_card(binding, context_kernel, metric_kernel, actor_role="analyst")
    bus = EventBus()
    bus.publish(MetadataChanged(kind="policy-change", ref="term:novashop:revenue"))
    answer = Answer(
        decision="answer",
        contract_version="abc",
        evidence_tier="fixture-backed",
        actor_role="analyst",
    )

    updated = apply_runtime_trust(
        card,
        answer,
        metric_kernel,
        context_kernel=context_kernel,
        event_bus=bus,
    )
    assert "policy_changed" in updated.trust.expiry_reasons
    assert updated.trust.drift_status == "expired"
    assert updated.trust.status == "not_usable"
