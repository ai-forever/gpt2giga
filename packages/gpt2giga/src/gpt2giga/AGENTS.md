# AGENTS.md — gpt2giga/

## Package Identity

- **What:** Source package for the `gpt2giga` compatibility gateway
- **Framework:** FastAPI + Starlette + Uvicorn, async-first
- **CLI entrypoint:** `gpt2giga/__init__.py` exports `run()` from `api_server.py`; the app is composed in `app/factory.py`

## Setup & Run

```bash
uv sync --all-extras --dev
uv run gpt2giga
uv run ruff check gpt2giga
uv run ruff format --check gpt2giga
```

## Architecture Overview

```text
Client SDK
  -> middleware
  -> api/* aggregator
  -> routers/* concrete handler
  -> protocol/protocols translation
  -> providers/gigachat
  -> sinks/metrics/logs/observability
  -> client-compatible response
```

## Key Modules

| Path | Role |
|---|---|
| `__init__.py` | Package entrypoint exporting `run()` |
| `api_server.py` | Uvicorn runner and compatibility facade |
| `app/factory.py` | FastAPI app factory, middleware registration, router mounting |
| `app/lifecycle.py` | Startup/shutdown dependency wiring |
| `app/settings.py` | App-level config loading, validation, CORS policy, logger setup |
| `app_state.py` | Request/app-scoped accessors for GigaChat client, batch store, file store |
| `cli.py` | Config loading and env-path handling |
| `auth.py` | API-key verification dependency |
| `logger.py` | Log setup and sensitive-data redaction |
| `constants.py` | Size limits, security field lists, shared constants |
| `models/config.py` | `ProxySettings`, `GigaChatCLI`, `ProxyConfig` |
| `models/security.py` | Security posture summary and request-size defaults |
| `api/openai/` | Public OpenAI-compatible router aggregation |
| `api/anthropic/` | Public Anthropic-compatible router aggregation |
| `api/gemini/` | Public Gemini-compatible router aggregation and operation routes |
| `api/admin/` | Opt-in admin traffic-log and debug translation endpoints |
| `api/system/metrics.py` | Prometheus metrics endpoint mounting |
| `common/` | Shared exception handling, client compatibility, request parsing, streaming, schema/tool utilities |
| `core/` | Provider/sink interfaces, request context, redaction primitives |
| `protocol/` | Legacy request, response, attachment, embedding, batch, and Anthropic translation logic |
| `protocols/` | Normalized protocol models/adapters/diagnostics, including OpenAI and Gemini adapters |
| `providers/gigachat/` | GigaChat SDK client creation, v1/v2 payload adapters, streaming, token handoff |
| `routers/` | Concrete OpenAI, Anthropic, Gemini, LiteLLM, system, and legacy log route handlers |
| `sinks/` | Traffic-log, metrics, and observability sink implementations |
| `storage/` | Optional Postgres/OpenSearch storage helpers and migrations |
| `openapi_specs/` | OpenAPI schema fragments for OpenAI, Anthropic and Gemini endpoints |
| `templates/log_viewer.html` | HTML log viewer for `/logs/html` |

## Router Layout

| Path | Endpoints |
|---|---|
| `api/openai/routes.py` | Aggregates mounted OpenAI routes |
| `api/anthropic/routes.py` | Aggregates mounted Anthropic routes |
| `api/gemini/routes.py` | Aggregates mounted Gemini routes and operation routes |
| `api/admin/routes.py` | `/_debug/translate*` when `debug_translate_enabled` is true |
| `api/admin/logs.py` | `/_admin/logs*` when `admin_api_enabled` is true |
| `api/system/metrics.py` | Metrics route when `metrics_enabled` is true |
| `routers/openai/chat_completions.py` | `/chat/completions` |
| `routers/openai/responses.py` | `/responses` |
| `routers/openai/embeddings.py` | `/embeddings` |
| `routers/openai/models.py` | `/models` |
| `routers/openai/files.py` | `/files` code exists but is not mounted |
| `routers/openai/batches.py` | `/batches` code exists but is not mounted |
| `routers/anthropic/messages.py` | `/messages` and `/messages/count_tokens` |
| `routers/anthropic/batches.py` | `/messages/batches` code exists but is not mounted |
| `routers/gemini/generate_content.py` | `/models/{model}:generateContent`, `:streamGenerateContent`, `:countTokens` |
| `routers/gemini/embeddings.py` | `/models/{model}:embedContent`, `:batchEmbedContents` |
| `routers/gemini/models.py` | `/v1beta/models` and Gemini-shaped model discovery |
| `routers/gemini/files.py` | Gemini `/files` code exists but is not mounted |
| `routers/gemini/batches.py` | Gemini `/batches` and `:batchGenerateContent` code exists but is not mounted |
| `routers/litellm/models.py` | `/model/info` |
| `routers/system_router.py` | `/health`, `/ping` |
| `routers/logs_router.py` | `/logs/{last_n_lines}`, `/logs/stream`, `/logs/html` |

- OpenAI and Anthropic routers are mounted at root, `/v1`, and `/v2`; root
  follows env API mode, while `/v1` and `/v2` force the matching GigaChat
  backend contract for that request.
- Gemini operation routes are mounted at root, `/v1`, and `/v2`; Gemini-style
  routes are mounted at `/v1beta`, `/v1/v1beta`, and `/v2/v1beta`.
- LiteLLM model-info routes are mounted at root, `/v1`, and `/v2`.
- System routes are root-only.
- Log routes are disabled in `PROD`.
- Admin/debug routes are root-only and require admin-key verification.

## Protocol Layout

