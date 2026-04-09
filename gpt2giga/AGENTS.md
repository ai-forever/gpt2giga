# AGENTS.md — gpt2giga/

## Package Identity

- **What:** Source package for the `gpt2giga` proxy server
- **Framework:** FastAPI + Starlette + Uvicorn, async-first
- **CLI entrypoint:** `gpt2giga/__init__.py` exports `run()` from `app/run.py`

## Setup & Run

```bash
uv sync --all-extras --dev
uv run gpt2giga
uv run ruff check gpt2giga
uv run ruff format --check gpt2giga
```

## Architecture Overview

```text
Client SDK -> middleware -> router -> transformer/helpers -> GigaChat SDK
GigaChat SDK -> response processor -> router -> client-compatible response
```

## Key Modules

| Path | Role |
|---|---|
| `app/factory.py` | FastAPI app factory, middleware registration, router mounting |
| `app/lifespan.py` | Startup/shutdown orchestration and runtime service lifecycle |
| `app/wiring.py` | App-scoped runtime wiring for GigaChat client and transformers |
| `app/run.py` | Runtime entrypoint that loads config, logs startup, and runs Uvicorn |
| `app/cli.py` | Config loading and env-path handling |
| `core/config/settings.py` | Primary `ProxySettings`, `GigaChatCLI`, and `ProxyConfig` implementation |
| `core/config/security.py` | Consolidated security posture model and limits |
| `core/logging/setup.py` | Logger setup, redaction, UTF-8 sanitization, and RQUID context |
| `core/constants.py` | Shared limits, MIME/ext allowlists, and redaction constants |
| `core/app_meta.py` | App version, port checks, and CLI secret warnings |
| `providers/gigachat/client.py` | GigaChat client lifecycle, factory resolution, and request-scoped access |
| `providers/gigachat/auth.py` | Pass-token auth handoff and request-level GigaChat client construction |
| `api_server.py` | Compatibility wrapper over the new `app/*` modules |
| `app_state.py` | Request/app-scoped metadata stores for batches, files, and responses |
| `cli.py` | Compatibility wrapper for `app/cli.py` |
| `api/dependencies/auth.py` | API-key verification dependencies |
| `api/middleware/*` | HTTP middleware for auth-adjacent request processing |
| `logger.py` | Compatibility wrapper for `core/logging/setup.py` |
| `constants.py` | Compatibility wrapper for `core/constants.py` |
| `models/config.py` | Compatibility wrapper for `core/config/settings.py` |
| `models/security.py` | Compatibility wrapper for `core/config/security.py` |
| `common/` | Shared exception handling, auth helpers, request parsing, streaming, schema/tool utilities |
| `protocol/` | Request, response, attachment, batch, and Anthropic translation logic |
| `api/` | HTTP transport adapters: provider endpoints, middleware, dependencies, and system routes |
| `api/*/openapi.py` | Provider-specific OpenAPI schema fragments colocated with routers |
| `api/_openapi.py` | Shared OpenAPI request-body helper |
| `templates/log_viewer.html` | HTML log viewer for `/logs/html` |

## API Layout

| Path | Endpoints |
|---|---|
| `api/openai/chat_completions.py` | `/chat/completions` |
| `api/openai/responses.py` | `/responses` |
| `api/openai/embeddings.py` | `/embeddings` |
| `api/openai/models.py` | `/models` |
| `api/openai/files.py` | `/files` and `/files/{file_id}/content` |
| `api/openai/batches.py` | `/batches` |
| `api/anthropic/messages.py` | `/messages` and `/messages/count_tokens` |
| `api/anthropic/batches.py` | `/messages/batches` |
| `api/gemini/content.py` | `/v1beta/models/*:generateContent`, `countTokens`, embeddings |
| `api/gemini/models.py` | `/v1beta/models` and `/v1beta/models/{model}` |
| `api/system/health.py` | `/health`, `/ping` |
| `api/system/logs.py` | `/logs`, `/logs/stream`, `/logs/html` |

- OpenAI and Anthropic routers are mounted both at root and `/v1`.
- Gemini routes are mounted under `/v1beta`.
- System routes are root-only.
- Log routes are disabled in `PROD`.

## Protocol Layout

