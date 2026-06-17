# How to add a provider or protocol

Этот документ описывает практический checklist для расширения gpt2giga новым
upstream provider или новым публичным protocol. Перед изменением API surface
сначала нужно решить, что именно добавляется:

- новый public protocol: клиенты отправляют Gemini-compatible payloads, а
  upstream остаётся GigaChat;
- новый upstream provider: normalized requests исполняются не только через
  GigaChat;
- оба слоя сразу.

Термины:

- protocol adapter переводит внешний wire format в normalized models и обратно;
- provider adapter исполняет normalized request в конкретном upstream;
- router монтирует HTTP surface и занимается auth, request context, streaming и
  response media type;
- observability, traffic logs и metrics получают безопасные normalized или
  request-context fields.

## 1. Зафиксировать scope

Для нового protocol:

- определить routes, headers, auth expectations и `/v1` alias policy;
- описать минимальные supported operations: chat/messages, embeddings,
  responses-like endpoint, count tokens, models;
- решить, какие optional поля принимаются и игнорируются для SDK
  compatibility.

Для нового upstream provider:

- определить auth settings и secret handling;
- описать sync/non-streaming и streaming SDK calls;
- определить model resolution, per-model concurrency label и timeout/retry
  semantics;
- решить, какие provider-specific поля можно хранить в `provider_metadata`.

## 2. Добавить конфигурацию

Обновите:

- `gpt2giga/models/config.py`: settings, validators, default values.
- `.env.example`: новые env vars и безопасные defaults.
- `docs/configuration.md`: user-facing описание.
- `tests/test_config/test_config.py`: defaults, env parsing, invalid values.

Секреты должны оставаться в env/secrets manager. Не добавляйте provider secrets
в CLI examples, traffic logs, metrics labels или debug output.

## 3. Добавить protocol adapter

Файлы для нового public protocol обычно живут в
`gpt2giga/protocols/<protocol>/`.

Минимальный набор:

- `adapter.py` с реализацией `ProtocolAdapter` из `gpt2giga/core/interfaces.py`;
- request mapper в `NormalizedChatRequest` или другой normalized model;
- response mapper из `NormalizedResponse` в public response shape;
- streaming mapper из `NormalizedStreamEvent` в public SSE/event format;
- parameter sanitizer/classifier, если SDK присылает много optional полей.

Правила маппинга:

- канонические поля кладите в normalized fields;
- unknown или accepted-but-not-executed public fields кладите в
  `raw_extensions`, если их нужно сохранить;
- provider-specific passthrough кладите в `provider_metadata`;
- не смешивайте auth/transport headers с model payload;
- tool schemas и tool calls приводите к `NormalizedTool` и
  `NormalizedToolCall`;
- usage приводите к `input_tokens`, `output_tokens`, `total_tokens`;
- finish reasons приводите к общему набору вроде `stop`, `length`,
  `tool_calls`, если это возможно.

Для уже смонтированного Gemini protocol это сделано отдельным
Gemini-to-normalized mapper, а не новой веткой внутри OpenAI adapter.
Gemini-specific safety settings, candidates, content parts, tool declarations и
stream events должны быть либо подняты в canonical fields, либо явно сохранены в
extensions. Для будущих protocols сохраняйте тот же принцип изоляции wire format
от OpenAI adapter.

## 4. Добавить provider adapter

Файлы для нового upstream provider живут в `gpt2giga/providers/<provider>/`.

Обычно нужны:

- `adapter.py`: implementation для non-streaming и streaming calls;
- `auth.py`: credentials/access-token helpers;
- `client.py`: SDK/client factory;
- `streaming.py`: upstream chunks в `NormalizedStreamEvent`;
- `types.py`: локальные Protocol/types, если SDK типы неудобны для тестов.

Provider adapter должен:

- принимать `NormalizedChatRequest`;
- вызывать upstream async-first;
- обновлять `RequestContext` effective model через `update_request_context`;
- использовать `ModelConcurrencyLimiter` с bounded provider label;
- возвращать `NormalizedResponse` для non-streaming;
- возвращать `NormalizedStreamEvent` для streaming;
- нормализовать provider errors в `NormalizedError`;
- сохранять только безопасную provider metadata;
- не писать raw credentials, API keys, cookies и authorization headers.

Если upstream provider умеет нативно принимать normalized-like payload, не
нужно реконструировать OpenAI shape. Для GigaChat текущий adapter пока
переиспользует OpenAI-like payload и legacy `RequestTransformer`; это
переходная деталь, а не требование для новых providers.

## 5. Подключить routes

Обновите нужные слои:

