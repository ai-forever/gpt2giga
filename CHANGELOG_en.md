# Changelog

All notable changes to the gpt2giga project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **LAR-1 semantic routing**: optional routing for `POST /v1/chat/completions` based on `metadata.lar1` (`confidence`, `evidence`, `time`, `act`, `mind`); the proxy classifies the request and overrides `model` with the selected GigaChat tier before the upstream call, with no extra LLM calls on the hot path.
- **LAR-1 configuration**: env vars `LAR1_ENABLED`, `LAR1_THRESHOLD_LOW|MEDIUM|HIGH`, `LAR1_MODEL_GIGACHAT_PRO|GIGACHAT_FAST|LOCAL`; disabled by default (`LAR1_ENABLED=false`).
- **LAR-1 classifier**: `UNVERIFIED` / low confidence → `gigachat-fast` (economical), `time=MEM` / mid confidence → `gigachat-pro` (advanced), high confidence → `local` (economical/fast); decisions logged as `[LAR-1] confidence=… → route (model=…)`.
- **LAR-1 tests**: `tests/test_lar1_router.py` (10 classifier unit tests) and `_apply_lar1_routing` integration tests.

## [0.2.2a1] - 2026-06-26

### Added
- **Docusaurus docs site**: added the `docs-site/` wrapper for GitHub Pages with TypeScript config, sidebar/theme settings, an npm lockfile, `en`/`ru` locales, and Russian documentation translations.
- **Docs Makefile targets**: added `make docs-install`, `make docs`, `make docs-preview`, `make docs-dev`, `make docs-dev-ru`, and related commands for local Docusaurus builds and previews.
- **Built-in tool mapping toggle**: added `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING` to disable mapping OpenAI/Anthropic/Gemini provider built-in tools into GigaChat v2 built-ins without disabling custom function tools.

### Changed
- **Docs publishing stack**: moved the GitHub Pages workflow from MkDocs/uv to Docusaurus/npm, removed `mkdocs.yml`, and updated README/docs for the new local preview and published site.
- **Gemini documentation alignment**: synchronized README, compatibility/configuration/deployment/operations/integrations docs, and OpenAPI descriptions with the Gemini-compatible API, current Files/Batches limitations, and built-in tool behavior.
- **Dependencies and CI**: updated the project version to `0.2.2a1`, refreshed lock files, pinned docs-site dependencies with security overrides, and moved GitHub Actions to current major versions.

### Fixed
- **Codex/MCP tool enum schemas**: JSON Schema normalization now emits only string `enum` values for tool/function schemas and removes incompatible literal-enum values so the GigaChat SDK does not fail on Codex CLI/MCP schemas.
- **Gemini abandoned function calls**: the Gemini adapter now drops unanswered model `functionCall` entries when a normal user follow-up arrives without a matching `functionResponse`, preventing invalid history from being sent upstream.
- **Built-in tool mapping opt-out**: OpenAI Responses/Chat, Anthropic Messages, Gemini GenerateContent, and debug translation now consistently honor `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING`; Responses stateful fields in v2 no longer depend on built-in tool mapping being enabled.

## [0.2.1a1] - 2026-06-17

### Added
- **Gemini-compatible API**: added Gemini-like routes for `generateContent`, `streamGenerateContent`, `countTokens`, `embedContent`, `batchEmbedContents`, and model discovery; operation routes are available at root, `/v1`, `/v2`, and `/v1beta`, while `/v1` and `/v2` explicitly select the GigaChat backend contract.
- **Gemini protocol adapters**: added normalization for Gemini `contents`/`parts`, `systemInstruction`, `generationConfig`, function declarations, `toolConfig`, text/image/file parts, plus reverse mapping for candidates, usage metadata, function calls, and SSE chunks into Gemini shape.
- **Gemini examples and docs**: added `google-genai` examples for content generation, streaming, chat sessions, function calling, structured output, `countTokens`, embeddings, and prepared Files/Batches examples; README and compatibility docs now describe the Gemini route matrix and limitations.
- **Prepared Gemini Files/Batches routers**: added router modules and OpenAPI helpers for Gemini Files API and `batchGenerateContent`, but they are still not mounted publicly until upstream file/batch execution is validated end to end.
- **Stateful Gemini conversations**: Gemini `generateContent` and `streamGenerateContent` now support opt-in conversation stitching by stable conversation id; stateful examples were added for Gemini and Anthropic.
- **Provider built-in tool mapping**: added shared mapping from provider tool aliases (`web_search*`, `googleSearch`, `urlContext`, `codeExecution`/`code_execution`, `image_generation`, `model_3d_generate`) into GigaChat v2 built-ins.
- **Examples smoke runner**: added `scripts/run_examples_smoke.py` for smoke-running examples across `/v1` and `/v2` with local base URL rewriting, known-skip rules, parallel execution, and JSON reporting.
- **Claude Desktop integration guide**: added a beta guide for Claude Desktop App through a local gateway, including `/v2` gateway setup, model aliasing through `GPT2GIGA_PASS_MODEL=False`, API-key notes, and plugins/MCP diagnostics.
- **Test coverage**: added unit/integration tests for Gemini router wiring, adapter mappings, streaming, embeddings, models, prepared Files/Batches, shared prefixes, Claude gateway path normalization, Anthropic provider tools, source rendering, and observability hardening.

