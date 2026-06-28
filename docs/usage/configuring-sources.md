# Configuring sources

Three files control everything about your scenario identity, where your data lives, and what it means.
You edit these files directly — there is no UI or database to update.

These files live in the directory named by `RECOSEARCH_SEMANTIC_DIR` (default `./semantic`, which ships as neutral
templates). The complete NovaMart example lives in `examples/novamart/` — run it with
`export RECOSEARCH_SEMANTIC_DIR=examples/novamart`.

| File | What it controls |
|------|-----------------|
| `scenario_config.yaml` | **Identity + governance** — scenario name/IDs and optional RBAC, field masking, and vocabulary |
| `source_config.yaml` | **Connections** — host, port, credentials for each source |
| `semantic.md` | **Meaning** — metrics, rules, dimensions, measures, field descriptions in plain business language |

After editing `source_config.yaml` or `semantic.md`, regenerate the compiled contract:

```bash
recosearch --write-semantic-json
```

Then validate the result:

```bash
recosearch --validate
```

---

## scenario_config.yaml — scenario identity and optional governance

This file is the single place a business owner edits to declare who this scenario is and, optionally,
to turn on runtime controls. It has one required block and three optional governance blocks.

**Required — scenario identity:**

```yaml
scenario:
  scenario_id: novamart
  name: NovaMart Semantic Contract
  dataset_id: novamart
  mcp_name: novamart
```

These four fields are stamped into the compiled contract and identify the scenario to the MCP server.

**Optional — governance blocks (omit any block and that control is simply off):**

`roles` — RBAC. Restricts which tools each role may call. The active role is read from the
`RECOSEARCH_ROLE` environment variable at request time. Omit this block and every tool is open to everyone.

```yaml
roles:
  admin:
    tools: ["*"]
  analyst:
    tools:
      - list_sources
      - get_semantic_contract
      - search_text
      - search_vector
      - run_guarded_sql
      - execute_semantic_query
      - combine_slices
      - validate_analysis_request
      - validate_cited_evidence_packet
  viewer:
    tools:
      - list_sources
      - get_semantic_contract
      - search_text
      - search_vector
      - combine_slices
      - validate_analysis_request
      - validate_cited_evidence_packet
```

`access` — field masking (ACL). Lists sensitive fields (`source.table.column`) that are masked for any
role not in `unmasked_roles`. Omit this block and no masking is applied.

```yaml
access:
  sensitive_fields:
    - novamart_opensearch.customer_reviews.customer_id
    - novamart_snowflake.sellers.seller_name
  unmasked_roles: [admin]
  mask: "***MASKED***"
```

`vocabularies` — interpretation terms. Extends the built-in domain-neutral defaults in
`recosearch/vocabularies.py` with project-specific field roles and rule stopwords.
Omit this block and the built-in defaults are used — nothing breaks.

```yaml
vocabularies:
  field_roles:
    body_text:
      terms: ["review text", "policy text"]
    score:
      terms: ["stars"]
  rule_stopwords:
    filter: ["orders", "order", "sales", "revenue", "analysis", "metrics", "metric"]
```

`scenario_config.yaml` is **not** a compile input for `semantic.json` — it supplies the scenario identity
(stamped into the contract at compile time) and the governance rules applied at request time. You do not
need to regenerate `semantic.json` when you change only the governance blocks; just restart the server.

---

## source_config.yaml — where each source lives

This is the **only** place connections are declared. Every source gets one block under `sources:`.
Each block must have an `id` field (used everywhere else to refer to that source) and
the required keys for its type.

**Never put secrets in plain text.** Use `${ENV_VAR}` references instead.
At startup the server reads the environment variable and substitutes its value.
If the variable is not set the connection fails loudly rather than silently using a blank password.

```yaml
# wrong — plain password
password: my_secret_123

# right — env var reference
password: ${PG_PASSWORD}
```

The validator flags any `password`, `token`, `secret`, or `api_key` value that is not an env var reference.

---

### Source type reference

#### postgres — structured SQL queries

**Required keys:** `host`, `port`, `database`

```yaml
sources:
  postgres:
    id: novamart_postgres
    host: localhost
    port: 15432
    database: novamart
    user: novamart
    password: ${PG_PASSWORD}
```

