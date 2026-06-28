# Contributing to RecoSearch

Thanks for your interest in contributing. RecoSearch is a governed MCP server that
separates AI reasoning from validated data execution: the LLM plans, RecoSearch
validates and executes only authorized requests against your declared sources.
This guide covers local setup, the project's design rules, and what we expect on a PR.

By contributing you agree your work is licensed under the project's Apache-2.0 license.

## Local development setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[all,dev]"      # full driver set + test tools
```

If you only need a subset of adapters, install narrower extras instead of `all`:
`duckdb`, `postgres`, `opensearch`, `qdrant`, `snowflake`, `mongodb`, `observability`.
For example `pip install -e ".[duckdb]"` installs only the DuckDB driver.

## Running the zero-infrastructure example

`examples/novashop-duckdb/` is a single DuckDB source — a local file, no server,
no credentials — so you can exercise the whole governance path with nothing running:

```bash
python examples/novashop-duckdb/seed.py        # writes novashop.duckdb + data/*.csv (deterministic)
export RECOSEARCH_SEMANTIC_DIR=examples/novashop-duckdb
recosearch --write-semantic-json     # compile the contract
recosearch --validate                # validate declared inputs
recosearch --health-check            # status ok with NO running services
recosearch                           # start the MCP server
```

This is the fastest way to confirm your environment is healthy before touching code.

## Running tests

```bash
pytest -q -m "not live"      # unit + integration + smoke; no running services needed
```

Non-live tests still need the relevant drivers installed (use the `all` extra). The
suite runs against `examples/novamart` (set by `conftest.py`), and the freshness smoke
tests require a compiled contract first — run `recosearch --write-semantic-json`
before `pytest` if they complain about a stale or missing `semantic.json`.

The `live` and `smoke` markers exercise real services and are excluded by default:

```bash
pytest -q -m live            # end-to-end; requires running data sources
pytest -q -m smoke           # sanity checks against a deployed stack
```

## The three-authority-file model

Each scenario directory holds three files you author — they are the **sole** source of truth:

| File | Role |
|------|------|
| `source_config.yaml` | Connection authority — where each source lives, secrets via `${ENV_VAR}` |
| `semantic.md` | Business meaning — metrics, dimensions, measures, rules, relations in plain language |
| `scenario_config.yaml` | Scenario identity and opt-in governance (RBAC, ACL masking, vocabulary) |

`RECOSEARCH_SEMANTIC_DIR` selects the active scenario directory; `semantic.json` is the
**compiled** output, never hand-edited. **No business logic lives in Python.** Metrics,
rules, dimensions, and source meaning belong in the authority files — not in adapters,
tools, or the contract layer. PRs that encode scenario-specific business logic in code
will be asked to move it into the authority files.

## Adding a source adapter

Follow [`docs/usage/adding-a-source.md`](docs/usage/adding-a-source.md) end to end, and
start from an existing adapter (e.g. [`recosearch/adapters/duckdb.py`](recosearch/adapters/duckdb.py));
see [`recosearch/adapters/base.py`](recosearch/adapters/base.py) for the `SourceAdapter`
contract. The governance layer — SQL guard,
citation tracking, global-rule enforcement, RBAC — is untouched: you wire one executor
and your adapter inherits governance the moment it declares its capabilities.

Conventions adapters must follow:

- **Lazy driver imports.** Import the driver inside the function body, never at module
  top. `adapters/__init__.py` imports every adapter eagerly, so a missing driver must
  not crash package import.
- **Capabilities are storage-only.** A capability string (`structured_query`,
  `text_search`, `vector_search`, `document_query`) describes what the *store* can do;
  tool routing is capability-based, so never hardcode tool-to-source-type wiring.
- **Respect the row ceilings.** Enforce `MAX_SOURCE_ROWS` (100) per source and let
  federation honor `MAX_FEDERATION_ROWS` (500); these live in `recosearch/settings.py`.
- Do not re-implement the SQL guard inside an adapter — it runs upstream in `tools.py`.

## Governance is always on

These checks are enforced regardless of config and should never be weakened by a change:
read-only SELECT-only SQL (non-SELECT refused, `reason_code: mutating_sql`), global-rule
enforcement on hand-written SQL (a SELECT omitting a declared global exclusion is refused
with `reason_code: missing_global_exclusion`), undeclared field/source rejection, and
cite-or-refuse evidence validation. RBAC tool gating (`RECOSEARCH_ROLE`) and ACL field
masking are opt-in — only active when configured in `scenario_config.yaml`.

## PR expectations

Before opening a pull request:

- `pytest -q -m "not live"` is green (run live/smoke locally too when you have services).
- `recosearch --validate` runs clean against any scenario you touched.
- Re-run `recosearch --write-semantic-json` if you changed authority files, and
  confirm `recosearch --check-semantic-json` reports no staleness.
- The change is the smallest correct one for the goal — no unrelated refactors.
- New behavior is covered by a test, and no business logic leaked into Python.

Keep PRs focused and describe what changed and why. Thanks for contributing.
