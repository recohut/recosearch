from __future__ import annotations

from pathlib import Path

from recosearch.semantic_layers.evidence.compose import compose_evidence_pack, execute_subclaim
from recosearch.semantic_layers.evidence.gate import apply_composite_gate, check_comparable_consistency
from recosearch.semantic_layers.evidence.loader import load_evidence_gates, pattern_matches
from recosearch.semantic_layers.evidence.types import ClaimSet, EvidenceGateKernel, Subclaim

__all__ = [
    "ClaimSet",
    "EvidenceGateKernel",
    "Subclaim",
    "apply_composite_gate",
    "check_comparable_consistency",
    "compose_evidence_pack",
    "execute_subclaim",
    "load_evidence_gates",
    "pattern_matches",
]
