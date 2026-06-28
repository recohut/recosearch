# Sources and Adapters

Last updated: 2026-06-17

This document explains how RecoSearch connects to data sources, how capability-based routing works, and what steps are needed to add a new source or a new source type.

---

## The adapter plugin model

Every source technology has exactly one adapter file under `recosearch/adapters/`. Each file declares a single `ADAPTER` object of type `SourceAdapter` (defined in `recosearch/adapters/base.py`). The `SourceAdapter` dataclass is the contract every adapter must satisfy:

| Field | Type | Purpose |
|---|---|---|
| `source_type` | `str` | Matches the key used in `source_config.yaml` (e.g. `"postgres"`, `"opensearch"`). |
| `capabilities` | `frozenset[str]` | Storage capabilities this adapter can execute (e.g. `frozenset({"structured_query"})`). Capabilities are storage primitives, never business roles. |
| `run_query` | `Callable` | The single execution entry-point. Called by the framework after governance checks pass. Signature must accept `limit` and `ref` as keyword arguments. |
| `sql_dialect` | `str \| None` | sqlglot dialect name for SQL adapters (`"postgres"`, `"snowflake"`); `None` for search adapters. |
| `health_check` | `Callable \| None` | Optional probe that returns `{"status": "ok"}` or `{"status": "error", "error": <str>}`. |
| `available` | `bool` | `True` means the adapter is fully implemented and reachable. `False` marks a placeholder — the adapter is registered but its capabilities are hidden from routing. |
| `config_schema` | `dict \| None` | Declares which connection keys the adapter reads from `source_config.yaml`: `required`, `identifiers`, and `allowed` lists. |

### The auto-registry

`recosearch/adapters/__init__.py` imports every adapter module and builds two dictionaries automatically:

```
ADAPTERS: dict[str, SourceAdapter]
    All registered adapters, keyed by source_type. Available whether or not
    available=True, so config validation and health checks can always reach them.

ADAPTER_CAPABILITIES: dict[str, set[str]]
    Derived from ADAPTERS — only includes entries where available=True.
    A placeholder adapter (available=False) contributes no capabilities here,
    so it cannot interfere with routing decisions.
```

Because `ADAPTER_CAPABILITIES` is derived automatically, registering a new adapter and setting `available=True` is all that is needed to bring it under capability-based routing, SQL guards, metrics, and other governance machinery.

---

## Live source types and their capabilities

The table below reflects the adapters registered in `recosearch/adapters/__init__.py` and their `available` state as read from the source files.

| Source type | Capability | `available` | Driver | Notes |
|---|---|---|---|---|
| `postgres` | `structured_query` | `True` | psycopg2 | Primary SQL source. SQL is validated by `validate_postgres_sql` before execution. |
| `snowflake` | `structured_query` | `True` | snowflake-connector-python (lazy import) | SQL dialect `"snowflake"`. The connector is imported lazily so the package stays importable when the driver is absent. |
| `opensearch` | `text_search` | `True` | requests (HTTP) | Executes Elasticsearch-compatible `_search` requests against an index. |
| `qdrant` | `vector_search` | `True` | qdrant-client + sentence-transformers | Embeds the query with a local SentenceTransformer model then calls `query_points`. |
| `mongodb` | `document_query` | `True` | pymongo (lazy import) | Available (`available=True`); exposes the `query_documents` tool. Requires a running MongoDB instance to return data. |
| `duckdb` | `structured_query` | driver-gated | duckdb (optional, `pip install -e ".[duckdb]"`) | Adapter is registered in `__init__.py`. `available` is `True` when the `duckdb` driver is importable; `False` (placeholder) when it is absent. Powers the zero-infrastructure `examples/novashop-duckdb` scenario. |

---

## Capability-based routing

The framework routes queries based on capability, not source type. The relevant MCP tools map to capabilities as follows:

