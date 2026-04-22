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

- OpenAI, Anthropic, and Gemini transport layers normalize into shared feature services.
- Admin HTTP routes stay thin; admin runtime/settings logic belongs in `app/`.
- Provider-to-provider payload translation lives in `api/translate.py` and provider adapter packages.

## Key Modules

| Path | Role |
|---|---|
| `app/factory.py` | FastAPI app factory, middleware registration, router mounting |
| `app/admin_settings.py` | Domain services for admin setup, settings, revisions, and API-key management |
| `app/admin_ui.py` | Optional admin UI detection and `/admin` setup-path helpers |
| `app/admin_runtime.py` | Domain services that build admin runtime/config/capability/usage payloads |
| `app/governance.py` | Governance presets and request-policy wiring helpers |
| `app/_observability/` | Internal request-audit implementation | `app/observability.py` remains the stable facade/re-export path |
| `app/_telemetry/` | Internal telemetry sink, registry, and OTLP/Prometheus implementation | `app/telemetry.py` remains the stable facade/re-export path |
| `app/_runtime_backends/` | Internal runtime store/feed backend implementation | `app/runtime_backends.py` remains the stable facade/re-export path |
| `app/lifespan.py` | Startup/shutdown orchestration and runtime service lifecycle |
| `app/wiring.py` | App-scoped runtime wiring for typed `app.state.services/stores/providers` |
| `app/run.py` | Runtime entrypoint that loads config, logs startup, and runs Uvicorn |
| `app/cli.py` | Config loading and env-path handling |
| `app/dependencies.py` | Typed runtime containers and accessors for config, services, stores, and providers |
| `core/config/_control_plane/` | Internal control-plane persistence/bootstrap implementation | `core/config/control_plane.py` remains the stable facade/re-export path |
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
| `providers/gigachat/tool_mapping.py` | GigaChat tool/function conversion and reserved-name remapping |
| `providers/gigachat/message_utils.py` | GigaChat-specific role/message normalization helpers |
| `providers/gigachat/content_utils.py` | Tool-result serialization helpers for provider message payloads |
| `core/errors.py` | Shared exception normalization decorator and GigaChat error mapping |
| `core/http/json_body.py` | Shared JSON request parsing helpers |
| `core/http/form_body.py` | Shared multipart/form-data parsing helpers |
| `core/schema/json_schema.py` | JSON Schema normalization and `$ref` resolution |
| `api/dependencies/auth.py` | API-key verification dependencies |
| `api/dependencies/governance.py` | Shared governance dependency resolution |
| `api/middleware/*` | HTTP middleware for auth-adjacent request processing |
| `features/batches/transforms.py` | Batch target mapping plus JSONL input/output transformation helpers |
| `features/batches/validation.py` | Batch-input validation reports and provider-specific diagnostics |
| `features/files_batches/service.py` | Admin mixed inventory/retrieve/create flows for files and batches |
| `features/files_batches/normalizers.py` | Admin-facing normalization for mixed file/batch inventory |
| `api/anthropic/request.py` | Anthropic request translation into the shared OpenAI-style intermediary |
| `api/anthropic/response.py` | Anthropic response/error shaping |
| `api/anthropic/streaming.py` | Anthropic SSE event translation |
| `api/gemini/request.py` | Gemini request parsing and translation into the shared intermediary |
| `api/gemini/response.py` | Gemini response/error shaping |
| `api/gemini/streaming.py` | Gemini SSE/data-only translation |
| `api/batch_validation.py` | HTTP helpers for staged/inline batch validation and cached batch input bytes |
| `api/translate.py` | Provider-to-provider payload translation endpoint |
| `api/` | HTTP transport adapters: provider endpoints, middleware, dependencies, system routes, and admin routes |
| `api/*/openapi.py` | Provider-specific OpenAPI schema fragments colocated with routers |
| `api/_openapi.py` | Shared OpenAPI request-body helper |
| `api/admin/access.py` | Admin bootstrap-token and scoped access verification helpers |
| `api/admin/runtime.py` | Thin HTTP layer for `/admin/api/version`, `/admin/api/config`, `/admin/api/runtime`, `/admin/api/routes`, `/admin/api/capabilities`, recent events, and usage endpoints |
| `api/admin/settings.py` | Thin HTTP layer for `/admin/api/setup`, `/admin/api/settings/*`, revisions, and `/admin/api/keys*` |
| `api/admin/logs.py` | `/admin/api/logs`, `/admin/api/logs/stream`, legacy `/logs*` compatibility shims |
| `api/admin/files_batches.py` | `/admin/api/files-batches/*` inventory, validation, and create/retrieve helpers |
| `api/admin/ui.py` | `/admin` operator UI |
| `api/system/metrics.py` | `/metrics` exposure for observability integrations |
| `frontend/admin/` | Admin console TypeScript source | Browser modules compiled into `../packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` |
| `../packages/gpt2giga-ui/` | Optional UI distribution | Runtime source of truth for the compiled admin shell/assets used by `gpt2giga[ui]` |
| `providers/registry.py` | Provider capability registry used by translation and compatibility flows |
| `providers/openai/`, `providers/anthropic/`, `providers/gemini/` | Provider adapter/capability packages used by translation and normalization |
| `providers/template_provider/` | Scaffold/example provider implementation kept in-tree with compat tests |

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
| `api/gemini/content.py` | `/v1beta/models/*:generateContent`, `streamGenerateContent`, and `countTokens` |
| `api/gemini/files.py` | `/v1beta/files` and file content/download helpers |
| `api/gemini/batches.py` | `/v1beta/batches` and batch result helpers |
| `api/gemini/models.py` | `/v1beta/models` and `/v1beta/models/{model}` |
| `api/system/health.py` | `/health`, `/ping` |
| `api/system/metrics.py` | `/metrics` |
| `api/batch_validation.py` | `/batches/validate`-style validation helpers for admin/system usage |
| `api/translate.py` | `/translate` |
| `api/admin/ui.py` | `/admin` |
| `api/admin/runtime.py` | `/admin/api/*` runtime/operator endpoints |
| `api/admin/logs.py` | `/admin/api/logs*` and legacy `/logs*` compatibility routes |
| `api/admin/files_batches.py` | `/admin/api/files-batches/*` inventory, file, batch, and validation routes |

