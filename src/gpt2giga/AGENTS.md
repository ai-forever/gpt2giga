# AGENTS.md — gateway package

## Scope and boundary

These rules apply to `src/gpt2giga/**` in addition to the root contract.
This source tree must build and install as a standalone gateway distribution.

- Keep the Python namespace `gpt2giga` and the `gpt2giga` command independent
  of Harness code, commands, package data, and optional control-plane behavior.
- Read metadata and dependencies from the repository-root `pyproject.toml`. Add an
  optional backend dependency to the correct extra and update `uv.lock`.
- The mounted public surface is defined by
  `src/gpt2giga/app/factory.py` and `src/gpt2giga/api/*/routes.py`.
  A router module existing on disk does not make its endpoints public.

## Layer ownership

| Path under `src/gpt2giga/` | Responsibility |
|---|---|
| `app/` | Composition, settings, lifecycle, middleware/router mounting |
| `api/` | Public protocol aggregation plus protected admin/system composition |
| `routers/` | Concrete HTTP handlers and transport behavior |
| `protocol/` | Existing request/response transformation paths |
| `protocols/` | Normalized protocol models and protocol-specific adapters |
| `providers/` | Upstream execution, authentication, SDK adaptation, streaming |
| `common/`, `core/` | Shared request helpers, contracts, context, redaction |
| `sinks/`, `storage/` | Logs, metrics, observability, optional durable backends |
| `openapi_specs/` | Client-visible schema supplements |

Keep HTTP handlers thin: use shared body parsers, request context, exception
normalization, protocol/provider adapters, and sink interfaces instead of
duplicating them in routes. Put shared application state in lifecycle wiring and
`app_state.py`, not module globals.

## Compatibility and security

- Preserve root, `/v1`, `/v2`, and Gemini `/v1beta`, `/v1/v1beta`, and
  `/v2/v1beta` path semantics unless the task explicitly changes the
  compatibility contract.
- Do not reorder middleware or change app-factory registration without
  app-level tests; Starlette request execution order is significant.
- Router code for OpenAI Files/Batches, Anthropic Message Batches, and Gemini
  Files/Batches is intentionally not mounted. Mount it only in explicit
  end-to-end scope with an executable backend, compatibility tests, examples,
  and docs.
- Keep upstream calls async. Reuse the existing provider/helper for the path
  being changed; do not migrate a mounted legacy execution path without
  explicit scope. Preserve per-request token handoff, model concurrency limits,
  streaming cleanup, and normalized errors.
- Treat `PROD`, auth, CORS, docs/log exposure, admin/debug/replay routes, and
  request-size limits as security-sensitive.
- Preserve admin-key checks and redaction. Never put credentials, raw auth
  headers, prompt bodies, tool args, or unbounded/high-cardinality values into
  logs, metrics, or traces by default.
- Config changes require safe defaults, field descriptions, env coverage,
  `.env.example`, tests, and user docs.

## Validation

```bash
uv run ruff check src/gpt2giga
uv run ruff format --check src/gpt2giga
uv build --no-sources
```

Run focused gateway tests while iterating. Run the full root coverage gate after
public protocol, app composition, middleware, shared config, sink/storage, or
package-boundary changes.
