# AGENTS.md — gpt2giga/ (source package)

## Package Identity

- **What:** FastAPI proxy server that translates OpenAI API → GigaChat API
- **Framework:** FastAPI + Uvicorn, async-first
- **Entry point:** `gpt2giga/__init__.py` → `run()` in `api_server.py`

## Setup & Run

```bash
# From repo root
uv sync --all-extras --dev

# Run server (reads .env by default via CLI)
uv run gpt2giga

# Lint/format just the package
uv run ruff check gpt2giga/ && uv run ruff format gpt2giga/
```

## Architecture Overview

```
Request flow:
  Client (OpenAI SDK) → Middlewares → Router → RequestTransformer → GigaChat SDK
  GigaChat SDK → ResponseProcessor → Router → Client
```

### Key Modules

| Module | Role |
|---|---|
| `api_server.py` | App factory (`create_app()`), lifespan, `run()` |
| `cli.py` | CLI argument parsing, config loading |
| `config.py` | Pydantic Settings: `ProxyConfig`, `ProxySettings`, `GigaChatCLI` |
| `auth.py` | API key verification (`verify_api_key` dependency) |
| `logger.py` | Loguru setup, `rquid_context` context var |
| `utils.py` | Error handling decorator, stream generators, schema normalization, tool conversion |
| `protocol/` | Request/response transformation layer (see below) |
| `routers/` | FastAPI route handlers (see below) |
| `middlewares/` | HTTP middleware chain (see below) |
| `templates/` | HTML log viewer template (`templates/log_viewer.html`) |

## Patterns & Conventions

### App Factory Pattern

- `create_app(config)` in `api_server.py` builds the FastAPI app.
- `lifespan()` async context manager initializes `GigaChat` client, processors, and logger on `app.state`.
- All shared state lives on `request.app.state` — no globals.

