# Asking questions

This page explains how to actually use the MCP server to get answers. It covers
what tools exist, when to use each one, how the server decides which data source
to query, and what "cited evidence" means.

---

## The tools at a glance

| Tool | What it does |
|------|-------------|
| `list_sources` | List every data source declared in `source_config.yaml` (with credentials redacted). |
| `health_check_sources` | Probe each live source and report whether it is reachable. |
| `validate_analysis_request` | Check that your planned analysis is specific enough before running it. |
| `execute_semantic_query` | Run a structured query expressed as a semantic plan (field ids, filters, aggregations). |
| `run_guarded_sql` | Run a hand-written SQL statement through the semantic allow-list guard. |
| `search_text` | Full-text search over a text-search source (OpenSearch). |
| `search_vector` | Semantic / similarity search over a vector source (Qdrant). |
| `query_documents` | Document queries over MongoDB. |
| `get_semantic_contract` | Retrieve the compiled semantic contract for the current configuration. |
| `generate_semantic_json` | Generate the semantic contract JSON from the authored semantic files. |
| `combine_slices` | Join rows from two different sources after querying each one separately. |
| `validate_cited_evidence_packet` | **Client must call this.** The server provides the validator and provenance; the client (LLM / calling process) invokes it to confirm every claim is backed by cited MCP evidence before presenting a final answer. The server does not auto-validate on the client's behalf. |

---

## The capability-to-tool map

The server is built around storage *capabilities*, not source names. A source
advertises a capability, and that is what routes it to a tool:

| Capability | Tool(s) |
|------------|---------|
| `structured_query` | `execute_semantic_query`, `run_guarded_sql` |
| `text_search` | `search_text` |
| `vector_search` | `search_vector` |
| `document_query` | `query_documents` |

The structured-query tools are generic: routing is capability-based, so they work
for any `structured_query` source (Postgres, Snowflake), not just Postgres. The
older postgres-named tools `execute_postgres_semantic_query` and
`run_guarded_postgres_sql` remain as compatibility aliases and continue to work.

Currently live sources:

- `novamart_postgres` — `structured_query` (Postgres)
- `novamart_snowflake` — `structured_query` (Snowflake)
- `novamart_opensearch` — `text_search` (OpenSearch)
- `novamart_qdrant` — `vector_search` (Qdrant)
- `novamart_mongodb` — `document_query` (MongoDB)

Snowflake (`novamart_snowflake`) is live (`available=True`), `structured_query`; it shares
that capability with Postgres so a `source_id` may be needed to disambiguate.

The MongoDB adapter is available (`available=True`) and exposes the
`query_documents` tool (`document_query` capability); it requires a running
MongoDB instance to return data. DuckDB has a `structured_query` adapter and
powers the **zero-infrastructure** example in `examples/novashop-duckdb` — a
single local file, no server, runnable with nothing else installed.

---

## How source selection works

When you call a tool you can pass a `source_id` argument to name the source
explicitly. What happens when you do not is determined by how many sources share
the same capability:

**Only one live source for that capability** — the server picks it automatically.
No `source_id` needed.

**Two or more live sources share the capability** — the server cannot guess which
one you mean. It refuses with:

```json
{
  "status": "refused",
  "reason_code": "source_selection_required",
  "capability": "structured_query",
  "candidates": ["novamart_postgres", "novamart_snowflake"]
}
```

Pass the `source_id` you want and the call succeeds:

```json
{ "source_id": "novamart_postgres", ... }
```

This refusal is intentional and correct. Two sources that share a capability
can have different schemas, different governance rules, and different data. The
server will not silently pick one and produce an answer whose data origin is
ambiguous.

A related refusal is `single_query_spans_sources` — this appears when your SQL
references tables that live in two different sources. The fix is to query each
source separately, then use `combine_slices` to join the results.

---

## What "cited evidence" means

Every row returned by a data tool carries a `_citation` object. That object
records where the row came from: which source, which contract version, which
fields were selected, and whether the output is safe to use in a final answer
(`may_support_final_answer`).

A final business answer must be backed by at least one piece of cited evidence.
Without it, the LLM is making a claim from memory or from exploratory data that
was never validated for claim support. The `validate_cited_evidence_packet` tool
checks the full evidence chain:

1. Each claim lists `evidence_ids`.
2. Each evidence id resolves to a row citation or provenance envelope.
3. The citation confirms the output status was `ok` and `may_support_final_answer`
   is `true`.
4. The citation's `contract_hash` matches the current compiled contract
   (so stale evidence from a previous schema version is rejected).

