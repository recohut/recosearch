from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directory holding the active scenario's declared inputs (scenario_config.yaml,
# source_config.yaml, semantic.md). Defaults to ./semantic; point
# RECOSEARCH_SEMANTIC_DIR at another directory (e.g. examples/novamart) to run a
# different scenario without code changes.
SEMANTIC_DIR = Path(os.environ.get("RECOSEARCH_SEMANTIC_DIR") or (ROOT / "semantic")).resolve()
SOURCE_CONFIG_PATH = SEMANTIC_DIR / "source_config.yaml"
SEMANTIC_MD_PATH = SEMANTIC_DIR / "semantic.md"
# Single declared scenario file: identity + roles (RBAC) + access (ACL) + vocabularies.
SCENARIO_PATH = SEMANTIC_DIR / "scenario_config.yaml"
# Compiled contract, written beside the inputs it is generated from.
SEMANTIC_JSON_PATH = SEMANTIC_DIR / "semantic.json"

# Embedding model is a deployment default, overridable per scenario/environment.
EMBEDDING_MODEL = os.environ.get("RECOSEARCH_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MAX_SOURCE_ROWS = 100
MAX_FEDERATION_ROWS = 500
