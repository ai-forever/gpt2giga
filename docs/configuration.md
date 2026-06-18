# Конфигурация

`gpt2giga` читает две группы настроек:

- настройки прокси с префиксом `GPT2GIGA_`;
- настройки GigaChat SDK с префиксом `GIGACHAT_`.

Секреты храните в `.env`, переменных окружения или secrets manager. Не передавайте credentials через CLI flags в production: аргументы процесса могут быть видны через `ps`.

## Источники настроек

CLI принимает явный env-файл:

```sh
gpt2giga --env-path .env
```

Можно передавать structured CLI flags:

```sh
gpt2giga \
  --proxy.host 127.0.0.1 \
  --proxy.port 8090 \
  --proxy.pass-model true \
  --gigachat.model GigaChat-2-Max
```

Полный CLI reference:

```sh
gpt2giga --help
```

Env template для копирования: [.env.example](https://github.com/ai-forever/gpt2giga/blob/main/.env.example).

## Как читать этот документ

`.env.example` намеренно остаётся copy-paste template: там удобно видеть все
ключи рядом, но не всегда удобно понимать tradeoff. Этот документ является
справочником по смыслу настроек и безопасным сочетаниям.

Практическое правило:

- для локального запуска начните с минимального блока `GPT2GIGA_*` и `GIGACHAT_*`;
- для production сначала настройте security, потом backend mode, потом optional
  traffic logs, metrics и observability;
- experimental/admin/debug flags включайте только когда понимаете, кто имеет к
  ним доступ и где будут храниться payloads.

## Быстрые профили

Минимальный локальный `.env`:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<local-proxy-api-key>"

GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

Минимум для production:

```dotenv
GPT2GIGA_MODE=PROD
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong-random-secret>"
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://your-app.example.com"]'
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_REDACT_SENSITIVE=True

GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

Явный выбор GigaChat v2 на стороне клиента:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

При таком env root routes без `/v1` или `/v2` остаются на v1, а клиент может
выбрать v2 через `base_url="http://localhost:8090/v2"`. `/v1` всегда
принудительно выбирает GigaChat v1 contract, `/v2` — GigaChat v2 contract.
Если хотите, чтобы root routes тоже использовали v2, задайте
`GPT2GIGA_GIGACHAT_API_MODE=v2`.

## Формат значений

Pydantic Settings читает env names без учёта регистра, но в документации и
examples используется верхний регистр.

Списки и словари задавайте JSON-строками:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://app.example.com"]'
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS='["customer_token"]'
```

`GPT2GIGA_TRAFFIC_LOG_SINKS` принимает JSON-массив или comma-separated list:

```dotenv
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
```

CLI flags удобны для несекретных локальных overrides. Для секретов используйте
`.env`, environment variables или secrets manager, потому что CLI arguments
могут быть видны другим процессам.

## Основные proxy settings

| Переменная | Default | Назначение |
|---|---:|---|
| `GPT2GIGA_MODE` | `DEV` | `DEV` или `PROD`. `PROD` отключает `/docs`, `/redoc`, `/openapi.json` и `/logs*`. |
| `GPT2GIGA_HOST` | `localhost` | Host локального сервера. |
| `GPT2GIGA_PORT` | `8090` | Port локального сервера. |
| `GPT2GIGA_USE_HTTPS` | `False` | Встроенный HTTPS. Для production обычно лучше TLS на reverse proxy. |
| `GPT2GIGA_HTTPS_KEY_FILE` / `GPT2GIGA_HTTPS_CERT_FILE` | empty | Local key/cert files для встроенного HTTPS. |
| `GPT2GIGA_ENABLE_API_KEY_AUTH` | `False` | Требовать proxy API-key auth для публичных API routes. В `PROD` обязательно. |
| `GPT2GIGA_API_KEY` | empty | Proxy API key. Для общих окружений используйте сильное случайное значение. |
| `GPT2GIGA_PASS_MODEL` | `True` | Передавать `model` из запроса в GigaChat. Поставьте `False`, чтобы всегда использовать настроенную GigaChat model. |
| `GPT2GIGA_PASS_TOKEN` | `False` | Разбирать client `Authorization` как GigaChat credentials для per-request upstream auth. |
| `GPT2GIGA_EMBEDDINGS` | `EmbeddingsGigaR` | Default embeddings model, если model из запроса не используется. |
| `GPT2GIGA_MAX_REQUEST_BODY_BYTES` | `10485760` | Максимальный размер HTTP request body. |
| `GPT2GIGA_LOG_LEVEL` | `INFO` | Runtime log level. В production избегайте `DEBUG`. |
| `GPT2GIGA_LOG_FILENAME` | `gpt2giga.log` | Файл runtime logs. |
| `GPT2GIGA_LOG_MAX_SIZE` | `10485760` | Максимальный размер log file перед rotation. |
| `GPT2GIGA_LOG_REDACT_SENSITIVE` | `True` | Маскировать секреты в runtime logs. |

## Auth и security

Proxy API key защищает публичные API routes (`/chat/completions`, `/responses`,
`/messages`, `/models`, `/embeddings`, `/model/info`, versioned variants).
Клиенты могут передавать ключ двумя способами:

```http
Authorization: Bearer <GPT2GIGA_API_KEY>
x-api-key: <GPT2GIGA_API_KEY>
```

`MODE=PROD` требует configured API key и отключает interactive docs/log routes.
Admin/debug endpoints используют отдельный `GPT2GIGA_ADMIN_API_KEY`.

`GPT2GIGA_PASS_TOKEN=True` нужен только для сценариев, где каждый клиент должен
передавать свои GigaChat credentials. Поддерживаются такие префиксы в
`Authorization`:

- `giga-cred-<credentials>:<scope>` для GigaChat authorization key credentials;
- `giga-auth-<access_token>` для готового access token;
- `giga-user-<user>:<password>` для user/password auth.

Для обычного deployment проще и безопаснее держать upstream credentials на
сервере через `GIGACHAT_*`.

## GigaChat settings

Частые upstream settings:

| Переменная | Default | Назначение |
|---|---:|---|
| `GIGACHAT_CREDENTIALS` | empty | Credentials authorization key. |
| `GIGACHAT_SCOPE` | SDK default | GigaChat API scope, например `GIGACHAT_API_PERS`. |
| `GIGACHAT_USER` / `GIGACHAT_PASSWORD` | empty | Альтернативная user/password auth. |
| `GIGACHAT_ACCESS_TOKEN` | empty | Альтернативная auth через готовый access token. |
| `GIGACHAT_MODEL` | SDK default | Default model, если proxy не передаёт client model или `GPT2GIGA_PASS_MODEL=False`. |
| `GIGACHAT_PROFANITY_CHECK` | SDK default | Upstream profanity check flag. |
| `GIGACHAT_VERIFY_SSL_CERTS` | SDK default | В production держите `True`. |
| `GIGACHAT_TIMEOUT` | SDK default | Upstream request timeout. |
| `GIGACHAT_MAX_CONNECTIONS` | SDK default | Global SDK/HTTP connection cap. |
| `GIGACHAT_MAX_RETRIES` | SDK default | SDK retry count для временных upstream errors. |

GigaChat также поддерживает TLS client certificate settings: `GIGACHAT_CA_BUNDLE_FILE`, `GIGACHAT_CERT_FILE`, `GIGACHAT_KEY_FILE`, `GIGACHAT_KEY_FILE_PASSWORD`.

`GPT2GIGA_PASS_MODEL=False` часто полезен для OpenAI-compatible clients,
которые отправляют model name не из GigaChat. Тогда upstream model берётся из
`GIGACHAT_MODEL`.

## Reasoning и structured output

Reasoning:

```dotenv
GPT2GIGA_ENABLE_REASONING=False
GPT2GIGA_DISABLE_REASONING=False
```

- `GPT2GIGA_ENABLE_REASONING=True` добавляет `reasoning_effort="high"`, если клиент не передал явную reasoning-настройку.
- `GPT2GIGA_DISABLE_REASONING=True` удаляет `reasoning` и `reasoning_effort`, включая явные client fields и `extra_body` passthrough.

Structured output:

```dotenv
GPT2GIGA_STRUCTURED_OUTPUT_MODE=function_call
```

Значения:

- `function_call`: compatibility fallback через function calling;
- `native`: передаёт JSON Schema через GigaChat `response_format`, если model/API это поддерживает.

Оба режима рассчитаны на schema-based structured output. OpenAI
`response_format.type=json_object` и Gemini `responseMimeType=application/json`
без `responseJsonSchema` / `responseSchema` не проксируются в GigaChat, потому
что upstream не поддерживает отдельный schema-less JSON mode.

## Backend API mode

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

| `GPT2GIGA_GIGACHAT_API_MODE` | `/chat/completions` backend | `/responses` backend |
|---|---|---|
| `v1` | `v1` | `v1` |
| `v2` | `v2` | `v2` |

Root URLs (`/chat/completions`, `/responses`, `/messages`) без `/v1` или `/v2`
используют этот flag.
Versioned prefixes являются явным per-request override:

- `/v1/chat/completions`, `/v1/responses`, `/v1/messages` используют GigaChat v1 contract;
- `/v2/chat/completions`, `/v2/responses`, `/v2/messages` используют GigaChat v2 contract.

## Fusion / multi-model deliberation

GigaFusion - локальный режим, в котором один client request запускает несколько
внутренних GigaChat panel calls и один judge/finalizer call. Он выключен по
умолчанию и не обращается к OpenRouter или другим внешним upstream.

Минимальное включение:

```dotenv
GPT2GIGA_FUSION_ENABLED=True
GPT2GIGA_FUSION_DEFAULT_PRESET=code-high
```

Частые overrides:

```dotenv
GPT2GIGA_FUSION_ALIASES='["gpt2giga/fusion","gpt2giga/fusion-code","GigaChat-Fusion-Code"]'
GPT2GIGA_FUSION_STREAMING_MODE=buffered
GPT2GIGA_FUSION_MAX_PANEL_MODELS=4
GPT2GIGA_FUSION_MAX_PANEL_CONCURRENCY=3
GPT2GIGA_FUSION_MAX_CONCURRENT_REQUESTS=4
GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST=5
GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS=0
GPT2GIGA_FUSION_EXPOSE_ANALYSIS_METADATA=False
GPT2GIGA_FUSION_EXPOSE_PANEL_RESPONSES=False
```

Используйте `GPT2GIGA_FUSION_PRESETS` для JSON-карты custom presets с
`analysis_models`, `judge_model`, `panel_roles`, generation limits,
`min_successful_panels`, `timeout_seconds` и `tools_mode`. `final_model`
зарезервирован для будущего strict pipeline и должен быть `null`; текущий
runtime поддерживает только compact `panel -> judge/finalizer`.

Подробно: [GigaFusion](fusion.md).

## Normalized layer flags

Экспериментальные flags, которые по умолчанию сохраняют legacy behavior:

```dotenv
GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER=False
GPT2GIGA_NORMALIZATION_MODE=off
GPT2GIGA_LEGACY_CHAT_FALLBACK=True
```

- `off`: только legacy path;
- `shadow`: строит normalized diagnostics рядом с legacy OpenAI Chat handling без изменения client responses;
- `on`: переводит OpenAI Chat на normalized path, с legacy fallback до старта ответа, если fallback включён.

Подробное описание моделей и текущих execution paths: [Normalized messages architecture](./architecture/normalized-messages.md).

## Conversation stitching

Conversation stitching - opt-in in-memory state для stateless chat-like
клиентов, которые передают стабильный conversation identifier. По умолчанию
выключено и не влияет на совместимость.
Поддержаны OpenAI Chat Completions, Anthropic Messages и Gemini GenerateContent.
Conversation identifier берётся из `conversation`, `metadata.conversation_id`,
`x-gpt2giga-conversation-id` или, если включено, `x-session-id`.

```dotenv
GPT2GIGA_CONVERSATION_STITCHING_ENABLED=False
GPT2GIGA_CONVERSATION_TTL_SECONDS=3600
GPT2GIGA_CONVERSATION_MAX_MESSAGES=40
GPT2GIGA_CONVERSATION_USE_SESSION_ID=False
GPT2GIGA_CONVERSATION_ON_DIVERGENCE=client_wins
```

| Переменная | Default | Назначение |
|---|---:|---|
| `GPT2GIGA_CONVERSATION_STITCHING_ENABLED` | `False` | Включить локальное stitching состояние. |
| `GPT2GIGA_CONVERSATION_TTL_SECONDS` | `3600` | Сколько хранить idle conversation state. |
| `GPT2GIGA_CONVERSATION_MAX_MESSAGES` | `40` | Максимум retained messages, отправляемых upstream. |
| `GPT2GIGA_CONVERSATION_USE_SESSION_ID` | `False` | Разрешить `x-session-id` как conversation key, если явного key нет. |
| `GPT2GIGA_CONVERSATION_ON_DIVERGENCE` | `client_wins` | `client_wins` заменяет state после успеха, `fork` создаёт revision-suffixed branch. |

State хранится в памяти процесса. При нескольких workers/pods используйте sticky
routing или не включайте stitching.

## Per-model concurrency

`GIGACHAT_MAX_CONNECTIONS` — global SDK/HTTP cap. Прокси также умеет ограничивать concurrent upstream model calls по effective model:

```dotenv
GIGACHAT_MAX_CONNECTIONS=7
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=30
```

Семантика:

- пустой `GPT2GIGA_MODEL_MAX_CONNECTIONS` и пустой default выключают limiter;
- explicit model limit важнее default;
- `GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=0` сразу возвращает локальный `429`;
- streaming calls удерживают slot до завершения stream или disconnect клиента;
- limits работают внутри одного процесса, поэтому workers/pods умножают effective capacity.

## CORS

Defaults удобны для локальной разработки:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["*"]'
GPT2GIGA_CORS_ALLOW_METHODS='["*"]'
GPT2GIGA_CORS_ALLOW_HEADERS='["*"]'
```

В production задайте конкретные origins и headers:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://your-app.example.com"]'
GPT2GIGA_CORS_ALLOW_METHODS='["GET","POST","OPTIONS"]'
GPT2GIGA_CORS_ALLOW_HEADERS='["authorization","content-type","x-api-key"]'
```

## HTTP body и attachments limits

Глобальный лимит body проверяется до JSON parsing:

```dotenv
GPT2GIGA_MAX_REQUEST_BODY_BYTES=10485760
```

Дополнительные лимиты защищают attachment processing:

| Переменная | Назначение |
|---|---|
| `GPT2GIGA_MAX_AUDIO_FILE_SIZE_BYTES` | Максимальный размер одного аудиофайла. |
| `GPT2GIGA_MAX_IMAGE_FILE_SIZE_BYTES` | Максимальный размер одного изображения. |
| `GPT2GIGA_MAX_TEXT_FILE_SIZE_BYTES` | Максимальный размер одного текстового файла. |
| `GPT2GIGA_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES` | Суммарный лимит аудио и изображений в одном request. |

Уменьшайте эти значения, если proxy доступен широкому кругу клиентов или стоит
перед дорогим storage/upload path.

## Runtime logs и `/logs*`

Runtime logs пишутся в stdout и log file:

```dotenv
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_FILENAME=gpt2giga.log
GPT2GIGA_LOG_MAX_SIZE=10485760
GPT2GIGA_LOG_REDACT_SENSITIVE=True
```

`/logs/{last_n_lines}`, `/logs/stream` и `/logs/html` доступны только в `DEV`.
В `PROD` они не монтируются. Если API-key auth включена, `/logs*` также требует
proxy key.

IP allowlist для `/logs*`:

```dotenv
GPT2GIGA_LOGS_IP_ALLOWLIST='["10.0.0.1"]'
```

Не используйте `GPT2GIGA_LOG_LEVEL=DEBUG` в production: debug output может
содержать operational context, который не должен попадать в общие логи.

## Traffic logs

Traffic logs - structured request/response records. Они выключены по умолчанию:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=False
GPT2GIGA_TRAFFIC_LOG_SINK=noop
```

Local JSONL:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=jsonl
GPT2GIGA_TRAFFIC_LOG_JSONL_PATH=traffic_logs.jsonl
```

Postgres:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Postgres plus OpenSearch mirror:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
GPT2GIGA_OPENSEARCH_URL=http://localhost:9200
```

| Переменная | Default | Назначение |
|---|---:|---|
| `GPT2GIGA_TRAFFIC_LOG_SINK` | `noop` | Single sink: `noop`, `jsonl`, `postgres`, `opensearch`. |
| `GPT2GIGA_TRAFFIC_LOG_SINKS` | `[]` | Ordered mirror sinks, например `postgres,opensearch`. Если пусто, используется single sink. |
| `GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT` | `False` | Сохранять request/response bodies после redaction. |
| `GPT2GIGA_TRAFFIC_LOG_QUEUE_SIZE` | `10000` | Максимум queued events. |
| `GPT2GIGA_TRAFFIC_LOG_BATCH_SIZE` | `500` | Максимум events в storage batch. |
| `GPT2GIGA_TRAFFIC_LOG_FLUSH_INTERVAL_MS` | `2000` | Best-effort flush interval. |
| `GPT2GIGA_TRAFFIC_LOG_DROP_ON_BACKPRESSURE` | `True` | Drop events instead of blocking request path when queue is full. |
| `GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE` | `True` | Redact sensitive fields before storage. |
| `GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS` | `[]` | Дополнительные case-insensitive keys для redaction. |
| `GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS` | `30` | Retention для Postgres traffic logs. |
| `GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS` | `3600` | Интервал best-effort retention purge. |

Content capture включайте только после решения вопросов storage encryption,
retention, redaction и доступа к admin endpoints.

## Postgres и OpenSearch helper variables

Compose profiles используют несколько helper variables, которые не являются
непосредственными полями `ProxySettings`, но нужны для storage services:

| Переменная | Назначение |
|---|---|
| `GPT2GIGA_POSTGRES_DB` | Database name для `deploy/postgres.yaml`. |
| `GPT2GIGA_POSTGRES_USER` | Postgres user для compose service. |
| `GPT2GIGA_POSTGRES_PASSWORD` | Postgres password. Задавайте сильное значение. |
| `GPT2GIGA_POSTGRES_PORT` | Host port для локального Postgres. |
| `GPT2GIGA_OPENSEARCH_PORT` | Host port для локального OpenSearch. |

OpenSearch runtime settings:

| Переменная | Default | Назначение |
|---|---:|---|
| `GPT2GIGA_OPENSEARCH_URL` | `http://localhost:9200` | OpenSearch endpoint. |
| `GPT2GIGA_OPENSEARCH_USERNAME` / `GPT2GIGA_OPENSEARCH_PASSWORD` | empty | Optional auth. |
| `GPT2GIGA_OPENSEARCH_INDEX` | `gpt2giga-traffic` | Index или data stream name. |
| `GPT2GIGA_OPENSEARCH_DATA_STREAM` | `True` | Использовать data stream bulk create semantics. |
| `GPT2GIGA_OPENSEARCH_BULK_SIZE` | `500` | Bulk batch size. |
| `GPT2GIGA_OPENSEARCH_FLUSH_INTERVAL_MS` | `2000` | Best-effort flush interval. |

## Metrics

Prometheus-compatible endpoint выключен по умолчанию:

```dotenv
GPT2GIGA_METRICS_ENABLED=False
GPT2GIGA_METRICS_PATH=/metrics
```

Когда включён, endpoint монтируется на `GPT2GIGA_METRICS_PATH`. Если proxy
API-key auth включена, metrics endpoint тоже требует proxy key.

Metrics labels ограничены bounded operational fields и не включают prompt,
response content, API keys, request ids или trace ids.

## Observability / Phoenix

OpenTelemetry/OpenInference observability выключена по умолчанию:

```dotenv
GPT2GIGA_OBSERVABILITY_ENABLED=False
GPT2GIGA_OBSERVABILITY_BACKEND=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=gpt2giga
PHOENIX_API_KEY=
```

Capture flags независимы и выключены по умолчанию:

```dotenv
GPT2GIGA_OBSERVABILITY_SAMPLE_RATE=1.0
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=False
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=False
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=False
GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH=8000
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

Payload content попадает в spans только при явном включении соответствующих
capture flags. Для production обычно оставляют capture выключенным или включают
его на короткое время под контролем доступа.

Compose helper variables для Phoenix и mitmproxy:

| Переменная | Назначение |
|---|---|
| `PHOENIX_PORT` | Host port для Phoenix UI. |
| `PHOENIX_GRPC_PORT` | Host port для OTLP gRPC collector. |
| `MITMPROXY_PORT` | Host port для mitmproxy proxy listener в compose overlay. |
| `MITMPROXY_WEB_PORT` | Host port для mitmproxy web UI в compose overlay. |

Подробности по emitted spans и metric names: [Operations](./operations.md).

## Admin и debug endpoints

Admin API выключен по умолчанию:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=False
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Когда включён, `/_admin/logs*` endpoints используют `GPT2GIGA_ADMIN_API_KEY`, а
не public proxy key. Для replay нужен отдельный opt-in:

```dotenv
GPT2GIGA_REPLAY_ENABLED=True
```

Debug translation endpoints включаются отдельно:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Эти endpoints предназначены для локальной отладки и protected admin workflows.
Не включайте их публично без reverse proxy controls и отдельного admin key.

`GPT2GIGA_UI_ENABLED` зарезервирован для будущего built-in UI. Сейчас не
используйте его как security control.