- OpenAI and Anthropic routers are mounted both at root and `/v1`.
- Gemini routes are mounted under `/v1beta`.
- System routes are root-only.
- Admin and legacy log routes are disabled in `PROD`.

## Provider And Transport Layout

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
| `features/files_batches/contracts.py` | Mixed admin files/batches inventory contracts |
| `features/files_batches/service.py` | Mixed admin files/batches orchestration |
| `features/models/contracts.py` | Internal model-discovery contracts and normalized model descriptors |
| `features/models/service.py` | Model-discovery service entrypoint used by OpenAI, Gemini, and LiteLLM routes |
| `features/batches/contracts.py` | Internal batches feature contracts and upstream/store protocols |
| `features/batches/service.py` | Batch service entrypoint used by OpenAI and Anthropic batch routes |
| `features/batches/store.py` | Batches metadata-store accessors over app state |
| `features/batches/validation.py` | Provider-aware validation for staged and inline batch inputs |
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
| `providers/gigachat/responses/` | Structured internal Responses pipeline helpers (`backend_request.py`, `input_normalizer.py`, `model_options.py`, `output_items.py`, `request_mapper.py`, `response_mapper.py`, `result_builder.py`, `threading.py`, `tool_mapping.py`) |
| `providers/gigachat/responses_request_mapper.py` | Compatibility wrapper exposing the public Responses request-mapper mixin |
| `providers/gigachat/response_mapper.py` | Public `ResponseProcessor` implementation for chat completions |
| `providers/gigachat/response_mapping_common.py` | Shared response status, usage, reasoning, and serialization helpers |
| `providers/gigachat/responses_response_mapper.py` | Compatibility wrapper exposing the public Responses response-mapper mixin |
| `providers/gigachat/streaming.py` | Provider-owned stream iteration, GigaChat error wrapping, and chunk parsing |
| `providers/gigachat/attachments.py` | Image/audio/text attachment handling, upload, and cleanup |
| `providers/gigachat/tool_mapping.py` | Tool/function conversion and reserved-name remapping |
| `providers/gigachat/message_utils.py` | Role normalization, message merging, and attachment limiting |
| `providers/gigachat/content_utils.py` | Provider-safe serialization for tool results |
| `features/batches/transforms.py` | Shared OpenAI batch target mapping and JSONL transforms |
| `api/anthropic/request.py` | Anthropic request → OpenAI-style intermediary |
| `api/anthropic/response.py` | OpenAI/GigaChat result → Anthropic response |
| `api/anthropic/streaming.py` | Anthropic SSE/event translation |
| `api/gemini/request.py` | Gemini request → OpenAI-style intermediary |
| `api/gemini/response.py` | OpenAI/GigaChat result → Gemini response/error |
| `api/gemini/streaming.py` | Gemini SSE/data-only translation |
| `providers/registry.py` | Runtime provider lookup and adapter registry |
| `providers/template_provider/*` | Template provider transport/presenter skeleton kept in sync with compat tests |

