"""L3 formal ontology / constraint layer (lite-first SHACL gate)."""

from recosearch.semantic_layers.ontology.loader import OntologyKernelLoader, load_ontology_kernel
from recosearch.semantic_layers.ontology.types import ConstraintDecision, OntologyKernel
from recosearch.semantic_layers.ontology.validate import validate_claim

__all__ = [
    "ConstraintDecision",
    "OntologyKernel",
    "OntologyKernelLoader",
    "load_ontology_kernel",
    "validate_claim",
]
