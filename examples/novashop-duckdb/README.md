# NovaShop — zero-infrastructure DuckDB example

NovaShop is a small single-store retail dataset that lets you run RecoSearch end
to end with **no servers, no credentials, and no external infrastructure** —
everything lives in one local DuckDB file.

The dataset models a tiny online store across three tables:

- **products** — 13 catalog SKUs (Electronics, Home & Kitchen, Beauty, Sports)
- **customers** — 60 buyers with segment, region, and a (sensitive) email
- **orders** — 600 order lines spanning Jul 2025 – Jun 2026, with status, channel,
  shipping region, quantity, unit price, discount, and total

Generation is **fully deterministic** (fixed RNG seed `42`), so the numbers in the
worked example are stable on every machine.

## What's in this directory

The three authority files RecoSearch reads for any scenario:

- `source_config.yaml` — one DuckDB source (`novashop`) pointing at `./novashop.duckdb`
- `semantic.md` — the human-authored contract: metrics, rules, dimensions, measures, relations
- `scenario_config.yaml` — scenario identity plus optional RBAC and field-masking governance

Plus the seed: `seed.py` (rebuilds the database and CSVs).

> `novashop.duckdb` and `semantic.json` are **git-ignored** — they are rebuilt
> locally. The CSVs under `data/` (`products.csv`, `customers.csv`, `orders.csv`)
> **are committed** as the human-readable source for the database.

## Build and run

```bash
# 1. Install RecoSearch with just the DuckDB driver
pip install -e ".[duckdb]"

# 2. Build the deterministic database (writes novashop.duckdb + data/*.csv)
python examples/novashop-duckdb/seed.py

# 3. Point RecoSearch at this scenario
export RECOSEARCH_SEMANTIC_DIR=examples/novashop-duckdb

# 4. Compile the semantic contract to JSON, then validate it
recosearch --write-semantic-json
recosearch --validate

# 5. Health check — returns status ok with NO running services needed
recosearch --health-check

# 6. Start the MCP server
recosearch
```

## Governance demonstrated

Governance is **always on**, independent of how a query is phrased:

- **Read-only SQL guard** — `run_guarded_sql` accepts `SELECT` only; any mutating
  statement is refused (`reason_code: mutating_sql`).
- **NS-013 blacklist (global rule)** — `semantic.md` declares NS-013 (a draft
  "Generic Clip-On Phone Lens") as a blacklisted product. Hand-written SQL that
  omits this declared exclusion is refused with `reason_code: missing_global_exclusion`.
- **Delivered-only revenue rule** — sales and revenue metrics must use delivered
  orders only, so returned, cancelled, and pending orders are excluded unless the
  request asks for them explicitly.

Two more controls are **opt-in** and configured in `scenario_config.yaml`:

- **RBAC tool gating** — the active role comes from `RECOSEARCH_ROLE`. `admin` gets
  every tool; `analyst` can run and validate queries; `viewer` is restricted to
  read-the-contract and validation tools.
- **Email masking (ACL)** — `novashop.customers.email` is masked
  (`***MASKED***`) for every role except `admin`. Query the email field as
  `analyst` vs `admin` to see the difference.

```bash
export RECOSEARCH_ROLE=analyst   # gated tools + masked email
export RECOSEARCH_ROLE=admin     # everything, unmasked email
```

## Learn more

See `docs/usage/worked-example.md` for a full, step-by-step walkthrough that runs
real queries against this dataset and shows each governance decision in action.
