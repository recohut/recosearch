# Federation: combining slices across sources

Last updated: 2026-06-17

Federation is how RecoSearch produces a single answer from data that lives in
two different sources. The core idea is simple: query each source independently,
then call `combine_slices` to join the results in memory. This page explains how
that join works, what the contract enforces before it runs, and how the output
signals disagreements between sources.

---

## How combine_slices works

`combine_slices` is a bounded, deterministic, in-memory join over rows that were
already returned by MCP data tools. It does not reach back to any data source;
it only operates on the row lists you pass in.

**Basic call shape:**

```json
{
  "left_rows":  [...],
  "right_rows": [...],
  "left_key":   "product_id",
  "right_key":  "product_id",
  "left_prefix":  "left_",
  "right_prefix": "right_",
  "match_strategy": "exact",
  "limit": 100
}
```

- `left_rows` and `right_rows` are the `rows` arrays from a previous tool call
  (e.g. `execute_semantic_query`, `search_text`).
- `left_key` / `right_key` name the join field on each side. They do not need
  to be the same string, but their values must resolve to the same entity under
  the chosen `match_strategy`.
- `left_prefix` / `right_prefix` namespace the merged output columns so that
  fields with the same name on both sides do not collide.
- `limit` caps the total number of joined rows. The hard upper bound is
  `MAX_FEDERATION_ROWS` (500); a `limit` above that is silently clamped.

**What comes back:**

```json
{
  "status": "ok",
  "source_boundary": "bounded_in_memory_slice_combiner",
  "semantic_contract_id": "<id>",
  "match_strategy": "exact",
  "provenance": { ... },
  "rows": [ ... ],
  "row_count": 3,
  "conflicts": [ ... ],
  "conflict_count": 0
}
```

Each row in `rows` is the merged left + right fields, prefixed, plus a
`_citation` object that records both source evidence ids and marks the result as
`evidence_kind: "derived"`. Per-source citations from the original slices are
preserved inside `supporting_evidence_ids` and `supporting_sources` — the origin
of every value is traceable all the way back to the tool call that fetched it.

---

## Declared-relation enforcement

Before the join runs, the contract is checked for a declared relation connecting
the two sources. Enforcement operates at **source-pair granularity**: there must
be at least one `# relations` entry in `semantic/semantic.md` that names the
left source and the right source (the specific field columns in the relation do
not have to match the join keys you pass — the check is source-to-source, not
field-to-field).

Declared relations as of this writing:

| Left | Right |
|------|-------|
| `novamart_postgres` (orders) | `novamart_postgres` (products) — same-source join |
| `novamart_postgres` | `novamart_opensearch` (customer_reviews) via `order_id`, `product_id`, `customer_id` |
| `novamart_snowflake` | `novamart_postgres` via `seller_id` |

If both slices come from declared sources and no relation connects them, the
call is refused immediately:

```json
{
  "status": "refused",
  "reason_code": "undeclared_relation",
  "left_source": "novamart_postgres",
  "right_source": "novamart_qdrant",
  "reason": "no declared relation connects these sources; cross-source joins must be declared"
}
```

The check is **fail-closed**: ambiguity or missing relation entries are not
treated as permission to proceed.

### Fail-closed on missing join keys

If a non-empty slice has no row that contains a non-null value for the specified
join key, the call is refused before any matching attempt:

```json
{
  "status": "refused",
  "reason_code": "join_key_missing",
  "side": "left",
  "join_key": "product_id"
}
```

Null join-key values are skipped during matching: a null on the left never
matches a null on the right, so a missing key cannot silently produce spurious
cross-joins.

---

## Entity resolution: the match_strategy registry

Key normalization is handled by a strategy registry in
`recosearch/entity_resolution.py`. The caller names a strategy; the join
applies the corresponding normalizer to both sides before comparing.

| Strategy | Normalizer behaviour |
|----------|---------------------|
| `exact` | Identity — values are compared as-is. This is the default and the only unconditionally safe strategy. |
| `casefold` | Calls `.casefold()` on string values; non-strings are passed through unchanged. Handles ASCII and Unicode case differences. |
| `trimmed` | Strips leading/trailing whitespace, then casefolds. Handles both case and padding differences. |

