from pathlib import Path

from recosearch.semantic_layers.context.probe import probe_term_local
from recosearch.semantic_layers.context.loader import load_context_kernel
from recosearch.semantic_layers.contract import compile_contract
from recosearch.semantic_layers.metrics.loader import MetricKernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


def test_probe_term_local_passes():
    if not (ROOT / "examples" / "novashop" / "shop.duckdb").exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    metric_kernel = MetricKernel.from_dir(ROOT / "semantic" / "metrics")
    context_kernel = load_context_kernel(ROOT / "semantic", metric_kernel=metric_kernel)
    binding = context_kernel.terms["term:novashop:revenue"]
    contract = compile_contract()
    result = probe_term_local(binding, metric_kernel, contract)
    assert result["passed"] is True
    assert result["evidence_tier"] == 3


def test_probe_no_metric_ref_fails():
    metric_kernel = MetricKernel.from_dir(ROOT / "semantic" / "metrics")
    context_kernel = load_context_kernel(ROOT / "semantic", metric_kernel=metric_kernel)
    binding = context_kernel.terms["term:novashop:customer"]
    contract = compile_contract()
    result = probe_term_local(binding, metric_kernel, contract)
    assert result["passed"] is False
