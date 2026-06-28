# Getting Started

This guide walks you from a fresh checkout to a running, question-ready RecoSearch MCP server.

There are two paths:

- **Fastest start (zero infrastructure)** — the bundled NovaShop DuckDB example runs with no external
  services. Best for trying RecoSearch in a couple of minutes. Start here.
- **Live multi-source example** — the NovaMart example queries Postgres + OpenSearch + Qdrant + Snowflake +
  MongoDB, which you run yourself. Covered in [Running the live multi-source example](#running-the-live-multi-source-example) below.

---

## Fastest start: the zero-infra example

NovaShop is a single local **DuckDB** file (products, customers, orders) — no server, no credentials.

```bash
pip install -e ".[duckdb]"                       # just the DuckDB driver
python examples/novashop-duckdb/seed.py          # build the sample DB (deterministic)
export RECOSEARCH_SEMANTIC_DIR=examples/novashop-duckdb
recosearch --write-semantic-json       # compile the contract
recosearch --validate                  # → is_valid: true
recosearch --health-check              # → status "ok", nothing else running
recosearch                             # start the MCP server
```

That is the whole loop with no infrastructure. For a real question → governed tool calls → cited answer
walkthrough against this exact scenario, see the [worked example](worked-example.md). To go deeper or run
against your own live sources, continue below.

---

## What you bring

Before you start, make sure you have:

- **Python 3.11 or newer** on your PATH.
- **For the live multi-source example only: the data services running** (Postgres, OpenSearch, Qdrant, and
  optionally Snowflake/MongoDB). These are the services the server queries. If you only have some of them, the
  others show as unavailable in the health check — that is fine. (The zero-infra NovaShop example above needs none.)
- **Your three input files.** The repo root `semantic/` directory holds neutral templates
  (placeholder `scenario_id: my_scenario`, empty `sources: {}`, and commented examples) for building
  your own scenario. A complete, ready-to-run example lives in `examples/novamart/`:
  - `scenario_config.yaml` — scenario identity (scenario_id, name, dataset_id, mcp_name) and optional
    governance (RBAC roles, ACL field masking, vocabulary extensions).
  - `source_config.yaml` — connection details for each data source (credentials via `${ENV_VAR}`).
  - `semantic.md` — business meaning: metrics, dimensions, rules, and relations in plain language.

  The server reads its input files from the directory named by `RECOSEARCH_SEMANTIC_DIR` (default `./semantic`).
  To run the NovaMart example below, point it at the example directory:

  ```bash
  export RECOSEARCH_SEMANTIC_DIR=examples/novamart
  ```

  To build your own scenario instead, leave it unset and edit the templates in `semantic/`. The server reads
  nothing else for connection details, business meaning, or governance. Details are in
  [Configuring Sources](configuring-sources.md).

DuckDB has a full `structured_query` adapter and needs no credentials or server — it powers the zero-infra
NovaShop example above. The MongoDB adapter is available and exposes `query_documents`, but it requires a running
MongoDB instance to return data (the NovaMart example does not bundle one). Snowflake is live and available.

---

## Running the live multi-source example

The steps below walk through the NovaMart example, which queries live Postgres / OpenSearch / Qdrant /
Snowflake / MongoDB that you run yourself. (The same `--validate` / `--write-semantic-json` / `--health-check` /
start commands apply to any scenario, including the zero-infra one above.)

### Step 1 — Install dependencies

From the project root:

```bash
pip install -e ".[all,dev]"
```

This installs the MCP server framework, database drivers for Postgres / OpenSearch / Qdrant / Snowflake, the local
embedding model for vector search, and the test tools. The observability packages (Phoenix / OpenTelemetry) are
optional — the server runs fine without them.

---

## Step 2 — Set up your three input files

To run the NovaMart example, point the server at the example directory first:

```bash
export RECOSEARCH_SEMANTIC_DIR=examples/novamart
```

Open `examples/novamart/source_config.yaml` and check that the connection details for your live services match your
local setup. The NovaMart example expects Postgres on port 15432, OpenSearch on 19200, and Qdrant on 16333 — you must
provide your own running services on those ports (this multi-source example does not bundle infrastructure or seed data;
if you want a runnable example with none, use the zero-infra NovaShop example above).

You do not need to touch `examples/novamart/semantic.md` to get started — it ships with the NovaMart business
definitions. When you add a new source or change a metric, that file is where you make the change.

You also do not need to change `examples/novamart/scenario_config.yaml` to get started — it ships with the NovaMart
scenario identity. Edit it when you want to enable RBAC role restrictions, ACL field masking, or custom vocabulary terms.

To build your own scenario instead of running the example, leave `RECOSEARCH_SEMANTIC_DIR` unset (it defaults to
`./semantic`) and edit the neutral templates in `semantic/`.

Full details on all three files are in [Configuring Sources](configuring-sources.md).

---

## Step 3 — Validate your inputs

```bash
recosearch --validate
```

This checks `scenario_config.yaml`, `source_config.yaml`, and `semantic.md` in the directory named by
`RECOSEARCH_SEMANTIC_DIR` (e.g. `examples/novamart/`) for errors and prints a summary. Exit code 0 means
everything is valid. Exit code 2 means there are error-severity issues — the output tells you exactly which lines
need fixing.

Fix any errors before continuing. Warnings do not block startup but are worth reading.

---

## Step 4 — Compile the semantic contract

```bash
recosearch --write-semantic-json
```

This reads your three input files and writes `semantic.json` beside them in the input directory (for the example,
`examples/novamart/semantic.json`) — the compiled, structured version of the contract that the server uses at runtime.
You must re-run this command any time you change `source_config.yaml` or `semantic.md`.

The command prints the output path and a `"status": "ok"` confirmation when it succeeds.

---

## Step 5 — Run a health check

```bash
recosearch --health-check
```

This probes each declared source and prints a JSON summary showing which sources are reachable. A healthy live setup
looks like:

```json
{
  "novamart_opensearch": {"status": "ok"},
  "novamart_postgres":   {"status": "ok"},
  "novamart_qdrant":     {"status": "ok"},
  "novamart_snowflake":  {"status": "ok"}
}
```

Only sources marked `"ok"` will accept queries. MongoDB is available, but without a running MongoDB instance its probe
reports a failure; the NovaMart `novamart_duckdb` source points at a DuckDB file that the example does not ship, so it
reports a failure too until you build one — that is expected. (The standalone NovaShop DuckDB example *does* ship a
build script, so its health check is `"ok"`.)

---

## Step 6 — Start the server

```bash
recosearch
```

The server starts and listens on the MCP stdio transport. By default it runs in `warn` mode — contract warnings are
logged but do not block startup. To enforce strict validation (for CI or production):

```bash
RECOSEARCH_CONTRACT_ENFORCEMENT=strict recosearch
```

In strict mode the server refuses to start if the contract has errors or if `semantic.json` is stale.

### Optional environment variables

| Variable | Values | Effect |
|---|---|---|
| `RECOSEARCH_SEMANTIC_DIR` | path (default `./semantic`) | Directory the server reads input files from; set to `examples/novamart` to run the example |
| `RECOSEARCH_CONTRACT_ENFORCEMENT` | `warn` (default) or `strict` | Controls whether contract errors block startup |
| `RECOSEARCH_TRACING_ENABLED` | `1` | Exports MCP tool spans to Phoenix (requires observability packages) |
| `RECOSEARCH_ROLE` | e.g. `analyst`, `admin` | Sets the RBAC role for this server process |

---

## Step 7 — Ask your first question

Connect an MCP-compatible client (such as Claude Desktop or a script using the MCP SDK) to the running server and
send a tool call. The server exposes these tools based on which sources are live:

- `search_text` — full-text search over OpenSearch (customer reviews, etc.)
- `search_vector` — semantic / similarity search over Qdrant (policy chunks, etc.)
- `execute_semantic_query` — governed SQL over any structured-query source (Postgres, Snowflake) using the
  semantic contract. Routing is capability-based. (`execute_postgres_semantic_query` is a compatibility alias.)
- `run_guarded_sql` — raw SQL over any structured-query source, restricted to allow-listed tables and columns.
  (`run_guarded_postgres_sql` is a compatibility alias.)
- `query_documents` — document query over MongoDB (available; requires a running MongoDB instance to return data)
- `generate_semantic_json` — compile the semantic contract from your three input files
- `combine_slices` — merge multiple result slices into a single response
- `validate_analysis_request` — validate an analysis request against the semantic contract
- `validate_cited_evidence_packet` — validate that cited evidence matches source data
- `get_semantic_contract` — inspect the compiled contract the server is using
- `list_sources` — see which sources are available right now
- `health_check_sources` — re-probe sources without restarting the server

For a step-by-step example with real queries and expected responses, see [Asking Questions](asking-questions.md).

---

## If something refuses

- **`source_selection_required`** — two or more live sources share the same capability. Pass an explicit `source_id`
  in your tool call to pick one. This is by design, not a bug.
- **Contract errors at startup** — run `recosearch --validate` to see the exact issues, fix them in your
  input files, then re-run `--write-semantic-json` before restarting.
- **`semantic.json` is stale** — run `recosearch --write-semantic-json` to recompile.
- **A source shows `unavailable`** — the service is not reachable or no adapter is built for it. Check that your
  service is running on the expected host/port and that its credential config is correct.

Full troubleshooting steps are in [Troubleshooting](troubleshooting.md).
