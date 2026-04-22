# AGENTS.md — docs/integrations/

## Package Identity

- **What:** Documentation-only integration guides for external tools and reverse proxies
- **Audience:** Users configuring editors, coding agents, or fronting `gpt2giga` with nginx
- **Runtime code:** None; this directory is docs and config samples

## Current Integrations

| Path | Purpose |
|---|---|
| `docs/integrations/README.md` | Index of integration guides |
| `docs/integrations/aider/README.md` | Aider setup |
| `docs/integrations/aider/.env.example` | Aider-specific env example |
| `docs/integrations/aider/.aider.model.metadata.json` | Aider model metadata checked in with the guide |
| `docs/integrations/claude-code/README.md` | Claude Code setup |
| `docs/integrations/codex/README.md` | OpenAI Codex setup |
| `docs/integrations/cursor/README.md` | Cursor setup |
| `docs/integrations/qwen-code/README.md` | Qwen Code setup |
| `docs/integrations/openhands/README.md` | OpenHands setup |
| `docs/integrations/xcode/README.md` | Xcode setup |
| `docs/integrations/nginx/README.md` | nginx reverse-proxy guide |
| `docs/integrations/nginx/gpt2giga.conf` | nginx config sample |
| `docs/integrations/nginx/cloud.png` | nginx guide asset |

## Patterns & Conventions

- Keep this directory docs-first. Prefer `README.md` updates over adding scripts or Python modules here.
- All copy-paste commands should default to the local proxy at `http://localhost:8090` unless the guide is specifically about reverse proxies or remote deployment.
- Document required dependency groups when an integration needs extras, such as `uv sync --group integrations`.
- Keep auth guidance aligned with current proxy behavior: API-key auth is optional in `DEV` and effectively required in `PROD`.
- When a guide refers to reverse proxying or `/v1`, verify the exact path behavior against the current routers and middleware.

## Touch Points

- Runtime config reference: `.env.example`
- Proxy config models: `gpt2giga/core/config/settings.py`
- Security behavior: `gpt2giga/core/config/security.py`
- Entrypoint and mounted routes: `gpt2giga/app/factory.py`
- Example clients to cross-check docs: `examples/`

## Quick Find Commands

```bash
# Find base URL or API-key instructions
rg -n "localhost:8090|base_url|api_key|x-api-key" docs/integrations

# Find model naming examples
rg -n "GigaChat|openai/" docs/integrations

# Find nginx-specific files
rg -n "server|proxy_pass|location" docs/integrations/nginx
```

## Common Gotchas

- The only checked-in integration-local env template today is `docs/integrations/aider/.env.example`; keep any new integration-local env examples clearly scoped and secret-free.
- `gpt2giga` supports both root and `/v1` mounted API routes for OpenAI and Anthropic-compatible endpoints; docs should only require `/v1` when the client tooling needs it.
- This folder should not become a dumping ground for ad hoc experiments; keep runnable examples in `examples/`.

## Pre-PR Check

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
```
