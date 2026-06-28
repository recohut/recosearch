from pathlib import Path

import pytest

from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.context.types import ContextKernel
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_load_context_kernel_round_trip():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    assert isinstance(kernel, ContextKernel)
    assert "term:novashop:revenue" in kernel.terms
    assert kernel.terms["term:novashop:revenue"].display_name == "revenue"


def test_context_kernel_immutable_maps():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    with pytest.raises(TypeError):
        kernel.terms["x"] = kernel.terms["term:novashop:revenue"]  # type: ignore[index]


def test_duplicate_term_id_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "a.yaml").write_text(
        "terms:\n  - id: term:test:one\n    display_name: one\n    definition: d\n"
        "    collection_id: global\n    primary_refs:\n      - novashop\n"
    )
    (context_dir / "b.yaml").write_text(
        "terms:\n  - id: term:test:one\n    display_name: two\n    definition: d\n"
        "    collection_id: global\n    primary_refs:\n      - novashop\n"
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="duplicate term id"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unknown_metric_ref_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        "terms:\n  - id: term:test:bad\n    display_name: bad\n    definition: d\n"
        "    collection_id: global\n    primary_refs:\n      - metric:missing:metric\n"
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown metric"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_to_dict_round_trip():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    raw = ContextKernelLoader.to_dict(kernel)
    reloaded = ContextKernelLoader._from_raw(raw, metric_kernel=metric_kernel)
    assert set(reloaded.terms) == set(kernel.terms)


def test_duplicate_alias_across_terms_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "dup.yaml").write_text(
        """
terms:
  - id: term:novashop:rev_a
    display_name: revenue a
    definition: a
    collection_id: novashop_custom
    primary_refs: [metric:novashop:order_revenue]
    aliases: [sales]
  - id: term:novashop:rev_b
    display_name: revenue b
    definition: b
    collection_id: novashop_custom
    primary_refs: [metric:novashop:gross_revenue]
    aliases: [sales]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="duplicate alias 'sales'"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_display_name_ambiguity_same_scope_still_loads(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "dup.yaml").write_text(
        """
terms:
  - id: term:novashop:rev_a
    display_name: revenue
    definition: a
    collection_id: novashop_custom
    primary_refs: [metric:novashop:order_revenue]
  - id: term:novashop:rev_b
    display_name: revenue
    definition: b
    collection_id: novashop_custom
    primary_refs: [metric:novashop:gross_revenue]
guidance:
  - term_id: term:novashop:rev_a
    when_to_use: u
    when_to_clarify: c
    when_to_refuse: r
  - term_id: term:novashop:rev_b
    when_to_use: u
    when_to_clarify: c
    when_to_refuse: r
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    assert len(kernel.terms) == 2


def test_unknown_relationship_target_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [novashop]
relationships:
  - from_id: term:test:one
    to_id: metric:missing:metric
    kind: resolves_to
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown target"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_valid_relationship_target_types(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "rels.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [novashop]
  - id: term:test:two
    display_name: two
    definition: d
    collection_id: global
    primary_refs: [novashop]
relationships:
  - from_id: term:test:one
    to_id: term:test:two
    kind: related_term
  - from_id: term:test:one
    to_id: metric:novashop:order_revenue
    kind: resolves_to
  - from_id: term:test:one
    to_id: entity:novashop:order
    kind: grounded_in
  - from_id: term:test:one
    to_id: dimension:novashop:order_status
    kind: grounded_in
  - from_id: term:test:one
    to_id: measure:novashop:total_amount
    kind: grounded_in
  - from_id: term:test:one
    to_id: relation:novashop:order_customer
    kind: grounded_in
  - from_id: term:test:one
    to_id: novashop
    kind: grounded_in
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    kernel = ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
    assert len(kernel.relationships) == 7


def test_semantic_relationships_load():
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    kernel = load_context_kernel(SEMANTIC, metric_kernel=metric_kernel)
    assert len(kernel.relationships) >= 9
