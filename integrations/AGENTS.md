# AGENTS.md — integrations/ (3rd-party guides)

## Package Identity

- **What:** Documentation for connecting external tools to `gpt2giga` (no runtime code)
- **Audience:** Users configuring editors/agents (Aider, OpenHands, etc.)

## Setup & Run

```bash
# Start the proxy (from repo root)
uv run gpt2giga

# Then follow the specific integration README
```

## Patterns & Conventions

- Keep integrations as **docs-first**: prefer updating `README.md` files over adding Python code here.
- All commands should be **copy-paste runnable** and default to `http://localhost:8090`.
- If an integration needs extra deps, document it as a **dependency group** (see `pyproject.toml` → `[dependency-groups]`).

Examples:

- ✅ DO: Put tool-specific instructions in `integrations/aider/README.md`
- ✅ DO: Keep OpenHands steps in `integrations/openhands/README.md`
- ❌ DON'T: Commit credentials in `.env` files (see `integrations/aider/.env.example` for a template)
- ❌ DON'T: Add “integration examples” under `local/` and link them here (e.g. `local/deepagents_example.py` is a scratch experiment; keep `integrations/` docs-only)

## Touch Points / Key Files

- **Aider integration**: `integrations/aider/README.md`, `integrations/aider/.aider.model.metadata.json`, `integrations/aider/.env.example`
- **OpenHands integration**: `integrations/openhands/README.md`
- **nginx reverse proxy**: `integrations/nginx/README.md`, `integrations/nginx/gpt2giga.conf`
- **Project config / env**: `.env.example`, `gpt2giga/models/config.py`

## JIT Index Hints

```bash
# Find base URL / API key guidance
rg -n "OPENAI_API_BASE|openai-api-base|Base URL|API Key" integrations/

# Find references to model naming conventions
rg -n "openai/|GigaChat-2" integrations/
```

## Common Gotchas

- If API-key auth is enabled (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), integrations must pass a key (OpenAI SDK `api_key=...` or header `x-api-key`).
- Don’t assume `/v1` in `base_url` unless the integration explicitly requires it; `gpt2giga` supports both root and `/v1` for most endpoints.

## Pre-PR Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/ --cov=. --cov-fail-under=80
```

