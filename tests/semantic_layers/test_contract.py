import shutil

from recosearch.semantic_layers.contract import compile_contract, write_semantic_json


def test_compile_has_metrics_and_hash():
    contract = compile_contract()
    assert isinstance(contract["contract_hash"], str)
    assert len(contract["contract_hash"]) == 16
    assert compile_contract()["contract_hash"] == contract["contract_hash"]
    assert contract["metrics"]
    assert "metric_kernel" in contract
    assert contract["metric_kernel"]["metrics"]
    assert "context_kernel" in contract
    assert contract["context_kernel"]["terms"]
    assert any(t["id"] == "term:novashop:revenue" for t in contract["context_kernel"]["terms"])
    assert "novashop" in str(contract["sources"])
    source = contract["sources"]["novashop"]
    assert source["type"] == "duckdb"
    assert source["mode"] == "runtime"
    assert source["operations"] == ["structured_query"]
    assert source["cost_controls"]["max_rows"] == 100


def test_write_semantic_json(tmp_path, monkeypatch):
    import recosearch.semantic_layers.contract as mod

    semantic = tmp_path / "semantic"
    semantic.mkdir()
    for name in ("source_config.yaml", "scenario_config.yaml", "semantic.md"):
        (semantic / name).write_text((mod.SEMANTIC_DIR / name).read_text())
    shutil.copytree(mod.SEMANTIC_DIR / "metrics", semantic / "metrics")
    shutil.copytree(mod.SEMANTIC_DIR / "context", semantic / "context")
    monkeypatch.setattr(mod, "SEMANTIC_DIR", semantic)
    out = write_semantic_json(semantic)
    assert out.exists()
    assert '"metrics"' in out.read_text()
