# AGENTS.md — gpt2giga

## Project Snapshot

- **Repo type:** Single Python package (not a monorepo)
- **What:** Proxy server translating OpenAI + Anthropic SDK requests → GigaChat API
- **Stack:** Python 3.10–3.14, FastAPI/Starlette, GigaChat SDK, Pydantic Settings, SSE
- **Tooling:** `uv` (lock: `uv.lock`), Ruff, pytest, Docker
- **Hierarchy:** Sub-folders have their own `AGENTS.md` (nearest-wins)

## Setup Commands

```bash
# Install all deps (dev included)
uv sync --all-extras --dev

# Run proxy server locally
uv run gpt2giga

# Build wheel/sdist (used by Docker builder stage)
uv build

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

- **Formatter/Linter:** Ruff (`ruff check`, `ruff format`). (Black may exist for tooling, but Ruff is the project standard.)
- **Commit style:** Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`)
- **Python compat:** Must work on 3.10–3.14. Avoid PEP-695-only syntax (`type Alias = ...`, `def f[T](...)`, etc.).
- **Async-first:** All endpoint handlers and GigaChat calls are async.
- **Docstrings:** Google style, imperative mood.
- **Imports:** stdlib → third-party → local (`gpt2giga.*`), absolute imports only.
- **PR template:** `.github/PULL_REQUEST_TEMPLATE.md` — follow the checklist.

## Security & Secrets

- **NEVER** commit credentials, tokens, or local env files (notably `.env`, `examples/.env`, `local/.env`).
- Secrets go in `.env` (template: `.env.example`).
- Env var prefixes: `GPT2GIGA_` for proxy settings, `GIGACHAT_` for GigaChat SDK.
- API key auth is optional (`GPT2GIGA_ENABLE_API_KEY_AUTH`).

## JIT Index (what to open, not what to paste)

### Source Structure

| Path | Purpose | Details |
|---|---|---|
| `gpt2giga/` | Main source package | [gpt2giga/AGENTS.md](gpt2giga/AGENTS.md) |
| `tests/` | Test suite | [tests/AGENTS.md](tests/AGENTS.md) |
| `examples/` | Runnable usage examples | [examples/AGENTS.md](examples/AGENTS.md) |
| `integrations/` | Third-party integration docs | [integrations/AGENTS.md](integrations/AGENTS.md) |
| `scripts/` | Utility scripts used by CI | [scripts/AGENTS.md](scripts/AGENTS.md) |
| `.github/` | CI/CD + PR templates | [.github/AGENTS.md](.github/AGENTS.md) |
| `local/` | Scratchpad experiments (not shipped) | [local/AGENTS.md](local/AGENTS.md) |
| `Dockerfile` | Multi-stage Docker build | builder runs `uv build` |
| `docker-compose.yaml` | Docker Compose setup | uses `.env`, default port `8090` |

### Quick Find Commands

```bash
# Find a class definition
rg -n "^class " gpt2giga/

# Find an async endpoint handler
rg -n "^async def " gpt2giga/routers/

# Find error mapping / exception handling
rg -n "ERROR_MAPPING|exceptions_handler" gpt2giga/

# Find all test files
rg --files -g "test_*.py" tests/

# Find env var usage
rg -n "GPT2GIGA_|GIGACHAT_" .env.example gpt2giga/config.py

# Find OpenAI ↔ GigaChat transformation logic
rg -n "class (RequestTransformer|ResponseProcessor|AttachmentProcessor)" gpt2giga/

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
