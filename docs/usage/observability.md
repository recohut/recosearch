# MCP tool observability (Phoenix)

Tool-level tracing for the governed MCP server. Each MCP tool call becomes one
span recording the request, the outcome (status / refusal reason / row count),
the source it hit, and how long it took. Implemented in
`recosearch/observability.py`; wired in at the single `register_tools`
chokepoint in `recosearch/tools.py`.

## Properties

- **Off by default.** With `RECOSEARCH_TRACING_ENABLED` unset, `traced_tool` is a
  pass-through and the tool surface is identical to an untraced build.
- **Fail-open.** Missing deps, an unreachable collector, or any setup error makes
  tracing silently no-op; tool calls are never blocked.
- **stdout-safe.** Spans export over HTTP (OTLP); diagnostics and Phoenix's own
  setup output go to stderr so the stdio MCP protocol is never corrupted.
- **Request redaction.** Secret-like arguments are masked.
- **Full-payload output.** Each span's `output.value` carries the complete tool
  response (rows included), so traces may contain PII. Flat attributes
  (`tool.status`, `tool.row_count`, `tool.source_id`, `tool.source_type`,
  `tool.source_boundary`) are also set for filtering. To switch back to a
  thinner, row-free summary, edit `_annotate_result` in
  `recosearch/observability.py`.

## Run Phoenix

Phoenix is an optional external service that you run yourself; the repo does not
bundle or manage it. `pip install arize-phoenix-otel` and run it as a local Python
process, or point at any reachable Phoenix/OTLP collector. Whichever you choose,
set `PHOENIX_COLLECTOR_ENDPOINT` (below) to its address.

UI: <http://localhost:6006>

## Enable tracing in the server

```bash
pip install -e ".[all,dev]"   # includes the optional observability deps

RECOSEARCH_TRACING_ENABLED=1 \
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006 \
  recosearch
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `RECOSEARCH_TRACING_ENABLED` | unset (off) | `1`/`true`/`yes`/`on` turns tracing on |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Where spans are sent |
| `PHOENIX_PROJECT_NAME` | `recosearch-mcp` | Project name shown in the Phoenix UI |

## Scope

Tool-level spans only. Sub-spans into the Postgres/OpenSearch/Qdrant/Snowflake/embedding
layers are intentionally deferred to a later pass.
