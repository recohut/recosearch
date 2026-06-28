# Request Lifecycle

This document traces a single analysis request from the moment the LLM client calls a tool to the moment a cited-evidence packet is returned.

## Sequence

```mermaid
sequenceDiagram
    participant LLM as LLM client
    participant Tools as Tool layer (tools.py)
    participant Adapter as Adapter (adapters/&lt;source&gt;.py)
    participant Ev as Evidence + ACL (evidence.py / acl.py)

    LLM->>Tools: 1. tool call (e.g. execute_semantic_query)
    Tools->>Tools: 2. RBAC check — is this role allowed?
    Tools->>Tools: 3. contract validation — fields/joins/metrics declared?
    Note over Tools: reject → role_not_permitted / contract_invalid
    Tools->>Adapter: 4. execute the validated query
    Adapter->>Ev: 5. wrap rows + provenance (source, fields, query hash, SQL)
    Ev->>Ev: 6. mask sensitive fields for the caller's role
    Ev-->>LLM: rows + _citation
    LLM->>Tools: 7. assemble answer, cite the evidence
    Tools->>Tools: 8. validate_cited_evidence_packet
    Note over Tools: every claim must cite returned evidence, else refused
    Tools-->>LLM: final cited answer (or refusal)
```

## Step-by-step detail

### 1. Tool call

The LLM client issues an MCP tool call with a structured payload: source ID, intent, fields, filters, and any SQL or query text. The server receives this via the FastMCP handler registered for that tool.

### 2. RBAC check

`recosearch/rbac.py` looks up the active role from `RECOSEARCH_ROLE`. If the role's allowed tool list (declared in `scenario_config.yaml`) does not include the requested tool, the call is rejected immediately with a `role_not_permitted` refusal (an unrecognized role is denied everything with `role_not_recognized`). With `RECOSEARCH_ROLE` unset, RBAC is off and every tool is open.

### 3. Contract validation

`recosearch/analysis_request.py` validates the request payload against the compiled semantic contract:

- Source ID must be declared in `source_config.yaml`
- Fields must match declared dimensions or measures for that source
- Joins must match declared relations
- Metrics referenced must be defined in `semantic.md`
- Global rules that apply to the request are attached (e.g. "delivered orders only")

Validation is pure — it does not touch any database. Failures return a structured error with the specific contract violation.

### 4. Query execution

The validated request is dispatched to the adapter for that source. The adapter translates the structured request into a native query (SQL, OpenSearch DSL, Qdrant vector search, etc.) and executes it against the live data source.

For structured sources, `run_guarded_sql` additionally passes the SQL through `sqlglot` (in the source's dialect) to reject any non-`SELECT` statement before execution (`mutating_sql` / `not_read_only_select`), and refuses a `SELECT` that omits a declared global exclusion (`missing_global_exclusion`).

### 5. Evidence envelope

The adapter wraps its result in an evidence envelope containing:

- `source_id` — which source this came from
- `query_hash` — deterministic hash of the exact query that ran
- `query_text` — the actual SQL or query body
- `fields` — columns returned
- `rows` — the result rows (or a summary for large results)
- `applied_rules` — which global rules were enforced on this query

### 6. Field masking

`recosearch/acl.py` inspects the envelope's fields against the `access.sensitive_fields` list in `scenario_config.yaml`. Any field the caller's role is not authorized to see is replaced with the configured mask value (default `***MASKED***`) in both the rows and the field list.

### 7. LLM assembles answer

The LLM receives one or more evidence envelopes (one per source queried). It uses `combine_slices` to merge results across sources when needed, then formulates its answer citing each envelope by `source_id` and `query_hash`.

### 8. Citation validation

Before the answer is returned to the end user, `validate_cited_evidence_packet` checks that:

- Every factual claim in the answer references an evidence envelope
- The referenced `source_id` and `query_hash` match an envelope that was actually returned in this session
- No metric claim is made without source-specific evidence from the source that defines that metric
- No cross-source conclusion is made unless each required source has cited evidence

Packets that fail validation are rejected with a structured explanation of which claims lack support.

## Reason codes

Refusals carry a structured `reason_code`. The most common ones:

| `reason_code` | Meaning |
|---------------|---------|
| `role_not_permitted` | The active role is not allowed to call this tool (RBAC) |
| `role_not_recognized` | `RECOSEARCH_ROLE` names a role not declared in `scenario_config.yaml` (deny-all) |
| `source_selection_required` | Multiple sources share a capability; caller must specify `source_id` |
| `no_source_for_capability` | No declared source provides the requested capability |
| `single_query_spans_sources` | SQL references tables from two different sources; split and use `combine_slices` |
| `contract_invalid` | Request references an undeclared source, field, or metric |
| `mutating_sql` / `not_read_only_select` | Guarded SQL executor received a non-`SELECT` statement |
| `missing_global_exclusion` | Hand-written SQL omitted a declared global exclusion (e.g. a blacklisted product) |
| `column_not_allowed` / `table_not_allowed` | SQL touches a column/table not in the contract allow-list |
| `source_execution_failed` | The adapter failed to execute the query against the source |
| `evidence_not_claim_supporting` | Cited evidence was exploratory and cannot back a final claim |
| `contract_hash_mismatch` | Cited evidence predates the current compiled contract |

See [troubleshooting.md](../usage/troubleshooting.md) for the full list and fixes.
