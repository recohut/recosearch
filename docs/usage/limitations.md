# Limitations — What v0.1 Does and Does Not Do

Last updated: 2026-06-20 · Applies to: RecoSearch 0.1.0

RecoSearch 0.1.0 is a deliberately narrow first release: a governed MCP server that
separates AI reasoning from validated data execution. This page is an honest map of
its boundaries. Each item is a conscious v0.1 scope choice, not an accident — every
constraint here exists to keep the trust surface small and auditable.

---

## Single active RBAC principal — not multi-tenant

RBAC is driven by one environment variable, `RECOSEARCH_ROLE`, read once at process
startup. The role is constant for the lifetime of the process — every request that
process handles runs as the same principal.

- There is no per-request identity, no session-scoped user switching, and no
  tenant isolation inside a single server.
- To serve different roles or tenants, run separate server processes, each with its
  own `RECOSEARCH_ROLE`.

**Why this is a v0.1 choice:** a single fixed principal makes the authorization
decision trivial to reason about and audit. Multi-tenant request-scoped identity is
deferred until the single-principal model is proven.

---

## Read and query only — no writes

The SQL guard is read-only and SELECT-only. Any non-SELECT statement is refused with
`reason_code: mutating_sql` before it can execute. There is no tool that inserts,
updates, deletes, or runs DDL against your sources.

**Why this is a v0.1 choice:** the entire value proposition is letting an LLM *read*
governed data safely. Keeping the server strictly read-only removes write-path risk
from the trust boundary entirely.

---

## Row ceilings on every result

Result sizes are capped in `recosearch/settings.py`:

| Limit | Value | Applies to |
|---|---|---|
| `MAX_SOURCE_ROWS` | 100 | rows returned from a single source |
| `MAX_FEDERATION_ROWS` | 500 | rows returned from a federated join |

These are fixed defaults, not per-request knobs.

**Why this is a v0.1 choice:** RecoSearch is built for evidence-grade analysis where
claims are cited, not for bulk export. Hard ceilings keep responses bounded and
predictable; they are not a substitute for a data warehouse extract.

---

## Examples: bring-your-own-infra vs. zero-infra

Two example scenarios ship with the repo, and they differ on what you must run.

- **`examples/novamart/`** — a multi-source example (Postgres, OpenSearch, Qdrant,
  Snowflake, MongoDB). It bundles **no live infrastructure**. You stand up the
  services yourself and supply credentials before `--health-check` will pass.
- **`examples/novashop-duckdb/`** — a **zero-infrastructure** example backed by a
  single DuckDB file. Run `python examples/novashop-duckdb/seed.py` to write a
  deterministic `novashop.duckdb` (plus `data/*.csv`), point
  `RECOSEARCH_SEMANTIC_DIR` at it, and the server runs with **no running services** —
  `--health-check` returns `ok` against the local file.

**Why this is a v0.1 choice:** novashop-duckdb exists so you can try the full
governed flow with zero setup, while novamart shows the real multi-source shape
without us shipping (or pretending to ship) live infrastructure you'd have to trust.

---

## Observability is opt-in, tool-span only

Tracing is off by default. With `RECOSEARCH_TRACING_ENABLED` unset, the tracing
wrapper is a pass-through and the tool surface is identical to an untraced build.
When enabled, it exports **one span per MCP tool call** to Phoenix — an external
service you run and point at yourself; the repo neither bundles nor manages it.

- Scope is tool-level spans only. Sub-spans into the Postgres / OpenSearch / Qdrant /
  Snowflake / embedding layers are intentionally deferred.
- When enabled, each span's `output.value` carries the full tool response, so traces
  may contain PII unless field masking is configured.

**Why this is a v0.1 choice:** keeping tracing opt-in and coarse-grained means the
default build has no observability dependency and no extra data egress; deeper
instrumentation is layered in later.

---

## Federation is a deterministic join only

Cross-source results come from `combine_slices`, which merges evidence slices over
the **relations declared** in your semantic contract. The join is deterministic: it
follows the relations you authored, nothing more. There is no query planner that
infers joins, no cost-based optimization, and no implicit cross-source inference.

**Why this is a v0.1 choice:** a deterministic, declaration-driven join is auditable
— every combination traces back to a relation you wrote down. Automatic join
discovery is exactly the kind of inference RecoSearch deliberately keeps out of the
execution layer.

---

## Experimental L4/L5 tools — per-process ledger only

The decision-ledger and calibration tools (L4 `record_decision`, `replay_decision`,
`record_outcome`; L5 `generate_calibration_signal`, `aggregate_calibration`,
`counterfactual_replay`, `propose_trust_prior`, `approve_trust_prior_proposal`,
`reject_trust_prior_proposal`) are **experimental** and disabled by default. Enable
them by setting `RECOSEARCH_EXPERIMENTAL=1`.

When enabled, the decision ledger is **per-process and in-memory**. Audit entries
are **not persisted across server restarts**. Do not rely on these tools for durable
audit trails in production until persistence is added.

---

## In short

v0.1 is a small, governed, read-only window onto data sources you declare — single
principal, bounded rows, deterministic joins, optional coarse tracing. Everything
omitted here is omitted on purpose, so that what *is* present can be trusted and
audited.
