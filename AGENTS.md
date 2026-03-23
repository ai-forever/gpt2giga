# AGENTS.md — gpt2giga

## Project Snapshot

- **Repo type:** Single Python package with examples, docs, CI workflows, and deployment assets
- **What:** FastAPI proxy that translates OpenAI and Anthropic-compatible requests into GigaChat API calls
- **Stack:** Python 3.10–3.14, FastAPI/Starlette, GigaChat SDK, Pydantic Settings, SSE, Docker
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
- **PR checklist:** Follow `.github/PULL_REQUEST_TEMPLATE.md`.

## Security & Secrets

- **Never commit secrets** such as `.env`, credentials, API keys, or local cert/key material.
- Proxy settings use the `GPT2GIGA_` prefix; GigaChat SDK settings use `GIGACHAT_`.
- `MODE=PROD` requires an API key and disables `/docs`, `/redoc`, `/openapi.json`, and `/logs*`.
- Prefer `.env` or environment variables for secrets; do not pass secrets via CLI flags.

## Repo Map

| Path | Purpose | Notes |
|---|---|---|
| `gpt2giga/` | Main application package | Routers, protocol transforms, config, middleware |
| `tests/` | Test suite | Mirrors source areas and router/protocol behavior |
| `examples/` | Runnable SDK examples | OpenAI, Responses, Anthropic, embeddings, agents |
| `integrations/` | Integration guides | Editor/agent/reverse-proxy setup docs |
| `scripts/` | Small maintenance/debug scripts | Coverage badge + mitmproxy SSE helper |
| `.github/` | Workflows and templates | CI, release, Docker publish, PR/issue templates |
| `traefik/` | Traefik config | Used by `compose/traefik.yaml` |
| `badges/` | Generated assets | Coverage badge written by CI |
| `Dockerfile` | Container build | `uv build`-based package install |
| `Dockerfile.mitmproxy` | Debug container image | mitmproxy/SSE debugging support |
| `compose/` | Docker Compose manifests | `base`, `traefik`, `observability`, and related stacks |

## Current Architecture Notes

- OpenAI-compatible endpoints live in `gpt2giga/routers/openai/`.
- Anthropic-compatible endpoints live in `gpt2giga/routers/anthropic/`.
- Shared request/response translation lives in `gpt2giga/protocol/`.
- Shared HTTP helpers live in `gpt2giga/common/`.
- Request/app-scoped stores for files and batches live in `gpt2giga/app_state.py`.
- OpenAPI schema builders live in `gpt2giga/openapi_specs/`.

## Quick Find Commands

```bash
# Find route handlers
rg -n "@router\.(get|post|delete)" gpt2giga/routers

# Find config/env settings
rg -n "GPT2GIGA_|GIGACHAT_" .env.example gpt2giga/models/config.py

# Find middleware classes
rg -n "class .*Middleware" gpt2giga/middlewares

# Find batch/file support
rg -n "batch|file" gpt2giga/routers gpt2giga/protocol gpt2giga/app_state.py

# Find tests for a feature
rg -n "batch|file|anthropic|responses" tests

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
- The repo also includes Traefik and observability compose variants; keep docs/config references aligned with those files when changing deployment behavior.
