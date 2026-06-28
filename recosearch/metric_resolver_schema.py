"""Structural schema + bounded vocabulary for metric packs and fallback policy.

The role / value-role vocabulary is loaded from the product-level roles.yaml
(scenario-agnostic concepts). Packs may only reference roles that exist there, so
packs cannot introduce free-form roles that become a weak parser.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import SEVERITY_ERROR, ContractIssue

_PACKS_DIR = Path(__file__).resolve().parent / "metric_packs"
_ROLES_FILE = _PACKS_DIR / "roles.yaml"

ALLOWED_AGGREGATIONS = {"sum", "avg", "count", "min", "max"}
FORMULA_TYPES = {"sum", "difference", "ratio"}
_SIGNS = {"+", "-"}
_LOC = "metric_packs"

_ROLES_CACHE: dict[str, Any] = {}


def load_roles() -> dict[str, Any]:
    text = _ROLES_FILE.read_text(encoding="utf-8") if _ROLES_FILE.exists() else ""
    if _ROLES_CACHE.get("text") != text:
        data = yaml.safe_load(text) if text.strip() else {}
        data = data if isinstance(data, dict) else {}
        _ROLES_CACHE.clear()
        _ROLES_CACHE.update({
            "text": text,
            "roles": data.get("roles") if isinstance(data.get("roles"), dict) else {},
            "value_roles": data.get("value_roles") if isinstance(data.get("value_roles"), dict) else {},
        })
    return _ROLES_CACHE


def semantic_roles() -> set[str]:
    return set(load_roles()["roles"])


def value_roles() -> set[str]:
    return set(load_roles()["value_roles"])


def _err(loc: str, message: str) -> ContractIssue:
    return ContractIssue("metric_pack_invalid", SEVERITY_ERROR, loc, message)


def validate_roles(roles_data: Mapping[str, Any] | None = None) -> list[ContractIssue]:
    """Validate the role vocabulary's own shape (roles.yaml). Pass roles_data to
    validate a synthetic vocabulary; otherwise the loaded roles.yaml is used."""
    data = roles_data if roles_data is not None else load_roles()
    loc = "metric_packs:roles.yaml"
    issues: list[ContractIssue] = []

    roles = data.get("roles")
    if not isinstance(roles, Mapping) or not roles:
        issues.append(_err(loc, "roles.yaml must define a non-empty roles object"))
    else:
        for name, spec in roles.items():
            rloc = f"{loc}:{name}"
            if not isinstance(spec, Mapping):
                issues.append(_err(rloc, "role must be an object"))
                continue
            if spec.get("kind") not in {"measure", "dimension"}:
                issues.append(_err(rloc, "role kind must be 'measure' or 'dimension'"))
            terms = spec.get("match_terms")
            if not isinstance(terms, list) or not terms or any(not isinstance(t, str) or not t.strip() for t in terms):
                issues.append(_err(rloc, "role match_terms must be a non-empty list of non-empty strings"))
            negatives = spec.get("negative_terms")
            if negatives is not None and (not isinstance(negatives, list) or any(not isinstance(t, str) for t in negatives)):
                issues.append(_err(rloc, "role negative_terms must be a list of strings"))
            if not isinstance(spec.get("concept"), str) or not spec.get("concept"):
                issues.append(_err(rloc, "role requires a string concept"))

    vroles = data.get("value_roles")
    if not isinstance(vroles, Mapping) or not vroles:
        issues.append(_err(loc, "roles.yaml must define a non-empty value_roles object"))
    else:
        for name, spec in vroles.items():
            if not isinstance(spec, Mapping) or not isinstance(spec.get("match_terms"), list) or not spec.get("match_terms"):
                issues.append(_err(f"{loc}:{name}", "value_role requires a non-empty match_terms list"))
    return issues


def _validate_terms(terms: Any, loc: str, roles: set[str]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if not isinstance(terms, list) or not terms:
        return [_err(loc, "formula terms must be a non-empty list")]
    for term in terms:
        if not isinstance(term, Mapping):
            issues.append(_err(loc, "term must be an object"))
            continue
        if term.get("role") not in roles:
            issues.append(_err(loc, f"unknown role {term.get('role')!r}; allowed {sorted(roles)}"))
        if term.get("agg") not in ALLOWED_AGGREGATIONS:
            issues.append(_err(loc, f"term agg must be one of {sorted(ALLOWED_AGGREGATIONS)}"))
        if term.get("sign", "+") not in _SIGNS:
            issues.append(_err(loc, "term sign must be '+' or '-'"))
    return issues


def _validate_formula(formula: Any, loc: str, roles: set[str]) -> list[ContractIssue]:
    if not isinstance(formula, Mapping):
        return [_err(loc, "formula must be an object")]
    ftype = formula.get("type")
    if ftype not in FORMULA_TYPES:
        return [_err(loc, f"formula.type must be one of {sorted(FORMULA_TYPES)}")]
    if ftype in {"sum", "difference"}:
        return _validate_terms(formula.get("terms"), f"{loc}.terms", roles)
    issues: list[ContractIssue] = []
    for part in ("numerator", "denominator"):
        section = formula.get(part)
        if not isinstance(section, Mapping):
            issues.append(_err(loc, f"ratio formula requires a {part} object"))
        else:
            issues.extend(_validate_terms(section.get("terms"), f"{loc}.{part}.terms", roles))
    return issues


def validate_metric_pack(pack: Any, *, pack_name: str = "pack") -> list[ContractIssue]:
    loc = f"{_LOC}:{pack_name}"
    if not isinstance(pack, Mapping):
        return [_err(loc, "pack must be an object")]
    roles = semantic_roles()
    vroles = value_roles()
    issues: list[ContractIssue] = []
    if not isinstance(pack.get("version"), str) or not pack.get("version"):
        issues.append(_err(loc, "pack requires a string version"))
    if not isinstance(pack.get("tier"), str) or not pack.get("tier"):
        issues.append(_err(loc, "pack requires a string tier"))
    metrics = pack.get("metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        issues.append(_err(loc, "pack requires a non-empty metrics object"))
        return issues

    for metric_id, metric in metrics.items():
        mloc = f"{loc}.{metric_id}"
        if not isinstance(metric, Mapping):
            issues.append(_err(mloc, "metric must be an object"))
            continue
        if not isinstance(metric.get("version"), str) or not metric.get("version"):
            issues.append(_err(mloc, "metric requires a string version"))
        # A metric must either define its own formula or delegate to another tier.
        delegate = metric.get("delegates_to")
        if delegate is not None:
            if not isinstance(delegate, str) or not delegate:
                issues.append(_err(mloc, "delegates_to must be a non-empty tier string"))
        elif "formula" not in metric:
            issues.append(_err(mloc, "metric requires a formula or a delegates_to"))
        else:
            issues.extend(_validate_formula(metric.get("formula"), f"{mloc}.formula", roles))
        for flt in metric.get("default_filters", []) or []:
            if not isinstance(flt, Mapping):
                issues.append(_err(mloc, "default_filters entry must be an object"))
                continue
            if flt.get("role") not in roles:
                issues.append(_err(mloc, f"default_filter unknown role {flt.get('role')!r}"))
            if flt.get("value_role") not in vroles:
                issues.append(_err(mloc, f"default_filter unknown value_role {flt.get('value_role')!r}; allowed {sorted(vroles)}"))
            if not isinstance(flt.get("op"), str) or not flt.get("op"):
                issues.append(_err(mloc, "default_filter requires a string op"))
    return issues


def validate_fallback_policy(policy: Any) -> list[ContractIssue]:
    loc = f"{_LOC}:fallback_policy"
    if not isinstance(policy, Mapping):
        return [_err(loc, "fallback_policy must be an object")]
    issues: list[ContractIssue] = []
    if not isinstance(policy.get("version"), str) or not policy.get("version"):
        issues.append(_err(loc, "fallback_policy requires a string version"))
    if not isinstance(policy.get("allow_global"), bool):
        issues.append(_err(loc, "allow_global must be a boolean"))
    if not isinstance(policy.get("allow_industry"), list):
        issues.append(_err(loc, "allow_industry must be a list"))
    return issues
