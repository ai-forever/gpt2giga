# Changelog

Все значительные изменения в проекте gpt2giga документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

## [Unreleased]

## [0.2.0a2] - 2026-06-11

### Исправлено
- **GigaChat v2 profanity filter mapping**: `profanity_check` теперь маппится в обратный GigaChat `disable_filter` для `v2/chat/completions`, включая request-level `extra_body`/SDK-style поля и дефолт `GIGACHAT_PROFANITY_CHECK`; явный `disable_filter` сохраняет приоритет.

## [0.2.0a1] - 2026-06-11

### Breaking changes
- **Внутренний GigaChat transformer API**: старые compatibility aliases `send_to_gigachat*`, `prepare_*_v2`, `stream_*_v2` и модуль `gigachat_v2_adapter` заменены на явные `chat` / `chat_completion` имена; внешние OpenAI/Anthropic-compatible endpoints не меняются.

### Добавлено
- **Явные GigaChat API mode routes**: публичные OpenAI/Anthropic/LiteLLM-compatible routes теперь доступны в корне, под `/v1` и под `/v2`; root routes следуют `GPT2GIGA_GIGACHAT_API_MODE` / `GPT2GIGA_RESPONSES_API_MODE`, `/v1` принудительно выбирает legacy chat contract, `/v2` - GigaChat chat-completion contract.
- **Configuration reference**: расширен `docs/configuration.md` с quick profiles, форматами env values, security/auth notes, backend API modes, observability, metrics, traffic-log и storage настройками.
- **Modular roadmap safety baseline**: начата подготовка release-дисциплины для `v0.2.0` с правилами semantic versioning и release checklist.
- **Modular feature flags**: добавлены выключенные по умолчанию `GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER`, `GPT2GIGA_NORMALIZATION_MODE`, `GPT2GIGA_LEGACY_CHAT_FALLBACK`, `GPT2GIGA_TRAFFIC_LOG_ENABLED`, `GPT2GIGA_OBSERVABILITY_ENABLED`, `GPT2GIGA_UI_ENABLED` и `GPT2GIGA_DEBUG_TRANSLATE_ENABLED`.
- **RequestContext**: добавлен внутренний request-scoped context с `request_id`, `trace_id`, protocol/route metadata и безопасными hash-полями для будущих traffic logs/observability без изменения публичного API.
- **Caller metadata**: добавлено безопасное определение caller-а по headers/user-agent для `swagger`, `redoc`, OpenAI/Anthropic SDK, Codex, Claude Code и Qwen Code; metadata используется в traces, traffic logs и observability annotations.
- **Conversation stitching**: добавлено выключенное по умолчанию in-memory stitching состояние для Chat Completions, OpenAI Responses v1 и Anthropic Messages по stable conversation id или `x-session-id`, с TTL, лимитом сообщений и стратегией divergence.
- **Golden compatibility fixtures**: добавлены fixtures и тесты для OpenAI chat/tool/structured/streaming/embeddings и Anthropic messages/streaming shapes на mocked upstream.
- **Logging terminology**: добавлен architecture doc, разделяющий runtime logs, future traffic logs, observability traces и metrics.
- **Normalized/provider architecture docs**: добавлены architecture guides для normalized messages и добавления новых providers с требованиями к protocol adapters, provider adapters, observability, metrics и traffic logs.
- **Modular package skeleton**: добавлены пустые namespace-пакеты `gpt2giga.api`, `gpt2giga.app`, `gpt2giga.protocols`, `gpt2giga.providers` и `gpt2giga.sinks` для поэтапной миграции без изменения текущего runtime wiring.
- **Extension interfaces**: добавлены внутренние `ProtocolAdapter`, `ProviderAdapter`, `TrafficLogSink`, `TrafficLogQueryStore`, `ObservabilitySink` и `MetricsSink` для будущих backend/provider/storage расширений без тяжелых зависимостей.
- **Traffic log event and sinks**: добавлена storage-independent модель `TrafficLogEvent`, noop traffic sink по умолчанию и opt-in JSONL sink для локальной проверки через `GPT2GIGA_TRAFFIC_LOG_ENABLED=True` и `GPT2GIGA_TRAFFIC_LOG_SINK=jsonl`.
- **Observability noop sink**: добавлен noop observability sink и безопасные helper-функции для будущих trace events.
- **Normalized schemas**: добавлены внутренние JSON-сериализуемые модели normalized layer для chat, embeddings, response, usage, error и stream events с `raw_extensions` и provider metadata.
- **OpenAI normalized adapter**: добавлен внутренний OpenAI Chat Completions -> `NormalizedChatRequest` adapter для shadow mode с покрытием messages, model, generation params, tools, tool_choice, response_format и metadata.
- **Normalized shadow mode**: OpenAI Chat route теперь может запускать normalized adapter в best-effort shadow mode при `GPT2GIGA_NORMALIZATION_MODE=shadow`; ошибки shadow translation не ломают legacy request path.
- **Shadow diagnostics**: добавлены safe diagnostic events для normalized shadow mode с `normalization_status`, `route`, `request_id`, shape hash, warnings и errors без записи raw prompt/response content.
- **Normalized OpenAI Chat path**: при `GPT2GIGA_NORMALIZATION_MODE=on` OpenAI Chat Completions non-stream проходит через `NormalizedChatRequest`, GigaChat provider adapter и normalized-to-OpenAI response adapter; `GPT2GIGA_LEGACY_CHAT_FALLBACK=True` сохраняет fallback на legacy path без записи raw prompt/response content.
- **Normalized streaming**: при `GPT2GIGA_NORMALIZATION_MODE=on` OpenAI Chat Completions `stream=true` проходит через canonical normalized stream events, GigaChat stream adapter и OpenAI-compatible SSE mapper; legacy stream path остается default при `off`/`shadow`.
- **Debug translate API**: добавлены protected endpoints `/_debug/translate/*` для просмотра OpenAI/Anthropic/normalized/GigaChat преобразований; routes выключены по умолчанию и требуют `GPT2GIGA_ADMIN_API_KEY` при включении.
- **Postgres traffic log extra**: добавлен optional extra `postgres` с `asyncpg`, `sqlalchemy[asyncio]` и `alembic` для будущего opt-in storage backend без изменения базовой установки.
- **Postgres traffic log schema**: добавлена packaged SQL migration для таблицы `gpt2giga_traffic_logs` с request/trace/model/error/token metadata, redacted payload JSONB columns и индексами для query/admin use cases.
- **Traffic log redaction**: добавлен `gpt2giga.core.redaction` с default-on redaction для durable traffic logs, включая nested dict/list payloads, cookies, auth/API keys, token-like strings и configurable extra keys.
- **Postgres traffic log writer**: добавлены opt-in `postgres` traffic sink, lazy asyncpg writer и background queue с batch writes, best-effort flush и default drop-on-backpressure policy, чтобы storage failures не ломали API request path.
- **Traffic event emission**: `RquidMiddleware` теперь эмитит safe traffic events для completed requests, validation errors, unhandled errors и stream completion/abort через configured sink; default noop path сохраняет публичное API behavior.
- **Postgres deploy profile**: добавлен `deploy/postgres.yaml` для локального Postgres traffic log backend и Dockerfile build arg `INSTALL_EXTRAS` для сборки образа с optional extra `[postgres]`.
- **Admin traffic logs API**: добавлены opt-in protected endpoints `/_admin/logs*` для list/get/request/response/tail/NDJSON export Postgres traffic logs с pagination, filters и admin-key auth; routes выключены по умолчанию.
- **OpenSearch traffic log extra**: добавлен optional extra `opensearch` с `opensearch-py` для будущего opt-in search mirror backend без изменения базовой установки.
- **OpenSearch traffic log mirror**: добавлены настройки `GPT2GIGA_TRAFFIC_LOG_SINKS`, `GPT2GIGA_OPENSEARCH_*`, OpenSearch bulk writer с retry/backoff, composite sink для `postgres,opensearch`, index template helper и `deploy/opensearch.yaml`.
- **Traffic log retention**: добавлены настройки `GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS` и `GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS`, best-effort Postgres retention job и protected admin dry-run/execute purge command `POST /_admin/logs/retention/purge`.
- **Traffic log CSV export**: добавлен `GET /_admin/logs/export.csv` для выгрузки summary-колонок traffic logs без stored request/response body payloads.
- **Traffic log replay**: добавлен выключенный по умолчанию `GPT2GIGA_REPLAY_ENABLED` и protected endpoint `POST /_admin/logs/{id}/replay`, который повторно редактирует captured body, не переиспользует stored credentials и помечает replay metadata.
- **Manual traffic log redaction**: добавлен protected endpoint `POST /_admin/logs/{id}/redact` для ручной очистки stored request/response payload columns.
- **Phoenix observability extra**: добавлен optional extra `phoenix` с Arize Phoenix/OpenTelemetry/OpenInference зависимостями для будущего opt-in observability backend без изменения базовой установки.
- **Phoenix observability settings**: добавлены настройки Phoenix/OpenTelemetry observability backend, collector endpoint, project name, API key, sample rate, content capture и redaction; observability и content capture выключены по умолчанию.
- **Phoenix/OpenTelemetry observability sink**: добавлен optional Phoenix OTLP sink с lazy imports, safe fallback на noop без extra `phoenix`, sample-rate control, attribute redaction и content-capture guard.
- **Trace/log linkage**: traffic log events сохраняют `trace_id`/optional `span_id`, а Phoenix spans получают matching gateway identifiers as attributes; README описывает поиск trace по `trace_id`.
- **Phoenix deploy profile**: добавлен opt-in `deploy/phoenix.yaml` для локального Arize Phoenix collector/UI и сборки gpt2giga с optional extra `[phoenix]`.
- **Request lifecycle observability**: `RquidMiddleware` best-effort эмитит `gpt2giga.request`, `provider.gigachat.request` и streaming `stream.emit` spans через configured observability sink; ошибки sink-а изолированы от API request path.
- **Rich observability content controls**: добавлены default-off flags `GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES`, `GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS`, `GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES` и `GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH` для safe opt-in LLM span payload attributes.
- **OpenInference-style LLM spans**: normalized OpenAI Chat path эмитит `protocol.normalize.request` и `protocol.normalize.response` spans с model/provider/usage/finish/tool metadata и opt-in redacted payload attributes.
- **API-format LLM spans**: Phoenix/OpenTelemetry observability теперь эмитит отдельные LLM spans `ChatCompletion`, `Responses`, `Messages` и `Embeddings` с bounded attribute `gpt2giga.api_format` и caller annotations.
- **Streaming observability span events**: normalized streaming path добавляет OTel span events `stream.start`, `stream.first_token`, `stream.tool_call_delta`, `stream.completed` и `stream.error`; generic streaming lifecycle дополнительно отмечает `stream.completed`/`stream.aborted`.
- **Prometheus metrics baseline**: добавлен выключенный по умолчанию `GPT2GIGA_METRICS_ENABLED`, configurable `GPT2GIGA_METRICS_PATH`, in-process Prometheus-compatible sink и endpoint для aggregate service metrics без prompt/response content, request ids или secrets.
- **Deploy Makefile commands**: добавлены Makefile targets для `deploy/base.yaml`, Phoenix, mitmproxy, observability, Traefik и multi-instance compose-профилей.