| Path | Purpose |
|---|---|
| `protocol/request/transformer.py` | OpenAI-style payload → GigaChat chat payload |
| `protocol/response/processor.py` | GigaChat response → OpenAI-style response |
| `protocol/response/gigachat_chat_completion_adapter.py` | GigaChat chat completion response adaptation |
| `protocol/attachment/attachments.py` | Image/audio/text attachment handling and cleanup |
| `protocol/batches.py` | Batch target mapping and JSONL transformations |
| `protocol/embeddings.py` | Embeddings input/result mapping helpers |
| `protocol/anthropic/request.py` | Anthropic request → OpenAI-style intermediary |
| `protocol/anthropic/response.py` | OpenAI/GigaChat result → Anthropic response |
| `protocol/anthropic/streaming.py` | Anthropic SSE/event translation |
| `protocols/normalized/` | Normalized chat request/response models, diagnostics, and shadow execution |
| `protocols/openai/` | OpenAI normalized adapter, response adapter, and streaming helpers |
| `protocols/gemini/` | Gemini normalized adapter, response adapter, and streaming helpers |

## Common Utilities

- `common/exceptions.py`: `@exceptions_handler` and exception normalization
- `common/client_params.py`: compatibility filtering for SDK `extra_*` and optional client params
- `providers/gigachat/auth.py`: per-request GigaChat auth/token handoff
- `common/gigachat_auth.py`: compatibility facade for GigaChat auth helpers
- `common/gigachat_options.py`: GigaChat option extraction and safe passthrough
- `common/request_json.py` and `common/request_form.py`: safe request parsing
- `common/streaming.py`: SSE generators for chat and responses
- `common/tools.py`: tool/function conversion helpers
- `common/json_schema.py`: JSON Schema normalization and `$ref` resolution
- `common/message_utils.py`: role mapping and message collapsing helpers
- `common/logs_access.py`: `/logs*` allowlist checks
- `common/model_concurrency.py`: per-model upstream concurrency limiter
- `common/app_meta.py`: version, port checks, CLI secret warnings

## Runtime Sinks & Storage

- `sinks/logs/`: noop, JSONL, Postgres, OpenSearch, composite, queue, retention, query, and serialization logic for traffic logs.
- `sinks/metrics/`: noop and Prometheus-compatible metrics emission.
- `sinks/observability/`: noop, Phoenix/OpenTelemetry, LLM span enrichment, and redaction-aware observability.
- `storage/postgres/`: traffic-log schema/migrations.
- `storage/opensearch/`: OpenSearch index/data-stream template helpers.

## Patterns & Conventions

- Keep reusable translation logic in `protocol/` or `common/`, not duplicated in routers.
- Use `protocols/normalized/` for the shared normalized contract; preserve legacy paths unless the feature flag behavior is intentionally changed. Gemini already uses its dedicated normalized adapter in the mounted execution path.
- Keep upstream-provider code in `providers/gigachat/`; routers should not call raw SDK methods directly when a provider/helper exists.
- Keep traffic-log, metrics, and observability writes behind sink interfaces; do not inline storage calls in routers.
- Decorate router handlers with `@exceptions_handler`.
- Use `request.app.state` and helpers in `app_state.py` for shared state instead of globals.
- New config belongs in `ProxySettings` or `GigaChatCLI` with a `Field(...)` description.
- Middleware order matters; revalidate behavior if changing `app/factory.py`.
- `PROD` mode behavior is security-sensitive. Treat changes to auth, CORS, docs exposure, and log endpoints carefully.
- Admin/debug/replay endpoints are security-sensitive. Keep admin-key checks and replay path blocking intact.

## Middleware Order

Applied via `app/factory.py`:

1. `CORSMiddleware`
2. `PathNormalizationMiddleware`
3. `RequestValidationMiddleware`
4. `RquidMiddleware`
5. `PassTokenMiddleware` when enabled

Remember that Starlette executes middleware in reverse registration order on requests.

## Quick Find Commands

```bash
# Find route handlers
rg -n "@router\.(get|post|delete|put|patch)" gpt2giga/api gpt2giga/routers

# Find middleware classes
rg -n "class .*Middleware" gpt2giga/middlewares

# Find request/response transformation methods
rg -n "def (prepare_|process_|transform_|_build_)" gpt2giga/protocol gpt2giga/protocols

# Find disabled Files/Batches wiring
rg -n "files_router|batches_router|messages/batches|batchGenerateContent|/files|/batches" gpt2giga/api gpt2giga/routers gpt2giga/protocol

# Find OpenAPI schema helpers
rg -n "openapi_extra|_openapi_extra" gpt2giga/openapi_specs gpt2giga/routers

# Find Gemini protocol wiring
rg -n "gemini|v1beta|generateContent" gpt2giga/app gpt2giga/api gpt2giga/routers gpt2giga/protocols tests

# Find traffic logs, metrics, and observability wiring
rg -n "traffic_log|metrics|observability|admin_api|debug_translate|replay" gpt2giga
```

## Common Gotchas

- Files and batch metadata helpers still exist in `app_state.py`, but public OpenAI, Anthropic and Gemini Files/Batches routers are not mounted in the current API surface.
- `MODE=PROD` implicitly requires an API key and disables docs/log routes.
- `PathNormalizationMiddleware` supports root, `/v1`, `/v2`, and Gemini `/v1beta` style paths; endpoint changes should preserve that behavior unless intentionally breaking it.
- `PassTokenMiddleware` only applies when `proxy.pass_token` is enabled.
- `traffic_log_capture_content` and observability payload capture are opt-in and must remain redaction-aware.
- Per-model concurrency limits are process-local; multi-worker deployments multiply effective capacity.

## Pre-PR Check

```bash
uv run ruff check gpt2giga
uv run ruff format --check gpt2giga
uv run pytest tests/ --cov=. --cov-fail-under=80
```