### Provider Execution Cheat Sheet

- Chat flow:
  `api/openai/chat.py` -> `features/chat/service.py` -> `providers/gigachat/chat_mapper.py` -> `RequestTransformer.prepare_chat_completion(...)` or `prepare_chat_completion_v2(...)` -> GigaChat `achat/astream` or `achat_v2/astream_v2` -> `ResponseProcessor`
- Responses flow:
  `api/openai/responses.py` -> `features/responses/service.py` -> `RequestTransformer.prepare_response(...)` or `prepare_response_v2(...)` -> GigaChat `achat` or `achat_v2` -> `ResponseProcessor.process_response_api(...)` or `process_response_api_v2(...)`
- `app/wiring.py` is the place that injects `chat_backend_mode` and `responses_backend_mode` into the mapper/service layer; routers should not branch on backend mode.
- `providers/gigachat/responses/` is the internal source of truth for native Responses v2 helper modules. Top-level `responses_*` modules remain compatibility wrappers for old imports.

## Shared Utilities

- `core/errors.py`: `@exceptions_handler` and exception normalization
- `core/http/json_body.py` and `core/http/form_body.py`: safe request parsing
- `core/schema/json_schema.py`: JSON Schema normalization and `$ref` resolution
- `core/app_meta.py`: app version, port checks, and CLI secret warnings
- `providers/gigachat/tool_mapping.py`: tool/function conversion helpers
- `providers/gigachat/message_utils.py`: provider-facing role/message normalization helpers
- `api/admin/logs.py`: admin/logs IP allowlist checks and legacy `/logs*` redirects

## Patterns & Conventions