### Изменено
- **GigaChat backend naming**: внутренний upstream path теперь называется `chat` для legacy GigaChat calls и `chat_completion` для GigaChat `v2/chat/completions`; `_v2`-суффиксы убраны из transformer, response adapter, streaming helpers и tests.
- **Versioned client docs**: README, integration guides, examples и `.env.example` уточняют выбор `base_url="http://localhost:8090/v1"` или `base_url="http://localhost:8090/v2"` для явного backend contract.
- **Docs layout**: README сокращен до overview/quick links, а подробные материалы разнесены по `docs/quickstart.md`, `docs/configuration.md`, `docs/api-compatibility.md`, `docs/deployment.md`, `docs/operations.md` и `docs/integrations.md`.
- **Deployment layout**: Docker Compose manifests перенесены из `compose/` в `deploy/`, добавлен `deploy/README.md`, а README, docs, Makefile и CI ссылки выровнены под новую структуру.
- **Examples layout**: runnable OpenAI/Anthropic examples сгруппированы по capability (`basic`, `tools`, `reasoning`, `structured_outputs`, `multimodal`, `files`, `concurrency`, `agents`) с обновленными README и assets.
- **App factory split**: создание FastAPI app, lifecycle startup/shutdown и загрузка app settings вынесены в `gpt2giga.app.factory`, `gpt2giga.app.lifecycle` и `gpt2giga.app.settings`; `gpt2giga.api_server` остается совместимым фасадом для `create_app` и `run`.
- **OpenAI API namespace**: OpenAI-compatible router aggregator добавлен в `gpt2giga.api.openai.routes`, а app factory подключает OpenAI routes через новый modular namespace без изменения публичных paths и response shapes.
- **Anthropic API namespace**: Anthropic-compatible router aggregator добавлен в `gpt2giga.api.anthropic.routes`, а app factory подключает Anthropic routes через новый modular namespace без изменения публичных paths, headers behavior и response shapes.
- **GigaChat provider namespace**: создание/закрытие GigaChat SDK client и request-scoped token handoff вынесены в `gpt2giga.providers.gigachat`, при этом env/settings parsing и публичное proxy behavior не изменены.
- **Extension sink lifecycle**: app factory создает traffic/observability sinks в `app.state`, а lifecycle делает best-effort flush на shutdown; ошибки sink-ов изолированы от API request path.
- **Request context protocol inference**: уточнено определение LiteLLM route до точного `/model/info`, чтобы OpenAI `/models` traffic events не классифицировались как LiteLLM.
- **Internal docs alignment**: package-level AGENTS notes обновлены под новый app factory/lifecycle/provider layout и сохраненный `gpt2giga.api_server` entrypoint facade.