| Key | Notes |
|-----|-------|
| `id` | Unique name used in semantic.md and tool calls |
| `host` | Hostname or IP of the Postgres server |
| `port` | Integer, 1–65535 |
| `database` | Database name to connect to |
| `user` | Login user (optional if your driver uses peer auth) |
| `password` | Use `${ENV_VAR}` — plain text is flagged as a warning |

Capability provided: `structured_query` (tools: `execute_semantic_query`, `run_guarded_sql`; the postgres-named
`execute_postgres_semantic_query` and `run_guarded_postgres_sql` remain as compatibility aliases)

---

#### opensearch — full-text search

**Required keys:** `url`, `index`

```yaml
sources:
  opensearch:
    id: novamart_opensearch
    url: http://localhost:19200
    index: customer_reviews
```

| Key | Notes |
|-----|-------|
| `id` | Unique name |
| `url` | Full URL including scheme and port |
| `index` | OpenSearch index to query |
| `user` / `password` | Optional — use `${ENV_VAR}` for passwords |
| `token` / `api_key` | Optional alternative auth — use `${ENV_VAR}` |

Capability provided: `text_search` (tool: `search_text`)

---

#### qdrant — vector / semantic search

**Required keys:** `url`, `collection`

```yaml
sources:
  qdrant:
    id: novamart_qdrant
    url: http://localhost:16333
    collection: novamart_policy_chunks
```

| Key | Notes |
|-----|-------|
| `id` | Unique name |
| `url` | Full URL including scheme and port |
| `collection` | Qdrant collection to search |
| `api_key` / `token` | Optional auth — use `${ENV_VAR}` |

Capability provided: `vector_search` (tool: `search_vector`)

---

#### snowflake — cloud data warehouse

**Required keys:** `url`, `database`, `warehouse`, `user`, `password`

```yaml
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

| Key | Notes |
|-----|-------|
| `id` | Unique name |
| `url` | Account URL from Snowflake; the adapter extracts the account identifier automatically |
| `database` | Snowflake database |
| `warehouse` | Compute warehouse to use |
| `schema` | Optional schema within the database |
| `role` | Optional Snowflake role |
| `user` | Login user — prefer `${ENV_VAR}` |
| `password` | Use `${ENV_VAR}` |

Capability provided: `structured_query` (tools: `execute_semantic_query`, `run_guarded_sql`; postgres-named aliases also work). Snowflake is live. Because routing is capability-based, the structured-query tools work against Snowflake just as they do against Postgres. It shares the `structured_query` capability with Postgres, so a `source_id` may be required to direct a query to the correct source when both are configured.

---

#### duckdb — local analytical SQL

**Required keys:** `path`

```yaml
sources:
  duckdb:
    id: novamart_duckdb
    path: ./data/novamart_analytics.duckdb
```

| Key | Notes |
|-----|-------|
| `id` | Unique name |
| `path` | File path to the `.duckdb` file (relative to the project root) |
| `database` / `schema` | Optional — for multi-database DuckDB setups |

Capability provided: none yet — no adapter built yet. DuckDB is declared in `source_config.yaml` only; it will not be probed or queried until an adapter exists.

---

#### mongodb — document store

**Required keys:** `url`, `database`, `collection`

```yaml
sources:
  mongodb:
    id: novamart_mongodb
    url: mongodb://localhost:27017
    database: novamart
    collection: seller_events
    user: novamart_app
    password: ${MONGO_PASSWORD}
```

| Key | Notes |
|-----|-------|
| `id` | Unique name |
| `url` | MongoDB connection string |
| `database` | Database name |
| `collection` | Collection to query |
| `user` / `password` | Auth credentials — use `${ENV_VAR}` for password |

Capability provided: `document_query` (tool: `query_documents`). The adapter is available and exposes `query_documents`; it requires a running MongoDB instance to return data (the example does not bundle one).

---

### Validation

Run this after any change to `source_config.yaml`:

```bash
recosearch --validate
```

The validator checks:
- All required keys are present for each source type
- No duplicate source IDs
- Port numbers are integers in the valid range
- URLs include a scheme and host
- Credential fields use `${ENV_VAR}` references (flags plain text as a warning)

---

## semantic.md — what the data means

This file is the **only** place business meaning lives. It is written in plain English.
Nothing about data meaning belongs in Python code.

The file uses five sections, each prefixed with a `#` heading:

```
# metrics
# rules
# dimensions
# measures
# relations
```

### Field format

Every dimension and measure uses the format:

```
source_id.table.column: plain English description
```

For example:

```markdown
- novamart_postgres.orders.order_status: fulfillment state of the order such as delivered, returned, cancelled, or pending
- novamart_opensearch.customer_reviews.rating: star score from 1 to 5 on a customer review, default average
- novamart_qdrant.novamart_policy_chunks.text: policy text extracted from the source PDF chunk
```

The `source_id` must match an `id` in `source_config.yaml`.

---

### Metrics

Named calculations expressed in plain English. The server uses these to understand what a question is asking for.

```markdown
# metrics

- delivered order revenue: sum of total amount from orders where order status = delivered.
  Excludes cancelled, returned, and pending orders.
- bad review count: count of customer reviews where rating is 1 or 2.
  Use this to identify products crossing review-risk thresholds.
```

---

### Rules

Business constraints that the server enforces on every query.
Each rule is marked `active` (enforced now) or `inactive` (noted but skipped).

```markdown
# rules

- active: Ignore product P003 from all calculations, it is a blacklisted product.
- active: Sales and revenue metrics must use delivered orders only unless the user explicitly asks
  for returned, cancelled, or pending order analysis.
- active: Reviews tagged suspicious_positive, incentivized_review, or fake_review_pattern are
  trust-risk signals and must not be used to override policy concerns or bad-review thresholds.
```

Rules compile into SQL `WHERE` clauses automatically. You never write the exclusion logic in code.

---

### Dimensions

Fields used to slice or filter results — order dates, categories, regions, statuses.
Write one entry per field using `source_id.table.column: description`.

```markdown
# dimensions

- novamart_postgres.orders.order_date: calendar date the order was placed
- novamart_postgres.orders.order_status: fulfillment state of the order such as delivered, returned,
  cancelled, or pending
- novamart_postgres.products.category: marketplace category assigned to the product such as Electronics or Beauty
- novamart_opensearch.customer_reviews.tags: keyword labels summarizing review themes such as good audio or durable
```

---

### Measures

Numeric fields that are aggregated — revenue, quantities, ratings.
Include the default aggregation in the description.

```markdown
# measures

- novamart_postgres.orders.total_amount: monetary value of the order line, default sum
- novamart_postgres.orders.discount_amount: discount value applied to the order line, default sum
- novamart_postgres.products.inventory_units: available catalog inventory units for the product, default sum
- novamart_opensearch.customer_reviews.rating: star score from 1 to 5 on a customer review, default average
```

---

### Relations

Cross-source joins declared as equality pairs. The server uses these to combine data across Postgres,
OpenSearch, and other sources in a single answer.

```markdown
# relations

- novamart_postgres.orders.product_id = novamart_postgres.products.product_id
- novamart_postgres.orders.order_id = novamart_opensearch.customer_reviews.order_id
- novamart_postgres.orders.product_id = novamart_opensearch.customer_reviews.product_id
- novamart_snowflake.sellers.seller_id = novamart_postgres.products.seller_id
```

---

## The generated file: semantic.json

`semantic.json` is a compiled output written beside the input files in the directory named by
`RECOSEARCH_SEMANTIC_DIR` (for the example, `examples/novamart/semantic.json`) — never edit it by hand.
Regenerate it whenever you change `source_config.yaml` or `semantic.md` (the scenario identity from
`scenario_config.yaml` is also stamped in, but governance-only edits do not require a recompile):

```bash
recosearch --write-semantic-json
```

Then validate that the contract is consistent:

```bash
recosearch --validate
```

A quick health check confirms that live sources are reachable:

```bash
recosearch --health-check
```

---

## Next steps

To add a brand new source from scratch — adapter code, config block, and semantic entries together — see [adding-a-source.md](adding-a-source.md).
