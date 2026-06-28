# Worked example: one real question, end to end

This page walks a single business question through RecoSearch against the bundled
zero-infrastructure **NovaShop** example — from the LLM's tool calls to the real
returned rows, their citations, and a validated final answer. Every output below
was captured from an actual run. You can reproduce it yourself:

```bash
pip install -e ".[duckdb]"
python examples/novashop-duckdb/seed.py
export RECOSEARCH_SEMANTIC_DIR=examples/novashop-duckdb
recosearch --write-semantic-json
recosearch            # then connect your MCP client
```

The question: **"Which product category drove the most delivered order revenue —
and can I trust the number?"**

---

## 1. See what's available

`list_sources` →

```json
{
  "status": "ok",
  "sources": {
    "novashop": { "id": "novashop", "path": "./novashop.duckdb", "type": "duckdb" }
  }
}
```

One structured source, no server required.

## 2. Run a governed semantic query

The LLM expresses the question as a **plan** (field ids, an aggregation, a join, a
filter) and calls `execute_semantic_query` with the declared metric:

```json
{
  "plan": {
    "select": [
      {"field": "novashop.products.category", "alias": "category"},
      {"field": "novashop.orders.total_amount", "aggregation": "sum", "alias": "delivered_order_revenue"}
    ],
    "joins": [{"left": "novashop.orders.product_id", "right": "novashop.products.product_id"}],
    "filters": [{"field": "novashop.orders.order_status", "operator": "=", "value": "delivered"}],
    "group_by": ["novashop.products.category"],
    "order_by": [{"field": "delivered_order_revenue", "direction": "desc"}],
    "limit": 10
  },
  "metric_id": "delivered order revenue"
}
```

RecoSearch compiles that into SQL and **applies the global rules automatically** —
note the blacklisted-product exclusion and the delivered-only filter that the LLM
never had to remember:

```sql
SELECT t_1.category AS category, SUM(t_0.total_amount) AS delivered_order_revenue
FROM orders t_0
JOIN products t_1 ON t_0.product_id = t_1.product_id
WHERE t_0.product_id != %s AND t_1.product_id != %s   -- NS-013 blacklist rule
  AND t_0.order_status = %s                            -- delivered-only rule
GROUP BY t_1.category
ORDER BY delivered_order_revenue DESC
LIMIT 10
```

> **Note:** The compiler emits `%s` placeholders (standard Python DBAPI). The DuckDB
> adapter converts `%s` → `?` at execution time to match DuckDB's parameter style.

Real returned rows:

| category | delivered_order_revenue |
|----------|------------------------:|
| Electronics | 38,535.95 |
| Home & Kitchen | 11,383.40 |
| Sports | 7,771.10 |
| Beauty | 3,044.60 |

Every row carries a `_citation` (trimmed here):

```json
{
  "category": "Electronics",
  "delivered_order_revenue": 38535.95,
  "_citation": {
    "evidence_id": "pg:6db0ec3a…",
    "source": "novashop",
    "source_ref": {"source_id": "novashop", "source_type": "duckdb", "boundary": "novashop"},
    "semantic_contract_id": "novashop_duckdb.semantic",
    "contract_hash": "sha256:d659e07e…",
    "provenance_id": "prov:e5dfe51e…",
    "may_support_final_answer": true,
    "claim_mode": "claim_support"
  }
}
```

## 3. Validate the evidence before answering

`validate_cited_evidence_packet` is a tool the **client** (LLM / calling process)
must invoke explicitly — the server provides the validator and provenance metadata,
but does not automatically run the gate. The LLM packages its claim with the
evidence ids it intends to cite and calls `validate_cited_evidence_packet`:

```json
{
  "claims": [{
    "claim": "Among delivered orders, Electronics drove the most order revenue.",
    "claim_type": "metric_aggregate",
    "required_sources": ["novashop"],
    "evidence_ids": ["pg:6db0ec3a…"]
  }],
  "tool_results": [ <the full execute_semantic_query response> ]
}
```

Result:

```json
{ "status": "ok", "valid": true, "evidence_count": 4,
  "contract_hash": "sha256:d659e07e…", "errors": [] }
```

`valid: true` — the claim is backed by evidence that was actually returned this
session, from the source that defines the metric, pinned to the current contract.
Only now should the answer be presented.

## 4. Governance you get for free

**Hand-written SQL must honour the same rules.** Ask for net revenue but omit the
blacklist exclusion and `run_guarded_sql` refuses:

```json
{ "status": "refused", "guard": { "reason_code": "missing_global_exclusion",
  "required_exclusions": [ { "column": "product_id", "value": "NS-013",
    "reason": "semantic.md declares: Ignore product NS-013 …" } ] } }
```

Add the required exclusion and it runs — returning delivered **net** revenue
(`total_amount - discount_amount`): Electronics 36,624.87, Home & Kitchen
10,722.31, Sports 7,455.10, Beauty 2,925.79. (These rows come back in
`exploratory` citation mode; to let them back a final claim, request
`claim_support` mode with a purpose.)

**Writes are impossible.** Any non-`SELECT` is rejected outright:

```json
{ "status": "refused", "guard": { "reason_code": "mutating_sql" } }
```

**Sensitive fields are masked by role.** With `RECOSEARCH_ROLE=analyst`, selecting
`novashop.customers.email` returns `***MASKED***`; with `RECOSEARCH_ROLE=admin`
(an `unmasked_roles` member) the real values come through. RBAC and masking are
configured in `scenario_config.yaml` — no code.

## 5. The final, cited answer

> Among delivered orders, **Electronics** drove the most order revenue at
> **$38,535.95** — roughly 3.4× the next category (Home & Kitchen, $11,383.40).
> The figure excludes returned/cancelled/pending orders and the blacklisted
> product NS-013 per the semantic contract, and is backed by cited evidence
> (`validate_cited_evidence_packet` → `valid: true`).

Every number in that sentence is traceable to a query RecoSearch actually ran,
under rules it enforced — not to the model's memory.

---

See [asking-questions.md](asking-questions.md) for the full tool reference and
[troubleshooting.md](troubleshooting.md) for every `reason_code`.
