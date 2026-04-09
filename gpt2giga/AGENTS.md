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
Client SDK -> middleware -> router -> feature service -> provider mapper -> GigaChat SDK
GigaChat SDK -> provider mapper -> feature service -> router -> client-compatible response
```

## Key Modules

| Path | Role |
|---|---|
| `app/factory.py` | FastAPI app factory, middleware registration, router mounting |
| `app/lifespan.py` | Startup/shutdown orchestration and runtime service lifecycle |
| `app/wiring.py` | App-scoped runtime wiring for typed `app.state.services/stores/providers` |
| `app/run.py` | Runtime entrypoint that loads config, logs startup, and runs Uvicorn |
| `app/cli.py` | Config loading and env-path handling |
| `app/dependencies.py` | Typed runtime containers and accessors for config, services, stores, and providers |
| `core/config/settings.py` | Primary `ProxySettings`, `GigaChatCLI`, and `ProxyConfig` implementation |
| `core/config/security.py` | Consolidated security posture model and limits |
| `core/logging/setup.py` | Logger setup, redaction, UTF-8 sanitization, and RQUID context |
| `core/constants.py` | Shared limits, MIME/ext allowlists, and redaction constants |
| `core/app_meta.py` | App version, port checks, and CLI secret warnings |
| `features/chat/service.py` | Chat-completions orchestration between HTTP routes and provider mapping |
| `features/chat/stream.py` | Chat-completions SSE streaming flow |
| `features/embeddings/service.py` | Embeddings orchestration shared by OpenAI and Gemini embedding routes |
| `features/files/service.py` | Files orchestration shared by OpenAI file routes and batch-output loading |
| `features/files/store.py` | In-memory files metadata store accessors |
| `features/models/service.py` | Shared model-discovery orchestration for OpenAI, Gemini, and LiteLLM routes |
| `features/batches/service.py` | Batch orchestration shared by OpenAI and Anthropic batch routes |
| `features/batches/store.py` | In-memory batches metadata store accessors |
| `features/responses/service.py` | Responses API orchestration between HTTP routes and provider mapping |
| `features/responses/stream.py` | Responses API SSE streaming flow |
| `features/responses/store.py` | In-memory Responses API metadata store accessors |
| `api/openai/streaming.py` | OpenAI SSE formatting helpers for chat and Responses streams |
| `providers/gigachat/client.py` | GigaChat client lifecycle, factory resolution, and request-scoped access |
| `providers/gigachat/auth.py` | Pass-token auth handoff and request-level GigaChat client construction |
| `providers/gigachat/chat_mapper.py` | Chat feature entrypoint for GigaChat request/response mapping |
| `providers/gigachat/embeddings_mapper.py` | Embeddings request normalization for the configured GigaChat embeddings model |
| `providers/gigachat/models_mapper.py` | Internal model-descriptor mapping for model-discovery routes |
| `providers/gigachat/request_mapper.py` | Primary GigaChat request-mapping entrypoint for chat and responses |
| `providers/gigachat/response_mapper.py` | Primary GigaChat response-mapping entrypoint for chat and responses |
| `providers/gigachat/streaming.py` | GigaChat stream iteration, error wrapping, and chunk normalization |
| `api_server.py` | Compatibility wrapper over the new `app/*` modules |
| `app_state.py` | Compatibility wrappers over feature-owned metadata stores |
| `cli.py` | Compatibility wrapper for `app/cli.py` |
| `api/dependencies/auth.py` | API-key verification dependencies |
| `api/middleware/*` | HTTP middleware for auth-adjacent request processing |
| `logger.py` | Compatibility wrapper for `core/logging/setup.py` |
| `constants.py` | Compatibility wrapper for `core/constants.py` |
| `models/config.py` | Compatibility wrapper for `core/config/settings.py` |
| `models/security.py` | Compatibility wrapper for `core/config/security.py` |
| `common/` | Shared exception handling, auth helpers, request parsing, streaming, schema/tool utilities |
| `protocol/` | Compatibility facades plus batch and non-GigaChat transport translation logic |
| `api/` | HTTP transport adapters: provider endpoints, middleware, dependencies, and system routes |
| `api/*/openapi.py` | Provider-specific OpenAPI schema fragments colocated with routers |
| `api/_openapi.py` | Shared OpenAPI request-body helper |
| `templates/log_viewer.html` | HTML log viewer for `/logs/html` |

## API Layout

| Path | Endpoints |
|---|---|
| `api/openai/chat.py` | `/chat/completions` |
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

## Provider And Protocol Layout

| Path | Purpose |
|---|---|
| `features/chat/contracts.py` | Internal chat feature contracts and provider/client protocols |
| `features/chat/service.py` | Chat service entrypoint used by OpenAI chat routes |
| `features/chat/stream.py` | Chat stream orchestration over provider-owned chunk iteration |
| `features/embeddings/contracts.py` | Internal embeddings feature contracts and upstream protocols |
| `features/embeddings/service.py` | Embeddings service entrypoint used by OpenAI and Gemini embedding routes |
| `features/files/contracts.py` | Internal files feature contracts and upstream/store protocols |
| `features/files/service.py` | Files service entrypoint used by OpenAI file routes |
| `features/files/store.py` | Files metadata-store accessors over app state |
| `features/models/contracts.py` | Internal model-discovery contracts and normalized model descriptors |
| `features/models/service.py` | Model-discovery service entrypoint used by OpenAI, Gemini, and LiteLLM routes |
| `features/batches/contracts.py` | Internal batches feature contracts and upstream/store protocols |
| `features/batches/service.py` | Batch service entrypoint used by OpenAI and Anthropic batch routes |
| `features/batches/store.py` | Batches metadata-store accessors over app state |
| `features/responses/contracts.py` | Internal Responses API contracts and upstream protocols |
| `features/responses/service.py` | Responses API service entrypoint used by OpenAI responses routes |
| `features/responses/stream.py` | Responses API stream orchestration over provider-normalized chunk updates |
| `features/responses/store.py` | Responses API metadata-store accessors over app state |
| `api/openai/streaming.py` | OpenAI chat/Responses SSE string formatting helpers |
| `providers/gigachat/chat_mapper.py` | Chat feature adapter over provider request/response mappers |
| `providers/gigachat/embeddings_mapper.py` | Embeddings input normalization and configured-model routing |
| `providers/gigachat/models_mapper.py` | Provider model catalog normalization into internal descriptors |
| `providers/gigachat/request_mapper.py` | Public `RequestTransformer` implementation for chat/responses request mapping |
| `providers/gigachat/request_mapping_base.py` | Shared request parameter, schema, and validation helpers |
| `providers/gigachat/chat_request_mapper.py` | Message role/content normalization and attachment handling |
| `providers/gigachat/responses_request_mapper.py` | Native Responses API v2 request/tool/thread mapping |
| `providers/gigachat/response_mapper.py` | Public `ResponseProcessor` implementation for chat completions |
| `providers/gigachat/response_mapping_common.py` | Shared response status, usage, reasoning, and serialization helpers |
| `providers/gigachat/responses_response_mapper.py` | Responses API and Responses v2 output shaping helpers |
| `providers/gigachat/streaming.py` | Provider-owned stream iteration, GigaChat error wrapping, and chunk parsing |
| `providers/gigachat/attachments.py` | Image/audio/text attachment handling, upload, and cleanup |
| `protocol/request/transformer.py` | Compatibility wrapper that re-exports `RequestTransformer` |
| `protocol/response/processor.py` | Compatibility wrapper that re-exports `ResponseProcessor` |
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
- `common/streaming.py`: compatibility wrappers over feature streaming entrypoints
- `common/tools.py`: tool/function conversion helpers
- `common/json_schema.py`: JSON Schema normalization and `$ref` resolution
- `common/message_utils.py`: shared role/message normalization helpers still used by provider request mapping
- `common/logs_access.py`: `/logs*` allowlist checks
- `common/app_meta.py`: compatibility wrapper over `core/app_meta.py`

## Patterns & Conventions

- Keep GigaChat-specific request/response mapping in `providers/gigachat/*_mapper.py`; use `protocol/` as compatibility or transport-adapter surface.
- Keep chat-completions orchestration in `features/chat/service.py`; `api/openai/chat.py` should stay thin.
- Keep files orchestration in `features/files/service.py`; `api/openai/files.py` should stay thin.
- Keep batch orchestration in `features/batches/service.py`; `api/openai/batches.py` and `api/anthropic/batches.py` should stay thin.
- Keep embeddings orchestration in `features/embeddings/service.py`; `api/openai/embeddings.py` and Gemini embedding routes should stay thin.
- Keep model-discovery orchestration in `features/models/service.py`; `api/openai/models.py`, `api/gemini/models.py`, and `api/litellm/models.py` should stay thin.
- Keep Responses API orchestration in `features/responses/service.py`; `api/openai/responses.py` should stay thin.
- Keep OpenAI SSE formatting in `api/openai/streaming.py`; keep GigaChat stream iteration and chunk parsing in `providers/gigachat/streaming.py`.
- Keep GigaChat SDK lifecycle/auth logic in `providers/gigachat/`, not in `common/` or route modules.
- Keep `RequestTransformer` and `ResponseProcessor` as the public import surface; add new GigaChat mapping logic under `providers/gigachat/` instead of growing `protocol/` wrappers.
- Use `prepare_chat_completion`, `prepare_response`, and `prepare_response_v2` for request shaping; do not reintroduce `send_to_gigachat*` aliases.
- Starlette `1.x` is the runtime baseline. Use `lifespan`, FastAPI router decorators, and `add_middleware`; do not introduce removed Starlette decorator/event-hook APIs such as `on_event()`, `add_event_handler()`, raw `@app.middleware()`, or raw `@app.route()`.
- Decorate router handlers with `@exceptions_handler`.
- Use `app/dependencies.py` accessors plus typed `app.state.services`, `app.state.stores`, and `app.state.providers` instead of scattering new runtime fields across flat `app.state.*`.
- Keep `app_state.py` as a compatibility layer for feature store accessors; do not move new runtime wiring back into it.
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
rg -n "def (prepare_|process_|transform_|_build_)" gpt2giga/providers/gigachat gpt2giga/protocol

# Find request/response mapper modules
rg --files gpt2giga/providers/gigachat gpt2giga/protocol/request gpt2giga/protocol/response

# Find batch/file state usage
rg -n "get_batch_store|get_file_store|batch_metadata_store|file_metadata_store" gpt2giga

# Find GigaChat provider lifecycle/auth helpers
rg -n "create_app_gigachat_client|close_app_gigachat_client|create_gigachat_client_for_request|pass_token_to_gigachat" gpt2giga/providers/gigachat

# Find OpenAPI schema helpers
rg -n "openapi_extra|_request_body_oneof" gpt2giga/api
```

## Common Gotchas

- Files and batch metadata are stored in-memory via `app.state.stores`; flat store aliases on `app.state.*` are compatibility shims.
- `MODE=PROD` implicitly requires an API key and disables docs/log routes.
- `PathNormalizationMiddleware` supports both root and `/v1` style paths; endpoint changes should preserve that behavior unless intentionally breaking it.
- `PassTokenMiddleware` only applies when `proxy.pass_token` is enabled.

## Pre-PR Check

```bash
uv run ruff check gpt2giga
uv run ruff format --check gpt2giga
uv run pytest tests/ --cov=. --cov-fail-under=80
```
