# Operations

This document describes runtime logs, traffic logs, metrics, observability, and admin/debug endpoints.

## System endpoints

Always mounted:

- `GET /health`
- `GET | POST /ping`

`DEV` only:

- `GET /logs/{last_n_lines}`
- `GET /logs/stream`
- `GET /logs/html`

The `/logs*` endpoints are disabled in `PROD`.

## Runtime logs

Runtime logs are process logs. They are written to stdout and the configured log file.

Common settings:

```dotenv
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_FILENAME=gpt2giga.log
GPT2GIGA_LOG_MAX_SIZE=10485760
```

Do not use `DEBUG` in production. Debug logs may contain sensitive operational context even with redaction enabled.

## Metrics

Prometheus-compatible metrics are disabled by default:

```dotenv
GPT2GIGA_METRICS_ENABLED=False
GPT2GIGA_METRICS_PATH=/metrics
```

Local enablement:

```dotenv
GPT2GIGA_METRICS_ENABLED=True
GPT2GIGA_METRICS_PATH=/metrics
```

If API-key authentication is enabled, pass `Authorization: Bearer <GPT2GIGA_API_KEY>` or `x-api-key`.

Metrics do not contain prompt/response content, API keys, request ids, trace ids, or raw payloads. Labels are limited to a bounded set of operational fields: protocol, route, method, status, lifecycle, provider, model.

Baseline series:

- `gpt2giga_requests_total`
- `gpt2giga_request_duration_seconds`
- `gpt2giga_upstream_duration_seconds`
- `gpt2giga_upstream_errors_total`
- `gpt2giga_tokens_input_total`
- `gpt2giga_tokens_output_total`
- `gpt2giga_stream_disconnects_total`
- `gpt2giga_traffic_log_dropped_total`

## Traffic logs

Traffic logs are structured records of request/response traffic. They are disabled by default:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=False
GPT2GIGA_TRAFFIC_LOG_SINK=noop
```

Local JSONL check:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=jsonl
GPT2GIGA_TRAFFIC_LOG_JSONL_PATH=traffic_logs.jsonl
```

Durable backend in Postgres:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Postgres plus an OpenSearch mirror:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
GPT2GIGA_OPENSEARCH_URL=http://localhost:9200
```

Content capture is opt-in and goes through redaction:

```dotenv
GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT=False
GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE=True
```

Keep content capture disabled until storage, retention, redaction, and access policies are approved.

## Admin Traffic Logs API

Admin endpoints are disabled by default:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=False
```

Enablement with a separate admin key:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Authorization header options:

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

Replay requires:

```dotenv
GPT2GIGA_REPLAY_ENABLED=True
```

## Debug Translate API

The debug translation endpoints are intended for local debugging and protected admin workflows:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Main endpoint:

- `POST /_debug/translate`

Short endpoints:

- `POST /_debug/translate/openai-to-normalized`
- `POST /_debug/translate/anthropic-to-normalized`
- `POST /_debug/translate/normalized-to-gigachat`
- `POST /_debug/translate/gigachat-to-openai`

Supported payload families: `openai`, `anthropic`, `normalized`, `gigachat`, depending on the direction.

How these formats pass through the internal normalized contract is described in
[Normalized messages architecture](./architecture/normalized-messages.md).

## Phoenix / OpenTelemetry

Phoenix observability is disabled by default:

```dotenv
GPT2GIGA_OBSERVABILITY_ENABLED=False
GPT2GIGA_OBSERVABILITY_BACKEND=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=gpt2giga
```

Enable it after installing the optional `phoenix` extra or via the Phoenix Compose profile.

LLM payload attributes require a double opt-in:

```dotenv
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=True
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=True
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

Traffic logs and Phoenix spans are linked through gateway identifiers:
`request_id`, `trace_id`, protocol, route, model metadata. For LLM routes,
Phoenix gets one root span per format: `OpenAI-Completions` for Chat
Completions, `OpenAI-Responses` for the Responses API, `Anthropic-Messages` for
Anthropic Messages, `Gemini-Content` for Gemini GenerateContent, and `Embeddings`
for OpenAI Embeddings. Streaming milestones are attached to the corresponding
root span as span events. For non-LLM routes, a single lifecycle span
`gpt2giga.request` is used.

For filtering and grouping by the compatible API format, model spans get the
attribute `gpt2giga.api_format`: `chat_completions`, `responses`, `messages`,
`generate_content`, or `embeddings`. Stateful Responses additionally get
`session.id` and `conversation.id` from the GigaChat `thread_id`; if the upstream
thread id is not yet available, `previous_response_id` is used without the
`resp_` prefix.

The OpenTelemetry span start time is taken from the gateway
`RequestContext.started_at`, so Phoenix `Latency` reflects the full request/stream
time, not just the time of the final observability span emission. The same value
is additionally written to the `latency_ms` attribute.

LLM spans set an explicit OpenTelemetry status (`OK` or `ERROR`) and duplicate
it in the safe `status` / `llm.response.status` attributes. Token usage is
written as the OpenInference fields `llm.token_count.*` and as the gateway
aliases `input_tokens`, `output_tokens`, `total_tokens`.

Tool visibility is safe by default: Phoenix gets `llm.tools.count`,
`llm.tools.names`, `llm.tool_calls.count`, `llm.tool_calls.names`, plus
`llm.tool_call` events without arguments. Tool call arguments and full tool
schemas are written only with a double opt-in:
`GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True` and
`GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=True`; they go through redaction before
being sent.

Phoenix spans also get a safe caller classification from the incoming
headers:

- `caller.name`: for example `swagger-ui`, `redoc-ui`, `openai-python`,
  `anthropic-compatible`, `claude-code`, `codex`, `qwen-code`, `browser`;
- `caller.category`: `ui`, `sdk`, `agent`, `browser`, `http_client`, or
  `unknown`;
- `caller.client_family`: `openai` or `anthropic`, when it can be inferred from
  the SDK headers or `User-Agent`;
- `caller.sdk`, `caller.agent`, `caller.ui`: more precise subtypes, when they are
  known.

The detailed object is duplicated in `annotations.caller`, so that in Phoenix you
can open the structured context without enabling payload capture. For Swagger UI
the source is determined by `Referer: .../docs`, for ReDoc by `.../redoc`; raw
prompt/response content is not added to annotations.

Terms and design constraints are described in [Logging and observability](./architecture/logging-and-observability.md).
A checklist for adding new providers/protocols and the related observability
changes: [Adding a provider or protocol](./architecture/how-to-add-provider.md).