### Changed
- **Unified backend mode for Responses**: removed `GPT2GIGA_RESPONSES_API_MODE`; OpenAI `/responses` now follows `GPT2GIGA_GIGACHAT_API_MODE`, and explicit backend-contract selection is done through `/v1/responses` or `/v2/responses`.
- **Model discovery negotiation**: shared `/models`, `/v1/models`, and `/v2/models` keep the OpenAI shape by default, but return the Gemini `models/*` shape for Google/Gemini clients based on headers, query parameters, or user-agent.
- **Gemini release hardening**: Gemini-compatible docs and examples now explicitly describe supported routes, version prefixes, disabled Files/Batches routes, text-only embeddings, the `countTokens` approximation, and the release smoke checklist for `google-genai`/Gemini CLI.
- **GigaChat provider adapter**: provider labels now pass into the per-model concurrency limiter so Gemini traffic is tracked separately from OpenAI/Anthropic paths; raw extensions are forwarded upstream only for OpenAI protocol payloads.
- **Dependencies**: added `google-genai` for Gemini examples/integration coverage, refreshed `uv.lock`, and widened supported `tiktoken` and `starlette` versions.
- **Docs alignment**: README, API compatibility, client parameter compatibility, configuration, examples index, and integrations index were updated for the Gemini-compatible API, Claude Desktop, and removal of the separate Responses API mode flag.
- **API version routing docs**: docs, examples, and integration guides now clarify explicit backend-contract selection through `/v1` or `/v2`, plus `GPT2GIGA_EXAMPLE_API_VERSION` and `GPT2GIGA_EXAMPLE_BASE_URL` for examples.
- **Phoenix span names**: LLM spans are aligned to compatible API formats: `OpenAI-Completions`, `OpenAI-Responses`, `Anthropic-Messages`, `Gemini-Content`, and `Embeddings`.
- **Built-in tools docs**: added the Russian built-in tools mapping reference and updated compatibility/configuration material.

### Fixed
- **Anthropic provider tools in v2 mode**: compatible Anthropic provider tools (`web_search*`, `web_fetch*`, `code_execution*`) now map to GigaChat v2 built-ins, including forced `tool_choice`; unsupported provider tools remain accepted/ignored.
- **Tool schema normalization**: function/tool schemas now normalize through a shared helper, get an object root and default `properties`, and collapse `allOf` into a GigaChat-supported schema shape.
- **GigaChat v2 stream completion**: the stream adapter now handles raw SSE strings, wrapped `data`, named done events, `choices[].delta/message`, `[DONE]`, and both `input/output` and `prompt/completion` usage aliases.
- **Source rendering**: GigaChat source markers and `inline_data.sources` now render into a visible Markdown `Sources` appendix in OpenAI Chat, OpenAI Responses, and streaming flows; Responses annotations use raw text so links are preserved after markers are stripped.
- **Codex Responses sources**: the Responses API now returns source annotations and a final source appendix correctly for Codex-style streaming/non-streaming responses.
- **Claude gateway path normalization**: Claude Desktop gateway paths such as `/v2/v1/messages` now normalize to `/v2/messages` while preserving the GigaChat v2 backend selection.
- **Observability isolation**: observability sink emit/flush calls are timeout-bounded, OpenTelemetry span emission is moved out of the event loop, and stream observer errors no longer break OpenAI/Anthropic/Gemini response paths.
- **Gemini tool and embeddings validation**: the Gemini adapter no longer loses multi-`functionResponse` or mixed text/tool parts, `toolConfig.functionCallingConfig` is validated explicitly, invalid `allowedFunctionNames` return `400`, and malformed `embedContent`/`batchEmbedContents` payloads no longer call upstream embeddings with an empty string.
- **Gemini model capabilities**: Gemini model discovery now conservatively distinguishes generation, embedding, and unknown/custom models instead of advertising the same `supportedGenerationMethods` for every model.
- **Gemini streaming and diagnostics hardening**: `streamGenerateContent` now returns deterministic Gemini-compatible SSE error chunks for early and partial stream failures, empty streams finish with a valid `STOP` chunk, and accepted-but-ignored Gemini request extensions are visible in redacted observability attributes.
- **Legacy GigaChat v1 function calling**: the legacy `/chat` path again preserves `functions` after tool/function results for following calls while stripping backend `functions_state_id`/`tools_state_id` values from history so GigaChat v1 validation keeps passing.
- **Tool state ids**: Anthropic `tool_use` blocks and Gemini `functionCall`/`functionResponse` now preserve upstream tool state ids in non-streaming and streaming flows, including multi-tool turns.
- **Gemini structured output aliases**: Gemini `generationConfig.responseJsonSchema` is now supported as a JSON Schema structured-output alias; conflicts with `responseSchema` and JSON mode without a schema return a compatible `400`.
- **Null reasoning stream deltas**: OpenAI Responses and Anthropic streaming no longer fail on `reasoning_content=null` and continue text deltas correctly.
- **Examples paths**: fixed the local image path in the Anthropic multimodal example.
- **CI runtime warning**: updated the coverage artifact download action to a Node.js 24-based release while keeping the coverage badge workflow behavior unchanged.

## [0.2.0a2] - 2026-06-11

### Fixed
- **GigaChat v2 profanity filter mapping**: `profanity_check` now maps to the inverse GigaChat `disable_filter` field for `v2/chat/completions`, including request-level `extra_body`/SDK-style fields and the `GIGACHAT_PROFANITY_CHECK` default; an explicit `disable_filter` keeps priority.

## [0.2.0a1] - 2026-06-11

### Breaking Changes
- **Internal GigaChat transformer API**: the old compatibility aliases `send_to_gigachat*`, `prepare_*_v2`, `stream_*_v2`, and the `gigachat_v2_adapter` module were replaced with explicit `chat` / `chat_completion` names; external OpenAI/Anthropic-compatible endpoints are unchanged.