| MCP tool | Capability |
|---|---|
| `execute_semantic_query`, `run_guarded_sql` | `structured_query` |
| `search_text` | `text_search` |
| `search_vector` | `vector_search` |
| `query_documents` | `document_query` |

The structured-query tools are generic and route by capability, so they apply to any `structured_query` source (Postgres, Snowflake). The postgres-named tools `execute_postgres_semantic_query` and `run_guarded_postgres_sql` remain as compatibility aliases.

### SQL auto-routing to the right source

For `structured_query`, the SQL guard (`validate_postgres_sql`) parses the SQL and extracts every table reference. It then looks up each table in the semantic contract to determine which source owns it. If a table belongs to a source that does not have `structured_query` capability (or belongs to a non-SQL source), the query is refused with `reason_code: table_not_allowed`, and the response includes the correct suggested tools for that table's source type.

This means a SQL query referencing only postgres-owned tables executes against postgres, and a SQL query referencing snowflake-owned tables executes against snowflake — without the caller needing to name the source explicitly. When two live sources share a capability (e.g. both postgres and snowflake declare `structured_query`), the table-ownership lookup in the semantic contract uniquely resolves which source to use.

---

## How to add a new source (business owner path)

A business owner who wants to add an additional instance of an already-supported source type (e.g. a second postgres database or an additional opensearch index) only needs two things:

### 1. Declare the source in `semantic/source_config.yaml`

Add a new entry under `sources:`. Credentials should use `${ENV_VAR}` references rather than plaintext values.

```yaml
sources:
  my_new_source:
    id: novamart_my_new_source
    host: ${MY_SOURCE_HOST}
    port: 5432
    database: ${MY_SOURCE_DB}
    user: ${MY_SOURCE_USER}
    password: ${MY_SOURCE_PASSWORD}
```

The key name must match one of the registered `source_type` values (`postgres`, `snowflake`, `opensearch`, `qdrant`). The `config_schema` on the adapter declares which keys are `required`, which are `identifiers`, and which are `allowed` — the config loader validates against this schema at startup.

### 2. Declare the source's fields in `semantic/semantic.md`

Every table and field that the framework should know about must be declared in the semantic contract. This is what allows SQL routing to map table names to the correct source. See `docs/usage/configuring-sources.md` for the field declaration syntax.

### The `available=False` gate for placeholders

When a source is declared in `source_config.yaml` but is not yet reachable (missing driver, no live credentials, under development), set `available=False` on the adapter. The adapter remains in the registry so that config validation and `health_check_sources` can reference it, but its capabilities are excluded from `ADAPTER_CAPABILITIES`. This prevents the placeholder from colliding with a real source in capability resolution.

---

## How to add a new source type (engineer path)

When an entirely new storage technology is needed (one that has no existing adapter), an engineer adds a single adapter file:

1. Copy the closest existing adapter (e.g. `recosearch/adapters/duckdb.py` for a structured-query store) to `recosearch/adapters/<type>.py`.
2. Implement the three functions: connection factory (with a lazy driver import), executor (`run_query`), and optionally a `health_check`.
3. Choose one capability from `{"structured_query", "text_search", "vector_search", "document_query"}` for the `ADAPTER` declaration. Do not claim a capability the executor cannot actually perform.
4. No registration step — `_discover_adapters()` in `recosearch/adapters/__init__.py` auto-scans the sub-package and registers any module exposing an `ADAPTER` object.
5. Add the source type to `semantic/source_config.yaml` and declare its fields in `semantic/semantic.md`.
6. Set `available=True` when the driver is installed and live credentials are available. Use `available=False` during development or when testing with no real connection.

The `SourceAdapter` contract in `recosearch/adapters/base.py` defines every field an adapter must supply; the shipped adapters (`duckdb.py`, `postgres.py`, `mongodb.py`, …) are worked references covering lazy driver imports, the correct import order for `base.py`, and which governance checks are the adapter's responsibility versus the framework's.
