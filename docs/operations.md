# Операции

Документ описывает runtime logs, traffic logs, metrics, observability и admin/debug endpoints.

## System endpoints

Всегда смонтированы:

- `GET /health`
- `GET | POST /ping`

Только в `DEV`:

- `GET /logs/{last_n_lines}`
- `GET /logs/stream`
- `GET /logs/html`

`/logs*` endpoints отключены в `PROD`.

## Runtime Logs

Runtime logs — это process logs. Они пишутся в stdout и настроенный log file.

Частые настройки:

```dotenv
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_FILENAME=gpt2giga.log
GPT2GIGA_LOG_MAX_SIZE=10485760
```

Не используйте `DEBUG` в production. Debug logs могут содержать чувствительный operational context даже при включённой redaction.

## Metrics

Prometheus-compatible metrics выключены по умолчанию:

```dotenv
GPT2GIGA_METRICS_ENABLED=False
GPT2GIGA_METRICS_PATH=/metrics
```

Локальное включение:

```dotenv
GPT2GIGA_METRICS_ENABLED=True
GPT2GIGA_METRICS_PATH=/metrics
```

Если API-key auth включена, передавайте `Authorization: Bearer <GPT2GIGA_API_KEY>` или `x-api-key`.

Метрики не содержат prompt/response content, API keys, request ids, trace ids или raw payloads. Labels ограничены bounded operational fields: protocol, route, method, status, lifecycle, provider, model.

Базовые series:

- `gpt2giga_requests_total`
- `gpt2giga_request_duration_seconds`
- `gpt2giga_upstream_duration_seconds`
- `gpt2giga_upstream_errors_total`
- `gpt2giga_tokens_input_total`
- `gpt2giga_tokens_output_total`
- `gpt2giga_stream_disconnects_total`
- `gpt2giga_traffic_log_dropped_total`

## Traffic Logs

Traffic logs — это structured records для request/response traffic. По умолчанию выключены:

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

Durable backend в Postgres:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Postgres плюс OpenSearch mirror:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
GPT2GIGA_OPENSEARCH_URL=http://localhost:9200
```

Content capture — opt-in и проходит redaction:

```dotenv
GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT=False
GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE=True
```

Держите content capture выключенным, пока не утверждены storage, retention, redaction и access policies.

## Admin Traffic Logs API

Admin endpoints выключены по умолчанию:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=False
```

Включение с отдельным admin key:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Варианты auth headers:

- `x-admin-api-key: <secret>`
- `Authorization: Bearer <secret>`

Endpoints:

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

Replay требует:

```dotenv
GPT2GIGA_REPLAY_ENABLED=True
```

## Debug Translate API

Debug translation endpoints предназначены для локальной отладки и protected admin workflows:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Основной endpoint:

- `POST /_debug/translate`

Короткие endpoints:

- `POST /_debug/translate/openai-to-normalized`
- `POST /_debug/translate/anthropic-to-normalized`
- `POST /_debug/translate/normalized-to-gigachat`
- `POST /_debug/translate/gigachat-to-openai`

Поддерживаемые payload families: `openai`, `anthropic`, `normalized`, `gigachat`, в зависимости от направления.

## Phoenix / OpenTelemetry

Phoenix observability выключена по умолчанию:

```dotenv
GPT2GIGA_OBSERVABILITY_ENABLED=False
GPT2GIGA_OBSERVABILITY_BACKEND=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=gpt2giga
```

Включайте после установки optional extra `phoenix` или через Phoenix compose profile.

LLM payload attributes требуют двойной opt-in:

```dotenv
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=True
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=True
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

Traffic logs и Phoenix spans связываются через gateway identifiers:
`request_id`, `trace_id`, protocol, route, model metadata. Для LLM routes
Phoenix получает один root span `llm.chat.completion` для Chat Completions,
Responses API и Anthropic Messages; streaming milestones прикрепляются к нему
как span events. Для non-LLM routes используется один lifecycle span
`gpt2giga.request`.

OpenTelemetry span start time берётся из gateway `RequestContext.started_at`,
поэтому Phoenix `Latency` отражает полное время request/stream, а не только
время финальной отправки observability span. То же значение дополнительно
пишется в атрибут `latency_ms`.

LLM spans выставляют явный OpenTelemetry status (`OK` или `ERROR`) и дублируют
его в безопасных атрибутах `status` / `llm.response.status`. Token usage
пишется как OpenInference-поля `llm.token_count.*` и как gateway aliases
`input_tokens`, `output_tokens`, `total_tokens`.

Tool visibility по умолчанию безопасная: Phoenix получает `llm.tools.count`,
`llm.tools.names`, `llm.tool_calls.count`, `llm.tool_calls.names`, а также
события `llm.tool_call` без аргументов. Аргументы tool calls и полные схемы
tools пишутся только при двойном opt-in:
`GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True` и
`GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=True`; перед отправкой они проходят
redaction.

Phoenix spans также получают безопасную caller-классификацию из входящих
headers:

- `caller.name`: например `swagger-ui`, `redoc-ui`, `openai-python`,
  `anthropic-compatible`, `claude-code`, `codex`, `qwen-code`, `browser`;
- `caller.category`: `ui`, `sdk`, `agent`, `browser`, `http_client` или
  `unknown`;
- `caller.client_family`: `openai` или `anthropic`, когда это можно вывести из
  SDK headers или `User-Agent`;
- `caller.sdk`, `caller.agent`, `caller.ui`: более точные подтипы, когда они
  известны.

Подробный объект дублируется в `annotations.caller`, чтобы в Phoenix можно было
открыть structured context без включения payload capture. Для Swagger UI
источник определяется по `Referer: .../docs`, для ReDoc — по `.../redoc`; raw
prompt/response content в annotations не добавляется.

Термины и design constraints описаны в [архитектуре logging и observability](./architecture/logging-and-observability.md).
