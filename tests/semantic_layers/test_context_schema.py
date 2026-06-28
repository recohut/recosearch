from pathlib import Path

import pytest

from recosearch.semantic_layers.context.schema import ContextSchemaError, validate_context_kernel

ROOT = Path(__file__).resolve().parents[2] / "recosearch" / "semantic_layers"


def test_schema_rejects_invalid_term():
    with pytest.raises(ContextSchemaError):
        validate_context_kernel({"terms": [{"id": "bad"}]})


def test_schema_rejects_invalid_relationship():
    with pytest.raises(ContextSchemaError):
        validate_context_kernel(
            {
                "relationships": [
                    {"from_id": "term:a", "to_id": "metric:b"}
                ]
            }
        )
