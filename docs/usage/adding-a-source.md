# Adding a New Data Source

This guide walks through adding a new source to the governed MCP server. The
worked example throughout is the Snowflake adapter (`snowflake.py`). Follow
these five steps in order.

The governance layer (SQL guards, citation tracking, RBAC, global exclusion
rules, semantic contract validation, metrics/citations) is completely untouched
by this process. You wire one executor function; everything else is automatic.

---

## Step 1 — Plan the connection-config shape

Each adapter declares the config keys it accepts via a `config_schema` on its
`SourceAdapter` (you attach it in Step 3c). `recosearch/adapters/__init__.py`
aggregates every adapter's schema automatically through `all_config_schemas()`,
and `recosearch/config.py` validates each entry in the active scenario's
`source_config.yaml` (the directory named by `RECOSEARCH_SEMANTIC_DIR`, default
`./semantic`) against it — there is no central registry to edit.

Decide the shape now; you attach it to the adapter in Step 3c:

```python
config_schema={
    "required": ["url", "database", "warehouse", "user", "password"],
    "identifiers": ["database"],
    "allowed": ["id", "url", "database", "schema", "warehouse", "role", "user", "password"],
}
```

Keys:

- `required` — keys that must be present; validation raises an error if absent.
- `identifiers` — keys used as human-readable source identifiers in log output.
- `allowed` — the complete set of config keys accepted for this type. Any key
  NOT listed here is flagged as an unknown config field.

---

## Step 2 — Add the source to the scenario's `source_config.yaml`

File: `source_config.yaml` in the active scenario directory
(`RECOSEARCH_SEMANTIC_DIR`, default `./semantic`). The worked NovaMart example
lives at `examples/novamart/source_config.yaml`.

This file is the single connection authority. All secrets must use the
`${ENV_VAR}` secret-reference syntax — never embed plaintext credentials.

```yaml
# examples/novamart/source_config.yaml
sources:
  snowflake:
    id: novamart_snowflake
    url: ${SF_URL}
    database: ${SF_DATABASE}
    schema: ${SF_SCHEMA}
    warehouse: ${SF_WAREHOUSE}
    role: ${SF_ROLE}
    user: ${SF_USER}
    password: ${SF_PASSWORD}
```

The `id` value becomes the `source_id` used in citations and semantic contract
references. All other keys must match the adapter's `config_schema["allowed"]`
list (Step 3c).

Set the corresponding environment variable before running the server:

```bash
export SF_PASSWORD=<the real password>
```

---

## Step 3 — Implement the adapter module and register it

### 3a. Start from an existing adapter

```bash
cp recosearch/adapters/duckdb.py recosearch/adapters/snowflake.py
```

`duckdb.py` is the smallest structured-query adapter — a good skeleton to adapt.
See `recosearch/adapters/base.py` for the `SourceAdapter` contract every adapter
must satisfy.

### 3b. Implement the three adapter functions

All intra-package imports use `..` (double-dot parent reference) because the
adapters live in the `recosearch/adapters/` sub-package:

```python
from ..config import _source_ref_by_type
from ..errors import BoundaryError
from ..json_utils import _json_safe
from ..settings import MAX_SOURCE_ROWS
```

**`_<type>_ref(ref)`** — returns the live `SourceRef` for this source type,
falling back to `_source_ref_by_type("<type>")` when the caller has not already
resolved it.

```python
def _snowflake_ref(ref: Any | None = None):
    return ref if ref is not None else _source_ref_by_type("snowflake")
```

**`_<type>_connection(ref)`** — opens a driver connection. The driver import
MUST be lazy (inside the function body, not at module top) so that importing
the package does not crash when the driver is absent. `__init__.py` imports
all adapter modules eagerly.

```python
def _snowflake_connection(ref: Any | None = None):
    import snowflake.connector  # noqa: PLC0415 — lazy, intentional

    cfg = _snowflake_ref(ref).config
    url = str(cfg.get("url") or "")
    account = url.replace("https://", "").split(".snowflakecomputing.com")[0]
    connect_kwargs = {
        "account": account,
        "user": cfg.get("user"),
        "password": cfg.get("password"),
        "database": cfg.get("database"),
        "warehouse": cfg.get("warehouse"),
    }
    if cfg.get("schema"):
        connect_kwargs["schema"] = cfg["schema"]
    if cfg.get("role"):
        connect_kwargs["role"] = cfg["role"]
    return snowflake.connector.connect(**connect_kwargs)
```

Note that Snowflake's connector does not support the `with conn:` context
manager, so the real implementation uses explicit `try/finally` blocks with
`cur.close()` and `conn.close()`.

**`_fetch_<type>(sql, params, *, limit, ref)`** — the capability executor.
Enforce the row-count ceiling; wrap in a `SELECT * FROM (...) LIMIT N`
subquery; return `list[dict]`. The SQL guard (`validate_postgres_sql` with the
right dialect) is applied UPSTREAM in `tools.py` before this function is
called — do not re-implement it here.

