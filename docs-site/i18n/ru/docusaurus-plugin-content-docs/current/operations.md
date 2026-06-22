# Операции

Документ описывает журналы выполнения, журналы трафика, метрики, наблюдаемость и admin/debug-эндпоинты.

## Системные эндпоинты

Всегда подключены:

- `GET /health`
- `GET | POST /ping`

Только в `DEV`:

- `GET /logs/{last_n_lines}`
- `GET /logs/stream`
- `GET /logs/html`

Эндпоинты `/logs*` отключены в `PROD`.

## Журналы выполнения

Журналы выполнения — это журналы процесса. Они пишутся в stdout и настроенный файл журнала.

Частые настройки:

```dotenv
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_FILENAME=gpt2giga.log
GPT2GIGA_LOG_MAX_SIZE=10485760
```

Не используйте `DEBUG` в production. Отладочные логи могут содержать чувствительный операционный контекст даже при включённом маскировании.

## Метрики

Метрики, совместимые с Prometheus, выключены по умолчанию:

```dotenv
GPT2GIGA_METRICS_ENABLED=False
GPT2GIGA_METRICS_PATH=/metrics
```

Локальное включение:

```dotenv
GPT2GIGA_METRICS_ENABLED=True
GPT2GIGA_METRICS_PATH=/metrics
```

Если включена аутентификация по API-ключу, передавайте `Authorization: Bearer <GPT2GIGA_API_KEY>` или `x-api-key`.

Метрики не содержат содержимого промптов и ответов, API-ключей, идентификаторов запросов и трейсов или необработанных полезных нагрузок. Метки ограничены конечным набором операционных полей: protocol, route, method, status, lifecycle, provider, model.

Базовые серии:

- `gpt2giga_requests_total`
- `gpt2giga_request_duration_seconds`
- `gpt2giga_upstream_duration_seconds`
- `gpt2giga_upstream_errors_total`
- `gpt2giga_tokens_input_total`
- `gpt2giga_tokens_output_total`
- `gpt2giga_stream_disconnects_total`
- `gpt2giga_traffic_log_dropped_total`

## Журналы трафика

Журналы трафика — это структурированные записи трафика запросов и ответов. По умолчанию выключены:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=False
GPT2GIGA_TRAFFIC_LOG_SINK=noop
```

Локальная JSONL-проверка:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=jsonl
GPT2GIGA_TRAFFIC_LOG_JSONL_PATH=traffic_logs.jsonl
```

Надёжный бэкенд в Postgres:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Postgres плюс зеркало OpenSearch:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
GPT2GIGA_OPENSEARCH_URL=http://localhost:9200
```

Захват содержимого включается по запросу и проходит маскирование:

```dotenv
GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT=False
GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE=True
```

Держите захват содержимого выключенным, пока не утверждены политики хранения, срока хранения, маскирования и доступа.

## Admin API журналов трафика

Admin-эндпоинты выключены по умолчанию:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=False
```

Включение с отдельным admin-ключом:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Варианты заголовков авторизации:

- `x-admin-api-key: <secret>`
- `Authorization: Bearer <secret>`

Эндпоинты:

- `GET /_admin/logs`
- `GET /_admin/logs/{id}`
- `GET /_admin/logs/{id}/request`
- `GET /_admin/logs/{id}/response`
- `GET /_admin/logs/tail`
- `GET /_admin/logs/export.ndjson`
- `GET /_admin/logs/export.csv`
- `POST /_admin/logs/retention/purge`
- `POST /_admin/logs/{id}/replay`
- `POST /_admin/logs/{id}/redact`

Повтор (replay) требует:

```dotenv
GPT2GIGA_REPLAY_ENABLED=True
```

## API отладочной трансляции

Эндпоинты отладочной трансляции предназначены для локальной отладки и защищённых admin-сценариев:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Основной эндпоинт:

- `POST /_debug/translate`

Короткие эндпоинты:

- `POST /_debug/translate/openai-to-normalized`
- `POST /_debug/translate/anthropic-to-normalized`
- `POST /_debug/translate/normalized-to-gigachat`
- `POST /_debug/translate/gigachat-to-openai`

