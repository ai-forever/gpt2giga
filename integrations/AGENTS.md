# AGENTS.md — integrations/

## Package Identity

- **What:** Documentation-only integration guides for external tools and reverse proxies
- **Audience:** Users configuring editors, coding agents, or fronting `gpt2giga` with nginx
- **Runtime code:** None; this directory is docs and config samples

## Current Integrations

| Path | Purpose |
|---|---|
| `integrations/aider/README.md` | Aider setup |
| `integrations/aider/.env.example` | Aider-specific env template; keep it secret-free |
| `integrations/aider/.aider.model.metadata.json` | Aider model metadata |
| `integrations/claude-code/README.md` | Claude Code setup |
| `integrations/codex/README.md` | OpenAI Codex setup |
| `integrations/gemini/README.md` | Gemini CLI setup |
| `integrations/cursor/README.md` | Cursor setup |
| `integrations/qwen-code/README.md` | Qwen Code setup |
| `integrations/openhands/README.md` | OpenHands setup |
| `integrations/xcode/README.md` | Xcode setup |
| `integrations/nginx/README.md` | nginx reverse-proxy guide |
| `integrations/nginx/gpt2giga.conf` | nginx TLS config sample |
| `integrations/nginx/gpt2giga-compose.conf` | nginx HTTP config used by `deploy/nginx.yaml` |
| `integrations/nginx/cloud.png` | nginx guide asset |

## Patterns & Conventions

- Keep this directory docs-first. Prefer `README.md` updates over adding scripts or Python modules here.
- All copy-paste commands should default to the local proxy at `http://localhost:8090` unless the guide is specifically about reverse proxies or remote deployment.
- Document required dependency groups when an integration needs extras, such as `uv sync --group integrations`.
- Keep auth guidance aligned with current proxy behavior: API-key auth is optional in `DEV` and effectively required in `PROD`.
- When a guide refers to reverse proxying or `/v1`, verify the exact path behavior against the current routers and middleware.
- Clearly mark unsupported API families. OpenAI Files/Batches and Anthropic Message Batches router code exists but is not mounted in the current public API.
- For tool-specific `.env.example` files, include only placeholders and safe defaults; never copy local credentials from a real `.env`.

## Touch Points

- Runtime config reference: `.env.example`
- Proxy config models: `gpt2giga/models/config.py`
- Security behavior: `gpt2giga/models/security.py`
- Entrypoint facade: `gpt2giga/api_server.py`
- Mounted routes and middleware: `gpt2giga/app/factory.py`
- Public API aggregators: `gpt2giga/api/openai/routes.py`, `gpt2giga/api/anthropic/routes.py`
- Example clients to cross-check docs: `examples/`
- Compatibility matrix: `docs/api-compatibility.md`
- Operations/admin/debug behavior: `docs/operations.md`

## Quick Find Commands

```bash
# Find base URL or API-key instructions
rg -n "localhost:8090|base_url|api_key|x-api-key" integrations

# Find model naming examples
rg -n "GigaChat|openai/|GEMINI_MODEL" integrations

# Find nginx-specific files
rg -n "server|proxy_pass|location" integrations/nginx

# Find unsupported or disabled API notes
rg -n "files|batches|not mounted|не смонт" integrations docs examples
```

## Common Gotchas

- `integrations/aider/.env.example` is checked in; keep it template-only and align broader config guidance with the repo-root `.env.example`.
- `gpt2giga` supports root, `/v1`, and `/v2` mounted API routes for OpenAI and Anthropic-compatible endpoints; docs should only require a versioned prefix when the client tooling needs an explicit backend contract.
- This folder should not become a dumping ground for ad hoc experiments; keep runnable examples in `examples/`.
- Reverse-proxy guides should keep `Host`, `X-Forwarded-*`, and path-prefix behavior aligned with `PathNormalizationMiddleware`.

## Pre-PR Check

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
```
