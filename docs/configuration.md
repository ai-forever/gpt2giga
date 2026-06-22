# Configuration

`gpt2giga` reads two groups of settings:

- proxy settings with the `GPT2GIGA_` prefix;
- GigaChat SDK settings with the `GIGACHAT_` prefix.

Keep secrets in `.env`, environment variables, or a secrets manager. Do not pass credentials via CLI flags in production: process arguments can be visible through `ps`.

## Settings sources

The CLI accepts an explicit env file:

```sh
gpt2giga --env-path .env
```

You can pass structured CLI flags:

```sh
gpt2giga \
  --proxy.host 127.0.0.1 \
  --proxy.port 8090 \
  --proxy.pass-model true \
  --gigachat.model GigaChat-2-Max
```

Full CLI reference:

```sh
gpt2giga --help
```

An env template to copy: [.env.example](https://github.com/ai-forever/gpt2giga/blob/main/.env.example).

## How to read this document

`.env.example` is intentionally a copy-paste template: it is convenient to see all
the keys side by side, but the trade-offs are not always visible. This document is
a reference for the meaning of the settings and safe combinations.

A practical rule:

- for a local run, start with the minimal block of `GPT2GIGA_*` and `GIGACHAT_*`;
- for production, first configure security, then the backend mode, then optional
  traffic logs, metrics, and observability;
- enable experimental/admin/debug flags only when you understand who has access to
  them and where payloads will be stored.

## Quick profiles

A minimal local `.env`:

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

A minimum for production:

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

Explicit selection of GigaChat v2 on the client side:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

With this value, root routes without `/v1` or `/v2` stay on v1, while a client can
choose v2 via `base_url="http://localhost:8090/v2"`. `/v1` always
forces the GigaChat v1 contract, `/v2` the GigaChat v2 contract.
If you want root routes to also use v2, set
`GPT2GIGA_GIGACHAT_API_MODE=v2`.

## Value format

Pydantic Settings reads environment variable names case-insensitively, but the
documentation and examples use uppercase.

Specify lists and dictionaries as JSON strings:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://app.example.com"]'
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS='["customer_token"]'
```

`GPT2GIGA_TRAFFIC_LOG_SINKS` accepts a JSON array or a comma-separated list:

```dotenv
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
```

CLI flags are convenient for non-secret local overrides. For secrets, use
`.env`, environment variables, or a secrets manager, because CLI arguments
can be visible to other processes.

## Core proxy settings

| Variable | Default | Purpose |
|---|---:|---|
| `GPT2GIGA_MODE` | `DEV` | `DEV` or `PROD`. `PROD` disables `/docs`, `/redoc`, `/openapi.json`, and `/logs*`. |
| `GPT2GIGA_HOST` | `localhost` | Local server host. |
| `GPT2GIGA_PORT` | `8090` | Local server port. |
| `GPT2GIGA_USE_HTTPS` | `False` | Built-in HTTPS. For production, TLS at a reverse proxy is usually better. |
| `GPT2GIGA_HTTPS_KEY_FILE` / `GPT2GIGA_HTTPS_CERT_FILE` | empty | Local key/cert files for built-in HTTPS. |
| `GPT2GIGA_ENABLE_API_KEY_AUTH` | `False` | Require proxy API-key authentication for public API routes. Mandatory in `PROD`. |
| `GPT2GIGA_API_KEY` | empty | Proxy API key. For shared environments, use a strong random value. |
| `GPT2GIGA_PASS_MODEL` | `True` | Pass the `model` from the request to GigaChat. Set `False` to always use the configured GigaChat model. |
| `GPT2GIGA_PASS_TOKEN` | `False` | Parse the client `Authorization` as GigaChat credentials for per-request upstream authorization. |
| `GPT2GIGA_EMBEDDINGS` | `EmbeddingsGigaR` | Default embeddings model when the model from the request is not used. |
| `GPT2GIGA_MAX_REQUEST_BODY_BYTES` | `10485760` | Maximum HTTP request body size. |
| `GPT2GIGA_LOG_LEVEL` | `INFO` | Runtime log level. Avoid `DEBUG` in production. |
| `GPT2GIGA_LOG_FILENAME` | `gpt2giga.log` | Runtime log file. |
| `GPT2GIGA_LOG_MAX_SIZE` | `10485760` | Maximum log file size before rotation. |
| `GPT2GIGA_LOG_REDACT_SENSITIVE` | `True` | Redact secrets in runtime logs. |

## Authentication and security

The proxy API key protects public API routes (`/chat/completions`, `/responses`,
`/messages`, `/models`, `/embeddings`, `/model/info`, versioned variants).
Clients can pass the key in two ways:

```http
Authorization: Bearer <GPT2GIGA_API_KEY>
x-api-key: <GPT2GIGA_API_KEY>
```

`MODE=PROD` requires a configured API key and disables the interactive docs and
log routes. Admin/debug endpoints use a separate `GPT2GIGA_ADMIN_API_KEY`.

`GPT2GIGA_PASS_TOKEN=True` is needed only for scenarios where each client must
pass its own GigaChat credentials. The following prefixes are supported in
`Authorization`:

- `giga-cred-<credentials>:<scope>` for GigaChat authorization key credentials;
- `giga-auth-<access_token>` for a ready access token;
- `giga-user-<user>:<password>` for username/password authorization.

For a regular deployment, it is simpler and safer to keep upstream credentials on
the server via `GIGACHAT_*`.

## GigaChat settings

Common upstream settings:

| Variable | Default | Purpose |
|---|---:|---|
| `GIGACHAT_CREDENTIALS` | empty | Authorization key credentials. |
| `GIGACHAT_SCOPE` | SDK default | GigaChat API scope, for example `GIGACHAT_API_PERS`. |
| `GIGACHAT_USER` / `GIGACHAT_PASSWORD` | empty | Alternative username/password authorization. |
| `GIGACHAT_ACCESS_TOKEN` | empty | Alternative authorization via a ready access token. |
| `GIGACHAT_MODEL` | SDK default | Default model when the proxy does not pass the client model or `GPT2GIGA_PASS_MODEL=False`. |
| `GIGACHAT_PROFANITY_CHECK` | SDK default | Upstream profanity check flag. |
| `GIGACHAT_VERIFY_SSL_CERTS` | SDK default | Keep `True` in production. |
| `GIGACHAT_TIMEOUT` | SDK default | Upstream request timeout. |
| `GIGACHAT_MAX_CONNECTIONS` | SDK default | Global SDK/HTTP connection cap. |
| `GIGACHAT_MAX_RETRIES` | SDK default | SDK retry count for transient upstream errors. |

GigaChat also supports TLS client certificate settings: `GIGACHAT_CA_BUNDLE_FILE`, `GIGACHAT_CERT_FILE`, `GIGACHAT_KEY_FILE`, `GIGACHAT_KEY_FILE_PASSWORD`.

`GPT2GIGA_PASS_MODEL=False` is often useful for OpenAI-compatible clients
that send a model name not from GigaChat. Then the upstream model is taken from
`GIGACHAT_MODEL`.

## Reasoning and structured output

Reasoning:

```dotenv
GPT2GIGA_ENABLE_REASONING=False
GPT2GIGA_DISABLE_REASONING=False
```

- `GPT2GIGA_ENABLE_REASONING=True` adds `reasoning_effort="high"` if the client did not pass an explicit reasoning setting.
- `GPT2GIGA_DISABLE_REASONING=True` removes `reasoning` and `reasoning_effort`, including explicit client fields and `extra_body` passthrough.

Structured output:

```dotenv
GPT2GIGA_STRUCTURED_OUTPUT_MODE=function_call
```

Values:

- `function_call`: a compatibility fallback through function calling;
- `native`: passes the JSON Schema through GigaChat `response_format` if the model/API supports it.

Both modes are designed for schema-based structured output. OpenAI
`response_format.type=json_object` and Gemini `responseMimeType=application/json`
without `responseJsonSchema` / `responseSchema` are not proxied to GigaChat,
because the upstream does not support a separate schema-less JSON mode.

## Backend API mode

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

| `GPT2GIGA_GIGACHAT_API_MODE` | `/chat/completions` backend | `/responses` backend |
|---|---|---|
| `v1` | `v1` | `v1` |
| `v2` | `v2` | `v2` |

Root URLs (`/chat/completions`, `/responses`, `/messages`) without `/v1` or `/v2`
use this flag.
Versioned prefixes are an explicit per-request override:

- `/v1/chat/completions`, `/v1/responses`, `/v1/messages` use the GigaChat v1 contract;
- `/v2/chat/completions`, `/v2/responses`, `/v2/messages` use the GigaChat v2 contract.

## Fusion / multi-model deliberation

GigaFusion - локальный режим, в котором один client request запускает direct
candidate и/или несколько внутренних GigaChat panel calls, затем judge/selector
и при необходимости finalizer call. Он выключен по
умолчанию и не обращается к OpenRouter или другим внешним upstream.

Минимальное включение:

```dotenv
GPT2GIGA_FUSION_ENABLED=True
GPT2GIGA_FUSION_DEFAULT_PRESET=code-high
```

Частые overrides:

```dotenv
GPT2GIGA_FUSION_ALIASES='["gpt2giga/fusion","gpt2giga/fusion-code","gpt2giga/fusion-accuracy","gpt2giga/fusion-benchmark","GigaChat-Fusion-Code"]'
GPT2GIGA_FUSION_STREAMING_MODE=buffered
GPT2GIGA_FUSION_MAX_PANEL_MODELS=4
GPT2GIGA_FUSION_MAX_PANEL_CONCURRENCY=3
GPT2GIGA_FUSION_MAX_CONCURRENT_REQUESTS=4
GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST=5
GPT2GIGA_FUSION_MAX_CLIENT_TOOL_ROUNDS=8
GPT2GIGA_FUSION_POST_TOOL_MODE=direct_continuation
GPT2GIGA_FUSION_DIRECT_TOOL_CALL_POLICY=return_immediately
GPT2GIGA_FUSION_META_TOOL_NAMES=update_topic,update_plan,todo_write
GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS=0
GPT2GIGA_FUSION_EXPOSE_ANALYSIS_METADATA=False
GPT2GIGA_FUSION_EXPOSE_PANEL_RESPONSES=False
```

Используйте `GPT2GIGA_FUSION_PRESETS` для JSON-карты custom presets с
`analysis_models`, `judge_model`, `direct_model`, `final_model`, `panel_roles`,
generation limits, `include_direct_candidate`, `return_selected_candidate`,
`decision_mode`, `prompt_mode`, output budgets, `min_successful_panels`,
`timeout_seconds`, `tools_mode`, `post_tool_mode`,
`direct_tool_call_policy` и `max_client_tool_rounds`.
`decision_mode="selector"` выбирает лучший candidate и возвращает его без
переписывания, если `needs_rewrite=false` и `return_selected_candidate=true`;
`decision_mode="synthesize"` сохраняет старый compact `panel -> judge/finalizer`
путь.

Подробно: [GigaFusion](fusion.md).

## Normalized layer flags

Experimental flags control the OpenAI Chat Completions normalized path and by
default keep the legacy behavior for this route:

```dotenv
GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER=False
GPT2GIGA_NORMALIZATION_MODE=off
GPT2GIGA_LEGACY_CHAT_FALLBACK=True
```

- `off`: OpenAI Chat Completions goes through the legacy path;
- `shadow`: builds normalized diagnostics alongside the legacy OpenAI Chat handling without changing client responses;
- `on`: switches OpenAI Chat to the normalized path, with a legacy fallback before the response starts, if the fallback is enabled.

Gemini GenerateContent uses its own dedicated Gemini-to-normalized adapter and
GigaChat provider path independently of these OpenAI Chat flags. OpenAI Responses
and Anthropic Messages stay on the legacy execution paths, but use a normalized
representation for observability/debug helpers where possible.

A detailed description of the models and current execution paths: [Normalized messages architecture](./architecture/normalized-messages.md).

## Conversation stitching

Conversation stitching is opt-in in-memory state for stateless chat-like
clients that pass a stable conversation identifier. It is disabled by default
and does not affect compatibility.
OpenAI Chat Completions, Anthropic Messages, and Gemini GenerateContent are supported.
The conversation identifier is taken from `conversation`, `metadata.conversation_id`,
`x-gpt2giga-conversation-id` or, if enabled, `x-session-id`.

```dotenv
GPT2GIGA_CONVERSATION_STITCHING_ENABLED=False
GPT2GIGA_CONVERSATION_TTL_SECONDS=3600
GPT2GIGA_CONVERSATION_MAX_MESSAGES=40
GPT2GIGA_CONVERSATION_USE_SESSION_ID=False
GPT2GIGA_CONVERSATION_ON_DIVERGENCE=client_wins
```

| Variable | Default | Purpose |
|---|---:|---|
| `GPT2GIGA_CONVERSATION_STITCHING_ENABLED` | `False` | Enable local stitching state. |
| `GPT2GIGA_CONVERSATION_TTL_SECONDS` | `3600` | How long to keep idle conversation state. |
| `GPT2GIGA_CONVERSATION_MAX_MESSAGES` | `40` | Maximum retained messages sent upstream. |
| `GPT2GIGA_CONVERSATION_USE_SESSION_ID` | `False` | Allow `x-session-id` as a conversation key when there is no explicit key. |
| `GPT2GIGA_CONVERSATION_ON_DIVERGENCE` | `client_wins` | `client_wins` replaces the state after success, `fork` creates a revision-suffixed branch. |

The state is kept in the process memory. With several workers/pods, use sticky
routing or do not enable stitching.

## Per-model concurrency

`GIGACHAT_MAX_CONNECTIONS` is a global SDK/HTTP cap. The proxy can also limit concurrent upstream model calls by effective model:

```dotenv
GIGACHAT_MAX_CONNECTIONS=7
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=30
```

Semantics:

- an empty `GPT2GIGA_MODEL_MAX_CONNECTIONS` and an empty default disable the limiter;
- an explicit model limit takes precedence over the default;
- `GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=0` immediately returns a local `429`;
- streaming calls hold a slot until the stream completes or the client disconnects;
- limits work within a single process, so workers/pods multiply the effective capacity.

## CORS

The defaults are convenient for local development:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["*"]'
GPT2GIGA_CORS_ALLOW_METHODS='["*"]'
GPT2GIGA_CORS_ALLOW_HEADERS='["*"]'
```

In production, set specific origins and headers:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://your-app.example.com"]'
GPT2GIGA_CORS_ALLOW_METHODS='["GET","POST","OPTIONS"]'
GPT2GIGA_CORS_ALLOW_HEADERS='["authorization","content-type","x-api-key"]'
```

## HTTP body and attachment limits

The global body limit is checked before JSON parsing:

```dotenv
GPT2GIGA_MAX_REQUEST_BODY_BYTES=10485760
```

Additional limits protect attachment processing:

| Variable | Purpose |
|---|---|
| `GPT2GIGA_MAX_AUDIO_FILE_SIZE_BYTES` | Maximum size of a single audio file. |
| `GPT2GIGA_MAX_IMAGE_FILE_SIZE_BYTES` | Maximum size of a single image. |
| `GPT2GIGA_MAX_TEXT_FILE_SIZE_BYTES` | Maximum size of a single text file. |
| `GPT2GIGA_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES` | Combined limit of audio and images in one request. |

Lower these values if the proxy is available to a wide range of clients or sits
in front of an expensive storage/upload path.

## Runtime logs and `/logs*`

Runtime logs are written to stdout and the log file:

```dotenv
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_FILENAME=gpt2giga.log
GPT2GIGA_LOG_MAX_SIZE=10485760
GPT2GIGA_LOG_REDACT_SENSITIVE=True
```

`/logs/{last_n_lines}`, `/logs/stream`, and `/logs/html` are available only in `DEV`.
In `PROD` they are not mounted. If API-key authentication is enabled, `/logs*` also requires
the proxy key.

An IP allowlist for `/logs*`:

```dotenv
GPT2GIGA_LOGS_IP_ALLOWLIST='["10.0.0.1"]'
```

Do not use `GPT2GIGA_LOG_LEVEL=DEBUG` in production: debug output may
contain operational context that should not end up in shared logs.

## Traffic logs

Traffic logs are structured request/response records. They are disabled by default:

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

Postgres plus an OpenSearch mirror:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
GPT2GIGA_OPENSEARCH_URL=http://localhost:9200
```

| Variable | Default | Purpose |
|---|---:|---|
| `GPT2GIGA_TRAFFIC_LOG_SINK` | `noop` | Single sink: `noop`, `jsonl`, `postgres`, `opensearch`. |
| `GPT2GIGA_TRAFFIC_LOG_SINKS` | `[]` | Ordered mirror sinks, for example `postgres,opensearch`. If empty, the single sink is used. |
| `GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT` | `False` | Store request/response bodies after redaction. |
| `GPT2GIGA_TRAFFIC_LOG_QUEUE_SIZE` | `10000` | Maximum queued events. |
| `GPT2GIGA_TRAFFIC_LOG_BATCH_SIZE` | `500` | Maximum events in a storage batch. |
| `GPT2GIGA_TRAFFIC_LOG_FLUSH_INTERVAL_MS` | `2000` | Best-effort flush interval. |
| `GPT2GIGA_TRAFFIC_LOG_DROP_ON_BACKPRESSURE` | `True` | Drop events instead of blocking the request path when the queue is full. |
| `GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE` | `True` | Redact sensitive fields before storage. |
| `GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS` | `[]` | Additional case-insensitive keys for redaction. |
| `GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS` | `30` | Retention for Postgres traffic logs. |
| `GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS` | `3600` | Best-effort retention purge interval. |

Enable content capture only after resolving storage encryption, retention,
redaction, and admin-endpoint access.

## Postgres and OpenSearch helper variables

The Compose profiles use several helper variables that are not direct
`ProxySettings` fields but are needed for the storage services:

| Variable | Purpose |
|---|---|
| `GPT2GIGA_POSTGRES_DB` | Database name for `deploy/postgres.yaml`. |
| `GPT2GIGA_POSTGRES_USER` | Postgres user for the Compose service. |
| `GPT2GIGA_POSTGRES_PASSWORD` | Postgres password. Set a strong value. |
| `GPT2GIGA_POSTGRES_PORT` | Host port for local Postgres. |
| `GPT2GIGA_OPENSEARCH_PORT` | Host port for local OpenSearch. |

OpenSearch runtime settings:

| Variable | Default | Purpose |
|---|---:|---|
| `GPT2GIGA_OPENSEARCH_URL` | `http://localhost:9200` | OpenSearch endpoint. |
| `GPT2GIGA_OPENSEARCH_USERNAME` / `GPT2GIGA_OPENSEARCH_PASSWORD` | empty | Optional authorization. |
| `GPT2GIGA_OPENSEARCH_INDEX` | `gpt2giga-traffic` | Index or data stream name. |
| `GPT2GIGA_OPENSEARCH_DATA_STREAM` | `True` | Use data stream bulk create semantics. |
| `GPT2GIGA_OPENSEARCH_BULK_SIZE` | `500` | Bulk batch size. |
| `GPT2GIGA_OPENSEARCH_FLUSH_INTERVAL_MS` | `2000` | Best-effort flush interval. |

## Metrics

The Prometheus-compatible endpoint is disabled by default:

```dotenv
GPT2GIGA_METRICS_ENABLED=False
GPT2GIGA_METRICS_PATH=/metrics
```

When enabled, the endpoint is mounted at `GPT2GIGA_METRICS_PATH`. If proxy
API-key authentication is enabled, the metrics endpoint also requires the proxy key.

Metrics labels are limited to a bounded set of operational fields and do not include the prompt,
response content, API keys, request ids, or trace ids.

## Observability / Phoenix

OpenTelemetry/OpenInference observability is disabled by default:

```dotenv
GPT2GIGA_OBSERVABILITY_ENABLED=False
GPT2GIGA_OBSERVABILITY_BACKEND=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=gpt2giga
PHOENIX_API_KEY=
```

The capture flags are independent and disabled by default:

```dotenv
GPT2GIGA_OBSERVABILITY_SAMPLE_RATE=1.0
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=False
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=False
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=False
GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH=8000
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

Payload content reaches spans only when the corresponding capture flags are
explicitly enabled. For production, capture is usually left disabled or enabled
for a short time under access control.

Compose helper variables for Phoenix and mitmproxy:

| Variable | Purpose |
|---|---|
| `PHOENIX_PORT` | Host port for the Phoenix UI. |
| `PHOENIX_GRPC_PORT` | Host port for the OTLP gRPC collector. |
| `MITMPROXY_PORT` | Host port for the mitmproxy proxy listener in the Compose overlay. |
| `MITMPROXY_WEB_PORT` | Host port for the mitmproxy web UI in the Compose overlay. |

Details on the emitted spans and metric names: [Operations](./operations.md).

## Admin and debug endpoints

The Admin API is disabled by default:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=False
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

When enabled, the `/_admin/logs*` endpoints use `GPT2GIGA_ADMIN_API_KEY`, not
the public proxy key. Replay requires a separate opt-in:

```dotenv
GPT2GIGA_REPLAY_ENABLED=True
```

The debug translation endpoints are enabled separately:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

These endpoints are intended for local debugging and protected admin workflows.
Do not enable them publicly without reverse-proxy controls and a separate admin key.

`GPT2GIGA_UI_ENABLED` is reserved for a future built-in UI. For now, do not
use it as a security control.