### Added
- **Explicit GigaChat API mode routes**: public OpenAI/Anthropic/LiteLLM-compatible routes are now available at root, `/v1`, and `/v2`; root routes follow `GPT2GIGA_GIGACHAT_API_MODE`, `/v1` forces the legacy chat contract, and `/v2` forces the GigaChat chat-completion contract.
- **Configuration reference**: expanded `docs/configuration.md` with quick profiles, env value formats, security/auth notes, backend API modes, observability, metrics, traffic-log, and storage settings.
- **Modular roadmap safety baseline**: started the `v0.2.0` release discipline with semantic versioning rules and a release checklist.
- **Modular feature flags**: added default-safe `GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER`, `GPT2GIGA_NORMALIZATION_MODE`, `GPT2GIGA_LEGACY_CHAT_FALLBACK`, `GPT2GIGA_TRAFFIC_LOG_ENABLED`, `GPT2GIGA_OBSERVABILITY_ENABLED`, `GPT2GIGA_UI_ENABLED`, and `GPT2GIGA_DEBUG_TRANSLATE_ENABLED`.
- **RequestContext**: added an internal request-scoped context with `request_id`, `trace_id`, protocol/route metadata, and safe hash fields for future traffic logs and observability without changing the public API.
- **Caller metadata**: added safe caller inference from headers/user-agent for `swagger`, `redoc`, OpenAI/Anthropic SDKs, Codex, Claude Code, and Qwen Code; metadata is used in traces, traffic logs, and observability annotations.
- **Conversation stitching**: added default-off in-memory stitching state for Chat Completions, OpenAI Responses v1, and Anthropic Messages using a stable conversation id or `x-session-id`, with TTL, message limits, and a divergence strategy.
- **Golden compatibility fixtures**: added mocked-upstream fixtures and tests for OpenAI chat/tool/structured/streaming/embeddings and Anthropic messages/streaming response shapes.
- **Logging terminology**: added an architecture document that separates runtime logs, future traffic logs, observability traces, and metrics.
- **Normalized/provider architecture docs**: added architecture guides for normalized messages and adding new providers, covering protocol adapters, provider adapters, observability, metrics, and traffic logs.
- **Modular package skeleton**: added empty namespace packages under `gpt2giga.api`, `gpt2giga.app`, `gpt2giga.protocols`, `gpt2giga.providers`, and `gpt2giga.sinks` for staged migration without changing current runtime wiring.
- **Extension interfaces**: added internal `ProtocolAdapter`, `ProviderAdapter`, `TrafficLogSink`, `TrafficLogQueryStore`, `ObservabilitySink`, and `MetricsSink` contracts for future backend/provider/storage extensions without heavy dependencies.
- **Traffic log event and sinks**: added the storage-independent `TrafficLogEvent` model, a default noop traffic sink, and an opt-in JSONL sink for local validation through `GPT2GIGA_TRAFFIC_LOG_ENABLED=True` and `GPT2GIGA_TRAFFIC_LOG_SINK=jsonl`.
- **Observability noop sink**: added a noop observability sink and safe helper functions for future trace events.
- **Normalized schemas**: added internal JSON-serializable normalized-layer models for chat, embeddings, responses, usage, errors, and stream events with `raw_extensions` and provider metadata.
- **OpenAI normalized adapter**: added an internal OpenAI Chat Completions to `NormalizedChatRequest` adapter for shadow mode, covering messages, model, generation parameters, tools, tool choice, response format, and metadata.
- **Normalized shadow mode**: OpenAI Chat routes can now run the normalized adapter in best-effort shadow mode when `GPT2GIGA_NORMALIZATION_MODE=shadow`; shadow translation errors do not break the legacy request path.
- **Shadow diagnostics**: added safe diagnostic events for normalized shadow mode with `normalization_status`, `route`, `request_id`, shape hash, warnings, and errors without recording raw prompt/response content.
- **Normalized OpenAI Chat path**: when `GPT2GIGA_NORMALIZATION_MODE=on`, OpenAI Chat Completions non-stream runs through `NormalizedChatRequest`, the GigaChat provider adapter, and the normalized-to-OpenAI response adapter; `GPT2GIGA_LEGACY_CHAT_FALLBACK=True` keeps fallback to the legacy path without recording raw prompt/response content.
- **Normalized streaming**: when `GPT2GIGA_NORMALIZATION_MODE=on`, OpenAI Chat Completions `stream=true` runs through canonical normalized stream events, the GigaChat stream adapter, and the OpenAI-compatible SSE mapper; the legacy stream path remains the default for `off`/`shadow`.
- **Debug translate API**: added protected `/_debug/translate/*` endpoints for inspecting OpenAI/Anthropic/normalized/GigaChat transformations; routes are disabled by default and require `GPT2GIGA_ADMIN_API_KEY` when enabled.
- **Postgres traffic log extra**: added the optional `postgres` extra with `asyncpg`, `sqlalchemy[asyncio]`, and `alembic` for future opt-in storage backends without changing the base install.
- **Postgres traffic log schema**: added a packaged SQL migration for the `gpt2giga_traffic_logs` table with request/trace/model/error/token metadata, redacted payload JSONB columns, and indexes for query/admin use cases.
- **Traffic log redaction**: added `gpt2giga.core.redaction` with default-on durable traffic-log redaction, including nested dict/list payloads, cookies, auth/API keys, token-like strings, and configurable extra keys.
- **Postgres traffic log writer**: added the opt-in `postgres` traffic sink, lazy asyncpg writer, and background queue with batch writes, best-effort flushes, and a default drop-on-backpressure policy so storage failures do not break the API request path.
- **Traffic event emission**: `RquidMiddleware` now emits safe traffic events for completed requests, validation errors, unhandled errors, and stream completion/abort through the configured sink; the default noop path preserves public API behavior.
- **Postgres deploy profile**: added `deploy/postgres.yaml` for a local Postgres traffic-log backend and Dockerfile `INSTALL_EXTRAS` build arg for images with the optional `[postgres]` extra.
- **Admin traffic logs API**: added opt-in protected `/_admin/logs*` endpoints for list/get/request/response/tail/NDJSON export of Postgres traffic logs with pagination, filters, and admin-key auth; routes are disabled by default.
- **OpenSearch traffic log extra**: added the optional `opensearch` extra with `opensearch-py` for a future opt-in search mirror backend without changing the base install.
- **OpenSearch traffic log mirror**: added `GPT2GIGA_TRAFFIC_LOG_SINKS`, `GPT2GIGA_OPENSEARCH_*`, an OpenSearch bulk writer with retry/backoff, a composite sink for `postgres,opensearch`, an index template helper, and `deploy/opensearch.yaml`.
- **Traffic log retention**: added `GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS` and `GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS`, a best-effort Postgres retention job, and the protected admin dry-run/execute purge command `POST /_admin/logs/retention/purge`.
- **Traffic log CSV export**: added `GET /_admin/logs/export.csv` to export traffic-log summary columns without stored request/response body payloads.
- **Traffic log replay**: added default-off `GPT2GIGA_REPLAY_ENABLED` and the protected endpoint `POST /_admin/logs/{id}/replay`, which replays a redacted captured body, does not reuse stored credentials, and marks replay metadata.
- **Manual traffic log redaction**: added protected `POST /_admin/logs/{id}/redact` for manually clearing stored request/response payload columns.
- **Phoenix observability extra**: added the optional `phoenix` extra with Arize Phoenix/OpenTelemetry/OpenInference dependencies for a future opt-in observability backend without changing the base install.
- **Phoenix observability settings**: added settings for the Phoenix/OpenTelemetry observability backend, collector endpoint, project name, API key, sample rate, content capture, and redaction; observability and content capture are disabled by default.
- **Phoenix/OpenTelemetry observability sink**: added an optional Phoenix OTLP sink with lazy imports, safe fallback to noop without the `phoenix` extra, sample-rate control, attribute redaction, and a content-capture guard.
- **Trace/log linkage**: traffic-log events store `trace_id`/optional `span_id`, and Phoenix spans receive matching gateway identifiers as attributes; README documents trace lookup by `trace_id`.
- **Phoenix deploy profile**: added opt-in `deploy/phoenix.yaml` for a local Arize Phoenix collector/UI and building gpt2giga with the optional `[phoenix]` extra.
- **Request lifecycle observability**: `RquidMiddleware` best-effort emits `gpt2giga.request`, `provider.gigachat.request`, and streaming `stream.emit` spans through the configured observability sink; sink errors are isolated from the API request path.
- **Rich observability content controls**: added default-off `GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES`, `GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS`, `GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES`, and `GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH` flags for safe opt-in LLM span payload attributes.
- **OpenInference-style LLM spans**: the normalized OpenAI Chat path emits `protocol.normalize.request` and `protocol.normalize.response` spans with model/provider/usage/finish/tool metadata and opt-in redacted payload attributes.
- **API-format LLM spans**: Phoenix/OpenTelemetry observability now emits distinct `ChatCompletion`, `Responses`, `Messages`, and `Embeddings` LLM spans with the bounded `gpt2giga.api_format` attribute and caller annotations.
- **Streaming observability span events**: the normalized streaming path adds OTel span events `stream.start`, `stream.first_token`, `stream.tool_call_delta`, `stream.completed`, and `stream.error`; generic streaming lifecycle also marks `stream.completed`/`stream.aborted`.
- **Prometheus metrics baseline**: added default-off `GPT2GIGA_METRICS_ENABLED`, configurable `GPT2GIGA_METRICS_PATH`, an in-process Prometheus-compatible sink, and an endpoint for aggregate service metrics without prompt/response content, request ids, or secrets.
- **Deploy Makefile commands**: added Makefile targets for `deploy/base.yaml`, Phoenix, mitmproxy, observability, Traefik, and multi-instance compose profiles.

