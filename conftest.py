"""Root conftest so tests under tests/ can import the project's top-level
modules (``recosearch`` package and ``mcp_server``).

Pytest inserts the directory of the first conftest.py it finds (this project
root) onto ``sys.path``. The explicit insert below makes that guarantee
independent of pytest's import mode / invocation directory.

The test suite runs against the bundled NovaMart example scenario, so we point
RECOSEARCH_SEMANTIC_DIR at examples/novamart before recosearch is imported
(settings.py reads it at import time). ``setdefault`` lets a caller override it.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
os.environ.setdefault("RECOSEARCH_SEMANTIC_DIR", os.path.join(_ROOT, "examples", "novamart"))
