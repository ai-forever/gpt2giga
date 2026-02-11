# AGENTS.md — gpt2giga/ (source package)

## Package Identity

- **What:** FastAPI proxy server that translates OpenAI API → GigaChat API
- **Framework:** FastAPI + Uvicorn, async-first
- **Entry point:** `gpt2giga/__init__.py` → `run()` in `api_server.py`

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

## Patterns & Conventions

### App Factory Pattern

- `create_app(config)` in `api_server.py` builds the FastAPI app.
- `lifespan()` async context manager initializes `GigaChat` client, processors, and logger on `app.state`.
- All shared state lives on `request.app.state` — no globals.

```
✅ DO: Access shared state via `request.app.state.gigachat_client`
✅ DO: See `api_server.py` create_app() for middleware registration order
❌ DON'T: Import global singletons — always use app.state
```

### Error Handling

- **`@exceptions_handler` decorator** in `utils.py` wraps all router handlers.
- Maps `gigachat.exceptions.*` to OpenAI-style HTTP errors via `ERROR_MAPPING` dict.
- Logs errors with `rquid` (request ID) for traceability.

```
✅ DO: Decorate every router handler with `@exceptions_handler`
✅ DO: See `utils.py` ERROR_MAPPING for the exception → status code mapping
❌ DON'T: Catch GigaChat exceptions manually in handlers — the decorator handles it
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
❌ DON'T: Transform messages outside the protocol/ layer
```

### Routers (`routers/`)

| File | Endpoints |
|---|---|
| `api_router.py` | `GET /models`, `GET /models/{model}`, `POST /chat/completions`, `POST /embeddings`, `POST /responses` |
| `system_router.py` | `GET /health`, `GET/POST /ping`, `GET /logs` |

- Routes are registered twice: at root `/` and under `/v1/` prefix.
- All API routes use `@exceptions_handler` decorator.
- Streaming uses `StreamingResponse` with async generators from `utils.py`.

```
✅ DO: Copy `chat_completions()` in api_router.py as template for new endpoints
✅ DO: Use `getattr(request.state, "gigachat_client", state.gigachat_client)` for client access
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
❌ DON'T: Change middleware order without understanding the chain
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
```

## Common Gotchas

- `fastapi` is pinned to `>=0.128.0,<0.129.0` — do not upgrade without checking compatibility.
- `gigachat` SDK is pinned to `>=0.2.0,<0.3.0` — breaking changes possible in 0.3.
- Middleware order matters: the last `add_middleware()` call executes first on requests.
- `rquid_context` uses `contextvars.ContextVar` — it's async-safe but not shared across tasks.
- Token counting for embeddings uses `tiktoken` — requires network on first use to download encodings.
