# Troubleshooting

This page is a lookup table. Find the `reason_code` or symptom you're seeing, read what it means in plain words, and follow the fix.

---

## Quick-reference table

| `reason_code` | When you see it | Fix |
|---|---|---|
| `source_selection_required` | Two live sources share a capability and you did not say which one to use | Pass `source_id` in your call |
| `no_source_for_capability` | No live source can handle the requested capability | Check sources with `--health-check`; fix config or driver |
| `source_not_found_for_capability` | You named a `source_id` that exists but does not have the right capability | Check the capability table below; use the correct source |
| `single_query_spans_sources` | Your SQL or plan touches tables that live on two different sources | Split into two calls, then use `combine_slices` |
| `source_execution_failed` | The source connected but threw an error when running the query | Check service logs; the `error` field in the response has details |
| `contract_invalid` | `semantic.json` has errors that block execution | Run `--validate`, fix `semantic/source_config.yaml`, `semantic/semantic.md`, or `semantic/scenario_config.yaml`, then `--write-semantic-json` |
| `table_not_allowed` | Your SQL references a table that is not in the semantic contract | Use only declared tables; check `get_semantic_contract` for the list |
| `column_not_allowed` | Your SQL references a column that is not declared for that table | Use only declared columns |
| `missing_global_exclusion` | Your SQL touches a table that has a mandatory filter, but the filter is missing | Add the required `WHERE` clause; the `required_exclusions` field tells you exactly what is needed |
| `mutating_sql` | Your SQL contains `INSERT`, `UPDATE`, `DELETE`, `DROP`, or similar | The server is read-only; rewrite as a `SELECT` |
| `not_read_only_select` | SQL does not start with `SELECT` or `WITH` | Rewrite as a `SELECT` or `WITH` query |
| `sql_parse_failed` | The SQL could not be parsed | Fix the syntax; the `error` field has the parser message |
| `plan_compile_failed` | The semantic plan JSON could not be compiled to SQL | Check the `reason` field; fix the field IDs or plan structure |
| `text_search_fields_unresolved` | You called `search_text` with a query but the source has no searchable fields declared | Add `body_text` or `display_name` field roles to `semantic/semantic.md` for that source |
| `missing_claim_support_purpose` | You used `citation_mode: claim_support` but did not pass a `purpose` object | Add the `purpose` argument to your call |
| `unsupported_citation_mode` | `citation_mode` was set to something other than `exploratory` or `claim_support` | Use one of the two supported values |
| `role_not_recognized` | `RECOSEARCH_ROLE` is set but that role does not appear in `semantic/scenario_config.yaml` | Add the role to the `roles` block in `semantic/scenario_config.yaml`, or correct the env-var value |
| `role_not_permitted` | The role is known but is not allowed to call this tool | Add the tool to the role's `tools` list in the `roles` block in `semantic/scenario_config.yaml` |
| `federation_slice_too_large` | A slice passed to `combine_slices` has more rows than the bounded limit (500) | Reduce the `limit` on the upstream tool call before combining |

---

## Detailed notes

### `source_selection_required`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "source_selection_required",
  "capability": "structured_query",
  "candidates": ["novamart_postgres", "novamart_snowflake"]
}
```

**What it means**

Two or more live sources both have the same capability (for example, `structured_query` for both Postgres and Snowflake). The server cannot pick for you — the choice is yours and it affects which data you see.

**How to fix**

Add `source_id` to your call:

```json
{ "source_id": "novamart_postgres", ... }
```

The `candidates` field in the refusal lists exactly the source IDs you can choose from. This is intentional governance behavior, not a bug.

---

### `no_source_for_capability`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "no_source_for_capability",
  "capability": "vector_search"
}
```

**What it means**

No source is currently live with the requested capability. The adapter may be gated off (`available=False`) or the service may be down.

**How to fix**

1. Run `recosearch --health-check` to see which sources are alive.
2. If the source shows `"unavailable"`, check that the service is running and that credentials are correct in `semantic/source_config.yaml`.
3. If the source is `"ok"` but the tool still refuses, check the capability table: not every source type has every capability (for example, Snowflake is `structured_query` only; Qdrant is `vector_search` only).

---

### `source_not_found_for_capability`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "source_not_found_for_capability",
  "capability": "text_search",
  "requested": "novamart_postgres",
  "candidates": ["novamart_opensearch"]
}
```

**What it means**

You named a specific `source_id`, but that source does not have the capability you are asking for. Postgres does structured queries, not text search.

**How to fix**

Use one of the `source_id` values listed in `candidates`. Capability-to-source mapping:

| Capability | Source |
|---|---|
| `structured_query` | `novamart_postgres`, `novamart_snowflake` |
| `text_search` | `novamart_opensearch` |
| `vector_search` | `novamart_qdrant` |
| `document_query` | `novamart_mongodb` |

---

### `single_query_spans_sources`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "single_query_spans_sources",
  "sources": ["novamart_postgres", "novamart_snowflake"],
  "hint": "query each source separately, then combine_slices to federate"
}
```

