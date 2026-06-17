# AGENTS.md — gpt2giga

## Project Snapshot

- **Repo type:** Single Python package with examples, docs, CI workflows, and deployment assets
- **What:** FastAPI compatibility gateway that translates OpenAI-, Anthropic-, and Gemini-shaped requests into GigaChat calls
- **Stack:** Python 3.10-3.14, FastAPI/Starlette, GigaChat SDK, Pydantic Settings, SSE, Docker, optional Postgres/OpenSearch/Phoenix backends
- **Tooling:** `uv`, Ruff, pytest, Docker, GitHub Actions
- **Hierarchy:** Subfolders with their own `AGENTS.md` override this file

## Setup Commands

```bash
# Install runtime + dev dependencies
uv sync --all-extras --dev

# Run the proxy locally
uv run gpt2giga

# Build wheel + sdist
uv build

# Run full quality gate
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80

# Install pre-commit hooks
uv run pre-commit install
```

## Universal Conventions

- **Formatter/Linter:** Ruff is the project standard. Keep `ruff check` and `ruff format` green.
- **Commit style:** Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`.
- **Python compat:** Code must remain compatible with Python `3.10` through `3.14`.
- **Async-first:** Endpoint handlers and upstream GigaChat interactions are async.
- **Imports:** stdlib → third-party → local (`gpt2giga.*`), using absolute imports.
- **Docstrings:** Google style, imperative mood, concise.
- **Architecture fit:** Keep route aggregation, protocol translation, upstream providers, and sink/storage concerns in their existing layers.
- **PR checklist:** Follow `.github/PULL_REQUEST_TEMPLATE.md`.

## Security & Secrets

- **Never commit secrets** such as `.env`, credentials, API keys, or local cert/key material.
- Proxy settings use the `GPT2GIGA_` prefix; GigaChat SDK settings use `GIGACHAT_`.
- `MODE=PROD` requires an API key and disables `/docs`, `/redoc`, `/openapi.json`, and `/logs*`.
- Admin/debug endpoints are opt-in and must be protected with `GPT2GIGA_ADMIN_API_KEY`.
- Traffic-log, observability, and content-capture features must preserve redaction defaults and avoid storing secrets by accident.
- Prefer `.env` or environment variables for secrets; do not pass secrets via CLI flags.

## Repo Map

| Path | Purpose | Notes |
|---|---|---|
| `gpt2giga/` | Main application package | App factory, API aggregation, routers, protocols, providers, sinks |
| `tests/` | Test suite | Mirrors app, router, protocol, sink, and compatibility behavior |
| `examples/` | Runnable SDK examples | OpenAI chat/responses/embeddings/models, Anthropic, Gemini, agents; files/batches examples are prepared but not mounted |
| `docs/` | User documentation | Compatibility, configuration, deployment, operations, integrations |
| `integrations/` | Integration guides | Editor/agent/reverse-proxy setup docs |
| `scripts/` | Small maintenance/debug scripts | Coverage badge + mitmproxy SSE helper |
| `.github/` | Workflows and templates | CI, release, Docker publish, PR/issue templates |
| `traefik/` | Traefik config | Used by `deploy/traefik.yaml` |
| `badges/` | Generated assets | Coverage badge written by CI |
| `Dockerfile` | Container build | `uv build`-based package install |
| `Dockerfile.mitmproxy` | Debug container image | mitmproxy/SSE debugging support |
| `deploy/` | Docker Compose manifests | `base`, `traefik`, `observability`, and related stacks |

## Current Architecture Notes

- `gpt2giga/app/factory.py` is the FastAPI composition root: middleware, auth dependencies, metrics, public routers, and admin/debug routers are mounted there.
- OpenAI, Anthropic, and Gemini public API aggregators live in `gpt2giga/api/openai/`, `gpt2giga/api/anthropic/`, and `gpt2giga/api/gemini/`; concrete route handlers live under the matching `gpt2giga/routers/*/` package.
- LiteLLM-compatible model-info endpoints live in `gpt2giga/routers/litellm/`.
- System health routes live in `gpt2giga/routers/system_router.py`; Prometheus metrics are mounted from `gpt2giga/api/system/metrics.py` when enabled.
- Runtime `/logs*` routes live in `gpt2giga/routers/logs_router.py` and are disabled in `PROD`.
- Admin traffic-log and debug translation routes live in `gpt2giga/api/admin/` and are opt-in.
- Legacy request/response translation lives in `gpt2giga/protocol/`; experimental normalized adapters and diagnostics live in `gpt2giga/protocols/`.
- Shared HTTP, schema, streaming, auth, and utility helpers live in `gpt2giga/common/`.
- GigaChat upstream integration lives in `gpt2giga/providers/gigachat/`.
- Traffic logs, metrics, and observability sinks live in `gpt2giga/sinks/`; Postgres/OpenSearch storage helpers live in `gpt2giga/storage/`.
- Files and batch router code exists, but OpenAI Files/Batches, Anthropic Message Batches, and Gemini Files/Batches are intentionally not mounted until the upstream SDK/backend can execute them end-to-end.
- OpenAPI schema builders live in `gpt2giga/openapi_specs/`.

## Quick Find Commands

```bash
# Find every AGENTS.md, including hidden/local directories
find . -name AGENTS.md -not -path './.git/*' -print | sort

# Find route handlers
rg -n "@router\.(get|post|delete|put|patch)" gpt2giga/api gpt2giga/routers

# Find config/env settings
rg -n "GPT2GIGA_|GIGACHAT_" .env.example gpt2giga/models/config.py

# Find middleware classes
rg -n "class .*Middleware" gpt2giga/middlewares

# Find admin, traffic log, metrics, and observability wiring
rg -n "admin|traffic_log|metrics|observability|debug_translate" gpt2giga docs .env.example

# Find tests for a feature
rg -n "batch|file|anthropic|gemini|responses|traffic|metrics|normalized" tests

# Find workflow usage of scripts
rg -n "scripts/" .github/workflows
```

## Definition Of Done

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
```

- Tests pass and coverage stays at or above `80%`
- Ruff passes without warnings
- Docs/config changes stay aligned with the real file layout
- `uv.lock` is updated if dependencies change

## Environment Notes

- Default local server address is `http://localhost:8090`.
- Docker Compose uses `.env` and supports `DEV` and `PROD` profiles.
- The repo also includes Traefik and observability Docker Compose variants in `deploy/`; keep docs/config references aligned with those files when changing deployment behavior.
