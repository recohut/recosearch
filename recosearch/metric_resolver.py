"""Metric registry and fallback resolution.

Resolves metric authority L0 customer -> L1 normalized -> L2 industry -> L3 global
-> L4 clarify. Pack formulas are structured data over abstract ROLES; roles are
mapped to scenario fields ONLY from the declared semantic contract (label /
description / column), never from hardcoded column names. Ambiguous or missing
mappings refuse, never guess.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ContractIssue
from .metric_resolver_schema import load_roles, validate_fallback_policy, validate_metric_pack, validate_roles

_PACKS_DIR = Path(__file__).resolve().parent / "metric_packs"
_NON_PACK_FILES = {"fallback_policy.yaml", "roles.yaml"}

# Confidence guards for role -> field mapping.
_MIN_SCORE = 1
_MARGIN = 1

_CACHE: dict[str, Any] = {}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _normalize(name: Any) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(name or "").casefold())
    return " ".join(t[:-1] if t.endswith("s") and len(t) > 3 else t for t in tokens)


def load_metric_data() -> dict[str, Any]:
    policy_text = _read(_PACKS_DIR / "fallback_policy.yaml")
    pack_files = sorted(p for p in _PACKS_DIR.glob("*.yaml") if p.name not in _NON_PACK_FILES)
    key = _hash(policy_text + "||" + "||".join(f"{p.name}:{_read(p)}" for p in pack_files))
    if _CACHE.get("key") == key:
        return _CACHE["data"]
    policy = yaml.safe_load(policy_text) if policy_text.strip() else {}
    packs: dict[str, Any] = {}
    for path in pack_files:
        text = _read(path)
        data = yaml.safe_load(text) if text.strip() else {}
        if isinstance(data, dict):
            tier = str(data.get("tier") or path.stem)
            packs[tier] = {"data": data, "version": str(data.get("version") or ""), "hash": _hash(text)}
    resolved = {
        "policy": policy if isinstance(policy, dict) else {},
        "policy_version": str((policy or {}).get("version") or ""),
        "policy_hash": _hash(policy_text),
        "packs": packs,
    }
    _CACHE.clear()
    _CACHE.update({"key": key, "data": resolved})
    return resolved


def validate_metric_packs() -> list[ContractIssue]:
    data = load_metric_data()
    issues = list(validate_roles())
    issues.extend(validate_fallback_policy(data["policy"]))
    for tier, pack in data["packs"].items():
        issues.extend(validate_metric_pack(pack["data"], pack_name=tier))
    return issues


# --- contract-driven role -> field mapping (no scenario column names) --------

def _kind_fields(contract: Mapping[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    from .contract import _source_ids_with_capability

    section = "measures" if kind == "measure" else "dimensions"
    sources = set(_source_ids_with_capability(contract, "structured_query"))
    return {
        field_id: field
        for field_id, field in contract.get(section, {}).items()
        if isinstance(field, Mapping) and field.get("source") in sources
    }


def _haystack(field: Mapping[str, Any]) -> str:
    column = str(field.get("column") or "").replace("_", " ")
    return f"{field.get('label', '')} {field.get('description', '')} {column}".casefold()


def _score(haystack: str, terms: Any) -> int:
    return sum(1 for term in terms or [] if str(term).casefold() in haystack)


def _role_score(haystack: str, spec: Mapping[str, Any]) -> int:
    """Score a field against a role; a negative term (e.g. 'rate', 'shipping')
    disqualifies the field so amount-vs-rate / cost-type look-alikes do not map."""
    if any(str(neg).casefold() in haystack for neg in spec.get("negative_terms") or []):
        return 0
    return _score(haystack, spec.get("match_terms"))


def map_role(contract: Mapping[str, Any], role: str) -> tuple[str, Any]:
    """('ok', field_id) | ('unmapped', None) | ('ambiguous', [...]) | ('unknown_role', None).

    A field maps to a role only if its kind matches, the top role score passes a
    minimum threshold AND is clearly ahead of the second-best role (margin), and
    exactly one such field maps to the role. Evidence is the declared contract.
    """
    roles = load_roles()["roles"]
    spec = roles.get(role)
    if not spec:
        return "unknown_role", None
    kind = spec.get("kind")
    kind_roles = {r: rs for r, rs in roles.items() if rs.get("kind") == kind}
    confident: list[str] = []
    for field_id, field in _kind_fields(contract, kind).items():
        haystack = _haystack(field)
        scores = {r: _role_score(haystack, rs) for r, rs in kind_roles.items()}
        if not scores:
            continue
        ordered = sorted(scores.values(), reverse=True)
        top = ordered[0]
        second = ordered[1] if len(ordered) > 1 else 0
        top_role = max(scores, key=lambda r: scores[r])
        if top >= _MIN_SCORE and (top - second) >= _MARGIN and top_role == role:
            confident.append(field_id)
    if len(confident) == 1:
        return "ok", confident[0]
    if not confident:
        return "unmapped", None
    return "ambiguous", sorted(confident)


def map_value_role(contract: Mapping[str, Any], value_role: str, status_field_id: str) -> str | None:
    spec = load_roles()["value_roles"].get(value_role) or {}
    haystack = _haystack(_kind_fields(contract, "dimension").get(status_field_id, {}))
    for term in spec.get("match_terms") or []:
        if str(term).casefold() in haystack:
            return str(term).casefold()
    return None


# --- packs / policy / precedence ---------------------------------------------

def _stamp(*, metric_id, source, level, metric_version, pack_version, pack_hash, data,
           formula_verified=False, inputs_verified=False, caveat=None, mapping=None, formula_source=None, delegated_from=None):
    stamp = {
        "metric_id": metric_id,
        "metric_source": source,
        "fallback_level": level,
        "metric_version": metric_version,
        "inputs_verified": inputs_verified,
        "formula_verified": formula_verified,
        "caveat": caveat,
        "fallback_policy_version": data["policy_version"],
        "fallback_policy_hash": data["policy_hash"],
        "metric_pack_version": pack_version,
        "metric_pack_hash": pack_hash,
    }
    if formula_source:
        stamp["formula_source"] = formula_source
    if delegated_from:
        stamp["delegated_from"] = delegated_from
    if mapping:
        stamp["required_field_mapping"] = mapping
    return stamp


def _find_customer_metric(name: str, contract: Mapping[str, Any]) -> tuple[str, dict[str, Any], str] | None:
    metrics = contract.get("metrics", {})
    for metric_id, metric in metrics.items():
        if name in (metric_id, str(metric.get("label"))):
            return metric_id, metric, "L0"
    norm = _normalize(name)
    for metric_id, metric in metrics.items():
        if norm in (_normalize(metric_id), _normalize(metric.get("label"))):
            return metric_id, metric, "L1"
    return None


def _pack_candidates(name: str, data: Mapping[str, Any]) -> list[tuple[str, str, dict, dict]]:
    norm = _normalize(name)
    tiers = [t for t in data["packs"] if t != "global"] + (["global"] if "global" in data["packs"] else [])
    out: list[tuple[str, str, dict, dict]] = []
    for tier in tiers:
        pack = data["packs"][tier]
        for metric_id, metric in pack["data"].get("metrics", {}).items():
            if name in (metric_id, str(metric.get("label"))) or norm in (_normalize(metric_id), _normalize(metric.get("label"))):
                out.append((tier, metric_id, metric, pack))
    return out


def _tier_enabled(tier: str, policy: Mapping[str, Any]) -> bool:
    if tier == "global":
        return bool(policy.get("allow_global"))
    return tier in set(policy.get("allow_industry") or [])


def resolve_metric(name: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    data = load_metric_data()

    customer = _find_customer_metric(name, contract)
    if customer:
        metric_id, metric, level = customer
        stamp = _stamp(
            metric_id=metric_id, source="customer", level=level,
            metric_version=str(metric.get("version") or "customer-prose"),
            pack_version=None, pack_hash=None, data=data, formula_source="customer",
            caveat="customer prose metric; formula not machine-verified",
        )
        return {"status": "resolved", "metric_source": "customer", "stamp": stamp, "pack_metric": None}

    candidates = _pack_candidates(name, data)
    if not candidates:
        return {"status": "clarify", "stamp": None, "pack_metric": None}
    enabled = [c for c in candidates if _tier_enabled(c[0], data["policy"])]
    if not enabled:
        return {"status": "fallback_disabled", "tier": candidates[0][0], "metric_id": candidates[0][1], "stamp": None, "pack_metric": None}

    tier, metric_id, metric, pack = enabled[0]
    source = "global" if tier == "global" else "industry"
    level = "L3" if tier == "global" else "L2"

    effective = metric
    formula_source = tier
    delegated_from = None
    if metric.get("delegates_to") or "formula" not in metric:
        target_tier = str(metric.get("delegates_to") or "global")
        target_pack = data["packs"].get(target_tier)
        target_metric = (target_pack or {}).get("data", {}).get("metrics", {}).get(metric_id) if target_pack else None
        if not isinstance(target_metric, Mapping) or "formula" not in target_metric:
            return {"status": "clarify", "stamp": None, "pack_metric": None}
        effective = {**metric, "formula": target_metric["formula"], "default_filters": metric.get("default_filters") or target_metric.get("default_filters", [])}
        formula_source = target_tier
        delegated_from = target_tier

    stamp = _stamp(
        metric_id=metric_id, source=source, level=level,
        metric_version=str(metric.get("version") or ""),
        pack_version=pack["version"], pack_hash=pack["hash"], data=data,
        formula_source=formula_source, delegated_from=delegated_from,
    )
    return {"status": "resolved", "metric_source": source, "stamp": stamp, "pack_metric": effective, "tier": tier}


# --- structured-formula plan verification ------------------------------------

def _formula_terms(formula: Mapping[str, Any]) -> list[dict[str, Any]]:
    if formula.get("type") in {"sum", "difference"}:
        return list(formula.get("terms") or [])
    return list((formula.get("numerator") or {}).get("terms") or []) + list((formula.get("denominator") or {}).get("terms") or [])


def validate_metric_plan(plan: Mapping[str, Any], pack_metric: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    formula = pack_metric.get("formula") or {}
    mapping: dict[str, Any] = {}
    expected: set[tuple[str, str]] = set()
    for term in _formula_terms(formula):
        role = str(term.get("role"))
        status, result = map_role(contract, role)
        if status == "unmapped":
            return {"refused": "metric_required_fields_unmapped", "role": role, "mapping": mapping}
        if status == "ambiguous":
            return {"refused": "metric_role_ambiguous", "role": role, "candidates": result, "mapping": mapping}
        if status == "unknown_role":
            return {"refused": "metric_pack_invalid", "role": role, "mapping": mapping}
        mapping[role] = result
        expected.add((result, str(term.get("agg"))))

    # Only AGGREGATED selects are metric terms; extra group-by dimensions are allowed.
    actual = {
        (str(item["field"]), str(item.get("aggregation")))
        for item in plan.get("select", []) or []
        if isinstance(item, Mapping) and item.get("field") and item.get("aggregation")
    }

    caveats: list[str] = []
    for flt in pack_metric.get("default_filters", []) or []:
        status, status_field = map_role(contract, str(flt.get("role")))
        if status != "ok":
            code = "metric_role_ambiguous" if status == "ambiguous" else "metric_required_fields_unmapped"
            return {"refused": code, "role": flt.get("role"), "mapping": mapping}
        value = map_value_role(contract, str(flt.get("value_role")), status_field)
        if value is None:
            return {"refused": "metric_required_fields_unmapped", "role": flt.get("value_role"), "mapping": mapping}
        present = [f for f in plan.get("filters", []) or [] if str(f.get("field")) == status_field]
        if not present:
            return {"refused": "metric_plan_mismatch", "reason": f"required default filter {status_field} {flt.get('op')} {value} is missing", "mapping": mapping}
        if not any(str(f.get("value")).casefold() == value and str(f.get("operator")) == str(flt.get("op")) for f in present):
            caveats.append(f"status_override: {status_field} differs from default {value!r}; not the standard metric")

    if str(formula.get("type")) == "ratio":
        if not expected.issubset(actual):
            return {"refused": "metric_plan_mismatch", "reason": "ratio inputs not all selected", "mapping": mapping}
        caveats.append("ratio metric: inputs verified, division not computed by MCP in v1")
        return {"inputs_verified": True, "formula_verified": False, "caveat": "; ".join(caveats) or None, "mapping": mapping}

    if actual != expected:
        return {"refused": "metric_plan_mismatch", "reason": f"metric term aggregates {sorted(actual)} do not match formula {sorted(expected)}", "mapping": mapping}
    # MCP returns the separate aggregates; it does not compute the derived
    # difference/multi-term arithmetic. formula_verified is true only when the
    # single aggregate IS the metric value; otherwise inputs are verified, not the
    # derived metric.
    terms = formula.get("terms") or []
    single_aggregate = str(formula.get("type")) == "sum" and len(terms) == 1 and str(terms[0].get("sign", "+")) == "+"
    if not single_aggregate:
        caveats.append("derived arithmetic not computed by MCP in v1; inputs and filters verified")
    formula_verified = single_aggregate and not any(c.startswith("status_override") for c in caveats)
    return {"inputs_verified": True, "formula_verified": formula_verified, "caveat": "; ".join(caveats) or None, "mapping": mapping}


def resolve_and_validate_metric(metric_id: str, plan: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    resolution = resolve_metric(metric_id, contract)
    if resolution["status"] == "clarify":
        return {"refused": "metric_unknown_clarify", "metric_id": metric_id}
    if resolution["status"] == "fallback_disabled":
        return {"refused": "metric_fallback_disabled", "metric_id": resolution.get("metric_id"), "tier": resolution.get("tier")}
    if resolution["metric_source"] == "customer":
        return {"stamp": resolution["stamp"]}
    verdict = validate_metric_plan(plan, resolution["pack_metric"], contract)
    if verdict.get("refused"):
        return {"refused": verdict["refused"], **{k: v for k, v in verdict.items() if k != "refused"}}
    stamp = dict(resolution["stamp"])
    stamp["inputs_verified"] = verdict.get("inputs_verified", False)
    stamp["formula_verified"] = verdict["formula_verified"]
    stamp["caveat"] = verdict["caveat"]
    stamp["required_field_mapping"] = verdict["mapping"]
    return {"stamp": stamp}
