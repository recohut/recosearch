"""tests/conftest.py – auto-mark tests by their folder layer.

Adds the following pytest marks automatically based on which sub-folder a
test module lives in:

  tests/unit/        -> @pytest.mark.unit
  tests/smoke/       -> @pytest.mark.smoke
  tests/integration/ -> @pytest.mark.integration
  tests/live/        -> @pytest.mark.live

No per-test decoration is required.
"""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/smoke/" in path:
            item.add_marker(pytest.mark.smoke)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/live/" in path:
            item.add_marker(pytest.mark.live)
