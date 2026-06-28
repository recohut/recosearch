# Changelog

All notable changes to RecoSearch are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Changes that make RecoSearch easy to try and easy to trust before the first
tagged release.

### Added
- **Zero-infrastructure DuckDB example** (`examples/novashop-duckdb/`): a single
  local `.duckdb` file source — no server, no credentials. Seed it deterministically
  with `python examples/novashop-duckdb/seed.py` (writes `novashop.duckdb` and
  `data/*.csv`), then point `RECOSEARCH_SEMANTIC_DIR` at the directory and run the
  standard `--write-semantic-json` / `--validate` / `--health-check` flow. The
  health check reports `ok` with no running services.
- **DuckDB adapter** (`recosearch/adapters/duckdb.py`) providing the
  `structured_query` capability, plus a new optional extra `pip install -e ".[duckdb]"`
  (just the `duckdb` driver).
- Unit coverage for the DuckDB adapter (`tests/unit/test_duckdb_adapter.py`).
- Expanded documentation and a worked example for asking governed questions.
- Continuous-integration scaffolding for the public repository.

### Changed
- README positioning and quickstart refinements.
- Adapter touch-ups (`opensearch`, `postgres`, `qdrant`) and capability/test updates.

## [0.1.0] - 2026-06-17

Initial public release: RecoSearch — a governed MCP server that separates AI
reasoning from validated data execution. The LLM does the planning; RecoSearch
exposes validated tools and executes only authorized requests, with full provenance.

### Added
- **Governed MCP server** exposing 14 tools (12 named plus the
  `execute_postgres_semantic_query` and `run_guarded_postgres_sql` compatibility
  aliases): `list_sources`, `get_semantic_contract`, `health_check_sources`,
  `search_text`, `search_vector`, `execute_semantic_query`, `run_guarded_sql`,
  `query_documents`, `combine_slices`, `validate_analysis_request`,
  `validate_cited_evidence_packet`, and `generate_semantic_json`. Console script
  `recosearch`; CLI flags `--write-semantic-json`, `--validate`, `--health-check`,
  and `--check-semantic-json`.
- **Three-authority-file model** per scenario directory: `source_config.yaml`
  (connections), `semantic.md` (business meaning), and `scenario_config.yaml`
  (identity and optional governance). `RECOSEARCH_SEMANTIC_DIR` selects the active
  scenario; everything else is compiled or derived — no business logic in Python.
- **Source adapters**: PostgreSQL, OpenSearch, Qdrant, Snowflake, and MongoDB,
  installable as optional extras (`postgres`, `opensearch`, `qdrant`, `snowflake`,
  `mongodb`, `observability`, `all`, `dev`).
- **Always-on governance**: read-only, SELECT-only SQL guard (non-SELECT refused
  with reason code `mutating_sql`); global-rule enforcement on hand-written SQL
  (a SELECT omitting a declared global exclusion is refused with reason code
  `missing_global_exclusion`); rejection of undeclared fields and sources; and
  cite-or-refuse evidence validation.
- **Opt-in governance** (when configured in `scenario_config.yaml`): RBAC tool
  gating via `RECOSEARCH_ROLE` and ACL field masking.
- **Provenance and cited-evidence validation** so every result carries an
  auditable trail of source, fields, filters, query hash, and returned rows.
- **Row ceilings**: `MAX_SOURCE_ROWS=100` and `MAX_FEDERATION_ROWS=500`
  (`recosearch/settings.py`).
- **Contract enforcement modes** via `RECOSEARCH_CONTRACT_ENFORCEMENT`
  (`warn`, the default, or `strict`).
- **Four-layer test suite** (`tests/`): `unit`, `smoke`, `integration`, and `live`,
  auto-marked by path. Non-live tests run with `pytest -q -m "not live"`; live and
  smoke layers require running services.
- Apache-2.0 license; requires Python 3.11+.

[Unreleased]: https://github.com/recohut/recosearch/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/recohut/recosearch/releases/tag/v0.1.0
