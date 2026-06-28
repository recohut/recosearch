from pathlib import Path

import pytest

from recosearch.semantic_layers.context.catalog import FileCatalogAdapter, apply_catalog_ingest
from recosearch.semantic_layers.context.cards import build_context_card
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


def test_catalog_merge_adds_related_refs():
    metric_kernel = MetricKernel.from_dir(ROOT / "semantic" / "metrics")
    context_kernel = load_context_kernel(ROOT / "semantic", metric_kernel=metric_kernel)
    binding = context_kernel.terms["term:novashop:revenue"]
    adapter = FileCatalogAdapter(ROOT / "examples" / "catalog" / "novashop_export.json")
    enriched_kernel = apply_catalog_ingest(context_kernel, adapter)
    card = build_context_card(binding, enriched_kernel, metric_kernel, actor_role="analyst")
    assert "catalog:novashop:orders_table" in card.related_refs
    assert "data-team@novashop" in card.operational["owners"]


def test_catalog_merge_scoped_to_exact_term_id(tmp_path):
    catalog = {
        "entities": [
            {
                "urn": "urn:term:novashop:revenue",
                "glossaryTerm": "term:novashop:revenue",
                "related": ["catalog:novashop:orders_table"],
                "owner": "data-team@novashop",
            }
        ]
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(__import__("json").dumps(catalog), encoding="utf-8")
    adapter = FileCatalogAdapter(catalog_path)
    revenue_refs = adapter.merge_related_refs("term:novashop:revenue", ("metric:novashop:order_revenue",))
    gross_refs = adapter.merge_related_refs("term:novashop:gross_revenue", ("metric:novashop:gross_revenue",))
    assert "catalog:novashop:orders_table" in revenue_refs
    assert "catalog:novashop:orders_table" not in gross_refs


    adapter = FileCatalogAdapter(ROOT / "examples" / "catalog" / "novashop_export.json")
    authored = ("metric:novashop:order_revenue",)
    merged = adapter.merge_related_refs("term:novashop:revenue", authored)
    assert adapter.conflicts