| Path | Purpose |
|---|---|
| `protocol/request/transformer.py` | Public `RequestTransformer` facade and chat/responses entrypoints |
| `protocol/request/_base.py` | Shared request parameter, schema, and validation helpers |
| `protocol/request/_messages.py` | Message role/content normalization and attachment handling |
| `protocol/request/_responses_v2.py` | Native Responses API v2 request/tool/thread mapping |
| `protocol/response/processor.py` | Public `ResponseProcessor` facade for chat completions |
| `protocol/response/_common.py` | Shared response status, usage, reasoning, and serialization helpers |
| `protocol/response/_responses.py` | Responses API and Responses v2 output shaping helpers |
| `protocol/attachment/attachments.py` | Image/audio/text attachment handling and cleanup |
| `protocol/batches.py` | Batch target mapping and JSONL transformations |
| `protocol/anthropic/request.py` | Anthropic request → OpenAI-style intermediary |
| `protocol/anthropic/response.py` | OpenAI/GigaChat result → Anthropic response |
| `protocol/anthropic/streaming.py` | Anthropic SSE/event translation |
| `protocol/gemini/request.py` | Gemini request → OpenAI-style intermediary |
| `protocol/gemini/response.py` | OpenAI/GigaChat result → Gemini response/error |
| `protocol/gemini/streaming.py` | Gemini SSE/data-only translation |

## Common Utilities

- `common/exceptions.py`: `@exceptions_handler` and exception normalization
- `common/request_json.py` and `common/request_form.py`: safe request parsing
- `common/streaming.py`: SSE generators for chat and responses
- `common/tools.py`: tool/function conversion helpers
- `common/json_schema.py`: JSON Schema normalization and `$ref` resolution
- `common/message_utils.py`: role mapping and message collapsing helpers
- `common/logs_access.py`: `/logs*` allowlist checks
- `common/app_meta.py`: compatibility wrapper over `core/app_meta.py`

## Patterns & Conventions

- Keep reusable translation logic in `protocol/` or `common/`, not duplicated in API handlers.
- Keep GigaChat SDK lifecycle/auth logic in `providers/gigachat/`, not in `common/` or route modules.
- Keep `RequestTransformer` and `ResponseProcessor` as the public import surface; grow the underscored helper modules instead of turning the facade files back into mega-modules.
- Use `prepare_chat_completion`, `prepare_response`, and `prepare_response_v2` for request shaping; do not reintroduce `send_to_gigachat*` aliases.
- Starlette `1.x` is the runtime baseline. Use `lifespan`, FastAPI router decorators, and `add_middleware`; do not introduce removed Starlette decorator/event-hook APIs such as `on_event()`, `add_event_handler()`, raw `@app.middleware()`, or raw `@app.route()`.
- Decorate router handlers with `@exceptions_handler`.
- Use `request.app.state`, `app_state.py` metadata stores, and `providers/gigachat/client.py` helpers instead of globals.
- New config belongs in `core/config/settings.py` with a `Field(...)` description.
- Middleware order matters; revalidate behavior if changing `app/factory.py`.
- `PROD` mode behavior is security-sensitive. Treat changes to auth, CORS, docs exposure, and log endpoints carefully.

## Middleware Order

Applied via `app/factory.py`:

1. `CORSMiddleware`
2. `PathNormalizationMiddleware`
3. `RquidMiddleware`
4. `RequestValidationMiddleware`
5. `PassTokenMiddleware` when enabled

Remember that Starlette executes middleware in reverse registration order on requests.

## Quick Find Commands

```bash
# Find route handlers
rg -n "@router\.(get|post|delete)" gpt2giga/api

# Find middleware classes
rg -n "class .*Middleware" gpt2giga/api/middleware

# Find request/response transformation methods
rg -n "def (prepare_|process_|transform_|_build_)" gpt2giga/protocol

# Find split request/response internals
rg --files gpt2giga/protocol/request gpt2giga/protocol/response

# Find batch/file state usage
rg -n "get_batch_store|get_file_store|batch_metadata_store|file_metadata_store" gpt2giga

# Find GigaChat provider lifecycle/auth helpers
rg -n "create_app_gigachat_client|close_app_gigachat_client|create_gigachat_client_for_request|pass_token_to_gigachat" gpt2giga/providers/gigachat

# Find OpenAPI schema helpers
rg -n "openapi_extra|_request_body_oneof" gpt2giga/api
```

## Common Gotchas

- Files and batch metadata are stored in-memory via `app.state`; they are not persisted across process restarts.
- `MODE=PROD` implicitly requires an API key and disables docs/log routes.
- `PathNormalizationMiddleware` supports both root and `/v1` style paths; endpoint changes should preserve that behavior unless intentionally breaking it.
- `PassTokenMiddleware` only applies when `proxy.pass_token` is enabled.

## Pre-PR Check

```bash
uv run ruff check gpt2giga
uv run ruff format --check gpt2giga
uv run pytest tests/ --cov=. --cov-fail-under=80
```