### Changed
- **GigaChat backend naming**: the internal upstream path is now named `chat` for legacy GigaChat calls and `chat_completion` for GigaChat `v2/chat/completions`; `_v2` suffixes were removed from the transformer, response adapter, streaming helpers, and tests.
- **Versioned client docs**: README, integration guides, examples, and `.env.example` now clarify using `base_url="http://localhost:8090/v1"` or `base_url="http://localhost:8090/v2"` to choose an explicit backend contract.
- **Docs layout**: README was reduced to an overview and quick links, while detailed material moved to `docs/quickstart.md`, `docs/configuration.md`, `docs/api-compatibility.md`, `docs/deployment.md`, `docs/operations.md`, and `docs/integrations.md`.
- **Deployment layout**: Docker Compose manifests moved from `compose/` to `deploy/`, `deploy/README.md` was added, and README, docs, Makefile, and CI links were aligned with the new structure.
- **Examples layout**: runnable OpenAI/Anthropic examples were grouped by capability (`basic`, `tools`, `reasoning`, `structured_outputs`, `multimodal`, `files`, `concurrency`, `agents`) with updated READMEs and assets.
- **App factory split**: FastAPI app creation, lifecycle startup/shutdown, and app settings loading moved to `gpt2giga.app.factory`, `gpt2giga.app.lifecycle`, and `gpt2giga.app.settings`; `gpt2giga.api_server` remains a compatible facade for `create_app` and `run`.
- **OpenAI API namespace**: added the OpenAI-compatible router aggregator under `gpt2giga.api.openai.routes`, and the app factory now mounts OpenAI routes through the new modular namespace without changing public paths or response shapes.
- **Anthropic API namespace**: added the Anthropic-compatible router aggregator under `gpt2giga.api.anthropic.routes`, and the app factory now mounts Anthropic routes through the new modular namespace without changing public paths, header behavior, or response shapes.
- **GigaChat provider namespace**: moved GigaChat SDK client creation/shutdown and request-scoped token handoff under `gpt2giga.providers.gigachat`; environment/settings parsing and public proxy behavior are unchanged.
- **Extension sink lifecycle**: the app factory now creates traffic/observability sinks in `app.state`, and lifecycle shutdown performs best-effort flushes; sink failures are isolated from the API request path.
- **Request context protocol inference**: tightened LiteLLM route detection to the exact `/model/info` path so OpenAI `/models` traffic events are not classified as LiteLLM.
- **Internal docs alignment**: package-level AGENTS notes were updated for the new app factory/lifecycle/provider layout and the retained `gpt2giga.api_server` entrypoint facade.

