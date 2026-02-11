# AGENTS.md — gpt2giga

## Project Snapshot

- **Type:** Single Python package (not a monorepo)
- **What:** Proxy server translating OpenAI API requests → GigaChat API
- **Stack:** Python 3.10-3.14, FastAPI, GigaChat SDK, Pydantic Settings
- **Package manager:** `uv` (lock: `uv.lock`, build: `hatchling`)
- Sub-packages have their own `AGENTS.md` — see JIT Index below

## Setup Commands

```bash
# Install all deps (dev included)
uv sync --all-extras --dev

# Run proxy server locally
uv run gpt2giga

# Run tests (80% coverage enforced)
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Pre-commit hooks (install once)
uv run pre-commit install
```

## Universal Conventions

- **Formatter/Linter:** Ruff (check + format). No separate Black/isort — Ruff handles both.
- **Commit style:** Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`)
- **Python compat:** Must work on 3.10-3.14. Avoid `type[X]` syntax; use `Type[X]` from `typing`.
- **Async-first:** All endpoint handlers and GigaChat calls are async.
- **Docstrings:** Google style, imperative mood.
- **Imports:** stdlib → third-party → local (`gpt2giga.*`), absolute imports only.
- **PR template:** `.github/PULL_REQUEST_TEMPLATE.md` — follow the checklist.

## Security & Secrets

- **NEVER** commit credentials, tokens, or `.env` files.
- Secrets go in `.env` (see `.env.example` for template).
- Env var prefixes: `GPT2GIGA_` for proxy settings, `GIGACHAT_` for GigaChat SDK.
- API key auth is optional (`GPT2GIGA_ENABLE_API_KEY_AUTH`).

## JIT Index

### Source Structure

| Path | Purpose | Details |
|---|---|---|
| `gpt2giga/` | Main source package | [gpt2giga/AGENTS.md](gpt2giga/AGENTS.md) |
| `tests/` | Test suite | [tests/AGENTS.md](tests/AGENTS.md) |
| `examples/` | Usage examples | [examples/AGENTS.md](examples/AGENTS.md) |
| `integrations/` | Third-party integration guides | READMEs for aider, openhands |
| `scripts/` | Utility scripts | `generate_badge.py` |
| `.github/workflows/` | CI/CD pipelines | `ci.yaml`, `docker_image.yaml`, `publish-*.yml` |
| `Dockerfile` | Multi-stage Docker build | Python 3.10 default, multi-arch |
| `docker-compose.yaml` | Docker Compose setup | Uses `.env` file, port `8090` |

### Quick Find Commands

```bash
# Find a class definition
rg -n "^class " gpt2giga/

# Find an async endpoint handler
rg -n "^async def " gpt2giga/routers/

# Find error mapping or exception handling
rg -n "ERROR_MAPPING|exceptions_handler" gpt2giga/

# Find all test files
rg --files -g "test_*.py" tests/

# Find env var usage
rg -n "GPT2GIGA_|GIGACHAT_" .env.example gpt2giga/config.py

# Find OpenAI ↔ GigaChat transformation logic
rg -n "class (RequestTransformer|ResponseProcessor|AttachmentProcessor)" gpt2giga/protocol/

# Find Anthropic compatibility layer
rg -n "anthropic" gpt2giga/routers/ examples/anthropic/
```

## Definition of Done (Pre-PR)

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/ --cov=. --cov-fail-under=80
```

- All tests pass, coverage ≥ 80%
- No lint warnings
- PR template checklist completed
- `uv.lock` updated if dependencies changed