An unregistered strategy is **refused** before any matching starts:

```json
{
  "status": "refused",
  "reason_code": "unknown_match_strategy",
  "match_strategy": "fuzzy_levenshtein",
  "reason": "match strategy 'fuzzy_levenshtein' is not a registered entity-resolution policy"
}
```

This is intentional. Fuzzy or similarity-based matching requires an explicit,
reviewed policy before it can be used. Adding a new strategy means appending one
entry to `MATCH_STRATEGIES` in `entity_resolution.py`; the join logic itself
does not change.

---

## Conflict surfacing

After pairs are matched, every registered conflict check runs over each
`(left, right)` pair. The current check is **shared_field_mismatch**: if a
field name appears on both sides (excluding the join keys and internal `_`
prefixed fields) and the values disagree for the same matched entity, a conflict
record is appended to the `conflicts` list in the response.

Example conflict record:

```json
{
  "join_value": "P001",
  "check": "shared_field_mismatch",
  "field": "category",
  "left_value": "Electronics",
  "right_value": "Consumer Electronics"
}
```

Key behaviour:

- Conflicts are **always reported** in the output. They are never hidden or
  silently discarded.
- A conflict does **not** fail the join. The matched rows are still returned.
  It is the responsibility of the LLM / caller to decide how to present or
  handle the disagreement.
- The `conflict_count` field in the response gives a quick integer signal;
  inspect `conflicts` for the detail.

The conflict check registry lives in `recosearch/conflicts.py`. New checks
can be added by appending a function to `CONFLICT_CHECKS` — the join loop does
not change.

---

## Practical source notes

### Qdrant (policy chunks) — evidence, not key-joins

`novamart_qdrant` has **no declared relations** to any other source. There is no
shared key column between policy chunks and structured data. This is intentional:
policy chunks are retrieved as semantic evidence (via `search_vector`) and
combined with structured answers at the answer-assembly layer, not joined as
rows. Attempting to `combine_slices` rows from `novamart_qdrant` with rows from a
declared source will be refused with `undeclared_relation`.

### Snowflake to OpenSearch — bridge through Postgres

`novamart_snowflake` (sellers) has a declared relation to `novamart_postgres`
(products) via `seller_id`. `novamart_opensearch` (customer_reviews) has declared
relations to `novamart_postgres` (orders, products) via `order_id`, `product_id`,
and `customer_id`. There is no direct declared relation between Snowflake and
OpenSearch.

To build a combined answer that draws on Snowflake seller data and OpenSearch
review data, the correct pattern is a two-step join that bridges through
Postgres:

1. Join Snowflake sellers with Postgres products on `seller_id`.
2. Join the Postgres products result with OpenSearch reviews on `product_id`.

Each step requires its own `combine_slices` call with the appropriate declared
relation in scope.

---

## Refusals at a glance

| `reason_code` | Cause | Fix |
|---------------|-------|-----|
| `contract_invalid` | Semantic contract failed validation before join. | Run `recosearch --validate` and fix `semantic/semantic.md`. |
| `federation_slice_too_large` | Either slice exceeds 500 rows. | Filter or aggregate in the source query to reduce row count before federating. |
| `undeclared_relation` | No relation in `semantic.md` connects the two source ids. | Add a relation entry, or reconsider whether a key-join is the right approach (Qdrant chunks are evidence, not join targets). |
| `join_key_missing` | The named key field is absent or null in every row of a non-empty slice. | Verify that the source query selects the join key field. |
| `unknown_match_strategy` | Strategy name is not in the registry. | Use `exact`, `casefold`, or `trimmed`; add a new strategy to `entity_resolution.py` if a different normalizer is needed. |

---

## Further reading

- [asking-questions.md](asking-questions.md) — how to query individual sources
  and build cited evidence before calling `combine_slices`.
- [adding-a-source.md](adding-a-source.md) — how to declare a new source and
  add relation entries so it can participate in federation.
- `semantic/semantic.md` — canonical list of declared relations (the `# relations` section).
