# AGENTS.md — gpt2giga

## Project Snapshot

- **Repo type:** Single Python package with examples, docs, CI workflows, and deployment assets
- **What:** FastAPI proxy and translation toolkit that adapts OpenAI-, Anthropic-, and Gemini-compatible traffic into GigaChat API calls
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
- **Commit discipline:** After every completed change slice with green targeted checks, create a separate commit before moving to the next slice. Do not leave finished work only in the working tree.
- **Python compat:** Code must remain compatible with Python `3.10` through `3.14`.
- **Starlette baseline:** Runtime targets `Starlette 1.x`. Use `lifespan`, `APIRouter`, and `add_middleware`; do not add removed decorator/event-hook APIs such as `on_event()`, `add_event_handler()`, raw `@app.middleware()`, or raw `@app.route()`.
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
| `gpt2giga/frontend/admin/` | Admin console TypeScript source | Browser modules compiled into `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` |
| `packages/gpt2giga-ui/` | Optional UI distribution | Runtime source of truth for the `/admin` HTML shell and static assets used by `gpt2giga[ui]` |
| `tests/` | Test suite | Organized into `unit/`, `integration/`, `smoke/`, and `compat/` |
| `examples/` | Runnable SDK examples | OpenAI, Anthropic, Gemini, Agents SDK, batch validation, and provider-translation examples |
| `docs/` | Project documentation | Integration guides currently live in `docs/integrations/` |
| `scripts/` | Small maintenance/debug scripts | Coverage badge, mitmproxy SSE helper, and maintainer-only internal utilities |
| `deploy/` | Deployment assets | Compose stacks in `deploy/compose/` + Traefik config in `deploy/traefik/` |
| `.github/` | Workflows and templates | CI, release, Docker publish, PR/issue templates |
| `badges/` | Generated assets | Coverage badge written by CI |
| `Dockerfile` | Container build | `uv build`-based package install |
| `Dockerfile.mitmproxy` | Debug container image | mitmproxy/SSE debugging support |

## Current Architecture Notes

- OpenAI-compatible endpoints live in `gpt2giga/api/openai/`.
- Anthropic-compatible endpoints live in `gpt2giga/api/anthropic/`.
- Gemini-compatible endpoints live in `gpt2giga/api/gemini/`.
- LiteLLM-compatible model-info endpoints live in `gpt2giga/api/litellm/`.
- Capability-level orchestration for chat, responses, embeddings, model discovery, files, and batches lives in `gpt2giga/features/`.
- Mixed admin inventory/create flows for files and batches live in `gpt2giga/api/admin/files_batches.py` and `gpt2giga/features/files_batches/`.
- Admin control-plane HTTP endpoints live in `gpt2giga/api/admin/`, while payload/mutation services live in `gpt2giga/app/admin_runtime.py` and `gpt2giga/app/admin_settings.py`.
- Provider-to-provider chat request translation lives in `gpt2giga/api/translate.py`, with serializer helpers under `gpt2giga/api/anthropic/request_adapter.py`, `gpt2giga/api/gemini/request_adapter.py`, and `gpt2giga/providers/*/capabilities.py`.
- Batch-input validation entrypoints live in `gpt2giga/api/batch_validation.py` and `gpt2giga/features/batches/validation.py`.
- GigaChat client/auth helpers and provider-specific request/response mappers live in `gpt2giga/providers/gigachat/`.
- Provider capability registries and provider scaffolding live under `gpt2giga/providers/`, including `registry.py`, `openai/`, `anthropic/`, `gemini/`, and `template_provider/`.
- Simple provider mappings for embeddings and model discovery live in `gpt2giga/providers/gigachat/embeddings_mapper.py` and `gpt2giga/providers/gigachat/models_mapper.py`.
- Request transformation is split across `gpt2giga/providers/gigachat/request_mapper.py`, `request_mapping_base.py`, `chat_request_mapper.py`, and the structured Responses helpers in `gpt2giga/providers/gigachat/responses/`.
- Response transformation is split across `gpt2giga/providers/gigachat/response_mapper.py`, `response_mapping_common.py`, and the structured Responses helpers in `gpt2giga/providers/gigachat/responses/`.
- GigaChat stream iteration and chunk normalization live in `gpt2giga/providers/gigachat/streaming.py`.
- Anthropic- and Gemini-specific request/response/stream translation helpers live next to those routers under `gpt2giga/api/anthropic/` and `gpt2giga/api/gemini/`.
- OpenAI SSE formatting helpers live in `gpt2giga/api/openai/streaming.py`, while feature-owned stream orchestration lives in `gpt2giga/features/chat/stream.py` and `gpt2giga/features/responses/stream.py`.
- Shared request parsing, schema normalization, app metadata, and exception handling live under `gpt2giga/core/`.
- Typed runtime dependencies live in `gpt2giga/app/dependencies.py`, with `app.state` organized around `config`, `logger`, `services`, `stores`, and `providers`.
- Runtime store/feed backend internals live in `gpt2giga/app/_runtime_backends/`, while `gpt2giga/app/runtime_backends.py` remains the public import path.
- Control-plane persistence internals live in `gpt2giga/core/config/_control_plane/`, while `gpt2giga/core/config/control_plane.py` remains the public import path.
- Request/app-scoped metadata stores for files, batches, and responses live in feature-owned store modules under `gpt2giga/features/*/store.py`.
- OpenAPI schema builders live next to provider routers in `gpt2giga/api/*/openapi.py`, with shared helpers in `gpt2giga/api/_openapi.py`.
- Runtime admin shell/assets are loaded from `packages/gpt2giga-ui/src/gpt2giga_ui/`; in a source checkout `gpt2giga/app/admin_ui.py` prefers that repo-local package copy over an installed wheel.
- Use `prepare_chat_completion`, `prepare_response`, and `prepare_response_v2`; do not add legacy `send_to_gigachat*` aliases back.

## Quick Find Commands

```bash
# Find route handlers
rg -n "@router\.(get|post|delete)" gpt2giga/api

# Find config/env settings
rg -n "GPT2GIGA_|GIGACHAT_" .env.example gpt2giga/core/config/settings.py

# Find middleware classes
rg -n "class .*Middleware" gpt2giga/api/middleware

# Find batch/file support
rg -n "batch|file" gpt2giga/api gpt2giga/features gpt2giga/providers/gigachat

# Find GigaChat provider helpers
rg -n "gigachat_client|pass_token|GigaChat" gpt2giga/providers/gigachat

# Find request/response mapper internals
rg --files gpt2giga/providers/gigachat gpt2giga/api/anthropic gpt2giga/api/gemini

# Find translation and provider-registry code
rg -n "translate|provider_adapters|template_provider|registry" gpt2giga

# Find tests for a feature
rg -n "batch|file|anthropic|gemini|translate|responses|compat" tests

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