```python
def _fetch_snowflake(
    sql: str,
    params: Iterable[Any] = (),
    *,
    limit: int = MAX_SOURCE_ROWS,
    ref: Any | None = None,
) -> list[dict[str, Any]]:
    params = list(params)
    bounded_limit = max(1, min(int(limit), MAX_SOURCE_ROWS))
    cleaned = sql.strip().rstrip(";")
    conn = _snowflake_connection(ref)
    try:
        cur = conn.cursor()
        try:
            bound_sql = f"SELECT * FROM ({cleaned}) AS guarded_query LIMIT {bounded_limit}"
            cur.execute(bound_sql, params if params else None)
            columns = [desc[0] for desc in cur.description]
            return [_json_safe(dict(zip(columns, row))) for row in cur.fetchall()]
        finally:
            cur.close()
    finally:
        conn.close()
```

**`_<type>_health_check(ref)`** (optional but recommended) — runs the
lightest possible connectivity probe; returns `{"status": "ok"}` or
`{"status": "error", "error": <str>}`.

### 3c. Declare ADAPTER at the bottom of the module

The `base.py` import must come AFTER all function definitions to avoid circular
imports between the sub-package modules.

```python
from .base import SourceAdapter  # noqa: E402 — intentionally after all functions

ADAPTER = SourceAdapter(
    source_type="snowflake",
    capabilities=frozenset({"structured_query"}),
    run_query=_fetch_snowflake,
    sql_dialect="snowflake",        # sqlglot dialect — None for text/vector adapters
    health_check=_snowflake_health_check,
    config_schema={                 # the connection-key shape from Step 1
        "required": ["url", "database", "warehouse", "user", "password"],
        "identifiers": ["database"],
        "allowed": ["id", "url", "database", "schema", "warehouse", "role", "user", "password"],
    },
)
```

Capability strings:

| Capability         | Use when the adapter…                         | Suggested tools                          |
|--------------------|-----------------------------------------------|------------------------------------------|
| `structured_query` | speaks SQL                                    | `execute_semantic_query`, `run_guarded_sql` (the `*_postgres_*` names are compatibility aliases) |
| `text_search`      | executes a text/keyword search (e.g. OpenSearch) | `search_text`                         |
| `vector_search`    | executes a nearest-neighbour vector search    | `search_vector`                          |
| `document_query`   | executes a document filter query (e.g. MongoDB) | `query_documents`                      |

Set `sql_dialect` to a sqlglot dialect name (e.g. `"postgres"`, `"snowflake"`,
`"duckdb"`) for `structured_query` adapters so that `validate_postgres_sql`
and the semantic query compiler can parse and transpile SQL correctly.

### 3d. Registration is automatic

`recosearch/adapters/__init__.py` calls `_discover_adapters()`, which scans the
sub-package and registers every module that exposes an `ADAPTER` object (modules
whose names start with `_` are skipped). Dropping `snowflake.py` into
`recosearch/adapters/` is all it takes — `ADAPTERS` and `ADAPTER_CAPABILITIES`
are built from it automatically, so `capabilities_for("snowflake")` returns
`{"structured_query"}` with no further edits.

---

## Step 4 — Declare the driver as an optional-dependency extra

Add the driver to `pyproject.toml` under `[project.optional-dependencies]` so it
installs only when someone opts into that source:

```toml
snowflake = ["snowflake-connector-python>=3.0"]   # snowflake structured-query adapter
```

Install it in the development environment:

```bash
pip install -e ".[snowflake]"
```

The driver import in the adapter is lazy, so the rest of the server continues
to run even when the driver is not installed (e.g. in CI environments that do
not need Snowflake).

---

## Step 5 — Validate and run tests

```bash
# Syntax-check the server and the live-test harness
python -m py_compile recosearch/mcp_server.py

# Verify the package imports cleanly (no driver crash even without the driver)
python -c "import recosearch.adapters as a; print(a.capabilities_for('snowflake'))"
# expected output: {'structured_query'}

# Regenerate semantic.json from semantic inputs
recosearch --write-semantic-json

# Full adapter test suite
python -m pytest -q tests/unit/test_adapters.py

# Full test suite
python -m pytest -q
```

If you have a live connection available, also run:

```bash
recosearch --health-check
pytest -q tests/live/
```

---

## What you did NOT have to touch

The following remain completely unchanged when adding a source:

- `semantic/semantic.md` — business meaning, metrics, dimensions, rules.
  Business owners manage this file; adapters are invisible to it.
- `semantic.json` — generated output written beside the scenario inputs in the
  active scenario directory (e.g. `examples/novamart/semantic.json`); regenerate
  with `recosearch --write-semantic-json`.
- `tools.py` — MCP tool implementations. The dispatch paths in
  `health_check_sources`, `run_guarded_postgres_sql`, and
  `execute_postgres_semantic_query` call `adapter_for_type(source_type)`, which
  automatically resolves your new adapter from `ADAPTERS`.
- `mcp_server.py` — server entry-point; no changes needed.
- `recosearch/contract.py` — governance/citation contract; unchanged.
- RBAC (`semantic/scenario_config.yaml (roles: block)`), observability, and the entire MCP tool layer — all
  governed by capability string, not source type. Your adapter inherits
  governance the moment it declares `capabilities=frozenset({"structured_query"})`.
