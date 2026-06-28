# Module Reference

All modules live under `recosearch/`. This document covers the purpose and public interface of each.

## Entry point

### `mcp_server.py` (root)

CLI entry point and FastMCP server setup. Registers all MCP tools and implements the boot guard (contract validation on startup). Also exposes `--write-semantic-json`, `--validate`, `--health-check`, and `--check-semantic-json` subcommands.

---

## Core infrastructure

### `config.py`

Loads and resolves connections from `source_config.yaml`, including `${ENV_VAR}` substitution (an unset variable is left as the literal ref so the connection fails loudly rather than using a blank secret). Capability/source resolution helpers live here; malformed config raises `BoundaryError`, and `validate_source_config()` returns structured issues without raising.

### `settings.py`

Server-level constants and paths: the active scenario directory (`RECOSEARCH_SEMANTIC_DIR` → `SEMANTIC_DIR`, `SOURCE_CONFIG_PATH`, `SEMANTIC_MD_PATH`, `SCENARIO_PATH`, `SEMANTIC_JSON_PATH`), the embedding model, and the row ceilings `MAX_SOURCE_ROWS` (100) and `MAX_FEDERATION_ROWS` (500). Other env vars (`RECOSEARCH_CONTRACT_ENFORCEMENT`, `RECOSEARCH_ROLE`, `RECOSEARCH_TRACING_ENABLED`) are read where they are used.

### `session.py`

Per-request session state. Holds the active role, request ID, and accumulated evidence envelopes for a single tool call chain.

### `errors.py`

Custom exception hierarchy. `BoundaryError` is the base for all user-facing errors; subtypes map to structured error codes returned to the LLM.

---

## Contract layer

### `contract.py`

`compile_semantic_contract()` compiles the three authority files into the structured contract (a dict). `validated_contract()` returns a `ValidatedContract` exposing `.is_valid`, `.errors`, `.issues`, and `.contract`.

### `contract_schema.py`

JSON Schema definitions used to validate the compiled contract structure.

### `scenario.py`

Loads `semantic/scenario_config.yaml` and returns a `Scenario` object with identity fields and governance blocks.

### `rules.py`

Global-rule compiler. Parses `active:` rules from `semantic.md` into structured predicates that the tool layer can attach to queries.

### `metric_resolver.py` / `metric_resolver_schema.py`

Metric definition parser and schema. Reads metric declarations from `semantic.md` and validates them.

### `field_roles.py`

Classifies fields by role (dimension, measure, identifier, body_text, score, etc.) using the vocabulary in `scenario_config.yaml` and built-in defaults.

### `vocabularies.py`

Domain vocabulary management. Merges built-in neutral defaults with scenario-specific extensions from `scenario_config.yaml`.

---

## Governance

### `rbac.py`

Role-based access control. `rbac_gate(func)` wraps each tool so a disallowed role gets a refusing stub (a known role missing the tool → `role_not_permitted`; an unknown role → deny-all `role_not_recognized`). `is_tool_allowed(role, tool_name, roles)` is the underlying check, consulting the `roles` block from `scenario_config.yaml`. With `RECOSEARCH_ROLE` unset, RBAC is off.

### `acl.py`

Field-level access control and masking. `mask_result(func)` wraps each tool so that, for callers whose role is not in `unmasked_roles`, values of the `access.sensitive_fields` columns are replaced with the configured mask string (default `***MASKED***`). No-op when masking does not apply.

---

## Tool layer

### `tools.py`

Registers all MCP tool handlers with FastMCP. Each handler validates the request, dispatches to the appropriate adapter, wraps the result in an evidence envelope, applies ACL masking, and returns a structured response.

### `analysis_request.py`

`validate_analysis_request(request)` validates an inbound analysis intent against the compiled semantic contract and returns a structured dict — either ready-to-run, or a `clarification_needed` response listing exactly which inputs (metric, time window, source) are missing.

### `entity_resolution.py`

Resolves free-text entity references (product names, seller names, etc.) to declared identifiers using the semantic contract.

### `conflicts.py`

Detects and resolves conflicts when the same entity or metric is referenced across multiple sources.

---

## Adapters

All adapters live in `recosearch/adapters/`.

### `base.py`

Defines the `SourceAdapter` frozen dataclass — the plugin contract for every adapter. Its fields: `source_type` (str), `capabilities` (frozenset, e.g. `{"structured_query"}`), `run_query` (the capability executor callable), `sql_dialect` (sqlglot dialect for SQL sources, else `None`), `health_check` (optional callable), `available` (bool — capabilities are advertised only when `True`), and `config_schema` (per-adapter connection-key schema). Each adapter module declares a module-level `ADAPTER = SourceAdapter(...)`; `adapters/__init__.py` auto-discovers them.

### `duckdb.py`

DuckDB adapter. Implements `structured_query` against a local DuckDB file (no server) — the zero-infrastructure source behind `examples/novashop-duckdb`. Driver import is lazy; `available` is gated on the `duckdb` driver being installed.

### `postgres.py`

PostgreSQL adapter. Implements `structured_query` via `psycopg2` (lazy import). `validate_postgres_sql()` uses `sqlglot` to reject non-`SELECT` statements before execution.

### `opensearch.py`

OpenSearch adapter. Implements `text_search` via `opensearch-py`. Translates structured text-search requests into OpenSearch Query DSL.

### `qdrant.py`

Qdrant adapter. Implements `vector_search` via `qdrant-client`. Generates embeddings via `sentence-transformers` and performs nearest-neighbour search.

### `snowflake.py`

Snowflake adapter. Implements `structured_query` via `snowflake-connector-python`. Driver import is lazy — the package is only loaded if a Snowflake source is declared and available.

### `mongodb.py`

MongoDB adapter. Implements `document_query` via `pymongo`. Driver import is lazy.

---

## Evidence and citations

### `evidence_validator.py`

Cited-evidence validation. `validate_cited_evidence_packet(packet)` verifies the full evidence closure for a set of final-answer claims: each claim's `evidence_ids` must resolve to a citation/provenance envelope that is claim-supporting and pinned to the current contract hash, else the packet is refused with per-claim errors. (Provenance records and per-row `_citation` objects are produced in `citations.py`.)

### `evidence_schema.py`

JSON Schema for evidence envelopes and cited-evidence packets.

### `citations.py`

Citation tracking within a session. Accumulates envelopes across tool calls so the final packet can be cross-validated.

---

## Federation

### `federation.py`

`combine_slices(left_rows, right_rows, left_key, right_key, ...)` performs a bounded, deterministic join over two row slices already returned by MCP tools. It refuses (`undeclared_relation`) unless the two sources have a declared relation in `semantic.md`, and surfaces (never hides) any cross-slice contradictions in a `conflicts` list.

---

## Utilities

### `json_utils.py`

JSON serialization helpers. Handles types that the standard library serializer does not support (e.g. `Decimal`, `datetime`).

### `observability.py`

OpenTelemetry tracing setup. `init_tracing()` connects to Phoenix when `RECOSEARCH_TRACING_ENABLED=true`. The server fails open — if the tracing backend is unreachable the server starts untraced.