```
✅ DO: Access shared state via `request.app.state.gigachat_client`
✅ DO: See `api_server.py` create_app() for middleware registration order
❌ DON'T: Copy “single-file script” patterns from `local/*.py` into `gpt2giga/` (the `local/` folder is a scratchpad)
```

### Error Handling

- **`@exceptions_handler` decorator** in `utils.py` wraps all router handlers.
- Maps `gigachat.exceptions.*` to OpenAI-style HTTP errors via `ERROR_MAPPING` dict.
- Logs errors with `rquid` (request ID) for traceability.

```
✅ DO: Decorate every router handler with `@exceptions_handler`
✅ DO: See `utils.py` ERROR_MAPPING for the exception → status code mapping
❌ DON'T: Add ad-hoc exception mapping in random scripts (see `local/check_ai.py` for experimentation; keep production mapping in `gpt2giga/utils.py`)
```

### Protocol Layer (`protocol/`)

This is the core transformation engine:

| File | Class | Purpose |
|---|---|---|
| `request_mapper.py` | `RequestTransformer` | OpenAI request → GigaChat `Chat` object |
| `response_mapper.py` | `ResponseProcessor` | GigaChat response → OpenAI response format |
| `attachments.py` | `AttachmentProcessor` | Image/document upload, LRU cache with TTL |
| `content_utils.py` | — | Content parsing/extraction utilities |
| `message_utils.py` | — | Message merging, role mapping, ordering |

**Key transformations:**
- Role mapping: `developer` → `system`/`user`, `tool` → `function`
- Message merging: consecutive same-role messages are collapsed
- Schema normalization: resolves `$ref`/`$defs`, strips `anyOf`/`oneOf` with null
- Tool conversion: OpenAI `tools` format → GigaChat `functions` format

```
✅ DO: Follow `request_mapper.py` prepare_chat_completion() for new request transformations
✅ DO: Follow `response_mapper.py` process_response() for new response transformations
✅ DO: Use normalize_json_schema() from utils.py for any JSON schema handling
❌ DON'T: Duplicate protocol logic in routers; keep transformations in `gpt2giga/protocol/*` (contrast with experimental code in `local/*.py`)
```

### Routers (`routers/`)

| File | Endpoints |
|---|---|
| `api_router.py` | `GET /models`, `GET /models/{model}`, `POST /chat/completions`, `POST /embeddings`, `POST /responses` |
| `anthropic_router.py` | `POST /messages` — Anthropic Messages API compatibility layer |
| `system_router.py` | `GET /health`, `GET/POST /ping`, `GET /logs`, `GET /logs/stream` |
| `system_router.py` (logs_router) | `GET /logs/html` — HTML log viewer page |

- Routes are registered twice: at root `/` and under `/v1/` prefix.
- System routes (`/health`, `/ping`, `/logs*`) are registered only once at root.
- All API routes use `@exceptions_handler` decorator.
- Streaming uses `StreamingResponse` with async generators from `utils.py`.
- Anthropic router converts Anthropic Messages format → OpenAI → GigaChat → Anthropic response.

```
✅ DO: Copy `chat_completions()` in api_router.py as template for new OpenAI-compatible endpoints
✅ DO: See `anthropic_router.py` for the Anthropic ↔ OpenAI ↔ GigaChat translation pattern
✅ DO: Use `getattr(request.state, "gigachat_client", state.gigachat_client)` for client access
❌ DON'T: Add new API endpoints directly into `gpt2giga/api_server.py` (keep endpoints in `gpt2giga/routers/*`)
```

### Middlewares (`middlewares/`)

Applied in order (last added = first executed):

1. **`PassTokenMiddleware`** — passes auth token from request to GigaChat (conditional)
2. **`RquidMiddleware`** — sets unique request ID in `contextvars`
3. **`PathNormalizationMiddleware`** — normalizes `/api/v1/...` → `/v1/...`
4. **`CORSMiddleware`** — allows all origins

```
✅ DO: Inherit from BaseHTTPMiddleware (Starlette) for new middleware
✅ DO: See `rquid_context.py` for the contextvars pattern
❌ DON'T: Change middleware registration order in `gpt2giga/api_server.py` without re-validating path normalization + request IDs
```

### Streaming

- `stream_chat_completion_generator()` — SSE stream for `/chat/completions`
- `stream_responses_generator()` — SSE stream for `/responses`
- Both are async generators yielding `data: {json}\n\n` strings.
- Handle client disconnections gracefully.

### Configuration

- `ProxyConfig` (root) nests `ProxySettings` + `GigaChatCLI`.
- Env var prefixes: `GPT2GIGA_` and `GIGACHAT_`.
- CLI args via `pydantic-settings` with `cli_parse_args=True`.
- See `.env.example` at repo root for all available settings.

```
✅ DO: Add new proxy settings to ProxySettings in config.py
✅ DO: Use Field(default=..., description="...") for every setting
```

## Touch Points / Key Files

- **App wiring + middleware order**: `gpt2giga/api_server.py`
- **OpenAI-compatible endpoints**: `gpt2giga/routers/api_router.py`
- **Anthropic Messages API**: `gpt2giga/routers/anthropic_router.py`
- **System/log endpoints + HTML viewer**: `gpt2giga/routers/system_router.py`, `gpt2giga/templates/log_viewer.html`
- **Protocol mapping**: `gpt2giga/protocol/request_mapper.py`, `gpt2giga/protocol/response_mapper.py`
- **Attachments caching + upload**: `gpt2giga/protocol/attachments.py`
- **Auth + API key dependency**: `gpt2giga/auth.py`
- **Settings/env parsing**: `gpt2giga/config.py`, `.env.example`

## JIT Search Hints

```bash
# Find all route handlers
rg -n "@router\.(get|post|put|delete)" gpt2giga/routers/

# Find all middleware classes
rg -n "class.*Middleware" gpt2giga/middlewares/

# Find protocol transformation methods
rg -n "def (prepare_|process_|transform_)" gpt2giga/protocol/

# Find streaming generators
rg -n "async def stream_" gpt2giga/utils.py

# Find schema normalization logic
rg -n "def (normalize_json_schema|resolve_schema_refs)" gpt2giga/utils.py

# Find all Pydantic settings
rg -n "class.*Settings|class.*Config" gpt2giga/config.py

# Find Anthropic-specific logic
rg -n "anthropic|messages" gpt2giga/routers/anthropic_router.py
```

## Common Gotchas

- `fastapi` is pinned to `>=0.128.0,<0.129.0` — do not upgrade without checking compatibility.
- `gigachat` SDK is pinned to `>=0.2.0,<0.3.0` — breaking changes possible in 0.3.
- Middleware order matters: the last `add_middleware()` call executes first on requests.
- `rquid_context` uses `contextvars.ContextVar` — it's async-safe but not shared across tasks.
- Token counting for embeddings uses `tiktoken` — requires network on first use to download encodings.

## Pre-PR Check

```bash
uv run ruff check gpt2giga/ && uv run ruff format --check gpt2giga/ && uv run pytest tests/ --cov=. --cov-fail-under=80
```