### Исправлено
- **Request fingerprints**: fingerprint-ы API key/client IP теперь строятся через keyed PBKDF2 вместо plain SHA-256, чтобы traffic logs и observability не хранили guessable hashes.
- **Traffic-log content capture**: redacted request headers/body и non-stream response body сохраняются только при opt-in `GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT=True`, с лимитом размера и redaction до durable storage.
- **Traffic-log query/replay**: query store корректно использует Postgres в composite `postgres,opensearch` setups, а replay добавляет proxy API key для PROD/API-key protected targets.
- **Traffic-log deploy hardening**: Phoenix deploy profile снова оставляет content capture выключенным по умолчанию, Postgres profile монтирует SQL migration init script, а deploy profile tests покрывают конфигурацию.
- **Phoenix span payloads**: OpenAI/Anthropic/Responses spans включают reasoning/thinking content в redacted payload attributes при включенном content capture.
- **Protocol inference**: request context корректно классифицирует `/v2/messages` как Anthropic и `/v2/model/info` как LiteLLM.
- **Release review regressions**: закрыты найденные на review ошибки admin logs retention/redaction/replay и lifecycle shutdown guards.

## [0.1.8a3] - 2026-06-10

### Изменено
- **Claude Code docs**: инструкция интеграции Claude Code отмечена как проверенная с `Claude Code v2.1.170`
- **Версия и lock-файл**: версия проекта обновлена до `0.1.8a3`, а `uv.lock` пересобран с актуальными dependency markers

