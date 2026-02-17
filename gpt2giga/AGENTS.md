# AGENTS.md — gpt2giga/ (source package)

## Package Identity

- **What:** FastAPI proxy server that translates OpenAI API → GigaChat API
- **Framework:** FastAPI + Uvicorn, async-first
- **Entry point:** `gpt2giga/__init__.py` → `run()` in `api_server.py`

## Setup & Run

```bash
# From repo root
uv sync --all-extras --dev

# Run server (reads .env by default via CLI; see --env-path)
uv run gpt2giga

# Lint/format just the package
uv run ruff check gpt2giga/ && uv run ruff format gpt2giga/
```

## Architecture Overview

```
Request flow:
  Client (OpenAI SDK / Anthropic SDK) → Middlewares → Routers → Protocol layer → GigaChat SDK
  GigaChat SDK → Protocol layer → Routers → Client
```

### Key Modules

| Module | Role |
|---|---|
| `api_server.py` | App factory (`create_app()`), lifespan, `run()` |
| `cli.py` | CLI argument parsing, config loading |
| `models/config.py` | Pydantic Settings: `ProxyConfig`, `ProxySettings`, `GigaChatCLI` |
| `models/security.py` | Security settings view + defaults (request limits, summaries) |
| `auth.py` | API key verification (`verify_api_key` dependency) |
| `logger.py` | Loguru setup, `rquid_context` context var |
| `common/` | Shared helpers: exception mapping, JSON parsing, schema normalization, streaming, tool mapping |
| `protocol/` | Request/response transformation layer (see below) |
| `routers/` | FastAPI route handlers (see below) |
| `middlewares/` | HTTP middleware chain (see below) |
| `templates/` | HTML log viewer template (`templates/log_viewer.html`) |
| `openapi_docs.py` | OpenAPI `openapi_extra` payloads for compatible endpoints |

## Patterns & Conventions

### App Factory Pattern

- `create_app(config)` in `api_server.py` builds the FastAPI app.
- `lifespan()` async context manager initializes `GigaChat` client, processors, and logger on `app.state`.
- All shared state lives on `request.app.state` — no globals.
- In `mode=PROD`, docs endpoints are disabled and `/logs*` routes are not registered.

