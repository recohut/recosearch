from __future__ import annotations

import yaml

from recosearch.semantic_layers.context.loader import ContextKernelLoader
from recosearch.semantic_layers.contract import compile_contract, SEMANTIC_DIR


def test_context_trust_overrides_merge(tmp_path):
    semantic = tmp_path / "semantic"
    import shutil

    shutil.copytree(SEMANTIC_DIR, semantic)
    overrides_path = semantic / "context" / "_trust_overrides.yaml"
    overrides_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "overrides": [
                    {
                        "term_id": "term:novashop:revenue",
                        "ares_confidence_interval": [0.42, 0.58],
                        "source_proposal_id": "proposal-test",
                        "operator": "cert-operator",
                        "applied_at": "2026-06-28T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    contract = compile_contract(semantic)
    kernel = ContextKernelLoader.from_contract(contract)
    cert = kernel.certifications["term:novashop:revenue"]
    assert cert.ares_confidence_interval == (0.42, 0.58)


def test_apply_trust_overrides_edge_cases(compile_contract):
    kernel = ContextKernelLoader.from_contract(compile_contract)
    unchanged = ContextKernelLoader._apply_trust_overrides(kernel, {"overrides": []})
    assert unchanged is kernel
    unchanged2 = ContextKernelLoader._apply_trust_overrides(
        kernel,
        {
            "overrides": [
                "bad",
                {"term_id": ""},
                {"term_id": "term:missing"},
                {"term_id": "term:novashop:revenue"},
            ]
        },
    )
    assert unchanged2 is kernel
    merged = ContextKernelLoader._apply_trust_overrides(
        kernel,
        {
            "overrides": [
                {
                    "term_id": "term:novashop:revenue",
                    "ares_confidence_interval": [0.1, 0.2],
                }
            ]
        },
    )
    assert merged.certifications["term:novashop:revenue"].ares_confidence_interval == (0.1, 0.2)