- `gpt2giga/routers/<protocol>/`: concrete HTTP handlers.
- `gpt2giga/api/<protocol>/routes.py`: route aggregation.
- `gpt2giga/app/factory.py`: mounting, auth dependencies, debug/admin flags.
- `gpt2giga/openapi_specs/`: OpenAPI extras для новых endpoints.
- `gpt2giga/app_state.py` и lifecycle setup, если нужен новый client.

Route handler должен:

- читать body через общие helpers;
- создавать или использовать request context;
- применять proxy/admin auth policy;
- вызывать protocol adapter и provider adapter;
- оборачивать streaming body iterator так, чтобы metrics, traffic logs и
  observability видели финальный lifecycle;
- сохранять conversation stitching только там, где semantics совпадают.

## 6. Добавить observability

Новый provider/protocol должен быть виден в Phoenix/OpenTelemetry, metrics и
traffic logs без включения prompt capture.

Обновите LLM observability:

- используйте `build_llm_chat_completion_attributes()` для chat-like flows,
  если request/response уже normalized;
- добавьте отдельный helper в `gpt2giga/sinks/observability/<protocol>.py`,
  если public protocol имеет особый output/event формат;
- задайте span name, если нужен новый root span, например `Gemini-Content`;
- выставляйте `gpt2giga.api_format` в bounded значение: `chat_completions`,
  `responses`, `messages`, `generate_content`, `embeddings` или новый explicit
  format;
- маппьте stream milestones в span events через `NormalizedStreamEvent`, где
  возможно;
- сохраняйте tool visibility: counts/names по умолчанию, args/schema только
  при `GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True` и
  `GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=True`;
- не добавляйте prompt, response, tool args или raw provider payload в
  attributes без opt-in и redaction.

Обновите request lifecycle observability:

- `RequestContext.protocol`, route, requested/effective model и provider
  должны заполняться до emission;
- LLM routes должны выставлять `context.llm_observability_emitted=True`, чтобы
  не дублировать successful lifecycle span;
- errors должны попадать в `error_type`, `error_message`, OpenTelemetry status
  и normalized error fields.

Обновите metrics:

- provider/protocol labels должны быть bounded;
- не добавляйте request id, trace id, user id, API key hash или raw model
  variants с высокой cardinality;
- проверьте request counts, latency, upstream latency, upstream errors, token
  totals, stream disconnects и dropped queue events.

Обновите traffic logs:

- request/response content capture остаётся opt-in;
- новые payload fields должны проходить redaction;
- если storage schema требует новые indexed fields, добавьте migration и
  OpenSearch template update;
- admin log filters должны использовать bounded fields.

## 7. Добавить debug translation

Для нового protocol/provider расширьте protected debug API:

- `SUPPORTED_TRANSLATE_FORMATS` в `gpt2giga/api/admin/routes.py`;
- `<protocol>-to-normalized` endpoint, если нужен короткий путь;
- generic `/_debug/translate` pair handling;
- fixtures в `tests/fixtures/debug_translate/`;
- tests на unsupported pairs и safe errors.

Debug translation не должен требовать real upstream credentials, кроме
направлений, где нужно реально подготовить provider SDK payload. Raw secrets не
должны попадать в response.

## 8. Добавить tests

Минимальный набор:

- adapter unit tests: request, response, tools, multimodal content, errors;
- streaming mapper tests: start/delta/tool/usage/end/error events;
- router tests: non-streaming, streaming, auth, invalid params, fallback;
- observability tests: spans, attributes, capture flags, redaction, tool events;
- metrics/traffic-log tests, если labels или emitted fields меняются;
- OpenAPI tests;
- golden fixtures для публичного response/SSE формата;
- SDK compatibility smoke tests, если есть доступный client package.

Для Gemini protocol отдельно проверьте candidate mapping, finish reasons,
safety-related fields, tool declarations/function calls, multimodal parts и
stream event order.

## 9. Обновить docs

Обновите:

- `docs/api-compatibility.md`: route status и ограничения.
- `docs/client-parameter-compatibility.md`: accepted/supported/ignored fields.
- `docs/configuration.md`: env vars и modes.
- `docs/operations.md`: metrics, traffic logs, observability, debug endpoints.
- `docs/deployment.md`: compose/env changes, если появились external services.
- `docs/architecture/normalized-messages.md`: если изменился normalized
  contract или execution status.
- README documentation table, если появился новый user-facing document.

Документация должна явно разделять "реализовано сейчас" и "подготовлено для
следующего шага". Это особенно важно для частично подготовленных API families,
например Files/Batches, чтобы не обещать public route, пока он не смонтирован и
не покрыт тестами.

## 10. Проверить качество

Перед PR:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

Если менялись зависимости, обновите `uv.lock`. Если менялись deploy/env
контракты, проверьте `.env.example`, compose files и docs вместе.