Поддерживаемые семейства полезных нагрузок: `openai`, `anthropic`, `normalized`, `gigachat`, в зависимости от направления.

Как эти форматы проходят через внутренний нормализованный контракт, описано в
[Нормализованных сообщениях](./architecture/normalized-messages.md).

## Phoenix / OpenTelemetry

Наблюдаемость через Phoenix выключена по умолчанию:

```dotenv
GPT2GIGA_OBSERVABILITY_ENABLED=False
GPT2GIGA_OBSERVABILITY_BACKEND=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=gpt2giga
```

Включайте после установки необязательного пакета `phoenix` или через профиль Compose для Phoenix.

Атрибуты полезной нагрузки LLM требуют двойного включения:

```dotenv
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=True
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=True
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

Журналы трафика и спаны Phoenix связываются через идентификаторы шлюза:
`request_id`, `trace_id`, protocol, route, метаданные модели. Для LLM-маршрутов
Phoenix получает один корневой спан на формат: `OpenAI-Completions` для Chat
Completions, `OpenAI-Responses` для Responses API, `Anthropic-Messages` для
Anthropic Messages, `Gemini-Content` для Gemini GenerateContent и `Embeddings`
для OpenAI Embeddings. Вехи потока (streaming milestones) прикрепляются к
соответствующему корневому спану как события спана. Для не-LLM-маршрутов используется
один спан жизненного цикла `gpt2giga.request`.

Для фильтрации и группировки по совместимому формату API спаны модели получают
атрибут `gpt2giga.api_format`: `chat_completions`, `responses`, `messages`,
`generate_content` или `embeddings`. Responses с состоянием дополнительно получают
`session.id` и
`conversation.id` из GigaChat `thread_id`; если идентификатор потока вышестоящего сервиса ещё не
доступен, используется `previous_response_id` без префикса `resp_`.

Время начала спана OpenTelemetry берётся из `RequestContext.started_at` шлюза,
поэтому `Latency` в Phoenix отражает полное время запроса/потока, а не только
время финальной отправки спана наблюдаемости. То же значение дополнительно
пишется в атрибут `latency_ms`.

Спаны LLM выставляют явный статус OpenTelemetry (`OK` или `ERROR`) и дублируют
его в безопасных атрибутах `status` / `llm.response.status`. Использование токенов
пишется как поля OpenInference `llm.token_count.*` и как псевдонимы шлюза
`input_tokens`, `output_tokens`, `total_tokens`.

Видимость инструментов по умолчанию безопасная: Phoenix получает `llm.tools.count`,
`llm.tools.names`, `llm.tool_calls.count`, `llm.tool_calls.names`, а также
события `llm.tool_call` без аргументов. Аргументы вызовов инструментов и полные схемы
инструментов пишутся только при двойном включении:
`GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True` и
`GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=True`; перед отправкой они проходят
маскирование.

Спаны Phoenix также получают безопасную классификацию вызывающей стороны из входящих
заголовков:

- `caller.name`: например `swagger-ui`, `redoc-ui`, `openai-python`,
  `anthropic-compatible`, `claude-code`, `codex`, `qwen-code`, `browser`;
- `caller.category`: `ui`, `sdk`, `agent`, `browser`, `http_client` или
  `unknown`;
- `caller.client_family`: `openai` или `anthropic`, когда это можно вывести из
  заголовков SDK или `User-Agent`;
- `caller.sdk`, `caller.agent`, `caller.ui`: более точные подтипы, когда они
  известны.

Подробный объект дублируется в `annotations.caller`, чтобы в Phoenix можно было
открыть структурированный контекст без включения захвата полезной нагрузки. Для Swagger UI
источник определяется по `Referer: .../docs`, для ReDoc — по `.../redoc`; необработанное
содержимое промптов и ответов в annotations не добавляется.

Термины и проектные ограничения описаны в [Логировании и наблюдаемости](./architecture/logging-and-observability.md).
Чек-лист для добавления новых провайдеров/протоколов и связанных изменений
наблюдаемости: [Добавление провайдера или протокола](./architecture/how-to-add-provider.md).