**What it means**

Your SQL or semantic plan references tables that belong to two different sources. A single SQL statement cannot run across two separate databases.

**How to fix**

Split the query into one call per source, then pass both result sets to `combine_slices` to join them by a shared key. The `hint` field in the refusal says the same thing.

---

### `source_execution_failed`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "source_execution_failed",
  "capability": "structured_query",
  "source_boundary": "novamart_postgres",
  "error": "could not connect to server: Connection refused"
}
```

**What it means**

The server reached the governed-query stage, but the underlying database threw an error. The governance layer passed; the problem is with the data service itself.

**How to fix**

1. Read the `error` field — it is the raw exception from the driver.
2. Common causes: the service is down, credentials changed, the database does not exist yet, or the query exceeds a server-side timeout.
3. Run `recosearch --health-check` to confirm the source is reachable.
4. Check the service logs (Postgres, OpenSearch, Qdrant) for the root error.

---

### `contract_invalid`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "contract_invalid",
  "issues": [{ "severity": "error", "message": "..." }]
}
```

**What it means**

`semantic.json` has error-severity validation problems. All governed tool calls are blocked until the contract is fixed, because the server cannot safely resolve fields, tables, or exclusion rules.

**How to fix**

```bash
# 1. See what is wrong
recosearch --validate

# 2. Fix the issues in:
#    semantic/source_config.yaml     (connection details)
#    semantic/semantic.md            (business definitions, field roles, rules)
#    semantic/scenario_config.yaml   (scenario identity, RBAC, ACL, vocabularies)

# 3. Recompile
recosearch --write-semantic-json

# 4. Confirm
recosearch --validate
```

---

### `table_not_allowed`

**What you see**

```json
{
  "status": "refused",
  "guard": {
    "reason_code": "table_not_allowed",
    "bad_tables": ["raw_events"],
    "allowed_postgres_tables": ["orders", "products", "sellers", ...]
  }
}
```

**What it means**

Your SQL references a table that is not declared in the semantic contract for any structured-query source. The server only allows queries against declared, governed tables.

**How to fix**

Use only the tables listed in `allowed_postgres_tables`. To see the full list of declared tables, call the `get_semantic_contract` tool and look at the `tables` key.

If the table you need is legitimately missing, add it to `semantic/semantic.md`, then re-run `recosearch --write-semantic-json`.

---

### `column_not_allowed`

**What you see**

```json
{
  "status": "refused",
  "guard": {
    "reason_code": "column_not_allowed",
    "bad_columns": ["orders.internal_flag"]
  }
}
```

**What it means**

Your SQL references a column that is not declared for that table in the semantic contract. Undeclared columns cannot be queried — this prevents data leakage.

**How to fix**

Use only columns that appear in the semantic contract for that table. Call `get_semantic_contract` and look at the `tables.<table_name>.column_names` list to see what is available.

---

### `missing_global_exclusion`

**What you see**

```json
{
  "status": "refused",
  "guard": {
    "reason_code": "missing_global_exclusion",
    "required_exclusions": [
      { "column": "status", "operator": "!=", "value": "deleted" }
    ]
  }
}
```

**What it means**

The semantic contract declares a mandatory filter for this table — for example, "never return deleted records". Your SQL is missing that filter, which would return data the contract says must be excluded.

**How to fix**

Add the required `WHERE` clause to your SQL. The `required_exclusions` array tells you exactly which `column`, `operator`, and `value` to add. For the example above:

```sql
SELECT * FROM orders WHERE status != 'deleted'
```

The `execute_postgres_semantic_query` tool applies these filters automatically from the compiled contract; only `run_guarded_postgres_sql` requires you to include them manually.

---

### `mutating_sql` / `not_read_only_select`

**What you see**

```json
{ "reason_code": "mutating_sql" }
// or
{ "reason_code": "not_read_only_select" }
```

**What it means**

The server is strictly read-only. SQL containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`, or `COPY` is rejected outright. Any statement that does not begin with `SELECT` or `WITH` is also rejected.

**How to fix**

Rewrite your query as a `SELECT` statement. The MCP server is a query layer only — data modifications must go through your application's own write path.

---

### `plan_compile_failed`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "plan_compile_failed",
  "reason": "unknown field_id: novamart_postgres.unknown_table.qty"
}
```

**What it means**

