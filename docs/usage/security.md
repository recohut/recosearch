# Security and Governance

Last updated: 2026-06-17

RecoSearch applies a layered governance model: role-based access control (RBAC) decides which MCP tools a caller may invoke, field-level ACL masking decides what data values are visible in results and traces, and `source_config.yaml` validation keeps credentials out of config files. All three layers are opt-in: omitting the relevant config block means that control is simply off.

---

## 1. RBAC — Role-Based Tool Access

### How it works

Every MCP tool registration passes through `rbac_gate` in `recosearch/rbac.py`. The gate reads the `RECOSEARCH_ROLE` environment variable (set in your MCP client config), compares it against the `roles` block in `semantic/scenario_config.yaml`, and either lets the tool through untouched or replaces it with a refusing stub that returns:

```json
{
  "status": "refused",
  "reason_code": "role_not_permitted",
  "role": "viewer",
  "tool": "run_guarded_sql",
  "rows": [],
  "row_count": 0
}
```

The decision is fixed at process startup — the role is constant for the process lifetime. Allowed tools run with zero overhead; denied tools return the refusal immediately without executing any query.

### Opt-in semantics

| Situation | Behaviour |
|---|---|
| `RECOSEARCH_ROLE` not set | Enforcement is off — every tool passes through unchanged. |
| `RECOSEARCH_ROLE` set, no `roles` block in scenario file | Enforcement is off — business owner declared no roles, open to all. |
| `RECOSEARCH_ROLE` = a known role | Only the tools listed for that role are allowed; all others are refused. |
| `RECOSEARCH_ROLE` = an unknown role | Every tool is denied (`reason_code: role_not_recognized`). This is a fail-closed / deny-all default. |

### Declaring roles in scenario_config.yaml

The `roles` block lives in `semantic/scenario_config.yaml`. Each key is a role name; `tools` is the list of MCP tool names that role may call. The special value `"*"` grants all tools.

```yaml
roles:
  admin:
    tools: ["*"]          # unrestricted

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

  policy_only:
    tools:
      - list_sources
      - get_semantic_contract
      - search_vector
      - validate_analysis_request
      - validate_cited_evidence_packet
```

To activate a role, set the environment variable in your MCP client config:

```json
{
  "env": {
    "RECOSEARCH_ROLE": "analyst"
  }
}
```

### Role summary (NovaMart scenario)

| Role | Key permissions |
|---|---|
| `admin` | All tools (`*`) |
| `analyst` | Search (text + vector), guarded SQL, semantic query, combine, validate |
| `viewer` | Search (text + vector), combine, validate — no SQL access |
| `policy_only` | Read-only policy tools — vector search and contract inspection only |

---

## 2. ACL — Field-Level PII Masking

### How it works

`recosearch/acl.py` wraps each tool with `mask_result`. When masking is active, any column named in `sensitive_fields` is replaced with the mask token before the result is returned to the caller.

Critically, `mask_result` runs **inside** `traced_tool` in the dispatch chain, so the Phoenix/OTEL span records the already-masked rows. PII does not leak into traces for restricted roles.

### Opt-in semantics

Masking applies only when all three conditions hold:

1. `RECOSEARCH_ROLE` is set (a role is active).
2. `sensitive_fields` is declared in the `access` block.
3. The active role is **not** in `unmasked_roles`.

If `RECOSEARCH_ROLE` is unset, or no `sensitive_fields` are declared, `mask_result` returns the original function with no wrapping — zero overhead.

### Declaring sensitive fields

The `access` block lives in `semantic/scenario_config.yaml`:

```yaml
access:
  sensitive_fields:
    - novamart_opensearch.customer_reviews.customer_id
    - novamart_snowflake.sellers.seller_name
  unmasked_roles: [admin]
  mask: "***MASKED***"
```

`sensitive_fields` uses dotted notation (`source.table.column`); only the final segment (the column name) is used for matching. Federated join results with `left_` / `right_` prefixes are also matched and masked.

### What gets masked

For any role **not** in `unmasked_roles` (i.e. analyst, viewer, policy_only):

- `customer_id` values in result rows become `***MASKED***`.
- `seller_name` values in result rows become `***MASKED***`.
- `_citation.record_ref` fields with those column names are also masked.
- The response envelope gains a `masking` metadata object:

```json
{
  "rows": [...],
  "masking": {
    "applied": true,
    "masked_columns": ["customer_id", "seller_name"],
    "role": "analyst"
  }
}
```

For `admin`, values are returned unmasked.

---

## 3. Secrets — ${ENV} References in source_config.yaml

Connection credentials must not be stored as plaintext in `source_config.yaml`. Use `${VAR}` syntax to reference environment variables:

```yaml
sources:
  postgres:
    id: novamart_postgres
    host: db.example.com
    password: ${PG_PASSWORD}
```

At server startup `_resolve_env_refs` in `recosearch/config.py` replaces each `${VAR}` with the value of the named environment variable. If the variable is unset, the literal reference string is passed through unchanged — the subsequent connection attempt will fail loudly rather than silently connecting with a blank credential.

### Validation at load time

`validate_source_config()` runs structural checks and flags credential hygiene issues:

| Issue | Severity | Description |
|---|---|---|
| `config_plaintext_secret` | WARNING | `password`, `token`, `secret`, or `api_key` is a literal string, not a `${VAR}` ref. |
| `config_duplicate_yaml_key` | ERROR | A YAML key appears more than once — last-wins merging is rejected. |
| `config_missing_required_key` | ERROR | A required field for the source type is absent. |
| `config_malformed_url` | ERROR | A `url` field lacks scheme or host. |
| `config_malformed_port` | ERROR | A `port` field is not an integer in 1..65535. |

Warnings do not block startup but should be resolved before production deployment.

---

## 4. The Dispatch Chain

Every registered MCP tool passes through four layers, applied innermost to outermost at registration time:

```
stamp_trace_id(
  traced_tool(
    mask_result(
      rbac_gate(tool)
    )
  )
)
```

| Layer | Location | Role |
|---|---|---|
| `rbac_gate` | `recosearch/rbac.py` | Innermost. Denies the call before any query runs if the role is not permitted. |
| `mask_result` | `recosearch/acl.py` | Applies PII masking to result rows. Runs before tracing so spans see masked data. |
| `traced_tool` | `recosearch/observability.py` | Records an OTEL span with role and session ID. No-op if tracing is not configured. |
| `stamp_trace_id` | `recosearch/observability.py` | Outermost. Adds `trace_id` to every response envelope. Always active. |

The ordering means:

- A denied tool never touches a data source — the refusal is returned at the gate.
- A permitted tool's results are masked before the span is written — PII cannot leak to the observability backend for restricted roles.
- Every response, including refusals, carries a `trace_id` for correlation.
