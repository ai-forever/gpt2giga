# Operator Guide

Этот документ описывает runtime switches и операторские сценарии для `gpt2giga`: какие provider-ы включать, когда выбирать backend `v1`/`v2`, как использовать `/admin`, `/metrics` и что меняется между `DEV` и `PROD`.

## Базовые runtime switches

Ключевые настройки:

- `GPT2GIGA_ENABLED_PROVIDERS`
- `GPT2GIGA_GIGACHAT_API_MODE`
- `GPT2GIGA_MODE`
- `GPT2GIGA_ENABLE_API_KEY_AUTH`
- `GPT2GIGA_OBSERVABILITY_SINKS`
- `GPT2GIGA_GOVERNANCE_LIMITS`

### `GPT2GIGA_ENABLED_PROVIDERS`

Управляет тем, какие внешние provider-роуты монтируются при старте.

Поддерживаемые значения:

- `openai`
- `anthropic`
- `gemini`
- `all`

Формат:

```dotenv
GPT2GIGA_ENABLED_PROVIDERS=openai,gemini
```

Поведение:

- по умолчанию включены все built-in provider-ы;
- `openai` включает и OpenAI routes, и LiteLLM-compatible `/model/info`;
- выключенные provider-ы не попадают ни в router mounting, ни в OpenAPI schema.

### `GPT2GIGA_GIGACHAT_API_MODE`

Управляет backend path для chat-like flows.

Значения:

- `v1`
- `v2`

