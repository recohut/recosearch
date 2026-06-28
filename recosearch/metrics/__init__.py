"""Compatibility shim: make `recosearch.metrics` resolve to the same module
object as `recosearch.metric_resolver` so that monkeypatching
`metrics.load_metric_data` affects the functions that call it internally.
"""
import sys as _sys
import importlib as _importlib

# Import the real implementation module.
_resolver = _importlib.import_module("recosearch.metric_resolver")

# Replace this package entry in sys.modules with the flat module so that
# `from recosearch import metrics; metrics.load_metric_data = X` patches
# the same namespace that metric_resolver.py functions use.
_sys.modules[__name__] = _resolver