The structured plan you passed to `execute_postgres_semantic_query` could not be turned into SQL. This usually means a `field_id` in the plan does not match any declared field in the semantic contract, or the plan structure is malformed.

**How to fix**

1. Check the `reason` field for the specific problem.
2. Field IDs must follow the format `source_id.table.column` exactly as declared in `semantic/semantic.md`. Call `get_semantic_contract` to see the exact field IDs available.

---

### `text_search_fields_unresolved`

**What you see**

```json
{
  "status": "refused",
  "reason_code": "text_search_fields_unresolved",
  "reason": "no body_text/display_name field roles resolved for this source"
}
```

**What it means**

You called `search_text` with a query string, but the source does not have any fields tagged with `body_text` or `display_name` field roles in the semantic contract. The server does not know which fields to search.

**How to fix**

Open `semantic/semantic.md` and add a `field_roles` entry for the OpenSearch source with a `body_text` or `display_name` role pointing to the right column. Then recompile:

```bash
recosearch --write-semantic-json
```

---

### Stale `semantic.json`

**What you see**

The server logs or the `--check-semantic-json` flag reports:

```
semantic.json does not match the compiled contract; run --write-semantic-json
```

**What it means**

You edited `semantic/source_config.yaml`, `semantic/semantic.md`, or `semantic/scenario_config.yaml` but did not recompile. The on-disk `semantic.json` is out of date. In `strict` mode the server refuses to start; in `warn` mode it starts but logs a warning on every request.

**How to fix**

```bash
recosearch --write-semantic-json
```

Run this every time you change any of the three input files.

---

### Missing driver (e.g. `snowflake.connector not found`)

**What you see**

The source shows `"status": "unavailable"` in the health check, or you get an `ImportError` in the logs.

**What it means**

The Python driver for that source type is not installed. The Snowflake adapter, for example, requires `snowflake-connector-python`, which is not in the default install.

**How to fix**

Install the missing driver:

```bash
pip install snowflake-connector-python   # Snowflake
```

For other sources the adapter extras already cover `psycopg2-binary` (Postgres), `opensearch-py` (OpenSearch), and `qdrant-client` (Qdrant). If you are missing one of those, re-run:

```bash
pip install -e ".[all,dev]"
```

---

### Unreachable source (service is down)

**What you see**

`recosearch --health-check` returns:

```json
{ "novamart_postgres": { "status": "failed", "error": "Connection refused" } }
```

**What it means**

The data service is not reachable at the host/port declared in `semantic/source_config.yaml`.

**How to fix**

1. Start your data services (Postgres, OpenSearch, Qdrant, etc.) however you run them locally, then wait for them to become healthy.

2. Confirm the host and port in `semantic/source_config.yaml` match where the service is actually listening (defaults: Postgres `15432`, OpenSearch `19200`, Qdrant `16333`).

3. Re-run the health check to confirm:

   ```bash
   recosearch --health-check
   ```

---

### RBAC refusals (`role_not_recognized` / `role_not_permitted`)

**What you see**

```json
{
  "status": "refused",
  "reason_code": "role_not_recognized",
  "role": "analyst",
  "tool": "run_guarded_postgres_sql"
}
```

**What it means**

`RECOSEARCH_ROLE` is set in your environment, so RBAC enforcement is active. Either the role name is not in the `roles` block of `semantic/scenario_config.yaml` (`role_not_recognized`), or the role exists but is not granted the tool you called (`role_not_permitted`).

When `RECOSEARCH_ROLE` is not set at all, RBAC is completely off and every tool passes through.

**How to fix**

- If `role_not_recognized`: add the role to the `roles` block in `semantic/scenario_config.yaml` and list the tools it may call.
- If `role_not_permitted`: add the tool name to the role's `tools` list in the `roles` block in `semantic/scenario_config.yaml`.
- To turn RBAC off entirely, unset the environment variable:

  ```bash
  unset RECOSEARCH_ROLE
  ```

---

## Quick-check commands

Run these in order when you are not sure what is wrong:

```bash
# 1. Check the input files for errors
recosearch --validate

# 2. Recompile if you changed any of the input files
recosearch --write-semantic-json

# 3. Check that live sources are reachable
recosearch --health-check
```

All three commands print JSON output. `--validate` exits with code 2 when there are errors. `--health-check` shows `"status": "failed"` for unreachable sources.

---

## Related pages

- [Getting Started](getting-started.md) — first-time setup and startup commands
- [Configuring Sources](configuring-sources.md) — editing `source_config.yaml` and `semantic.md`
- [Observability](observability.md) — reading traces and spans to diagnose slow or refused queries
- [Asking Questions](asking-questions.md) — how to structure tool calls correctly
