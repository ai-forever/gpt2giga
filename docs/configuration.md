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

Relative `--env-path` values resolve from the current working directory, including
when launched with `uvx`. An explicitly named missing file is an error. Without
the flag, the CLI optionally loads `.env` from the current working directory.

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

Version 0.3 can also load one immutable multi-provider configuration with
`--config <path>` or `GPT2GIGA_CONFIG=<path>`. See
[Provider profiles and model aliases](provider-profiles.md) for the versioned
schema, secure four-provider examples, and exact alias behavior.

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
| `GPT2GIGA_HARNESS_MODEL_KEY` | empty | Backward-compatible HMAC setting shared only with a trusted external controller, such as standalone GigaLoom, when the gateway must accept request-scoped Claude/Gemini model pins. |
| `GPT2GIGA_PASS_MODEL` | `True` | Pass the `model` from the request to GigaChat. Set `False` to always use the configured GigaChat model. |
| `GPT2GIGA_PASS_TOKEN` | `False` | Parse the client `Authorization` as GigaChat credentials for per-request upstream authorization. |
| `GPT2GIGA_SHUTDOWN_TIMEOUT_SECONDS` | `10.0` | Maximum graceful drain time before active requests are cancelled during shutdown. |
| `GPT2GIGA_PASS_TOKEN_CLIENT_CACHE_SIZE` | `32` | Maximum idle credential-specific clients retained for connection reuse. |
| `GPT2GIGA_EMBEDDINGS` | `EmbeddingsGigaR` | Default embeddings model when the model from the request is not used. |
| `GPT2GIGA_ENABLE_IMAGES` | `True` | Accept and translate supported image inputs. Disable when the deployment must reject image processing. |
| `GPT2GIGA_DEFAULT_MAX_TOKENS` | empty | Add this positive `max_tokens` value only when the client did not provide `max_tokens`, `max_completion_tokens`, or `max_output_tokens`. Empty means no injected limit. |
| `GPT2GIGA_MAX_REQUEST_BODY_BYTES` | `10485760` | Maximum received body size for POST/PUT/PATCH, including chunked requests without `Content-Length`. Oversized bodies return HTTP 413 before the handler runs. |
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
When pass-through is enabled, clients are pooled by credential and closed on
least-recently-used eviction or shutdown; active streaming requests are never evicted.

## GigaChat settings

This gateway candidate pins `gigachat[aiohttp]==0.3.0a1`. The SDK default API base
URL is `https://api.giga.chat/v1`.

Common upstream settings:

| Variable | Default | Purpose |
|---|---:|---|
| `GIGACHAT_CREDENTIALS` | empty | Authorization key credentials. |
| `GIGACHAT_SCOPE` | SDK default | GigaChat API scope, for example `GIGACHAT_API_PERS`. |
| `GIGACHAT_USER` / `GIGACHAT_PASSWORD` | empty | Alternative username/password authorization; configure `GIGACHAT_BASE_URL` explicitly for this flow. |
| `GIGACHAT_ACCESS_TOKEN` | empty | Alternative authorization via a ready access token. |
| `GIGACHAT_BASE_URL` | `https://api.giga.chat/v1` | SDK API endpoint. Set it explicitly for username/password authorization. |
| `GIGACHAT_MODEL` | empty | Recommended explicit upstream model and the fallback when the gateway does not accept a request model. |
| `GIGACHAT_SESSION_ID` | empty | Default upstream `X-Session-ID`; an incoming request header overrides it. Use a distinct identifier per conversation. Cache hits are not guaranteed. |
| `GIGACHAT_PROFANITY_CHECK` | SDK default | Upstream profanity check flag. |
| `GIGACHAT_VERIFY_SSL_CERTS` | SDK default | Keep `True` in production. |
| `GIGACHAT_USE_BUNDLED_CA` | `True` | Add the packaged Russian Trusted Root CA to the GigaChat client trust store. |
| `GIGACHAT_TIMEOUT` | SDK default | Upstream request timeout. |
| `GIGACHAT_MAX_CONNECTIONS` | SDK default | Global SDK/HTTP connection cap. |
| `GIGACHAT_MAX_RETRIES` | SDK default | SDK retry count for transient upstream errors. |

GigaChat also supports TLS client certificate settings: `GIGACHAT_CA_BUNDLE_FILE`, `GIGACHAT_CERT_FILE`, `GIGACHAT_KEY_FILE`, `GIGACHAT_KEY_FILE_PASSWORD`.