### Fixed
- **Request fingerprints**: API key/client IP fingerprints now use keyed PBKDF2 instead of plain SHA-256, so traffic logs and observability do not store guessable hashes.
- **Traffic-log content capture**: redacted request headers/body and non-stream response bodies are stored only when `GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT=True`, with a size cap and redaction before durable storage.
- **Traffic-log query/replay**: the query store now correctly uses Postgres in composite `postgres,opensearch` setups, and replay injects the proxy API key for PROD/API-key protected targets.
- **Traffic-log deploy hardening**: the Phoenix deploy profile leaves content capture disabled by default again, the Postgres profile mounts the SQL migration init script, and deploy profile tests cover the configuration.
- **Phoenix span payloads**: OpenAI/Anthropic/Responses spans include reasoning/thinking content in redacted payload attributes when content capture is enabled.
- **Protocol inference**: request context now correctly classifies `/v2/messages` as Anthropic and `/v2/model/info` as LiteLLM.
- **Release review regressions**: fixed review-found issues in admin logs retention/redaction/replay and lifecycle shutdown guards.

## [0.1.8a3] - 2026-06-10

### Changed
- **Claude Code docs**: marked the Claude Code integration guide as tested with `Claude Code v2.1.170`
- **Version and lock file**: updated the project version to `0.1.8a3` and refreshed `uv.lock` with current dependency markers

### Fixed
- **Claude Code tool schemas**: tool schemas with nested properties that omit explicit `type` now get a valid object type and `properties`, preventing GigaChat `422` errors

## [0.1.8a2] - 2026-06-09

### Added
- **Disable reasoning**: added `GPT2GIGA_DISABLE_REASONING` / `--proxy.disable-reasoning` to remove `reasoning` and `reasoning_effort` from upstream payloads entirely, including explicit client parameters and `extra_body` passthrough; the setting suppresses `GPT2GIGA_ENABLE_REASONING`

### Changed
- **Parameter compatibility**: known unsupported optional OpenAI/Anthropic client parameters are now accepted and ignored for SDK compatibility instead of rejected, and README, OpenAPI specs, and the compatibility matrix now document this behavior
- **Codex provider docs**: updated the Codex integration guide for the current provider config
- **Version and lock file**: updated the project version to `0.1.8a2` and refreshed `uv.lock` with current dependency markers and dependency updates

### Fixed
- **Codex Responses tools**: fixed support for Codex-style tool declarations in OpenAI Responses, including namespace/input-schema forms and correct streaming output handling
- **JSON Schema normalization**: schemas for GigaChat validators are normalized more consistently, including arrays without typed `items`
- **Chat Completions tool metadata**: OpenAI Chat Completions now preserves called-tool metadata in non-streaming and streaming responses

## [0.1.8a1] - 2026-06-06

