from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
SEMANTIC_DIR = ROOT / "semantic"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_semantic_md(text: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("# "):
            current = line[2:].strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(line)
    return {
        "metrics": [ln.strip()[2:] for ln in sections.get("metrics", []) if ln.strip().startswith("- ")],
        "rules": [ln.strip() for ln in sections.get("rules", []) if ln.strip() and not ln.startswith("#")],
        "dimensions": [ln.strip()[2:] for ln in sections.get("dimensions", []) if ln.strip().startswith("- ")],
        "measures": [ln.strip()[2:] for ln in sections.get("measures", []) if ln.strip().startswith("- ")],
        "relations": [ln.strip()[2:] for ln in sections.get("relations", []) if ln.strip().startswith("- ")],
    }


def _load_metric_kernel(semantic_dir: Path) -> dict[str, Any]:
    from recosearch.semantic_layers.metrics.loader import MetricKernel

    metrics_dir = semantic_dir / "metrics"
    if not metrics_dir.exists():
        raise FileNotFoundError(f"missing metric registry directory: {metrics_dir}")
    return MetricKernel.from_dir(metrics_dir).to_dict()


def _load_context_kernel(semantic_dir: Path, metric_kernel: dict[str, Any]) -> dict[str, Any]:
    from recosearch.semantic_layers.context.loader import ContextKernelLoader, load_context_kernel
    from recosearch.semantic_layers.metrics.loader import MetricKernel

    context_dir = semantic_dir / "context"
    if not context_dir.exists():
        return {}
    mk = MetricKernel._from_raw(metric_kernel)
    kernel = load_context_kernel(semantic_dir, metric_kernel=mk)
    return ContextKernelLoader.to_dict(kernel)


def _load_ontology_kernel(
    semantic_dir: Path,
    context_kernel: dict[str, Any],
    metric_kernel: dict[str, Any],
) -> dict[str, Any]:
    from recosearch.semantic_layers.context.loader import ContextKernelLoader
    from recosearch.semantic_layers.metrics.loader import MetricKernel
    from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader, load_ontology_kernel

    ontology_dir = semantic_dir / "ontology"
    if not ontology_dir.exists():
        return {}
    mk = MetricKernel._from_raw(metric_kernel)
    ck = ContextKernelLoader._from_raw(context_kernel, metric_kernel=mk)
    kernel = load_ontology_kernel(semantic_dir, context_kernel=ck)
    return OntologyKernelLoader.to_dict(kernel)


def compile_contract(semantic_dir: Path = SEMANTIC_DIR) -> dict[str, Any]:
    from recosearch.semantic_layers.sources import normalize_sources

    source_config = yaml.safe_load(_read_text(semantic_dir / "source_config.yaml"))
    scenario_config = yaml.safe_load(_read_text(semantic_dir / "scenario_config.yaml"))
    semantic = _parse_semantic_md(_read_text(semantic_dir / "semantic.md"))
    contract = {
        "sources": normalize_sources(source_config.get("sources", {})),
        "scenario": scenario_config.get("scenario", {}),
        "roles": scenario_config.get("roles", {}),
        **semantic,
    }
    metric_kernel = _load_metric_kernel(semantic_dir)
    if metric_kernel:
        contract["metric_kernel"] = metric_kernel
    context_kernel = _load_context_kernel(semantic_dir, metric_kernel)
    if context_kernel:
        contract["context_kernel"] = context_kernel
    if context_kernel and metric_kernel:
        ontology_kernel = _load_ontology_kernel(semantic_dir, context_kernel, metric_kernel)
        if ontology_kernel:
            contract["ontology_kernel"] = ontology_kernel
    from recosearch.semantic_layers.decisions.apply_proposal import trust_overrides_to_dict
    from recosearch.semantic_layers.decisions.loader import (
        config_to_dict,
        counterfactuals_to_dict,
        load_counterfactuals_config,
        load_decisions_config,
    )
    from recosearch.semantic_layers.evidence.loader import gates_to_dict, load_evidence_gates

    evidence_dir = semantic_dir / "evidence"
    if evidence_dir.exists():
        contract["evidence_gates"] = gates_to_dict(load_evidence_gates(evidence_dir))
    decisions_dir = semantic_dir / "decisions"
    if decisions_dir.exists():
        contract["decisions_config"] = config_to_dict(load_decisions_config(decisions_dir))
        counterfactuals = load_counterfactuals_config(decisions_dir)
        if counterfactuals:
            contract["counterfactuals_config"] = counterfactuals_to_dict(counterfactuals)
    context_dir = semantic_dir / "context"
    trust_overrides_path = context_dir / "_trust_overrides.yaml"
    if trust_overrides_path.exists():
        raw_overrides = yaml.safe_load(trust_overrides_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw_overrides, dict) and raw_overrides.get("overrides"):
            contract["trust_overrides"] = trust_overrides_to_dict(raw_overrides)
    payload = json.dumps(contract, sort_keys=True)
    contract["contract_hash"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return contract


def write_semantic_json(semantic_dir: Path = SEMANTIC_DIR) -> Path:
    contract = compile_contract(semantic_dir)
    out = semantic_dir / "semantic.json"
    out.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return out
