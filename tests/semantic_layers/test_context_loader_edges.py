from pathlib import Path

import pytest

from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
SEMANTIC = ROOT / "semantic"


def test_from_dir_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing context registry"):
        ContextKernelLoader.from_dir(tmp_path / "missing")


def test_from_contract_missing_kernel():
    with pytest.raises(ValueError, match="missing context_kernel"):
        ContextKernelLoader.from_contract({})


def test_from_contract_invalid_type():
    with pytest.raises(ValueError, match="must be a mapping"):
        ContextKernelLoader.from_contract({"context_kernel": "bad"})


def test_yaml_not_mapping_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        ContextKernelLoader.from_dir(context_dir)


def test_duplicate_alias_within_term_rejected(tmp_path):
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
    aliases: [sales, sales]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="duplicate alias"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unknown_guidance_term_rejected(tmp_path):
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
guidance:
  - term_id: term:missing:one
    when_to_use: u
    when_to_clarify: c
    when_to_refuse: r
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown term"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_duplicate_guidance_rejected(tmp_path):
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
guidance:
  - term_id: term:test:one
    when_to_use: u
    when_to_clarify: c
    when_to_refuse: r
  - term_id: term:test:one
    when_to_use: u2
    when_to_clarify: c2
    when_to_refuse: r2
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="duplicate guidance"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unknown_entity_ref_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [entity:missing:entity]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown entity"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unknown_dimension_ref_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [dimension:missing:dim]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown dimension"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unknown_measure_ref_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [measure:missing:measure]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown measure"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unknown_source_ref_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [unknown_source]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown source"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_unsupported_ref_prefix_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "bad.yaml").write_text(
        """
terms:
  - id: term:test:one
    display_name: one
    definition: d
    collection_id: global
    primary_refs: [foo:bar:baz]
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unsupported ref prefix"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)


def test_relationship_without_metric_kernel_rejected(tmp_path):
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
    to_id: metric:novashop:order_revenue
    kind: resolves_to
"""
    )
    with pytest.raises(ValueError, match="unknown target"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=None)


def test_load_context_kernel_auto_metric_kernel(tmp_path):
    import shutil

    semantic = tmp_path / "semantic"
    shutil.copytree(SEMANTIC, semantic)
    kernel = load_context_kernel(semantic)
    assert "term:novashop:revenue" in kernel.terms


def test_certification_unknown_term_rejected(tmp_path):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "cert.yaml").write_text(
        """
certifications:
  - term_id: term:missing:one
    definition_hash: abc
    golden_questions:
      - term: x
        expected_decision: clarify
        expected_trust_status: trusted
"""
    )
    metric_kernel = MetricKernel.from_dir(SEMANTIC / "metrics")
    with pytest.raises(ValueError, match="unknown term"):
        ContextKernelLoader.from_dir(context_dir, metric_kernel=metric_kernel)
