import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOVASHOP_DB = ROOT / "examples" / "novashop" / "shop.duckdb"


def ensure_novashop_db() -> Path:
    """Build examples/novashop/shop.duckdb when missing."""
    if not NOVASHOP_DB.exists():
        import runpy

        runpy.run_path(str(ROOT / "examples" / "novashop" / "build_db.py"))
    return NOVASHOP_DB


@pytest.fixture(autouse=True)
def _clear_ledger():
    from recosearch.semantic_layers import ledger

    ledger.clear()
    ledger.configure_persist_dir(None)
    yield
    ledger.clear()
    ledger.configure_persist_dir(None)


@pytest.fixture(scope="module")
def compile_contract():
    ensure_novashop_db()
    from recosearch.semantic_layers.contract import compile_contract as _compile

    return _compile()