If any link in that chain is broken, `validate_cited_evidence_packet` returns
`"valid": false` with a list of errors per claim. Fix the errors — usually by
re-running the source tool in `claim_support` citation mode — before presenting
the answer.

---

## Step-by-step: a typical query

### 1. Check what is available

```
list_sources
```

Returns the declared sources and their types. Use `health_check_sources` to
confirm they are reachable before running queries.

### 2. Validate your plan (optional but recommended)

```
validate_analysis_request({
  "metric_ids": ["delivered order revenue"],
  "time_window": "last_30_days",
  "expected_sources": ["novamart_postgres"]
})
```

If the plan is missing a required input (no metric, no time window, ambiguous
source), the response lists exactly what to ask the user before proceeding.

### 3. Query a source

**Semantic plan query (preferred for structured data):**

```
execute_semantic_query({
  "plan": {
    "select": [
      {"field": "novamart_postgres.products.category", "alias": "category"},
      {"field": "novamart_postgres.orders.total_amount", "aggregation": "sum", "alias": "delivered_order_revenue"}
    ],
    "joins": [
      {"left": "novamart_postgres.orders.product_id", "right": "novamart_postgres.products.product_id"}
    ],
    "filters": [
      {"field": "novamart_postgres.orders.order_status", "operator": "=", "value": "delivered"}
    ],
    "group_by": ["novamart_postgres.products.category"],
    "order_by": [{"field": "delivered_order_revenue", "direction": "desc"}],
    "limit": 100
  },
  "metric_id": "delivered order revenue",
  "source_id": "novamart_postgres"
})
```

The server compiles that plan into SQL, validates every field against the
contract, applies the active global rules (e.g. the blacklisted-product
exclusion and delivered-only filter), runs it, and returns rows with `_citation`
objects attached. Every non-aggregate `select` field must appear in `group_by`.
For a full, reproducible run against real data, see the
[worked example](worked-example.md).

**Text search:**

```
search_text({
  "source_id": "novamart_opensearch",
  "query": "damaged packaging",
  "limit": 10
})
```

**Vector search:**

```
search_vector({
  "query": "return policy for electronics",
  "source_id": "novamart_qdrant",
  "limit": 5
})
```

### 4. Validate evidence before stating a final answer

```
validate_cited_evidence_packet({
  "claims": [
    {
      "claim": "Among delivered orders, the Electronics category generated the highest order revenue.",
      "claim_type": "metric_aggregate",
      "required_sources": ["novamart_postgres"],
      "evidence_ids": ["<evidence_id from the row _citation>"]
    }
  ],
  "tool_results": [<the full response object from execute_semantic_query>]
})
```

If `"valid": true`, you can present the claim. If not, review the `errors` list
and re-run the relevant tool with `citation_mode` set to `"claim_support"`.

---

## Example: combining two sources

If your question needs both structured order data and customer reviews, you query
each source separately and then merge:

```
# Step 1: structured data
execute_semantic_query({ "plan": {...}, "source_id": "novamart_postgres" })

# Step 2: text search
search_text({ "source_id": "novamart_opensearch", "query": "return experience" })

# Step 3: join on a declared relation field
combine_slices({
  "left_rows": <postgres_result.rows>,
  "right_rows": <opensearch_result.rows>,
  "left_key": "order_id",
  "right_key": "order_id"
})
```

`left_key` and `right_key` are the column names as they appear in each slice's
rows. The `combine_slices` tool requires that the two sources have a declared
relation in `semantic/semantic.md` (here `orders.order_id =
customer_reviews.order_id`). If no relation is declared, the call is refused with
`undeclared_relation`; if the key is absent from a slice, it refuses with
`join_key_missing`.

---

## Common refusals and what they mean

| `reason_code` | Meaning | Fix |
|---------------|---------|-----|
| `source_selection_required` | Two sources share the capability; server cannot pick one. | Pass `source_id` explicitly. |
| `single_query_spans_sources` | SQL references tables from two different sources. | Split the query; use `combine_slices`. |
| `contract_invalid` | The compiled semantic contract has errors. | Run `recosearch --validate` and fix the issues in `semantic/semantic.md`. |
| `evidence_not_claim_supporting` | The row was from an exploratory call and cannot back a final answer. | Re-run the tool with `citation_mode: "claim_support"`. |
| `contract_hash_mismatch` | Evidence was collected before the contract changed. | Re-run all source tools after updating `semantic.md`. |

---

## Further reading

- Stuck on a refusal or connection error? See [troubleshooting.md](troubleshooting.md).
- Want to add a new source? See [adding-a-source.md](adding-a-source.md).
- Want to trace what the server is doing? See [observability.md](observability.md).