Формат:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v2
```

Режим `v2` влияет на:

- OpenAI `chat/completions`
- OpenAI `responses`
- Anthropic `messages`
- Gemini `generateContent` / `streamGenerateContent`
- responses-targeted batches

Если вы хотите предсказуемый rollout, сначала включайте `v2` на staging или на отдельном instance.

### `GPT2GIGA_MODE`

Режимы:

- `DEV`
- `PROD`

`DEV`:

- доступны `/admin` и `/admin/api/*`;
- доступны legacy `/logs*`;
- доступны `/docs`, `/redoc`, `/openapi.json`.

`PROD`:

- `/admin*` отключены;
- `/logs*` отключены;
- `/docs`, `/redoc`, `/openapi.json` отключены;
- нужен `GPT2GIGA_API_KEY`;
- CORS policy ужесточается автоматически.

### `GPT2GIGA_OBSERVABILITY_SINKS`

Управляет telemetry sink-ами для normalized request events.

Примеры:

```dotenv
GPT2GIGA_OBSERVABILITY_SINKS=prometheus
GPT2GIGA_OBSERVABILITY_SINKS=none
GPT2GIGA_OBSERVABILITY_SINKS=prometheus,otlp
GPT2GIGA_OTLP_TRACES_ENDPOINT=http://otel-collector:4318/v1/traces
GPT2GIGA_LANGFUSE_BASE_URL=http://langfuse-web:3000
GPT2GIGA_LANGFUSE_PUBLIC_KEY=pk-lf-...
GPT2GIGA_LANGFUSE_SECRET_KEY=sk-lf-...
```

`prometheus` включает `/metrics` и `/admin/api/metrics`.
`otlp` экспортирует trace spans через OTLP/HTTP.
`langfuse` отправляет те же spans в Langfuse через его OTLP endpoint.

### `GPT2GIGA_GOVERNANCE_LIMITS`

Управляет fixed-window governance rules для:

- request rate limiting по `max_requests`;
- token quota по `max_total_tokens`.

Rule может быть scoped по:

- `api_key`
- `provider`

И дополнительно фильтроваться по:

- `providers`
- `endpoints`
- `models`

Пример:

```dotenv
GPT2GIGA_GOVERNANCE_LIMITS=[{"name":"openai-burst","scope":"api_key","providers":["openai"],"endpoints":["chat/completions"],"window_seconds":60,"max_requests":30},{"name":"openai-provider-quota","scope":"provider","providers":["openai"],"models":["GigaChat-2-Max"],"window_seconds":3600,"max_total_tokens":200000}]
```

Поведение:

- request-based rule резервирует слот на входе в handler и возвращает `429`, если окно уже заполнено;
- token-based quota обновляется после завершения запроса из normalized audit event;
- scoped `api_key` rules работают только когда request уже аутентифицирован и `request.state.api_key_context` известен.

## Типовые сценарии

### Только OpenAI-compatible surface

```dotenv
GPT2GIGA_ENABLED_PROVIDERS=openai
GPT2GIGA_GIGACHAT_API_MODE=v1
```

Итог:

- доступны OpenAI routes;
- доступен LiteLLM-compatible `/model/info`;
- Anthropic и Gemini routes не монтируются.

### OpenAI + Gemini

```dotenv
GPT2GIGA_ENABLED_PROVIDERS=openai,gemini
GPT2GIGA_GIGACHAT_API_MODE=v1
```

Итог:

- доступны OpenAI и Gemini routes;
- Anthropic routes отсутствуют;
- OpenAPI показывает только включенные группы.

### Rollout backend `v2`

```dotenv
GPT2GIGA_ENABLED_PROVIDERS=openai,anthropic,gemini
GPT2GIGA_GIGACHAT_API_MODE=v2
```

Подходит для:

- testing/staging;
- отдельных инстансов для новых клиентов;
- поэтапного перевода chat-like traffic на `achat_v2/astream_v2`.

## Локальный запуск

```bash
cp .env.example .env
uv sync --all-extras --dev
uv run gpt2giga
```

Измените `.env` перед стартом:

```dotenv
GPT2GIGA_ENABLED_PROVIDERS=openai,gemini
GPT2GIGA_GIGACHAT_API_MODE=v2
GPT2GIGA_MODE=DEV
```

После старта можно открыть:

- `http://localhost:8090/admin`
- `http://localhost:8090/metrics`

## Docker / Compose

Готовые compose-стеки лежат в `deploy/compose/`.
Краткая карта файлов и соответствующих `make`-команд: [deploy/README.md](../deploy/README.md).

Основные файлы:

- `deploy/compose/base.yaml` — обычный single-instance запуск;
- `deploy/compose/multiple.yaml` — несколько инстансов с разными моделями;
- `deploy/compose/observability-prometheus.yaml` — preset для Prometheus scrape `/metrics`;
- `deploy/compose/observability-otlp.yaml` — preset для локального OpenTelemetry Collector;
- `deploy/compose/observability-langfuse.yaml` — локальный Langfuse stack для trace inspection;
- `deploy/compose/observability.yaml` — запуск через mitmproxy для debug/SSE inspection;
- `deploy/compose/traefik.yaml` — reverse proxy и несколько инстансов.

Базовый workflow:

1. Скопируйте `.env.example` в `.env`.
2. Задайте нужные switches в `.env`.
3. Запустите нужный профиль.

Пример для DEV:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_ENABLED_PROVIDERS=openai,gemini
GPT2GIGA_GIGACHAT_API_MODE=v2
```

Примеры запуска observability preset-ов:

```bash
docker compose -f deploy/compose/base.yaml -f deploy/compose/observability-prometheus.yaml --profile DEV up -d
docker compose -f deploy/compose/base.yaml -f deploy/compose/observability-otlp.yaml --profile DEV up -d
docker compose -f deploy/compose/base.yaml -f deploy/compose/observability-langfuse.yaml --profile DEV up -d
```

`observability-langfuse.yaml` использует локальные dev-секреты по умолчанию. Для staging/production их нужно заменить.

```bash
docker compose -f deploy/compose/base.yaml --profile DEV up -d
```

Пример для PROD:

```dotenv
GPT2GIGA_MODE=PROD
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<strong-secret>
GPT2GIGA_ENABLED_PROVIDERS=openai
GPT2GIGA_GIGACHAT_API_MODE=v1
```

```bash
docker compose -f deploy/compose/base.yaml --profile PROD up -d
```

## Admin и legacy logs

В `DEV` доступны:

- `/admin`
- `/admin/api/version`
- `/admin/api/config`
- `/admin/api/runtime`
- `/admin/api/routes`
- `/admin/api/capabilities`
- `/admin/api/requests/recent`
- `/admin/api/errors/recent`
- `/admin/api/logs`
- `/admin/api/logs/stream`

Legacy endpoints:

- `/logs`
- `/logs/stream`
- `/logs/html`

`/logs/html` больше не является отдельным UI и работает как deprecated redirect на `/admin?tab=logs`.

Если включен `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, admin endpoints требуют тот же API key, что и provider routes.

Если задан `GPT2GIGA_LOGS_IP_ALLOWLIST`, он применяется и к `/admin*`, и к `/logs*`.

## Metrics и observability

`/metrics`:

- доступен в `DEV` и `PROD`;
- публикуется только если включен sink `prometheus`;
- при API-key auth защищается тем же ключом.

Admin UI и admin API используют structured request audit feed:

- recent requests;
- recent errors;
- filters по `provider` и `endpoint` на API-уровне;
- runtime summary с `enabled_providers`, `gigachat_api_mode`, `runtime_store_backend`, `observability_sinks`.

Для runtime storage доступны built-in backend-ы:

- `memory` — process-local dict/ring-buffer storage;
- `sqlite` — durable/queryable SQLite storage для metadata stores и recent feeds.

Пример:

```dotenv
GPT2GIGA_RUNTIME_STORE_BACKEND=sqlite
GPT2GIGA_RUNTIME_STORE_DSN=sqlite:///var/lib/gpt2giga/runtime.db
GPT2GIGA_RUNTIME_STORE_NAMESPACE=prod-main
```

Telemetry sink layer можно отключить отдельно:

```dotenv
GPT2GIGA_ENABLE_TELEMETRY=false
```

Это оставит working recent request/error feeds для `/admin`, но выключит
Prometheus/OTLP/Langfuse fan-out и сделает `/metrics` недоступным.

Встроенные telemetry sink-и:

- `prometheus` — in-process counters/histograms с публикацией на `/metrics`;
- `otlp` — OTLP/HTTP trace export в Collector/APM backend;
- `langfuse` — OTLP/HTTP export напрямую в Langfuse.

Готовые compose override-файлы:

- `deploy/compose/observability-prometheus.yaml`
- `deploy/compose/observability-otlp.yaml`
- `deploy/compose/observability-langfuse.yaml`

Scaffolding для custom runtime backend-ов и compose-примеры для Redis/Postgres/S3:

- [deploy/compose/runtime-backends/README.md](../deploy/compose/runtime-backends/README.md)

## Рекомендуемый rollout

1. Для локальной разработки используйте `DEV`, `prometheus`, и только нужные provider-ы.
2. Для staging поднимайте отдельный instance с `GPT2GIGA_GIGACHAT_API_MODE=v2`.
3. Для production ограничивайте `GPT2GIGA_ENABLED_PROVIDERS` только реально используемыми API surfaces.
4. `PROD` запускайте только с API key и внешним TLS/reverse proxy.
