from pathlib import Path

from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.context.trust import build_trust_signal
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def _binding(term_id: str = "term:novashop:revenue"):
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    context_kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    return context_kernel.terms[term_id], context_kernel, metric_kernel


def test_trusted_revenue_for_analyst():
    binding, _, metric_kernel = _binding()
    trust = build_trust_signal(binding, metric_kernel, actor_role="analyst")
    assert trust.status in ("trusted", "usable_with_caveats")
    assert trust.evidence_tier >= 1
    assert trust.claim_scope.metrics == ("metric:novashop:order_revenue",)


def test_guest_not_usable():
    binding, _, metric_kernel = _binding()
    trust = build_trust_signal(binding, metric_kernel, actor_role="guest")
    assert trust.status == "not_usable"
    assert "policy_denied" in trust.reasons


def test_revenue_card_six_facets_stable_id():
    binding, context_kernel, metric_kernel = _binding()
    card_a = build_context_card(binding, context_kernel, metric_kernel, actor_role="analyst")
    card_b = build_context_card(binding, context_kernel, metric_kernel, actor_role="analyst")
    assert card_a.card_id == card_b.card_id
    assert card_a.card_id.startswith("ctx-")
    assert card_a.technical["schema"]
    assert card_a.semantic["primary_refs"]
    assert card_a.operational["owners"]
    assert card_a.relationships["related_refs"]
    assert card_a.trust.signal_id.startswith("trust-")
    assert card_a.client_guidance["when_to_use"]
    assert "metric:novashop:order_revenue" in card_a.primary_refs


def test_card_id_distinguishes_drift_and_scope():
    from pathlib import Path

    from recosearch.semantic_layers.context.hash import compute_card_id

    base = {
        "term_id": "term:x:one",
        "display_name": "x",
        "definition": "d",
        "primary_refs": ["metric:x:y"],
        "related_refs": [],
    }
    at_risk = dict(base, trust={
        "status": "usable_with_caveats",
        "evidence_tier": 1,
        "drift_status": "at_risk",
        "expiry_reasons": ["missing_freshness_sla"],
        "claim_scope": {"sources": ["novashop"], "roles": ["*"], "metrics": ["metric:novashop:order_revenue"]},
    })
    expired = dict(base, trust={
        "status": "usable_with_caveats",
        "evidence_tier": 1,
        "drift_status": "expired",
        "expiry_reasons": ["definition_hash_mismatch"],
        "claim_scope": {"sources": ["novashop"], "roles": ["*"], "metrics": ["metric:novashop:order_revenue"]},
    })
    same_scope_diff_source = dict(base, trust={
        "status": "usable_with_caveats",
        "evidence_tier": 1,
        "drift_status": "at_risk",
        "expiry_reasons": ["missing_freshness_sla"],
        "claim_scope": {"sources": ["other"], "roles": ["*"], "metrics": ["metric:novashop:order_revenue"]},
    })
    assert compute_card_id(at_risk) != compute_card_id(expired)
    assert compute_card_id(at_risk) != compute_card_id(same_scope_diff_source)
    assert compute_card_id(at_risk) == compute_card_id(at_risk)
