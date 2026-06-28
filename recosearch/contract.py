from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .config import SourceRef, _assert_source_allowed, _source_refs, identifiers_for, validate_source_config
from .contract_schema import validate_structure
from .errors import SEVERITY_ERROR, SEVERITY_WARNING, BoundaryError, ContractIssue, ContractValidationError
from .field_roles import resolve_field_roles
from .rules import LIFECYCLE_STATES, compile_rules, parse_inline_status
from .scenario import Scenario, load_scenario, validate_scenario
from .settings import ROOT, SCENARIO_PATH, SEMANTIC_MD_PATH, SOURCE_CONFIG_PATH

_KNOWN_SECTIONS = {"metrics", "rules", "dimensions", "measures", "relations"}
_UNKNOWN_SECTION = "__unknown__"
_LIFECYCLE_STATES = set(LIFECYCLE_STATES)


def _parse_source_field(token: str) -> tuple[str, str, str] | None:
    pieces = token.strip().split(".")
    if len(pieces) != 3:
        return None
    return pieces[0], pieces[1], pieces[2]


def _path_label(path: Any) -> str:
    """Repo-relative path label for provenance; falls back to the path name when
    the input directory lives outside the repo root (custom RECOSEARCH_SEMANTIC_DIR)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _empty_contract(source_refs: Mapping[str, SourceRef], scenario: Scenario) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "artifact_kind": "runtime_contract",
        "artifact_id": scenario.artifact_id,
        "dataset_id": scenario.dataset_id,
        "name": scenario.name,
        "version": "1.0",
        "evidence_boundary": "source_config_yaml_and_semantic_md_only",
        "source_reference": {
            "semantic": _path_label(SEMANTIC_MD_PATH),
            "source_config": _path_label(SOURCE_CONFIG_PATH),
        },
        "sources": {},
        "metrics": {},
        "rules": [],
        "dimensions": {},
        "measures": {},
        "relations": [],
        "tables": {},
    }
    for source_id, ref in source_refs.items():
        source_entry: dict[str, Any] = {"type": ref.source_type}
        # Copy declared location identifiers (database / index / collection / ...)
        # generically from the source-type's config schema, so a new source type
        # surfaces its location keys without per-type branches here.
        for key in identifiers_for(ref.source_type):
            value = ref.config.get(key)
            if value is not None:
                source_entry[key] = value
        contract["sources"][source_id] = source_entry
    return contract


def _parse_semantic(
    semantic_text: str,
    source_refs: Mapping[str, SourceRef],
    scenario: Scenario,
) -> tuple[dict[str, Any], list[ContractIssue]]:
    """Parse semantic.md into a contract, collecting structured issues instead of
    silently dropping malformed input."""
    contract = _empty_contract(source_refs, scenario)
    issues: list[ContractIssue] = []
    seen_field_tokens: set[str] = set()
    raw_rules: list[dict[str, Any]] = []
    rules_had_subsection = False

    section: str | None = None
    rule_status: str | None = None
    for raw_line in semantic_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            name = line.lstrip("#").strip().casefold()
            if level == 1:
                rule_status = None
                if name in _KNOWN_SECTIONS:
                    section = name
                else:
                    section = _UNKNOWN_SECTION
                    issues.append(ContractIssue("unknown_section", SEVERITY_ERROR, f"semantic.md:{name}", f"unknown section heading {name!r}; expected one of {sorted(_KNOWN_SECTIONS)}"))
            elif section == "rules":
                rules_had_subsection = True
                if name in _LIFECYCLE_STATES:
                    rule_status = name
                else:
                    rule_status = None
                    issues.append(ContractIssue("rule_status_unknown", SEVERITY_ERROR, "semantic.md:rules", f"unknown rule status subsection {name!r}; expected one of {sorted(_LIFECYCLE_STATES)}"))
            else:
                issues.append(ContractIssue("subsection_outside_rules", SEVERITY_ERROR, f"semantic.md:{name}", f"'##' status subsection {name!r} is only valid under '# rules'"))
            continue
        if not line.startswith("- "):
            continue
        item = line[2:].strip()

        if section is None:
            issues.append(ContractIssue("bullet_ignored", SEVERITY_ERROR, "semantic.md", f"bullet outside any section: {item!r}"))
            continue
        if section == _UNKNOWN_SECTION:
            continue  # heading already flagged via unknown_section

        loc = f"semantic.md:{section}"
        if section == "metrics":
            if ":" not in item:
                issues.append(ContractIssue("malformed_metric", SEVERITY_ERROR, loc, f"metric line missing ':' separator: {item!r}"))
                continue
            name, definition = item.split(":", 1)
            metric_id = _slug(name)
            if metric_id in contract["metrics"]:
                issues.append(ContractIssue("metric_id_collision", SEVERITY_ERROR, loc, f"metric label {name.strip()!r} collides on id {metric_id!r}"))
            contract["metrics"][metric_id] = {
                "metric_id": metric_id,
                "label": name.strip(),
                "definition": definition.strip(),
            }
        elif section == "rules":
            # Prefer an inline "- <status>: <text>" label; fall back to the
            # enclosing "## <status>" subsection (back-compat) when absent.
            inline_status, rule_text = parse_inline_status(item)
            raw_rules.append({"text": rule_text, "status": inline_status if inline_status is not None else rule_status})
        elif section in {"dimensions", "measures"}:
            if ":" not in item:
                issues.append(ContractIssue("malformed_field_token", SEVERITY_ERROR, loc, f"{section} line missing ':' separator: {item!r}"))
                continue
            token, description = item.split(":", 1)
            token = token.strip()
            parsed = _parse_source_field(token)
            if not parsed:
                issues.append(ContractIssue("malformed_field_token", SEVERITY_ERROR, loc, f"field token {token!r} is not 'source.table.column'"))
                continue
            source_id, table, column = parsed
            if source_id not in source_refs:
                issues.append(ContractIssue("unknown_source", SEVERITY_ERROR, loc, f"field {token!r} references undeclared source {source_id!r}"))
                continue
            if token in seen_field_tokens:
                issues.append(ContractIssue("duplicate_field_id", SEVERITY_ERROR, loc, f"field {token!r} declared more than once"))
            seen_field_tokens.add(token)
            field = {
                "source": source_id,
                "table": table,
                "column": column,
                "description": description.strip(),
            }
            if section == "measures":
                default = _default_aggregation(description)
                if default:
                    field["default_aggregation"] = default
            contract[section][token] = field
            table_entry = contract["tables"].setdefault(
                table,
                {"source": source_id, "columns": {}, "column_names": []},
            )
            if table_entry["source"] != source_id:
                issues.append(ContractIssue("table_in_multiple_sources", SEVERITY_ERROR, loc, f"table {table!r} appears in multiple sources"))
            table_entry["columns"][column] = field
            if column not in table_entry["column_names"]:
                table_entry["column_names"].append(column)
        elif section == "relations":
            if "=" not in item:
                issues.append(ContractIssue("malformed_relation", SEVERITY_ERROR, loc, f"relation line missing '=': {item!r}"))
                continue
            left, right = [piece.strip() for piece in item.split("=", 1)]
            l_parsed = _parse_source_field(left)
            r_parsed = _parse_source_field(right)
            if not l_parsed or not r_parsed:
                issues.append(ContractIssue("malformed_relation", SEVERITY_ERROR, loc, f"relation requires 'source.table.column = source.table.column': {item!r}"))
                continue
            if l_parsed[0] not in source_refs:
                issues.append(ContractIssue("unknown_source", SEVERITY_ERROR, loc, f"relation references undeclared source {l_parsed[0]!r}"))
                continue
            if r_parsed[0] not in source_refs:
                issues.append(ContractIssue("unknown_source", SEVERITY_ERROR, loc, f"relation references undeclared source {r_parsed[0]!r}"))
                continue
            contract["relations"].append({"left": left, "right": right})

    compile_rules(raw_rules, rules_had_subsection, contract, issues)
    return contract, issues


def _build_contract(
    semantic_text: str | None = None,
    source_refs: Mapping[str, SourceRef] | None = None,
    scenario: Scenario | None = None,
) -> tuple[dict[str, Any], list[ContractIssue]]:
    refs = source_refs if source_refs is not None else _source_refs()
    text = semantic_text if semantic_text is not None else SEMANTIC_MD_PATH.read_text(encoding="utf-8")
    scenario = scenario if scenario is not None else load_scenario()
    contract, parse_issues = _parse_semantic(text, refs, scenario)
    contract["field_roles"] = resolve_field_roles(contract)
    contract["contract_hash"] = _contract_hash(contract)
    return contract, parse_issues


def compile_semantic_contract(
    semantic_text: str | None = None,
    source_refs: Mapping[str, SourceRef] | None = None,
) -> dict[str, Any]:
    """Compile semantic.md + source_config.yaml into a structured contract.

    Thin back-compat wrapper: builds the contract (including ``contract_hash``)
    without running validation, so existing hot-path callers are unchanged. Use
    ``validated_contract()`` / ``compile_with_issues()`` for the hardened path.
    """
    contract, _issues = _build_contract(semantic_text, source_refs)
    return contract


def _contract_hash(contract: Mapping[str, Any]) -> str:
    without_hash = {key: value for key, value in contract.items() if key != "contract_hash"}
    digest = hashlib.sha256(_canonical_bytes(without_hash)).hexdigest()
    return f"sha256:{digest}"


def _canonical_bytes(contract: Mapping[str, Any]) -> bytes:
    return (json.dumps(contract, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_contract_json(contract: Mapping[str, Any]) -> str:
    """The single canonical serialization used for both writing and freshness."""
    return json.dumps(contract, indent=2, sort_keys=True) + "\n"


def validate_contract(contract: Mapping[str, Any]) -> list[ContractIssue]:
    """Post-compile structural, semantic-structure, and presence validation.

    Non-raising; returns structured issues. Parse-time and source-config issues
    are added separately by ``compile_with_issues`` / ``validated_contract``.
    """
    issues: list[ContractIssue] = list(validate_structure(contract))

    field_ids = set(contract.get("dimensions", {})) | set(contract.get("measures", {}))
    for index, relation in enumerate(contract.get("relations", []) or []):
        if not isinstance(relation, Mapping):
            continue
        for side in ("left", "right"):
            ref = str(relation.get(side) or "")
            if ref and ref not in field_ids:
                issues.append(ContractIssue("relation_references_undeclared_field", SEVERITY_ERROR, f"semantic.md:relations[{index}]", f"relation {side} {ref!r} is not a declared dimension/measure"))

    # Presence checks.
    if not contract.get("dimensions"):
        issues.append(ContractIssue("no_dimensions", SEVERITY_ERROR, "semantic.md:dimensions", "no dimensions declared"))
    if not contract.get("measures"):
        issues.append(ContractIssue("no_measures", SEVERITY_ERROR, "semantic.md:measures", "no measures declared"))
    if not contract.get("metrics"):
        issues.append(ContractIssue("no_metrics", SEVERITY_WARNING, "semantic.md:metrics", "no metrics declared"))
    if not contract.get("rules"):
        issues.append(ContractIssue("no_rules", SEVERITY_WARNING, "semantic.md:rules", "no rules declared"))
    if not contract.get("relations"):
        severity = SEVERITY_ERROR if len(contract.get("sources", {})) > 1 else SEVERITY_WARNING
        issues.append(ContractIssue("no_relations", severity, "semantic.md:relations", "no relations declared while multiple sources exist" if severity == SEVERITY_ERROR else "no relations declared"))

    return issues


def compile_with_issues(
    semantic_text: str | None = None,
    source_refs: Mapping[str, SourceRef] | None = None,
    config_text: str | None = None,
    scenario_text: str | None = None,
) -> tuple[dict[str, Any], list[ContractIssue]]:
    """Full hardened compile: parse + scenario + source-config + contract
    validation. Inputs may be injected for offline tests."""
    scenario = load_scenario(scenario_text) if scenario_text is not None else None
    contract, parse_issues = _build_contract(semantic_text, source_refs, scenario)
    scenario_issues = validate_scenario(scenario_text)
    source_issues = validate_source_config(config_text)
    issues = [*parse_issues, *scenario_issues, *source_issues, *validate_contract(contract)]
    return contract, issues


@dataclass(frozen=True)
class ValidatedContract:
    contract: dict[str, Any]
    issues: list[ContractIssue]

    @property
    def errors(self) -> list[ContractIssue]:
        return [issue for issue in self.issues if issue.is_error]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            raise ContractValidationError(self.issues)


_VALIDATED_CACHE: dict[str, ValidatedContract] = {}


def validated_contract() -> ValidatedContract:
    """Compiled + validated contract for the declared inputs, cached on input
    content. This is the hardened path used by CLI, tests, and tool gating."""
    semantic_text = SEMANTIC_MD_PATH.read_text(encoding="utf-8")
    config_text = SOURCE_CONFIG_PATH.read_text(encoding="utf-8")
    scenario_text = SCENARIO_PATH.read_text(encoding="utf-8") if SCENARIO_PATH.exists() else ""
    key = hashlib.sha256("\0".join((semantic_text, config_text, scenario_text)).encode("utf-8")).hexdigest()
    cached = _VALIDATED_CACHE.get(key)
    if cached is None:
        contract, issues = compile_with_issues(semantic_text=semantic_text, config_text=config_text, scenario_text=scenario_text)
        cached = ValidatedContract(contract=contract, issues=issues)
        _VALIDATED_CACHE[key] = cached
    return cached


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().casefold()).strip("_")


def _default_aggregation(description: str) -> str | None:
    lowered = description.casefold()
    if "default sum" in lowered:
        return "sum"
    if "default average" in lowered:
        return "avg"
    return None


def _contract_id() -> str:
    return str(compile_semantic_contract()["artifact_id"])


def _contract_hash_id() -> str:
    """Content identity of the current contract; used to pin evidence to the exact contract version that produced it."""
    return str(compile_semantic_contract().get("contract_hash") or "")


def _global_rule_filters_for_tables(tables: Iterable[str]) -> list[dict[str, Any]]:
    contract = compile_semantic_contract()
    table_set = set(tables)
    rules: list[dict[str, Any]] = []
    for exclusion in contract.get("exclusions", []):
        if not isinstance(exclusion, dict):
            continue
        if exclusion.get("table") in table_set:
            rules.append(
                {
                    "rule_id": exclusion.get("rule_id"),
                    "rule_type": exclusion.get("rule_type"),
                    "effect": exclusion.get("effect"),
                    "application_mode": exclusion.get("application_mode"),
                    "scope": exclusion.get("scope"),
                    "source": exclusion.get("source"),
                    "table": exclusion.get("table"),
                    "column": exclusion.get("column"),
                    "operator": exclusion.get("operator"),
                    "value": exclusion.get("value"),
                    "reason": exclusion.get("reason"),
                }
            )
    return rules


def _field_index(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for section in ("dimensions", "measures"):
        for field_id, field in contract.get(section, {}).items():
            if isinstance(field, dict):
                fields[field_id] = {**field, "field_id": field_id, "semantic_kind": section[:-1]}
    return fields


def _source_ids_by_type(contract: Mapping[str, Any], source_type: str) -> list[str]:
    return sorted(
        source_id
        for source_id, source in contract.get("sources", {}).items()
        if isinstance(source, Mapping) and source.get("type") == source_type
    )


def _source_ids_with_capability(contract: Mapping[str, Any], capability: str) -> list[str]:
    """Source ids whose declared adapter type provides ``capability`` (e.g.
    ``structured_query``). Governance keys off capability, not a literal source
    type, so any SQL-capable adapter (postgres, snowflake, ...) is covered."""
    from .adapters import capabilities_for

    return sorted(
        source_id
        for source_id, source in contract.get("sources", {}).items()
        if isinstance(source, Mapping) and capability in capabilities_for(str(source.get("type") or ""))
    )


def _source_id_by_type(contract: Mapping[str, Any], source_type: str) -> str:
    ids = _source_ids_by_type(contract, source_type)
    if not ids:
        raise BoundaryError(f"no {source_type} source is declared in source_config.yaml")
    if len(ids) > 1:
        raise BoundaryError(f"multiple {source_type} sources are declared; specify one of {ids}")
    return ids[0]


def _fields_for_source_type(
    contract: Mapping[str, Any],
    source_type: str,
    *,
    table: str | None = None,
) -> dict[str, dict[str, Any]]:
    source_ids = set(_source_ids_by_type(contract, source_type))
    fields: dict[str, dict[str, Any]] = {}
    for field_id, field in _field_index(contract).items():
        if field.get("source") not in source_ids:
            continue
        if table is not None and field.get("table") != table:
            continue
        fields[field_id] = field
    return fields


def _field_ids_for_source_type(
    contract: Mapping[str, Any],
    source_type: str,
    *,
    table: str | None = None,
) -> list[str]:
    return sorted(_fields_for_source_type(contract, source_type, table=table))


def _tables_for_source_type(contract: Mapping[str, Any], source_type: str) -> list[str]:
    return sorted(
        {
            str(field.get("table"))
            for field in _fields_for_source_type(contract, source_type).values()
            if field.get("table")
        }
    )


def _first_table_for_source_type(contract: Mapping[str, Any], source_type: str) -> str:
    tables = _tables_for_source_type(contract, source_type)
    if not tables:
        raise BoundaryError(f"no declared {source_type} table/index/collection fields found in semantic.md")
    return tables[0]


def _table_for_source(contract: Mapping[str, Any], source_id: str) -> str:
    source = contract.get("sources", {}).get(source_id, {})
    table = source.get("index") or source.get("collection") if isinstance(source, Mapping) else None
    if table:
        return str(table)
    for section in ("dimensions", "measures"):
        for field in contract.get(section, {}).values():
            if isinstance(field, Mapping) and field.get("source") == source_id and field.get("table"):
                return str(field["table"])
    raise BoundaryError(f"no declared table for source {source_id!r}")


def _postgres_field(field_id: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    field = _field_index(contract).get(field_id)
    if not field:
        raise BoundaryError(f"field {field_id!r} is not declared in semantic.md")
    if field.get("source") not in _source_ids_with_capability(contract, "structured_query"):
        raise BoundaryError(f"field {field_id!r} is not a structured-query field")
    return field


def _declared_relation_pairs(contract: Mapping[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for relation in contract.get("relations", []):
        if not isinstance(relation, dict):
            continue
        left = str(relation.get("left") or "")
        right = str(relation.get("right") or "")
        if left and right:
            pairs.add((left, right))
            pairs.add((right, left))
    return pairs
