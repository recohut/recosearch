# Security Policy

RecoSearch is a governed MCP server that separates AI reasoning from validated
data execution. Governance is part of the product, not an add-on, so security
issues are taken seriously. This document covers how to report a vulnerability,
which versions are supported, and a short recap of the built-in security model.

For the full governance reference — RBAC, ACL field masking, secrets handling,
and the tool dispatch chain — see [`docs/usage/security.md`](docs/usage/security.md).

## Reporting a Vulnerability

Please report security issues privately. **Do not** open a public GitHub issue
for a suspected vulnerability.

- Email: **security@recohut.com**
  *(placeholder — maintainers should confirm this address routes to the right
  people, or replace it with GitHub private security advisories before relying
  on it.)*

When reporting, please include:

- A description of the issue and its potential impact.
- Steps to reproduce, or a minimal proof of concept.
- Affected version (see `pyproject.toml`, currently `0.1.0`) and configuration
  (which adapters/extras and which scenario authority files are in use).

Please give maintainers a reasonable window to investigate and ship a fix before
any public disclosure. We will acknowledge your report and keep you updated on
remediation progress.

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

Security fixes are applied to the `0.1.x` line. Older or unreleased versions are
not supported — please upgrade to the latest `0.1.x` release.

## Security Model (Recap)

The full details live in [`docs/usage/security.md`](docs/usage/security.md). In short:

- **Secrets via `${ENV}` only.** Connection credentials must be referenced as
  `${VAR}` in `source_config.yaml` and resolved from the environment at startup —
  never committed as plaintext. Plaintext secrets are flagged during config
  validation; do not commit real credentials to the repository.
- **Read-only SQL guard (always on).** Hand-written SQL is restricted to
  `SELECT`. Non-`SELECT` statements are refused (`reason_code: mutating_sql`),
  and a `SELECT` that omits a declared global exclusion is refused
  (`reason_code: missing_global_exclusion`). Undeclared fields and sources are
  rejected.
- **RBAC + ACL when configured (opt-in).** When roles are declared in
  `scenario_config.yaml`, `RECOSEARCH_ROLE` gates which MCP tools a caller may
  invoke (unknown roles fail closed), and field-level ACL masking redacts
  sensitive columns before results — and traces — are returned.
- **Provenance / citation enforcement (always on).** Evidence packets are
  validated cite-or-refuse, so answers must be grounded in cited, contract-backed
  records.
- **Strict enforcement in production.** Set
  `RECOSEARCH_CONTRACT_ENFORCEMENT=strict` for production deployments. The
  default is `warn`, which surfaces violations without blocking; `strict`
  turns contract violations into hard refusals.

If you find a way to bypass any of these controls — for example, executing a
mutating statement, reading an undeclared field, escaping RBAC/ACL, or returning
uncited evidence — please treat it as a security vulnerability and report it
using the process above.