- Keep GigaChat-specific request/response mapping in `providers/gigachat/*_mapper.py`; keep Anthropic/Gemini transport translation next to those routers in `api/<provider>/`.
- Keep chat-completions orchestration in `features/chat/service.py`; `api/openai/chat.py` should stay thin.
- Keep files orchestration in `features/files/service.py`; `api/openai/files.py` should stay thin.
- Keep batch orchestration in `features/batches/service.py`; `api/openai/batches.py` and `api/anthropic/batches.py` should stay thin.
- Keep batch validation logic in `features/batches/validation.py` and request caching helpers in `api/batch_validation.py`.
- Keep embeddings orchestration in `features/embeddings/service.py`; `api/openai/embeddings.py` and Gemini embedding routes should stay thin.
- Keep model-discovery orchestration in `features/models/service.py`; `api/openai/models.py`, `api/gemini/models.py`, and `api/litellm/models.py` should stay thin.
- Keep Responses API orchestration in `features/responses/service.py`; `api/openai/responses.py` should stay thin.
- Keep admin mixed inventory flows in `features/files_batches/service.py`; `api/admin/files_batches.py` should stay thin.
- Keep OpenAI SSE formatting in `api/openai/streaming.py`; keep GigaChat stream iteration and chunk parsing in `providers/gigachat/streaming.py`.
- Keep GigaChat SDK lifecycle/auth logic in `providers/gigachat/`, not in shared utility buckets or route modules.
- Keep provider-to-provider translation wiring in `api/translate.py` plus `providers/*/capabilities.py`; do not reimplement provider serializers ad hoc in routes or examples.
- Keep `RequestTransformer`, `ResponseProcessor`, and `AttachmentProcessor` imported from `providers/gigachat/`; add new GigaChat mapping logic there instead of reintroducing legacy wrapper layers.
- Use `prepare_chat_completion`, `prepare_response`, and `prepare_response_v2` for request shaping; do not reintroduce `send_to_gigachat*` aliases.
- Starlette `1.x` is the runtime baseline. Use `lifespan`, FastAPI router decorators, and `add_middleware`; do not introduce removed Starlette decorator/event-hook APIs such as `on_event()`, `add_event_handler()`, raw `@app.middleware()`, or raw `@app.route()`.
- Decorate router handlers with `@exceptions_handler`.
- Use `app/dependencies.py` accessors plus typed `app.state.services`, `app.state.stores`, and `app.state.providers` instead of scattering new runtime fields across flat `app.state.*`.
- Keep `gpt2giga.app.runtime_backends` as the stable import facade when splitting runtime storage internals; move implementation into `app/_runtime_backends/`.
- Keep `gpt2giga.core.config.control_plane` as the stable import facade when splitting control-plane persistence internals; move implementation into `core/config/_control_plane/`.
- When splitting oversized runtime modules, prefer underscore-prefixed internal packages such as `app/_observability/` and `app/_telemetry/`, while keeping the old top-level module as the stable import facade.
- Follow `docs/compatibility-facades.md` when deciding whether a wrapper is a permanent facade, a migration-only import shim, or removable legacy surface.
- New config belongs in `core/config/settings.py` with a `Field(...)` description.
- For internal reads, prefer grouped views such as `proxy_settings.security`, `proxy_settings.runtime_store`, and `proxy_settings.observability`; flat proxy fields remain the env/control-plane compatibility layer.
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
rg -n "def (prepare_|process_|transform_|_build_)" gpt2giga/providers/gigachat gpt2giga/api/anthropic gpt2giga/api/gemini gpt2giga/features/batches

# Find request/response mapper modules
rg --files gpt2giga/providers/gigachat gpt2giga/api/anthropic gpt2giga/api/gemini

# Find batch/file state usage
rg -n "get_batch_store|get_file_store|get_files_batches_service_from_state|batch_metadata_store|file_metadata_store" gpt2giga

# Find GigaChat provider lifecycle/auth helpers
rg -n "create_app_gigachat_client|close_app_gigachat_client|create_gigachat_client_for_request|pass_token_to_gigachat" gpt2giga/providers/gigachat

# Find OpenAPI schema helpers
rg -n "openapi_extra|_request_body_oneof" gpt2giga/api

# Find translation and provider-registry code
rg -n "translate|provider_adapters|template_provider|registry" gpt2giga
```

## Common Gotchas

- Files and batch metadata are stored in-memory via `app.state.stores`; flat store aliases on `app.state.*` are compatibility shims.
- Template-provider scaffolding under `providers/template_provider/` is intentionally in-tree and should stay aligned with `tests/compat/template_provider/`.
- `MODE=PROD` implicitly requires an API key and disables docs/log routes.
- `PathNormalizationMiddleware` supports both root and `/v1` style paths; endpoint changes should preserve that behavior unless intentionally breaking it.
- `PassTokenMiddleware` only applies when `proxy.pass_token` is enabled.

## Pre-PR Check

```bash
uv run ruff check gpt2giga
uv run ruff format --check gpt2giga
uv run pytest tests/ --cov=. --cov-fail-under=80
```