With TLS verification enabled, the gateway adds the bundled public Russian Trusted
Root CA to its GigaChat client context, alongside certifi (or `SSL_CERT_FILE` /
`SSL_CERT_DIR`). This applies to API and OAuth requests, including pass-token clients.
An explicit `GIGACHAT_CA_BUNDLE_FILE` or SDK `ssl_context` takes precedence.
`GIGACHAT_USE_BUNDLED_CA=False` disables the addition. No system trust store is
modified and no certificates are downloaded at runtime. See the
[official certificate guidance](https://developers.sber.ru/docs/ru/gigachat/certificates).

Set `GIGACHAT_MODEL` explicitly for predictable routing. With
`GPT2GIGA_PASS_MODEL=True`, the gateway can accept a non-empty request model;
otherwise it uses the configured `GIGACHAT_MODEL`. If neither source provides a
model, the gateway returns a validation error before upstream I/O.

`GPT2GIGA_PASS_MODEL=False` is often useful for OpenAI-compatible clients that
send a public alias instead of a GigaChat model. In that mode the alias is not
treated as an upstream model, so `GIGACHAT_MODEL` must be configured.

### Tool schema compatibility

`GPT2GIGA_NORMALIZE_TOOL_SCHEMAS=True` enables lossy compatibility conversion for
function parameters sent to **GigaChat-2 models** (including Pro/Max) over either
backend API v1/v2, including `tools` and legacy `functions`, **only when
`GIGACHAT_BASE_URL=https://api.giga.chat/v1`** (a trailing slash is accepted).
Other base URLs, including `https://staging.example.com/v1/` and
`https://gateway.example.com/v1`, preserve schemas even with the flag enabled.
GigaChat-3 and unknown
models retain their original schemas even when this flag is enabled. Selection
uses the effective upstream model, including the configured model and forced overrides;
the API version does not determine the model generation.
It defaults to `False`, preserving native schemas. Enable it for clients such as
Hermes Agent whose union schemas cause upstream 422 responses.

Nested `anyOf`/`oneOf` object branches are merged: properties and duplicate-property
enums are combined, and required fields are intersected. Objects are preferred over
scalar alternatives; otherwise the first non-null branch is selected. Type lists
use the first non-null type. Objects without `properties` get an empty map.
This can narrow accepted types and relax constraints; it is not equivalent JSON
Schema validation. References are not expanded, all-null/empty unions are retained,
and other unsupported keywords can still be rejected upstream. Literal defaults,
examples, and structured-output response schemas are unchanged.

## Reasoning and structured output

Reasoning:

- Reasoning is controlled by each client request; the proxy does not inject or globally override an effort.
- Client `reasoning.effort="none"` or `reasoning_effort="none"` disables reasoning for that request and removes reasoning fields from the GigaChat payload.
- Other explicit reasoning efforts are forwarded to GigaChat.

Structured output:

JSON Schema is passed natively through GigaChat `response_format`; the gateway
does not synthesize a function call for structured output. OpenAI
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

The gateway supports the SDK's v1 root compatibility methods and its v2
resource methods. A model-less call is not a general default: it is allowed only
for a supported v2 flow that carries an `assistant_id` or an existing
`storage.thread_id`. This exception does not expose OpenAI Assistants or Threads
routes through the gateway.

Recognized OpenAI/Anthropic/Gemini provider built-in tools (`web_search*`,
`code_execution*`, `urlContext`, and similar) are mapped to GigaChat built-ins
on v2 routes. User function/local tools are mapped independently.

## Normalized layer flags

The configuration defaults remain unchanged:

```dotenv
GPT2GIGA_NORMALIZATION_MODE=off
GPT2GIGA_LEGACY_CHAT_FALLBACK=True
```

`off`, `shadow`, and `on` are compatibility modes of one execution core.
`shadow` adds content-free diagnostics from the decoded request. The legacy
fallback setting remains accepted for config/admin schema compatibility; it
never retries dispatch or selects a second execution implementation.
The obsolete `GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER` key remains unsupported.

Provider selection always precedes preparation. External aliases use their
admitted Responses, Anthropic Messages or Gemini path; Chat Completions to
OpenAI-compatible remains blocked by the executable loss matrix.

Gemini GenerateContent uses its own dedicated Gemini-to-normalized adapter and
GigaChat provider path independently of these flags. Its admitted bridge subset
uses typed inline images and fully modeled function/JSON Schema fields; safety
settings, cached content, files, unsupported tools, and other unmodeled
semantics remain explicit and fail OpenAI-compatible bridge admission before
provider I/O. OpenAI Responses for the built-in GigaChat route keeps its
existing execution path; Responses for an explicit external alias uses the
normalized bridge. Anthropic semantics outside normalized v1, including prompt
caching, computer use, files, and unsupported content blocks, are not claimed
by an external route and are rejected rather than redirected to another
provider.

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

Anthropic stitching also applies in normalized mode and retains tool-call IDs
and `tools_state_id`. A batch of tool results, optionally followed by user text,
extends the saved history as one new turn. Gemini saves a streamed assistant
turn only after successful completion; failed or interrupted streams do not
replace the previous history.

## Prompt-cache reuse with X-Session-ID

GigaChat keeps a prefix key-value cache for a short window and reports reused
tokens as `precached_prompt_tokens`, which the gateway surfaces as OpenAI
`usage.prompt_tokens_details.cached_tokens` (and Anthropic
`cache_read_input_tokens`). A stable upstream `X-Session-ID` keeps repeated
requests on the same cache entry, so a long unchanged prefix is not reprocessed.

Two independent mechanisms enable this:

1. **Client header pass-through.** Any client can send `X-Session-ID`; the
   gateway forwards it upstream without changes. `GIGACHAT_SESSION_ID` sets a
   global default that the request header overrides.
2. **Built session id.** For clients that cannot send custom headers, the
   gateway can build a stable session id from the request's own stable prefix (a
   one-way hash of the prompt text, never the raw content). Identical prefixes
   map to the same id across workers and restarts.