### Added
- **GigaChat v2 backend mode**: added `GPT2GIGA_GIGACHAT_API_MODE` to switch chat-like upstream calls to the GigaChat chat-completion contract (`v2/chat/completions` in SDK 0.2.2a1) while keeping the external OpenAI/Anthropic-compatible contract and URLs unchanged
- **Responses built-in tools in v2 mode**: added support for GigaChat built-in tools in OpenAI Responses API (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`); normalized output items, stream progress events, file/inline metadata, and image hydration are implemented for `web_search*` and `image_generation` / `image_generate`
- **Per-model max connections**: added local in-process limits for concurrent upstream model calls by effective GigaChat model via `GPT2GIGA_MODEL_MAX_CONNECTIONS`, `GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT`, and `GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT`, plus matching CLI flags
- **Debug payload logs**: added non-PROD DEBUG payload logs for upstream GigaChat requests and processed responses; payloads are omitted in PROD
- **Examples and coverage**: added runnable examples for per-model concurrency, GigaChat built-in tools, and multiple tool calls, plus tests for v2 adapters, v2 routes, streaming, metadata, and model concurrency

### Changed
- **Default `max_tokens`**: `GPT2GIGA_DEFAULT_MAX_TOKENS` is now unset by default; `max_tokens` is added to GigaChat requests only when the client sends a limit or the administrator explicitly configures the environment variable
- **OpenAI Responses stateful mapping**: in GigaChat v2 mode, `store=true` and `previous_response_id` now map to GigaChat storage/thread state, and the response id is built from `thread_id` when available
- **Response metadata**: GigaChat `x-request-id`, `x-session-id`, `thread_id`, `message_id`, tool state ids, called tools, files, and inline data are forwarded into OpenAI/Anthropic-compatible responses and stream events where applicable
- **Logging**: structured extra fields are now recursively redacted, and Loguru markup in structured logs is escaped
- **Documentation and settings**: README, `.env.example`, OpenAPI specs, and the client parameter compatibility guide now cover v2 mode, built-in tools, per-model limits, and new defaults
- **Dependencies**: updated `aiohttp`, `openai-agents`, integration extras, security-sensitive dependencies, and GitHub Actions versions

### Fixed
- **Streaming built-in tools**: fixed progress/result/done event generation for GigaChat built-in tools in Responses streaming
- **Responses streaming limits**: `/responses` streaming now acquires the per-model concurrency slot before creating the HTTP stream, so local timeout returns a normal HTTP `429`, matching `/chat/completions`
- **Responses v2 streaming id**: streaming Responses in GigaChat v2 mode now builds `response.id` from `thread_id` when it is available in stream metadata
- **Tool state ids**: aligned `functions_state_id` and GigaChat v2 tool/message state metadata handling across non-streaming and streaming responses
- **Response id metadata**: OpenAI-compatible responses now preserve upstream identifiers in `metadata` without dropping user-provided `metadata`
- **Embeddings metadata**: OpenAI embeddings responses now include allowlisted GigaChat response headers in `metadata`
- **Reserved tool names**: user-defined `web_search` is mapped to an internal safe name before sending to GigaChat and mapped back in client responses to avoid conflicts with the built-in GigaChat tool

## [0.1.7] - 2026-05-28

### Added
- **Client parameter compatibility**: added OpenAI and Anthropic policies that classify parameters as `supported`, `accepted_ignored`, or `rejected`, including compatible `400` responses for unsupported capabilities
- **Safe `extra_*` forwarding**: added request-scoped forwarding of safe `extra_headers`, `extra_query`, and `extra_body` data into GigaChat SDK calls while blocking credentials, transport headers, and SDK-internal headers
- **Anthropic Models API**: `GET /models` and `GET /models/{model_id}` now return Anthropic-compatible payloads for Anthropic SDK requests
- **Compatibility documentation**: added `docs/client-parameter-compatibility.md` with the supported, ignored, and rejected OpenAI/Anthropic SDK parameter matrix
- **Test coverage**: added tests for client parameter policies, GigaChat options forwarding, OpenAI/Anthropic SDK compatibility, OpenAPI specs, Anthropic models, embeddings, and router behavior

### Changed
- **OpenAI Chat/Responses**: top-level SDK-style unknown fields and literal `extra_body` are normalized into GigaChat `additional_fields`, while `tool_choice`, `tools`, and function tools now go through explicit validation
- **Anthropic Messages**: added validation for `tool_choice`, `tools`, system/messages content blocks, and unsupported beta/server-tool capabilities before converting requests to GigaChat format
- **OpenAPI and README**: schemas and capability tables now reflect the current OpenAI/Anthropic routes, temporarily disabled Files/Batches routes, and `gigachat==0.2.1` limitations
- **CI dependencies**: bumped GitHub Actions versions for `setup-uv`, `upload-artifact`, `dependency-review-action`, `release-drafter`, and `actionlint`
- **Package version**: updated the project version and lock file to `0.1.7`

### Fixed
- **`extra_body` passthrough**: relaxed `extra_body` handling so GigaChat-specific fields reach upstream correctly through `additional_fields`
- **Tool validation**: malformed OpenAI/Anthropic tool definitions now return clear compatible errors instead of internal exceptions
- **Embeddings**: OpenAI embeddings now explicitly reject unsupported parameters and `extra_body` while keeping support for `dimensions`, `encoding_format`, `extra_headers`, `extra_query`, `input`, `model`, and `user`
- **Anthropic unsupported options**: `container`, `context_management`, `mcp_servers`, unsupported content blocks, and invalid tool options are rejected before calling GigaChat
- **Batch/File routes**: responses for temporarily disabled Files/Batches routes and OpenAPI exposure are aligned with current GigaChat SDK support

## [0.1.6] - 2026-05-20

### Breaking Changes
- **Model forwarding**: `GPT2GIGA_PASS_MODEL` / `--proxy.pass-model` now defaults to `True`. Client-provided models are forwarded to GigaChat for Chat Completions, Responses API, and Embeddings; set `GPT2GIGA_PASS_MODEL=False` explicitly to keep using the proxy-configured model.

### Added
- **OpenAI Files API**: added router modules for `/files`, `/files/{file_id}`, and `/files/{file_id}/content` plus the `examples/openai/files.py` example; these routes are temporarily not mounted in the public OpenAI router until the next GigaChat SDK release
- **OpenAI Batches API**: added router modules for `/batches` and `/batches/{batch_id}` plus the `examples/openai/batches.py` example; these routes are temporarily not mounted in the public OpenAI router until the next GigaChat SDK release
- **Anthropic Message Batches API**: added router modules for `/v1/messages/batches`, `/v1/messages/batches/{message_batch_id}`, and `/v1/messages/batches/{message_batch_id}/results` plus the `examples/anthropic/message_batches.py` example; these routes are temporarily not mounted in the public Anthropic router until the next GigaChat SDK release
- **New integrations**: added setup guides for Qwen Code and Xcode
- **CI and automation**: added `actionlint`, `CodeQL`, `dependency-review`, `docker-smoke`, `nightly-smoke`, `pr-labeler`, `release-drafter`, `stale-issues`, and Dependabot configuration
- **Reasoning / think tags**: added extraction of `<think>...</think>` into reasoning/thinking content for OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages, including streaming
- **Structured output mode**: added `GPT2GIGA_STRUCTURED_OUTPUT_MODE` / `--proxy.structured-output-mode` with `function_call` and `native` modes; native mode forwards JSON Schema through GigaChat SDK 0.2.1+ `response_format`
- **Anthropic structured output**: added `output_config.format` and legacy `output_format` support with `json_schema` for Anthropic Messages, streaming, and Message Batches, including new runnable examples
- **Embeddings dimensions**: added `dimensions` validation for known embedding models

### Changed
- **Examples**: moved OpenAI examples under `examples/openai/` and aligned README/AGENTS docs with the new layout
- **Example models**: updated runnable examples to `GigaChat-2-Max`; the embeddings example now demonstrates `dimensions`, `float`, and `base64`
- **OpenAPI**: split OpenAI and Anthropic schema builders into `gpt2giga/openapi_specs/`
- **LiteLLM router**: moved `/model/info` handling into the dedicated `gpt2giga/routers/litellm/` package
- **Docker Compose**: standardized compose files under `compose/` (`base.yaml`, `observability.yaml`, `nginx.yaml`, `observe-multiple.yaml`, `traefik.yaml`)
- **GitHub templates**: added Russian-language issue and pull request templates
- **Model forwarding**: `GPT2GIGA_PASS_MODEL` now defaults to `True`; request models are forwarded to GigaChat for chat, Responses API, and embeddings, while `GPT2GIGA_EMBEDDINGS` remains the embeddings fallback
- **Dependencies**: updated `gigachat`, `python-dotenv`, `aiohttp`, `pillow`, `pytest`, and `uv.lock` after the Dependabot/security bump

### Fixed
- **Path normalization**: fixed normalization for `/v1`, repeated `/v1/v1`, `files`, `batches`, `messages`, and `model/info`
- **OpenAI payload mapping**: `extra_body` now maps correctly to `additional_fields`
- **Batches**: fixed `completion_window` handling and Python 3.10 datetime behavior
- **Examples**: refreshed runnable OpenAI and Anthropic examples after the directory reorganization
- **Docker Compose docs**: startup commands now pass `--env-file .env` explicitly so the root `.env` is applied correctly with `-f compose/*.yaml`
- **Docker Hub tags**: `latest` and `<version>` are now published only by the Python 3.13 job, while other matrix jobs publish Python-specific tags only
- **Docs/examples links**: fixed stale paths after moving OpenAI examples under `examples/openai/`
- **Embeddings**: `encoding_format="base64"` now returns OpenAI-compatible base64 float32 embeddings for direct `/embeddings` calls and embeddings batches, and responses are normalized to an OpenAI-compatible envelope without GigaChat-specific fields
- **Embeddings input validation**: OpenAI-compatible validation now rejects empty or mixed `input`, unsupported `encoding_format`, invalid `model`, and token id inputs without a model that can be decoded through `tiktoken`
- **Embeddings model routing**: `pass_model` now applies to `/embeddings` and batch requests to `/v1/embeddings`
- **Model/top_p mapping**: fixed default model forwarding and avoided implicitly setting `top_p=0` when the client did not send `temperature`
- **Unsupported Files/Batches routes**: temporarily disabled unsupported OpenAI Files/Batches and Anthropic Message Batches routes in the default routers; they are no longer exposed in the OpenAPI schema until GigaChat SDK support lands

## [0.1.5] - 2026-03-10

### Added
- **Model info endpoint**: Added `GET /model/info` for compatibility with Kilo Code autocomplete and LiteLLM-style clients

### Changed
- **GitHub Actions**: `ci.yaml`, `docker_image.yaml`, and `publish-ghcr.yml` now run only when relevant files change

### Fixed
- **Pull Request CI**: The test workflow no longer runs for draft PRs

## [0.1.4.post1] - 2026-02-27

### Added
- **Cursor integration**: Added `integrations/cursor/README.md` — guide for using GigaChat in Cursor as a custom model
- **Codex integration**: Added `integrations/codex/README.md` — OpenAI Codex setup via `config.toml` with custom gpt2giga provider
- **Claude Code integration**: Added `integrations/claude-code/README.md` — Claude Code setup via `ANTHROPIC_BASE_URL`
- **AGENTS.md documentation**: Updated all `AGENTS.md` files to match the current codebase structure

### Changed
- **Async I/O**: Moved blocking I/O operations in route handlers to worker threads via `anyio.to_thread.run_sync`:
  - `logs_router.py` — log file reading and HTML template loading
  - `api_router.py` — `tiktoken.encoding_for_model()` initialization

## [0.1.4] - 2026-02-26

### Added
- **Nginx**: Added `gpt2giga.conf` config and README for deployment behind nginx
- **Docker Compose**: Updated compose (#77) — mitmproxy in `compose/observability.yaml`, password for mitmproxy
- **Logs router**: Extracted `logs_router.py`, split system router in two

### Changed
- Updated `.env.example`
- Updated README for nginx

### Fixed
- **Giga-auth**: Fixed giga-auth behaviour (#74)

## [0.1.3.post1] - 2026-02-20

### Added
- **Traefik**: Added Traefik integration
- **MITMProxy**: Added mitmproxy to `compose/observability.yaml`
- **Reasoning toggle**: Added `GPT2GIGA_ENABLE_REASONING` environment variable

### Changed
- **Docker Compose profiles**: Set `dev` as the default profile in `compose/base.yaml`

## [0.1.3] - 2026-02-17

### Added
- **DEV/PROD Mode**: Added support for development and production modes
- **Configurable CORS**: Added CORS configuration via environment variables
- **Graceful shutdown**: Added graceful server shutdown handling
- **Gitleaks**: Added gitleaks to pre-commit for secret detection
- **OpenAPI for count_tokens**: Added OpenAPI documentation for count_tokens endpoint
- **Profiles in Docker**: Added profiles DEV and PROD in `compose/base.yaml`

### Changed
- **Structure Refactoring**: Split large files into modules:
  - `gpt2giga/common/` — common utilities (exceptions, json_schema, streaming, tools)
  - `gpt2giga/models/` — configuration and security models
  - `gpt2giga/protocol/attachment/` — attachment processing
  - `gpt2giga/protocol/request/` — request transformation
  - `gpt2giga/protocol/response/` — response processing
- **Improved Logging**: Log redaction policy, disabled full payload logging

### Fixed
- **CLI Security**: Fixed command-line argument issues
- **Port Bindings**: Fixed port binding and redirect issues
- **SSRF Protection**: Hardened SSRF protection in attachment handling
- **Authentication**: Switched to `secrets.compare_digest` for key comparison
- **Attachment Limits**: Added limits for attachments
- **Mapping for reversed tool name**: Fixed bug with function name `web_search`, which can break function_call

## [0.1.2.post1] - 2026-02-13

### Added
- **OpenAPI Documentation**: Added full OpenAPI documentation for all endpoints
- **Count tokens for Anthropic**: Added `/v1/messages/count_tokens` endpoint for token counting in Anthropic format
- **count_tokens Example**: Added `examples/anthropic/count_tokens.py` example
- **Version on Initialize**: Display version on server startup

### Changed
- **Path Normalizer**: Improved path normalizer for responses and messages

### Fixed
- **405 Error**: Fixed 405 error on certain requests
- **Safe Request Reading**: Improved request body reading handling

## [0.1.2] - 2026-02-11

### Added
- **Anthropic Messages API**: New `POST /v1/messages` endpoint for Anthropic Messages API compatibility
  - Streaming support (SSE) in Anthropic format (`message_start`, `content_block_delta`, `message_stop`, etc.)
  - Anthropic message conversion (text, image, tool_use, tool_result) to GigaChat format
  - Anthropic tool conversion (`input_schema`) to GigaChat functions format
  - `tool_choice` support (auto, tool, none)
  - System prompt support (`system`) as string or content block array
  - `stop_reason` mapping (end_turn, tool_use, max_tokens)
- **Extended Thinking (Reasoning)**: Support for Anthropic `thinking` parameter
  - `thinking.budget_tokens` mapped to GigaChat `reasoning_effort` (high/medium/low)
  - GigaChat `reasoning_content` converted to Anthropic `thinking` content block
  - Reasoning support in streaming (`thinking_delta`)
- **Anthropic API Examples**: Added examples in `examples/anthropic/`:
  - `messages.py` — basic request
  - `messages_stream.py` — streaming
  - `system_prompt.py` — system prompt
  - `multi_turn.py` — multi-turn conversation
  - `function_calling.py` — function calling (tool use)
  - `image_url.py` — image from URL
  - `base64_image.py` — base64 image
  - `reasoning.py` — extended thinking

## [0.1.1] - 2026-02-06

### Added
- **GitHub Templates**: Added Pull Request and Issue (bug report) templates to improve contribution process (#58)
- **$ref Resolution in Schemas**: Added `_resolve_schema_refs` function for handling JSON Schema references (#57)
- **Missing Properties Handling**: Implemented proper handling of schemas without `properties` field

### Changed
- **request_mapper.py Refactoring**: Logic split into separate modules for better maintainability:
  - `content_utils.py` — utilities for content handling
  - `message_utils.py` — utilities for message handling
  - `schema_utils.py` — utilities for schema handling
- **Extended Test Coverage**: Added tests for streaming and tool conversion

### Fixed
- **Responses API Streaming**: Fixed streaming responses in Responses API (#60)
- **Function Calling in Streaming**: Fixed function call handling during streaming in Responses API

## [0.1.0b2] - 2025-01-21

### Added
- Python 3.14 support
- Updated tiktoken library

### Changed
- Test refactoring
- Updated library dependencies

### Fixed
- Creating new GigaChat instance when pass_token=True

## [0.1.0b] - 2025-12-26

### Added
- **Pydantic v2**: Full project migration to Pydantic v2.
- **Dependency Management**: Project and CI migration to `uv`.
- **Configuration**: Added `pydantic-settings` library for convenient settings management via CLI and environment variables.
- **Error Handling**: Implemented error mapping for proper exception handling.
- **Structured Output**: Added structured output support as a function.
- **GigaChat Integration**: Added integration with `gigachat` package.
- **Tests**: Significantly expanded test coverage.

### Changed
- **Protocol Refactoring**: `protocol.py` logic split into `request_mapper.py`, `response_mapper.py`, and `attachments.py` modules.
- **Logic Separation**: Completely separated `chat_completion` and `responses` logic.
- **Examples**: Updated ports in usage examples.

### Fixed
- **Streaming**: Fixed streaming response issues.
- **Responses API**: Fixed errors in Responses API.
- **CI/CD**: Fixed SSL error in GitHub Actions.
- **Security**: Fixed vulnerabilities in dependencies.

## [0.0.15.post1] - 2025-12-22

### Added
- API key authorization with support for various methods (query parameter, x-api-key header, Bearer token)
- Logging using loguru library
- System endpoints for monitoring (/health, /ping, /logs)
- HTML page for real-time log viewing
- File parsing support
- Workflow for GHCR publishing
- Workflow for PyPI publishing

### Changed
- Migration to FastAPI
- Switched to loguru for logging

### Fixed
- Fixed exception handling during byte decoding
- Fixed validation error for developer role
- Fixed Python versions in workflows

## [0.0.14] - 2025-10-28

### Added
- mTLS authentication support
- Docker Compose configuration

### Changed
- Updated README documentation

## [0.0.13] - 2025-09-19

### Added
- Basic proxy server functionality
- Streaming generation support
- Embeddings support
- Function calling support
- Structured output support

---

[0.2.2a1]: https://github.com/ai-forever/gpt2giga/compare/v0.2.1a1...v0.2.2a1
[0.2.1a1]: https://github.com/ai-forever/gpt2giga/compare/v0.2.0a2...v0.2.1a1
[0.2.0a2]: https://github.com/ai-forever/gpt2giga/compare/v0.2.0a1...v0.2.0a2
[0.2.0a1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.8a3...v0.2.0a1
[0.1.8a3]: https://github.com/ai-forever/gpt2giga/compare/v0.1.8a2...v0.1.8a3
[0.1.8a2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.8a1...v0.1.8a2
[0.1.8a1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.7...v0.1.8a1
[0.1.7]: https://github.com/ai-forever/gpt2giga/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/ai-forever/gpt2giga/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/ai-forever/gpt2giga/compare/v0.1.4.post1...v0.1.5
[0.1.4.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.4...v0.1.4.post1
[0.1.4]: https://github.com/ai-forever/gpt2giga/compare/v0.1.3.post1...v0.1.4
[0.1.3.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.3...v0.1.3.post1
[0.1.3]: https://github.com/ai-forever/gpt2giga/compare/v0.1.2.post1...v0.1.3
[0.1.2.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.2...v0.1.2.post1
[0.1.2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0...v0.1.1
[0.1.0b2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0b...v0.1.0b2
[0.1.0b]: https://github.com/ai-forever/gpt2giga/compare/v0.0.15.post1...v0.1.0b
[0.0.15.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.0.14...v0.0.15.post1
[0.0.14]: https://github.com/ai-forever/gpt2giga/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/ai-forever/gpt2giga/releases/tag/v0.0.13