### Исправлено
- **Claude Code tool schemas**: tool-схемы с вложенными свойствами без явного `type` теперь дополняются валидным объектным типом и `properties`, что предотвращает `422` от GigaChat

## [0.1.8a2] - 2026-06-09

### Добавлено
- **Disable reasoning**: добавлен `GPT2GIGA_DISABLE_REASONING` / `--proxy.disable-reasoning` для полного удаления `reasoning` и `reasoning_effort` из upstream payload, включая явные параметры клиента и `extra_body` passthrough; настройка подавляет `GPT2GIGA_ENABLE_REASONING`

### Изменено
- **Совместимость параметров**: известные unsupported optional параметры OpenAI/Anthropic клиентов теперь принимаются и игнорируются для SDK-совместимости вместо отклонения, а README, OpenAPI specs и матрица совместимости обновлены под это поведение
- **Codex provider docs**: инструкция интеграции Codex обновлена под актуальный provider config
- **Версия и lock-файл**: версия проекта обновлена до `0.1.8a2`, а `uv.lock` пересобран с актуальными dependency markers и обновлениями зависимостей

### Исправлено
- **Codex Responses tools**: исправлена поддержка Codex-style tool declarations в OpenAI Responses, включая namespace/input-schema формы и корректную обработку streaming output
- **JSON Schema normalization**: схемы для GigaChat validators нормализуются стабильнее, включая массивы без typed `items`
- **Chat Completions tool metadata**: OpenAI Chat Completions теперь сохраняет metadata о вызванных инструментах в non-streaming и streaming ответах

## [0.1.8a1] - 2026-06-06