```
✅ DO: Access shared state via `request.app.state.gigachat_client`
✅ DO: See `api_server.py` create_app() for middleware registration order
❌ DON'T: Copy “single-file script” patterns from `local/*.py` into `gpt2giga/` (the `local/` folder is a scratchpad)
```

### Error Handling

- **`@exceptions_handler` decorator** in `common/exceptions.py` wraps all router handlers.
- Maps `gigachat.exceptions.*` to OpenAI-style HTTP errors via `ERROR_MAPPING`.
- Logs errors with `rquid` (request ID) for traceability.

```
✅ DO: Decorate every router handler with `@exceptions_handler`
✅ DO: See `common/exceptions.py` ERROR_MAPPING for the exception → status code mapping
❌ DON'T: Add ad-hoc exception mapping in random scripts; keep production mapping in `gpt2giga/common/exceptions.py`
```

### Protocol Layer (`protocol/`)

This is the core transformation engine:

| File | Class | Purpose |
|---|---|---|
| `protocol/request/transformer.py` | `RequestTransformer` | OpenAI request → GigaChat messages payload |
| `protocol/response/processor.py` | `ResponseProcessor` | GigaChat response → OpenAI Responses/ChatCompletions formats |
| `protocol/attachment/attachments.py` | `AttachmentProcessor` | Image/audio/document upload + caching/limits |
| `common/content_utils.py` | — | Content parsing/extraction utilities |
| `common/message_utils.py` | — | Message merging, role mapping, ordering, attachment limiting |
| `common/json_schema.py` | — | `$ref`/`$defs` resolution + schema normalization |
| `common/tools.py` | — | OpenAI/Anthropic tool mapping ↔ GigaChat functions |

**Key transformations:**
- Role mapping: `developer` → `system` (if first) / `user` (otherwise), `tool` → `function`
- Message merging: consecutive same-role messages are collapsed
- Schema normalization: resolves `$ref`/`$defs`, strips `anyOf`/`oneOf` with null
- Tool conversion: OpenAI `tools` format → GigaChat `functions` format

```
✅ DO: Follow `protocol/request/transformer.py` for new request transformations
✅ DO: Follow `protocol/response/processor.py` for new response transformations
✅ DO: Use `normalize_json_schema()` from `common/json_schema.py` for any JSON schema handling
❌ DON'T: Duplicate protocol logic in routers; keep transformations in `gpt2giga/protocol/*`
```

### Routers (`routers/`)

| File | Endpoints |
|---|---|
| `api_router.py` | `GET /models`, `GET /models/{model}`, `POST /chat/completions`, `POST /embeddings`, `POST /responses` |
| `anthropic_router.py` | `POST /messages`, `POST /messages/count_tokens` — Anthropic Messages API compatibility layer |
| `system_router.py` | `GET /health`, `GET/POST /ping` |
| `system_router.py` (logs_api_router, DEV only) | `GET /logs`, `GET /logs/stream` |
| `system_router.py` (logs_router, DEV only) | `GET /logs/html` — HTML log viewer page |

- Routes are registered twice: at root `/` and under `/v1/` prefix.
- System routes (`/health`, `/ping`) are registered only once at root.
- `/logs*` routes are registered only in non-PROD mode.
- All API routes use `@exceptions_handler` decorator.
- Streaming uses `StreamingResponse` with async generators from `common/streaming.py`.
- Anthropic router converts Anthropic Messages format → OpenAI → GigaChat → Anthropic response.

```
✅ DO: Copy `chat_completions()` in api_router.py as template for new OpenAI-compatible endpoints
✅ DO: See `anthropic_router.py` for the Anthropic ↔ OpenAI ↔ GigaChat translation pattern
✅ DO: Use `getattr(request.state, "gigachat_client", state.gigachat_client)` for client access
❌ DON'T: Add new API endpoints directly into `gpt2giga/api_server.py` (keep endpoints in `gpt2giga/routers/*`)
```

### Middlewares (`middlewares/`)

Request execution order (last `add_middleware()` executes first):

1. **`PassTokenMiddleware`** — passes auth token from request to GigaChat (optional; only if `proxy.pass-token=true`)
2. **`RequestValidationMiddleware`** — rejects too-large requests early via `Content-Length` (413)
3. **`RquidMiddleware`** — sets unique request ID in `contextvars` + returns `X-Request-ID`
4. **`PathNormalizationMiddleware`** — normalizes `/.../v1/...` → `/v1/...` (also fixes common `/api/v1/...`)
5. **`CORSMiddleware`** — CORS policy (tightened in `mode=PROD`)

```
✅ DO: Inherit from BaseHTTPMiddleware (Starlette) for new middleware
✅ DO: See `middlewares/rquid_context.py` for the contextvars pattern
❌ DON'T: Change middleware registration order in `gpt2giga/api_server.py` without re-validating path normalization + request IDs + body limits
```

### Streaming

- `stream_chat_completion_generator()` — SSE stream for `/chat/completions`
- `stream_responses_generator()` — SSE stream for `/responses`
- Both are async generators yielding `data: {json}\n\n` strings.
- Handle client disconnections gracefully.

### Configuration

- `ProxyConfig` (in `models/config.py`) nests `ProxySettings` + `GigaChatCLI`.
- Env var prefixes: `GPT2GIGA_` and `GIGACHAT_`.
- CLI args via `pydantic-settings` with `cli_parse_args=True`.
- See `.env.example` at repo root for all available settings.

```
✅ DO: Add new proxy settings to ProxySettings in `models/config.py`
✅ DO: Use Field(default=..., description="...") for every setting
```

## Touch Points / Key Files

- **App wiring + middleware order**: `gpt2giga/api_server.py`
- **OpenAI-compatible endpoints**: `gpt2giga/routers/api_router.py`
- **Anthropic Messages API**: `gpt2giga/routers/anthropic_router.py`
- **System/log endpoints + HTML viewer**: `gpt2giga/routers/system_router.py`, `gpt2giga/templates/log_viewer.html`
- **Protocol mapping**: `gpt2giga/protocol/request/transformer.py`, `gpt2giga/protocol/response/processor.py`
- **Attachments caching + upload**: `gpt2giga/protocol/attachment/attachments.py`
- **Auth + API key dependency**: `gpt2giga/auth.py`
- **Settings/env parsing**: `gpt2giga/models/config.py`, `.env.example`

## JIT Search Hints

```bash
# Find all route handlers
rg -n "@router\.(get|post|put|delete)" gpt2giga/routers/

# Find all middleware classes
rg -n "class.*Middleware" gpt2giga/middlewares/

# Find protocol layer classes/entrypoints
rg -n "class (RequestTransformer|ResponseProcessor|AttachmentProcessor)" gpt2giga/

# Find streaming generators
rg -n "async def stream_" gpt2giga/common/streaming.py

# Find schema normalization logic
rg -n "def (normalize_json_schema|resolve_schema_refs)" gpt2giga/common/json_schema.py

# Find all Pydantic settings
rg -n "class.*Settings|class.*Config" gpt2giga/models/config.py

# Find Anthropic-specific logic
rg -n "anthropic|messages" gpt2giga/routers/anthropic_router.py
```

## Common Gotchas

- `fastapi` is pinned to `>=0.128.0,<0.129.0` — do not upgrade without checking compatibility.
- `gigachat` SDK is pinned to `>=0.2.0,<0.3.0` — breaking changes possible in 0.3.
- Middleware order matters: the last `add_middleware()` call executes first on requests.
- `rquid_context` uses `contextvars.ContextVar` — it's async-safe but not shared across tasks.
- Token counting for embeddings uses `tiktoken` — requires network on first use to download encodings.
- In `mode=PROD`, docs endpoints are disabled and `/logs*` routes are not exposed.

## Pre-PR Check

```bash
uv run ruff check gpt2giga/ && uv run ruff format --check gpt2giga/ && uv run pytest tests/ --cov=. --cov-fail-under=80
```