```dotenv
GPT2GIGA_CACHE_SESSION_ENABLED=False
GPT2GIGA_CACHE_SESSION_SCOPE=system
GPT2GIGA_CACHE_SESSION_MIN_PREFIX_TOKENS=1024
```

| Variable | Default | Purpose |
|---|---:|---|
| `GPT2GIGA_CACHE_SESSION_ENABLED` | `False` | Build an upstream `X-Session-ID` from the request's stable prefix. |
| `GPT2GIGA_CACHE_SESSION_SCOPE` | `system` | `system` hashes only the system prompt; `prefix` also includes the leading user turn. `system` is the default because it stays stable across turns. |
| `GPT2GIGA_CACHE_SESSION_MIN_PREFIX_TOKENS` | `1024` | Minimum estimated prefix tokens before a built session id is applied. |

The built session id applies to chat-like routes (OpenAI Chat Completions,
OpenAI Responses, Anthropic Messages, Gemini GenerateContent) and is skipped
when the client already supplies `X-Session-ID`, when `GIGACHAT_SESSION_ID` is
set, or when the prefix is shorter than the configured minimum. It never changes
the generated answer: it only affects which upstream cache entry a request
reuses. See [Prompt caching](prompt-caching.md) for the measured cache
behaviour.

## Per-model concurrency

`GIGACHAT_MAX_CONNECTIONS` is a global SDK/HTTP cap. The proxy can also limit concurrent upstream model calls by effective model:

```dotenv
GIGACHAT_MAX_CONNECTIONS=7
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT=1
GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=30
```

Semantics:

- an empty `GPT2GIGA_MODEL_MAX_CONNECTIONS` and an empty
  `GPT2GIGA_MODEL_MAX_CONNECTIONS_DEFAULT` disable the limiter;
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
GPT2GIGA_LOGS_TRUSTED_PROXIES='["127.0.0.1"]'
```

`X-Forwarded-For` is honored only when the direct peer is listed in
`GPT2GIGA_LOGS_TRUSTED_PROXIES`; otherwise the allowlist checks the connection
address.

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
All storage backends, including JSONL, use the bounded background queue. JSONL
writes are batched so a request does not wait for a file open and worker-thread handoff.

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
GPT2GIGA_PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
GPT2GIGA_PHOENIX_PROJECT_NAME=gpt2giga
GPT2GIGA_PHOENIX_API_KEY=
```

The unprefixed `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_PROJECT_NAME`, and
`PHOENIX_API_KEY` names remain supported as fallbacks for compatibility with
Phoenix tooling. Prefer the `GPT2GIGA_PHOENIX_*` names in gateway-specific
configuration so ownership is explicit.

The capture flags are independent and disabled by default:

```dotenv
GPT2GIGA_OBSERVABILITY_SAMPLE_RATE=1.0
GPT2GIGA_OBSERVABILITY_QUEUE_SIZE=10000
GPT2GIGA_OBSERVABILITY_DROP_ON_BACKPRESSURE=True
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=False
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=False
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=False
GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH=8000
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

The bounded queue exports spans outside the request path. With the default
backpressure policy, new events are dropped rather than delaying responses when
the exporter cannot keep up.

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

### SDK alpha candidate

Gateway 0.3.3a1 pins `gigachat[aiohttp]==0.3.0a1`; install the locally built wheel
to test this candidate, which is not declared published. Native HTTPX2 remains
the default. Select `GIGACHAT_ASYNC_BACKEND=aiohttp` or
`--gigachat.async-backend aiohttp` to opt in. The aiohttp backend uses HTTP/1.1;
HTTP2, SOCKS, separate finite write timeouts and finite max_keepalive_connections
are unsupported. Explicit finite connect/pool timeouts must match; the SDK rejects
unsupported configurations. No throughput improvement is promised.

`GIGACHAT_TRUST_ENV=False` ignores environment proxy and CA overrides. Explicit CA
and SSL contexts keep their semantics. Bundled trust combines certifi and the
Russian root; factory-loaded API mTLS certificates are not sent to OAuth. Explicit
`auth_ssl_context` controls OAuth trust separately. Request credentials do not
inherit server auth fields.

## Resource storage

Files, upload sessions and batch mappings share a SQLite store and bounded blob directory. `GPT2GIGA_RESOURCE_STORE_PATH` defaults to `var/resources`, relative to the working directory. All workers must use the same persistent directory, including its namespace secret in `resources.sqlite3`. An unavailable configured path fails startup; there is no in-memory fallback. SQLite is intended for workers sharing a local filesystem, not independent hosts on an arbitrary network filesystem.

`GPT2GIGA_RESOURCE_RETENTION_SECONDS` defaults to 2592000 (30 days). Expired metadata and local blobs are purged on startup and resource creation; expired records are inaccessible immediately. This retention is independent of batch delivery deadlines and does not delete upstream documents. Local blobs are limited by `GPT2GIGA_RESOURCE_MAX_BLOB_BYTES` (104857600) and `GPT2GIGA_RESOURCE_MAX_TOTAL_BLOB_BYTES` (1073741824). Keep the directory private: it contains uploaded/result content, not traffic logs.

Ownership uses a persistent HMAC over the configured authenticated identity, provider profile and credential context. No raw credentials are written into resource keys. Anonymous local mode has one shared namespace; a shared gateway API key also identifies one namespace. Opaque pass-through tokens are credential-scoped: rotating a token changes the namespace. `GPT2GIGA_RESOURCE_TRUSTED_IDENTITY` is a deployment-controlled identity label, never an unverified HTTP header; it does not remove separation by upstream credential/profile. Back up the database, its secret, and blobs together.

`GPT2GIGA_RESPONSES_STORAGE_MODE=native|gateway` defaults to `native`. Select `gateway` for owner-scoped immutable Responses snapshots and Conversations over the same resource store and retention policy. See [Response storage](response-storage.md).

After deletion or expiry, the store retains only a small kind/ID registration marker. It contains no owner or content and prevents old upstream IDs from bypassing ownership through the legacy-file fallback.


Resource metadata has independent limits: `GPT2GIGA_RESOURCE_MAX_METADATA_BYTES=67108864`
and `GPT2GIGA_RESOURCE_MAX_RESOURCES=100000`. These are store-wide admission budgets,
not per-file blob limits. Writes, including response-only snapshot workloads, purge
expired records in bounded batches before checking the budget. Registered-ID tombstones
remain so expired/foreign resources cannot fall back to native lookup.


Token counting retains one narrow input-projection compatibility difference: `on` includes
normalized tool/schema text, while `off`/`shadow` retain the tolerant legacy text subset.
All modes share the same token-count dispatch, client binding, limiter and cleanup.

### Request and telemetry cleanup

A disconnected model request stops waiting for a concurrency slot before dispatch.
An empty acquire timeout still permits indefinite waiting by a connected client.
Dynamic model entries are released after their final holder or waiter exits.
Credential-pool eviction owns client cleanup even if acquisition is cancelled;
client close has a five-second timeout, and failed closes remain recorded for a
shutdown retry.

`GPT2GIGA_SHUTDOWN_TIMEOUT_SECONDS` limits request draining. Separately, each
telemetry sink receives up to five seconds for best-effort flush. A stalled queued
traffic sink is cancelled, pending events are counted as dropped, and dependency
cleanup continues. After flush (including timeout or cancellation), sinks receive a
separate five-second terminal-close budget. Queue shutdown abandons remaining
work before closing the backend, without draining again. Phoenix closes its
app-owned OpenTelemetry provider once; ordinary flush keeps export available.
The async deadline cannot forcibly stop a blocking SDK/exporter thread:
OpenTelemetry's synchronous shutdown continues under the SDK's own limits.
These budgets are not a total shutdown deadline for all dependencies.

HTTP metrics use route templates, such as `/v1/files/{file_id}`, and `unmatched`
for unknown paths. Built-in model names and configured per-model concurrency keys
are retained; other model/error label values become `other`. Raw request paths
remain available to the logging boundary, subject to its capture/redaction policy.

Multipart Files parsing uses Starlette spooled uploads. `python-multipart` is a
base runtime dependency; no integrations extra is needed. The total request-body
limit and MIME-specific file limits still apply, including files larger than the
spool's memory threshold. Temporary files are closed on success, error and cancellation.