### Добавлено
- **GigaChat v2 backend mode**: добавлены `GPT2GIGA_GIGACHAT_API_MODE` и `GPT2GIGA_RESPONSES_API_MODE` для переключения chat-like upstream-вызовов на GigaChat chat-completion contract (`v2/chat/completions` в SDK 0.2.2a1); внешний OpenAI/Anthropic-compatible контракт и URL остаются прежними
- **Responses built-in tools в v2 mode**: добавлена поддержка встроенных GigaChat-инструментов для OpenAI Responses API (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`); нормализованные output items, stream progress events, file/inline metadata и гидратация изображений реализованы для `web_search*` и `image_generation` / `image_generate`
- **Per-model max connections**: добавлены локальные in-process лимиты одновременных upstream model-call по effective GigaChat model через `GPT2GIGA_MODEL_MAX_CONNECTIONS`, `GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT` и `GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT`, а также соответствующие CLI-флаги
- **Debug payload logs**: добавлены non-PROD DEBUG-логи payload'ов для upstream-запросов и обработанных ответов GigaChat; в PROD payload'ы не пишутся
- **Примеры и покрытие**: добавлены runnable-примеры для per-model concurrency, GigaChat built-in tools и multiple tool calls, а также тесты для v2 adapters, v2 routes, streaming, metadata и model concurrency

### Изменено
- **`max_tokens` по умолчанию**: `GPT2GIGA_DEFAULT_MAX_TOKENS` теперь не задан по умолчанию; `max_tokens` добавляется к GigaChat-запросам только если клиент передал лимит сам или администратор явно настроил переменную окружения
- **OpenAI Responses stateful mapping**: в GigaChat v2 mode `store=true` и `previous_response_id` маппятся в GigaChat storage/thread state, а response id строится из `thread_id`, когда он доступен
- **Метаданные ответов**: GigaChat `x-request-id`, `x-session-id`, `thread_id`, `message_id`, tool state ids, called tools, files и inline data прокидываются в OpenAI/Anthropic-compatible ответы и stream events там, где это применимо
- **Логирование**: структурированные extra-поля теперь редактируются рекурсивно, а Loguru markup в structured logs экранируется
- **Документация и настройки**: README, `.env.example`, OpenAPI specs и справочник совместимости параметров обновлены под v2 mode, built-in tools, per-model limits и новые defaults
- **Зависимости**: обновлены `aiohttp`, `openai-agents`, интеграционные extras и security-sensitive зависимости, а также версии GitHub Actions

### Исправлено
- **Streaming built-in tools**: исправлена генерация progress/result/done events для встроенных инструментов GigaChat в Responses streaming
- **Responses streaming limits**: `/responses` streaming теперь занимает per-model concurrency slot до создания HTTP stream, поэтому локальный timeout возвращает обычный HTTP `429`, как и `/chat/completions`
- **Responses v2 streaming id**: streaming Responses в GigaChat v2 mode теперь строит `response.id` из `thread_id`, когда он приходит в stream metadata
- **Tool state ids**: сохранение `functions_state_id` и GigaChat v2 tool/message state metadata выровнено для non-streaming и streaming ответов
- **Response id metadata**: OpenAI-compatible ответы теперь сохраняют upstream identifiers в `metadata`, не теряя пользовательскую `metadata`
- **Embeddings metadata**: OpenAI embeddings responses теперь добавляют allowlisted GigaChat response headers в `metadata`
- **Reserved tool names**: пользовательский `web_search` маппится во внутреннее безопасное имя при отправке в GigaChat и обратно при ответе клиенту, чтобы не конфликтовать со встроенным GigaChat tool

## [0.1.7] - 2026-05-28

### Добавлено
- **Совместимость параметров клиентов**: добавлены политики OpenAI и Anthropic для классификации параметров как `supported`, `accepted_ignored` и `rejected`, включая совместимые `400`-ответы для неподдерживаемых возможностей
- **Безопасная передача `extra_*`**: добавлена request-scoped передача безопасных `extra_headers`, `extra_query` и `extra_body` в вызовы GigaChat SDK с блокировкой учетных данных, transport headers и SDK-internal заголовков
- **Anthropic Models API**: `GET /models` и `GET /models/{model_id}` теперь возвращают Anthropic-совместимый формат для запросов Anthropic SDK
- **Документация совместимости**: добавлен справочник `docs/client-parameter-compatibility.md` с матрицей поддерживаемых, игнорируемых и отклоняемых параметров OpenAI/Anthropic SDK
- **Тестовое покрытие**: добавлены тесты для client parameter policies, GigaChat options forwarding, OpenAI/Anthropic SDK compatibility, OpenAPI specs, Anthropic models, embeddings и router behavior

### Изменено
- **OpenAI Chat/Responses**: top-level SDK-style unknown fields и literal `extra_body` нормализуются в GigaChat `additional_fields`, а `tool_choice`, `tools` и function tools проходят явную валидацию
- **Anthropic Messages**: добавлена валидация `tool_choice`, `tools`, system/messages content blocks и unsupported beta/server-tool возможностей перед преобразованием в GigaChat-запрос
- **OpenAPI и README**: схемы и таблицы возможностей обновлены под текущие OpenAI/Anthropic routes, временно отключенные Files/Batches routes и ограничения `gigachat==0.2.1`
- **CI dependencies**: обновлены версии GitHub Actions для `setup-uv`, `upload-artifact`, `dependency-review-action`, `release-drafter` и `actionlint`
- **Версия пакета**: версия проекта и lock-файла обновлена до `0.1.7`

### Исправлено
- **`extra_body` passthrough**: ослаблена обработка `extra_body`, чтобы GigaChat-specific поля корректно доходили до upstream через `additional_fields`
- **Tool validation**: malformed OpenAI/Anthropic tool definitions теперь возвращают понятные совместимые ошибки вместо внутренних исключений
- **Embeddings**: OpenAI embeddings теперь явно отклоняют unsupported параметры и `extra_body`, сохраняя поддержку `dimensions`, `encoding_format`, `extra_headers`, `extra_query`, `input`, `model` и `user`
- **Anthropic unsupported options**: `container`, `context_management`, `mcp_servers`, unsupported content blocks и некорректные tool options теперь отклоняются до вызова GigaChat
- **Batch/File routes**: ответы временно отключенных Files/Batches routes и OpenAPI-представление выровнены с текущей поддержкой GigaChat SDK

## [0.1.6] - 2026-05-20
### Breaking changes
- **Model forwarding**: `GPT2GIGA_PASS_MODEL` / `--proxy.pass-model` теперь по умолчанию `True`. Модель из клиентского запроса прокидывается в GigaChat для Chat Completions, Responses API и Embeddings; если нужен прежний режим с моделью из настроек прокси, явно задайте `GPT2GIGA_PASS_MODEL=False`.

### Добавлено
- **OpenAI Files API**: добавлены router-модули для `/files`, `/files/{file_id}` и `/files/{file_id}/content`, а также пример `examples/openai/files.py`; маршруты временно не монтируются в публичный OpenAI router до следующего релиза GigaChat SDK
- **OpenAI Batches API**: добавлены router-модули для `/batches` и `/batches/{batch_id}` вместе с примером `examples/openai/batches.py`; маршруты временно не монтируются в публичный OpenAI router до следующего релиза GigaChat SDK
- **Anthropic Message Batches API**: добавлены router-модули для `/v1/messages/batches`, `/v1/messages/batches/{message_batch_id}` и `/v1/messages/batches/{message_batch_id}/results`, а также пример `examples/anthropic/message_batches.py`; маршруты временно не монтируются в публичный Anthropic router до следующего релиза GigaChat SDK
- **Новые интеграции**: добавлены инструкции для Qwen Code и Xcode
- **CI и автоматизация**: добавлены `actionlint`, `CodeQL`, `dependency-review`, `docker-smoke`, `nightly-smoke`, `pr-labeler`, `release-drafter`, `stale-issues` и Dependabot-конфигурация
- **Reasoning / think tags**: добавлено извлечение `<think>...</think>` в reasoning/thinking content для OpenAI Chat Completions, OpenAI Responses и Anthropic Messages, включая streaming
- **Structured output mode**: добавлен режим `GPT2GIGA_STRUCTURED_OUTPUT_MODE` / `--proxy.structured-output-mode` с вариантами `function_call` и `native`; нативный режим прокидывает JSON Schema в `response_format` GigaChat SDK 0.2.1+
- **Anthropic structured output**: добавлена поддержка `output_config.format` и legacy `output_format` с `json_schema` для Anthropic Messages, streaming и Message Batches, включая новые runnable-примеры
- **Embeddings dimensions**: добавлена проверка параметра `dimensions` для известных embedding-моделей

### Изменено
- **Примеры**: OpenAI-примеры перенесены в `examples/openai/`, README и AGENTS выровнены под новую структуру
- **Примеры моделей**: runnable-примеры обновлены на `GigaChat-2-Max`, а пример embeddings теперь показывает `dimensions`, `float` и `base64`
- **OpenAPI**: схемы OpenAI и Anthropic вынесены в `gpt2giga/openapi_specs/`
- **LiteLLM router**: обработчик `/model/info` вынесен в отдельный пакет `gpt2giga/routers/litellm/`
- **Docker Compose**: структура compose-файлов выровнена под каталог `compose/` (`base.yaml`, `observability.yaml`, `nginx.yaml`, `observe-multiple.yaml`, `traefik.yaml`)
- **GitHub templates**: добавлены русскоязычные шаблоны issue и pull request
- **Model forwarding**: `GPT2GIGA_PASS_MODEL` теперь по умолчанию `True`; модель из запроса прокидывается в GigaChat для чата, Responses API и эмбеддингов, а `GPT2GIGA_EMBEDDINGS` используется как fallback для эмбеддингов
- **Зависимости**: обновлены `gigachat`, `python-dotenv`, `aiohttp`, `pillow`, `pytest` и `uv.lock` после Dependabot/security bump

### Исправлено
- **Path normalization**: исправлена нормализация путей для `/v1`, повторного `/v1/v1`, `files`, `batches`, `messages` и `model/info`
- **OpenAI payload mapping**: `extra_body` теперь корректно маппится в `additional_fields`
- **Batches**: исправлены `completion_window` и обработка дат для Python 3.10
- **Examples**: обновлены runnable-примеры OpenAI и Anthropic после реорганизации каталогов
- **Docker Compose docs**: команды запуска теперь явно передают `--env-file .env`, чтобы `.env` из корня корректно применялся при `-f compose/*.yaml`
- **Docker Hub tags**: теги `latest` и `<version>` теперь публикуются только из Python 3.13 job, а остальные matrix jobs публикуют только Python-специфичные теги
- **Docs/examples links**: исправлены устаревшие пути после переноса OpenAI-примеров в `examples/openai/`
- **Embeddings**: `encoding_format="base64"` теперь возвращает OpenAI-совместимые base64 float32 embeddings для прямого `/embeddings` и embeddings batches, а ответы нормализуются в OpenAI-совместимый envelope без GigaChat-специфичных полей
- **Embeddings input validation**: OpenAI-совместимая валидация теперь отклоняет пустой или смешанный `input`, неподдерживаемый `encoding_format`, некорректный `model` и token id inputs без модели, которую можно декодировать через `tiktoken`
- **Embeddings model routing**: `pass_model` теперь применяется к `/embeddings` и batch-запросам на `/v1/embeddings`
- **Model/top_p mapping**: исправлена передача `model` по умолчанию и предотвращена неявная установка `top_p=0`, когда клиент не передавал `temperature`
- **Unsupported Files/Batches routes**: временно отключены неподдерживаемые OpenAI Files/Batches и Anthropic Message Batches маршруты в default routers; они больше не попадают в OpenAPI-схему до появления поддержки в GigaChat SDK

## [0.1.5] - 2026-03-10
### Добавлено
- **Model info endpoint**: Добавлен `GET /model/info` для совместимости с автодополнением в Kilo Code и клиентами в стиле LiteLLM

### Изменено
- **GitHub Actions**: Workflow `ci.yaml`, `docker_image.yaml` и `publish-ghcr.yml` теперь запускаются только при изменениях релевантных файлов

### Исправлено
- **CI для Pull Request**: Тестовый workflow больше не запускается для draft PR

## [0.1.4.post1] - 2026-02-27
### Добавлено
- **Интеграция Cursor**: Добавлен `integrations/cursor/README.md` — инструкция по использованию GigaChat в Cursor через кастомную модель
- **Интеграция Codex**: Добавлен `integrations/codex/README.md` — настройка OpenAI Codex через `config.toml` с кастомным провайдером gpt2giga
- **Интеграция Claude Code**: Добавлен `integrations/claude-code/README.md` — настройка Claude Code через `ANTHROPIC_BASE_URL`
- **Документация AGENTS.md**: Обновлены все `AGENTS.md` файлы для соответствия актуальной структуре кодовой базы

### Изменено
- **Асинхронность**: Блокирующие операции ввода-вывода в обработчиках маршрутов перенесены в рабочие потоки через `anyio.to_thread.run_sync`:
  - `logs_router.py` — чтение файлов логов и HTML-шаблона
  - `api_router.py` — инициализация `tiktoken.encoding_for_model()`

## [0.1.4] - 2026-02-26

### Добавлено
- **Nginx**: Добавлен конфиг `gpt2giga.conf` и README для развёртывания nginx `integrations/nginx/`
- **Docker Compose**: Обновлён compose (#77) — mitmproxy в `compose/observability.yaml`, пароль для mitmproxy
- **Роутер логов**: Вынесен отдельный `logs_router.py`, разделение system router на два

### Изменено
- Обновлён `.env.example`
- Обновлён README для nginx

### Исправлено
- **Giga-auth**: Исправлено поведение giga-auth (#74)

## [0.1.3.post1] - 2026-02-20

### Добавлено
- **Traefik**: Добавлена интеграция Traefik
- **MITMProxy**: Добавлен mitmproxy в `compose/observability.yaml`
- **Reasoning toggle**: Добавлена переменная окружения `GPT2GIGA_ENABLE_REASONING`

### Изменено
- **Docker Compose профили**: Профиль `dev` установлен как профиль по умолчанию в `compose/base.yaml`

## [0.1.3] - 2026-02-17

### Добавлено
- **Режим DEV/PROD**: Добавлена поддержка режимов разработки и продакшена
- **Настраиваемый CORS**: Добавлена возможность конфигурации CORS через переменные окружения
- **Graceful shutdown**: Добавлено корректное завершение работы сервера
- **Gitleaks**: Добавлен gitleaks в pre-commit для проверки секретов
- **OpenAPI для count_tokens**: Добавлена OpenAPI документация для эндпоинта count_tokens
- **Профили в Docker**: Добавлены профили DEV и PROD в `compose/base.yaml`

### Изменено
- **Рефакторинг структуры**: Разделение больших файлов на модули:
  - `gpt2giga/common/` — общие утилиты (exceptions, json_schema, streaming, tools)
  - `gpt2giga/models/` — модели конфигурации и безопасности
  - `gpt2giga/protocol/attachment/` — обработка вложений
  - `gpt2giga/protocol/request/` — трансформация запросов
  - `gpt2giga/protocol/response/` — обработка ответов
- **Улучшено логирование**: Политика редактирования логов, отключено логирование полных payload'ов

### Исправлено
- **Безопасность CLI**: Исправлены проблемы с аргументами командной строки
- **Привязка портов**: Исправлены проблемы с привязкой портов и редиректами
- **SSRF защита**: Усилена защита от SSRF в обработке вложений
- **Аутентификация**: Переход на `secrets.compare_digest` для сравнения ключей
- **Лимиты вложений**: Добавлены лимиты для вложений
- **Название внутренних функций**: Исправлена ошибка с внутренней функцией `web_search`, которая могла ломать function_call

## [0.1.2.post1] - 2026-02-13

### Добавлено
- **OpenAPI документация**: Добавлена полная OpenAPI документация для всех эндпоинтов
- **Count tokens для Anthropic**: Добавлен эндпоинт `/v1/messages/count_tokens` для подсчёта токенов в формате Anthropic
- **Пример count_tokens**: Добавлен пример `examples/anthropic/count_tokens.py`
- **Версия при инициализации**: Отображение версии при запуске сервера

### Изменено
- **Path normalizer**: Улучшен нормализатор путей для responses и messages

### Исправлено
- **Ошибка 405**: Исправлена ошибка 405 при некоторых запросах
- **Безопасное чтение запросов**: Улучшена обработка чтения тела запроса

## [0.1.2] - 2026-02-11

### Добавлено
- **Anthropic Messages API**: Новый эндпоинт `POST /v1/messages` для совместимости с Anthropic Messages API
  - Поддержка стриминга (SSE) в формате Anthropic (`message_start`, `content_block_delta`, `message_stop` и др.)
  - Конвертация сообщений Anthropic (text, image, tool_use, tool_result) в формат GigaChat
  - Конвертация инструментов Anthropic (`input_schema`) в формат GigaChat functions
  - Поддержка `tool_choice` (auto, tool, none)
  - Поддержка системного промпта (`system`) в виде строки или массива контент-блоков
  - Маппинг `stop_reason` (end_turn, tool_use, max_tokens)
- **Extended Thinking (Reasoning)**: Поддержка параметра `thinking` из Anthropic API
  - Конвертация `thinking.budget_tokens` в `reasoning_effort` для GigaChat (high/medium/low)
  - Конвертация `reasoning_content` из ответа GigaChat в блок `thinking` формата Anthropic
  - Поддержка reasoning в стриминге (`thinking_delta`)
- **Примеры Anthropic API**: Добавлены примеры в `examples/anthropic/`:
  - `messages.py` — базовый запрос
  - `messages_stream.py` — стриминг
  - `system_prompt.py` — системный промпт
  - `multi_turn.py` — многоходовый диалог
  - `function_calling.py` — вызов функций (tool use)
  - `image_url.py` — изображение по URL
  - `base64_image.py` — изображение в base64
  - `reasoning.py` — extended thinking

## [0.1.1] - 2026-02-06

### Добавлено
- **Шаблоны GitHub**: Добавлены шаблоны для Pull Request и Issue (bug report) для улучшения процесса (#58)
- **Разрешение $ref в схемах**: Добавлена функция `_resolve_schema_refs` для обработки JSON Schema ссылок (#57)
- **Обработка пропущенных properties**: Реализована корректная обработка схем без поля `properties`

### Изменено
- **Рефакторинг request_mapper.py**: Логика разделена на отдельные модули для лучшей поддерживаемости:
  - `content_utils.py` — утилиты для работы с контентом
  - `message_utils.py` — утилиты для работы с сообщениями
  - `schema_utils.py` — утилиты для работы со схемами
- **Расширено тестовое покрытие**: Добавлены тесты для стриминга и конвертации инструментов

### Исправлено
- **Стриминг Responses API**: Исправлена потоковая передача ответов в Responses API (#60)
- **Function calling в стриминге**: Исправлена обработка вызовов функций при потоковой передаче в Responses API

## [0.1.0b2] - 2025-01-21

### Добавлено
- Поддержка Python 3.14
- Обновлена библиотека tiktoken

### Изменено
- Рефакторинг тестов
- Обновлены зависимости библиотек

### Исправлено
- Создание нового экземпляра GigaChat при pass_token=True

## [0.1.0b] - 2025-12-26

### Добавлено
- **Pydantic v2**: Полный переход проекта на Pydantic v2.
- **Управление зависимостями**: Миграция проекта и CI на использование `uv`.
- **Конфигурация**: Добавлена библиотека `pydantic-settings` для удобного управления настройками через CLI и переменные окружения.
- **Обработка ошибок**: Реализован маппинг ошибок для корректной обработки исключений.
- **Структурированный вывод**: Добавлена поддержка структурированного вывода (structured output) в виде функции.
- **Интеграция GigaChat**: Добавлена интеграция с пакетом `gigachat`.
- **Тесты**: Значительно расширено покрытие тестами.

### Изменено
- **Рефакторинг протокола**: Логика `protocol.py` разделена на модули `request_mapper.py`, `response_mapper.py` и `attachments.py`.
- **Разделение логики**: Полностью разделена логика `chat_completion` и `responses`.
- **Примеры**: Обновлены порты в примерах использования.

### Исправлено
- **Стриминг**: Исправлены проблемы с потоковой передачей ответов.
- **API ответов**: Устранены ошибки в API ответов.
- **CI/CD**: Исправлена ошибка SSL в GitHub Actions.
- **Безопасность**: Устранены уязвимости в зависимостях.

## [0.0.15.post1] - 2025-12-22

### Добавлено
- Авторизация по API-ключу с поддержкой различных способов передачи (query параметр, заголовок x-api-key, Bearer token)
- Логирование с использованием библиотеки loguru
- Системные эндпоинты для мониторинга (/health, /ping, /logs)
- HTML-страница для просмотра логов в реальном времени
- Поддержка парсинга файлов
- Workflow для публикации в GHCR
- Workflow для публикации в PyPI

### Изменено
- Миграция на FastAPI
- Переход на loguru для логирования

### Исправлено
- Исправлена обработка исключений при декодировании байтов
- Исправлена ошибка валидации для роли developer
- Исправлены версии Python в workflows

## [0.0.14] - 2025-10-28

### Добавлено
- Поддержка mTLS аутентификации
- Docker Compose конфигурация

### Изменено
- Обновлена документация README

## [0.0.13] - 2025-09-19

### Добавлено
- Базовая функциональность прокси-сервера
- Поддержка потоковой генерации (streaming)
- Поддержка эмбеддингов
- Поддержка функций (function calling)
- Поддержка структурированного вывода

---

[Unreleased]: https://github.com/ai-forever/gpt2giga/compare/v0.2.0a1...HEAD
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
