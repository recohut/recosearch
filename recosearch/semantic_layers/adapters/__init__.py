from __future__ import annotations

import importlib
import pkgutil
import sys

from recosearch.semantic_layers.adapters.base import SourceAdapter

_NON_ADAPTER = {"base"}


def _discover() -> dict[str, SourceAdapter]:
    found: dict[str, SourceAdapter] = {}
    package = __name__
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name in _NON_ADAPTER or info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{package}.{info.name}")
        except Exception as exc:  # pragma: no cover
            print(f"[adapters] skip {info.name}: {exc!r}", file=sys.stderr)
            continue
        adapter = getattr(mod, "ADAPTER", None)
        if isinstance(adapter, SourceAdapter):
            found[adapter.source_type] = adapter
    return found


ADAPTERS: dict[str, SourceAdapter] = _discover()

CAPABILITIES_BY_TYPE: dict[str, set[str]] = {
    t: set(a.capabilities) for t, a in ADAPTERS.items() if a.available
}


def adapter_for(source_type: str) -> SourceAdapter | None:
    return ADAPTERS.get(source_type)


def capabilities_for(source_type: str) -> set[str]:
    return CAPABILITIES_BY_TYPE.get(source_type, set())
