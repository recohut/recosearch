from __future__ import annotations

import sys

from recosearch.semantic_layers.contract import compile_contract, write_semantic_json


def main() -> int:
    contract = compile_contract()
    if not contract.get("metrics"):
        print("error: no metrics in semantic.md")
        return 1
    if not contract.get("sources"):
        print("error: no sources in source_config.yaml")
        return 1
    path = write_semantic_json()
    print(f"ok: {path} (hash {contract['contract_hash']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
