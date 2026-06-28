"""Rule compiler for semantic.md.

Compiles each business rule written in semantic.md into typed metadata. Lifecycle
status is authored inline in semantic.md (## <status> subsections); everything
else is generated here. No sidecar, no new input file, no DSL.

Classifiers parse GENERIC linguistic shapes and resolve against DECLARED
fields/metrics — never fixture values.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .errors import SEVERITY_ERROR, SEVERITY_WARNING, ContractIssue
from .vocabularies import filter_stopwords, metric_stopwords

LIFECYCLE_STATES = ("draft", "review", "approved", "active", "deprecated", "superseded", "suspended")
_ENFORCED_STATE = "active"

# Friendly inline labels (the word before the colon in "- <label>: <rule>") map
# to canonical lifecycle states. Tolerates common variants/typos so authors can
# tag a rule's lifecycle in the line itself instead of grouping by subsection.
_STATUS_ALIASES = {
    "active": "active",
    "approve": "approved", "approved": "approved",
    "review": "review", "in_review": "review", "in-review": "review",
    "deprecate": "deprecated", "deprecated": "deprecated", "depricate": "deprecated", "depricated": "deprecated",
    "suspend": "suspended", "suspended": "suspended",
    "draft": "draft",
    "supersede": "superseded", "superseded": "superseded",
}


def parse_inline_status(rule_line: str) -> tuple[str | None, str]:
    """Split an inline-typed rule line ``"<label>: <text>"`` into a canonical
    lifecycle status and the bare rule text.

    Returns ``(status, text)`` when the part before the first colon is a known
    status label; otherwise ``(None, rule_line)`` so the caller can fall back to
    a ``## <status>`` subsection or the back-compat default. The returned text is
    stripped of the label so classification and rule ids stay label-independent.
    """
    if ":" not in rule_line:
        return None, rule_line
    prefix, rest = rule_line.split(":", 1)
    status = _STATUS_ALIASES.get(prefix.strip().casefold())
    if status is None:
        return None, rule_line
    return status, rest.strip()

# Generic exclusion verbs/phrases (not paired with a specific scenario value).
_EXCLUSION_VERB_RE = re.compile(
    r"\b(?:ignore|exclude|omit|remove|drop|do not include|don't include|do not count|don't count|blacklist(?:ed)?)\b",
    re.IGNORECASE,
)
# Broader negative/exclusion wording used only to flag ambiguous rules.
_NEGATIVE_WORD_RE = re.compile(
    r"\b(?:not|never|avoid|skip|disregard|exclude|ignore|omit|remove|drop|blacklist(?:ed)?|leave out|without)\b",
    re.IGNORECASE,
)
# Identifier-like value token (e.g. P003, CUST-1, SKU-9, WIDG).
_VALUE_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*)\b")
_THRESHOLD_RE = re.compile(r"\b(?:more than|greater than|over|at least|>)\s*(\d+)\b", re.IGNORECASE)
_STATE_RE = re.compile(r"\bunder\s+(?:a\s+)?([a-z][a-z ]+?)(?:\s+(?:until|on|and)\b|[.,]|$)", re.IGNORECASE)
_PRECEDENCE_RE = re.compile(r"\bnot\b[^.]*\boverrid", re.IGNORECASE)
_DEFAULT_FILTER_RE = re.compile(r"\b(?:must use|use|using|only use)\b", re.IGNORECASE)
_BINDING_VERB_RE = re.compile(r"\b(?:must use|use|using|must be|based on)\b", re.IGNORECASE)

# Stopwords: domain-neutral defaults + scenario domain nouns from
# the scenario 'vocabularies' block (a new domain extends config, not this module).
_METRIC_STOP = metric_stopwords()
_FILTER_STOP = filter_stopwords()


def rule_id_for(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().casefold())
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().casefold()).strip("_")


def _field_index(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for section in ("dimensions", "measures"):
        for field_id, field in contract.get(section, {}).items():
            if isinstance(field, Mapping):
                fields[field_id] = {**field, "field_id": field_id}
    return fields


def _resolve_fields_by_columns(contract: Mapping[str, Any], columns: set[str]) -> list[dict[str, Any]]:
    """All declared fields whose column matches — an exclusion applies to every
    table/source carrying that identifier (e.g. P003 across orders/products/reviews)."""
    return [field for field in _field_index(contract).values() if str(field.get("column") or "") in columns]


def _norm(token: str) -> str:
    return token[:-1] if token.endswith("s") and len(token) > 3 else token


def _resolve_value_to_field(contract: Mapping[str, Any], value: str) -> dict[str, Any] | None:
    """Resolve a filter value word (e.g. a status token) to a declared dimension
    whose description mentions it. Generic — driven by declared descriptions."""
    needle = value.casefold()
    for field in _field_index(contract).values():
        if needle and needle in str(field.get("description") or "").casefold():
            return field
    return None


def _resolve_field_reference(contract: Mapping[str, Any], text: str) -> str | None:
    """Resolve a field reference by full field id, column name (token or words),
    or a distinctive description token. Generic — declared-field driven."""
    lowered = text.casefold()
    fields = _field_index(contract)
    for field_id in fields:
        if field_id.casefold() in lowered:
            return field_id
    for field_id, field in fields.items():
        column = str(field.get("column") or "").casefold()
        if column and (
            re.search(rf"\b{re.escape(column)}\b", lowered)
            or re.search(rf"\b{re.escape(column.replace('_', ' '))}\b", lowered)
        ):
            return field_id
    token_owners: dict[str, set[str]] = {}
    for field_id, field in fields.items():
        for token in set(re.findall(r"[a-z]{6,}", str(field.get("description") or "").casefold())):
            token_owners.setdefault(token, set()).add(field_id)
    for token in re.findall(r"[a-z]{6,}", lowered):
        owners = token_owners.get(token)
        if owners and len(owners) == 1:
            return next(iter(owners))
    return None


def _match_metric(contract: Mapping[str, Any], text: str) -> str | None:
    """Best-effort plural-insensitive match of a metric label (minus stopwords)
    against the rule text. E.g. 'bad reviews' -> 'bad review count'."""
    words = {_norm(word) for word in re.findall(r"[a-z]+", text.casefold())}
    best_id: str | None = None
    best_score = 0.0
    for metric_id, metric in contract.get("metrics", {}).items():
        label_tokens = [_norm(token) for token in re.findall(r"[a-z]+", str(metric.get("label") or "").casefold())]
        significant = [token for token in label_tokens if token not in _METRIC_STOP]
        if not significant:
            continue
        score = sum(1 for token in significant if token in words) / len(significant)
        if score > best_score:
            best_score, best_id = score, metric_id
    return best_id if best_score >= 0.6 else None


def _exclusion_value(text: str) -> str | None:
    for match in _VALUE_TOKEN_RE.finditer(text):
        token = match.group(1)
        if len(token) >= 3 or any(char.isdigit() for char in token) or "-" in token or "_" in token:
            return token
    return None


def _detect_exclusion(text: str, contract: Mapping[str, Any]) -> dict[str, Any] | None:
    """Detect a row-exclusion intent from generic exclusion wording + an
    identifier-like value, then resolve the entity against declared fields."""
    if not _EXCLUSION_VERB_RE.search(text):
        return None
    value = _exclusion_value(text)
    if not value:
        return None
    before = re.search(r"\b([a-z][a-z_]+)\s+" + re.escape(value), text, re.IGNORECASE)
    entity = _slug(before.group(1)).removesuffix("_") if before else None
    fields = _resolve_fields_by_columns(contract, {f"{entity}_id", entity}) if entity else []
    return {"value": value, "entity": entity, "fields": fields}


def _default_filter_value(contract: Mapping[str, Any], text: str) -> tuple[str | None, dict[str, Any] | None]:
    for word in re.findall(r"[a-z]+", text.casefold()):
        if word in _FILTER_STOP:
            continue
        field = _resolve_value_to_field(contract, word)
        if field:
            return word, field
    return None, None


def _classify(text: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    # 1. Enforceable row exclusion (generic verbs + identifier value).
    exclusion = _detect_exclusion(text, contract)
    if exclusion:
        if exclusion["fields"]:
            targets = [
                {"field_id": f["field_id"], "source": f["source"], "table": f["table"], "column": f["column"]}
                for f in exclusion["fields"]
            ]
            return {
                "rule_type": "row_exclusion", "effect": "exclude", "scope": "all_calculations",
                "compiled_policy": {"scope": "all_calculations", "operator": "!=", "value": exclusion["value"], "targets": targets},
            }
        return {"rule_type": "row_exclusion", "effect": "exclude", "scope": "all_calculations",
                "compiled_policy": None, "_unresolved": {"entity": exclusion["entity"], "value": exclusion["value"]}}

    # 2. Precedence ("... not ... override ...").
    if _PRECEDENCE_RE.search(text):
        return {"rule_type": "precedence", "effect": "reasoning_precedence", "scope": "global",
                "compiled_policy": {"directive": "must_not_override", "text": text.strip()}}

    # 3. Threshold / state ("more than N ...").
    threshold = _THRESHOLD_RE.search(text)
    if threshold:
        state = _STATE_RE.search(text)
        operator = ">=" if "at least" in text.casefold() else ">"
        return {"rule_type": "threshold_state", "effect": "state_classification", "scope": "metric",
                "compiled_policy": {
                    "subject_metric": _match_metric(contract, text),
                    "operator": operator, "value": int(threshold.group(1)),
                    "state": _slug(state.group(1)) if state else None,
                }}

    # 4. Metric default filter ("use ... only", either word order).
    if _DEFAULT_FILTER_RE.search(text) and re.search(r"\bonly\b", text, re.IGNORECASE):
        value, field = _default_filter_value(contract, text)
        policy: dict[str, Any] = {"directive": "default_filter"}
        if value:
            policy["value"] = value
        if field:
            policy["field_id"] = field["field_id"]
            policy["operator"] = "="
        return {"rule_type": "metric_default_filter", "effect": "metric_scope", "scope": "metric",
                "compiled_policy": policy}

    # 5. Metric field binding ("must use <declared field>").
    if _BINDING_VERB_RE.search(text):
        field_id = _resolve_field_reference(contract, text)
        if field_id:
            return {"rule_type": "metric_field_binding", "effect": "field_binding", "scope": "metric",
                    "compiled_policy": {"directive": "must_use", "field_id": field_id}}

    # 6. Advisory fallback.
    return {"rule_type": "advisory", "effect": "advisory", "scope": "global",
            "compiled_policy": {"note": text.strip()}}


def compile_rules(
    raw_rules: list[dict[str, Any]],
    rules_had_subsection: bool,
    contract: dict[str, Any],
    issues: list[ContractIssue],
) -> None:
    """Compile raw {text, status} rules into the contract's enriched rules and
    enforced exclusions. Mutates ``contract``."""
    enriched: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen_exclusion: set[tuple[str, str, str]] = set()

    for raw in raw_rules:
        text = str(raw.get("text") or "")
        status = raw.get("status")
        if status is None:
            if rules_had_subsection:
                issues.append(ContractIssue(
                    "rule_status_required", SEVERITY_ERROR, "semantic.md:rules",
                    f"bare rule needs a '## <status>' subsection once lifecycle subsections are used: {text!r}",
                ))
                status = "unstatused"  # not active -> not enforced
            else:
                status = _ENFORCED_STATE  # back-compat default when no subsections exist

        classified = _classify(text, contract)
        rule_type = classified["rule_type"]
        compiled_policy = classified["compiled_policy"]
        application_mode = "recorded_only"

        if status == _ENFORCED_STATE and rule_type == "row_exclusion":
            if compiled_policy is None:
                unresolved = classified.get("_unresolved") or {}
                issues.append(ContractIssue(
                    "enforceable_rule_not_compiled", SEVERITY_ERROR, "semantic.md:rules",
                    f"enforceable rule matched no declared field (entity {unresolved.get('entity')!r}, "
                    f"value {unresolved.get('value')!r}): {text!r}",
                ))
                application_mode = "unresolved"
            else:
                application_mode = "enforced"
                rule_id = rule_id_for(text)
                policy = compiled_policy
                for target in policy["targets"]:
                    key = (target["field_id"], policy["operator"], str(policy["value"]))
                    if key in seen_exclusion:
                        continue
                    seen_exclusion.add(key)
                    exclusions.append({
                        "scope": policy["scope"], "source": target["source"], "table": target["table"],
                        "column": target["column"], "field_id": target["field_id"],
                        "operator": policy["operator"], "value": policy["value"],
                        "reason": f"semantic.md declares: {text}",
                        "rule_id": rule_id, "rule_type": "row_exclusion", "effect": "exclude",
                        "application_mode": "enforced",
                    })

        if status == _ENFORCED_STATE and rule_type == "advisory":
            if _NEGATIVE_WORD_RE.search(text) and _exclusion_value(text):
                issues.append(ContractIssue(
                    "ambiguous_enforcement_rule", SEVERITY_WARNING, "semantic.md:rules",
                    f"active rule has an identifier-like value and exclusion/negative wording but did not compile "
                    f"to an enforceable rule: {text!r}",
                ))
            else:
                issues.append(ContractIssue(
                    "active_advisory_unstructured", SEVERITY_WARNING, "semantic.md:rules",
                    f"active rule compiled only as advisory (no structured policy): {text!r}",
                ))

        enriched.append({
            "rule_id": rule_id_for(text), "source": "semantic.md", "text": text, "status": status,
            "rule_type": rule_type, "effect": classified["effect"], "application_mode": application_mode,
            "scope": classified["scope"], "compiled_policy": compiled_policy,
        })

    contract["rules"] = enriched
    if exclusions:
        contract["exclusions"] = exclusions


def recorded_policies(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Active rules that are recorded policy (not enforced data guards)."""
    return [
        rule for rule in contract.get("rules", [])
        if isinstance(rule, Mapping)
        and rule.get("status") == _ENFORCED_STATE
        and rule.get("application_mode") == "recorded_only"
    ]


def _policy_field_ids(rule: Mapping[str, Any]) -> set[str]:
    policy = rule.get("compiled_policy")
    if not isinstance(policy, Mapping):
        return set()
    return {str(policy[key]) for key in ("field_id",) if policy.get(key)}


def relevant_recorded_policies(
    contract: Mapping[str, Any],
    *,
    source_id: str | None = None,
    table: str | None = None,
    field_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Recorded policies that reference a touched source/table/field. Policies
    with no resolvable field target are contract-level only (not attached here),
    so per-call context stays relevant and non-noisy."""
    touched_fields = field_ids or set()
    relevant: list[dict[str, Any]] = []
    for rule in recorded_policies(contract):
        policy_fields = _policy_field_ids(rule)
        if not policy_fields:
            continue
        hit = bool(policy_fields & touched_fields)
        if not hit and (source_id or table):
            for field_id in policy_fields:
                field = _field_index(contract).get(field_id, {})
                if (source_id and field.get("source") == source_id) or (table and field.get("table") == table):
                    hit = True
                    break
        if hit:
            relevant.append(rule)
    return relevant
