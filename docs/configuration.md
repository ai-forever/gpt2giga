# Конфигурация и запуск

Этот документ собирает практическую конфигурацию `gpt2giga`: как запускать proxy локально и в Docker, какие переменные менять чаще всего, когда включать API-key auth, pass-token режим и HTTPS.

Полный пример конфигурации находится в [../.env.example](../.env.example), а полный список CLI-аргументов всегда доступен через `gpt2giga --help`.

## Где настраивать сервис

Обычно используют три источника конфигурации:

- `.env` в корне проекта или в текущей рабочей директории;
- обычные переменные окружения;
- CLI-флаги `gpt2giga`.

Практическое правило простое: базовую конфигурацию храните в `.env`, а CLI используйте для локальных точечных override-ов.

## Быстрые профили

### Локальная разработка

```bash
cp .env.example .env
uv sync --all-extras --dev
uv run gpt2giga
```

Минимальный `.env`:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<your_api_key>"
GIGACHAT_CREDENTIALS="<your_gigachat_credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

В `DEV` режиме доступны:

- `/docs`, `/redoc`, `/openapi.json`;
- `/admin` и `/admin/api/*`;
- `/admin/api/logs` и `/admin/api/logs/stream`.

### Минимальный production

```dotenv
GPT2GIGA_MODE=PROD
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong_secret>"
GPT2GIGA_CORS_ALLOW_ORIGINS=["https://your-app.example.com"]
GIGACHAT_CREDENTIALS="<your_gigachat_credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

В `PROD` режиме автоматически отключаются:

- `/docs`, `/redoc`, `/openapi.json`;
- `/admin*`;
- `/admin/api/logs*`.

### Docker / Compose

Базовый single-instance запуск:

```bash
cp .env.example .env
docker compose -f deploy/compose/base.yaml --profile DEV up -d
```

Полезные compose-стеки:

- `deploy/compose/base.yaml` — один instance;
- `deploy/compose/traefik.yaml` — Traefik + несколько инстансов;
- `deploy/compose/observability-prometheus.yaml` — Prometheus scrape для `/metrics`;
- `deploy/compose/observability-otlp.yaml` — OTLP Collector для trace export-а;
- `deploy/compose/observability-langfuse.yaml` — локальный Langfuse stack;
- `deploy/compose/observability-phoenix.yaml` — локальный Phoenix stack;
- `deploy/compose/observability.yaml` — debug/inspection сценарии;
- `deploy/compose/runtime-backends/README.md` — runtime store backends.

## Основные переменные окружения

### Proxy и runtime

| Переменная | Для чего нужна |
|---|---|
| `GPT2GIGA_MODE` | Режим `DEV` или `PROD` |
| `GPT2GIGA_HOST` | Bind host proxy-сервера |
| `GPT2GIGA_PORT` | Bind port |
| `GPT2GIGA_ENABLE_API_KEY_AUTH` | Включает API-key auth на пользовательских endpoint-ах |
| `GPT2GIGA_API_KEY` | Глобальный API key с полным доступом |
| `GPT2GIGA_ENABLED_PROVIDERS` | Какие provider-роуты монтировать: `openai`, `anthropic`, `gemini`, `all` |
| `GPT2GIGA_GIGACHAT_API_MODE` | Backend mode для chat-like flows: `v1` или `v2` |
| `GPT2GIGA_RUNTIME_STORE_BACKEND` | Где хранить runtime metadata: `memory` или `sqlite` |
| `GPT2GIGA_RUNTIME_STORE_DSN` | Файл/DSN для runtime store backend-а |
| `GPT2GIGA_ENABLE_TELEMETRY` | Включает fan-out в telemetry sinks |
| `GPT2GIGA_OBSERVABILITY_SINKS` | Встроенные sinks: `prometheus`, `otlp`, `langfuse`, `phoenix`, либо `none` |
| `GPT2GIGA_OTLP_TRACES_ENDPOINT` | Полный OTLP/HTTP traces endpoint (`.../v1/traces`) |
| `GPT2GIGA_OTLP_HEADERS` | Дополнительные headers для OTLP export-а |
| `GPT2GIGA_OTLP_TIMEOUT_SECONDS` | Таймаут одного OTLP export request |
| `GPT2GIGA_OTLP_MAX_PENDING_REQUESTS` | Максимум in-flight OTLP exports |
| `GPT2GIGA_OTLP_SERVICE_NAME` | `service.name` resource attribute для OTLP/Langfuse/Phoenix |
| `GPT2GIGA_LANGFUSE_BASE_URL` | Base URL Langfuse instance-а |
| `GPT2GIGA_LANGFUSE_PUBLIC_KEY` | Public key для Langfuse ingest-а |
| `GPT2GIGA_LANGFUSE_SECRET_KEY` | Secret key для Langfuse ingest-а |
| `GPT2GIGA_PHOENIX_BASE_URL` | Base URL Phoenix instance-а |
| `GPT2GIGA_PHOENIX_API_KEY` | API key для Phoenix ingest-а (`Authorization: Bearer ...`) |
| `GPT2GIGA_PHOENIX_PROJECT_NAME` | Phoenix/OpenInference project name |
| `GPT2GIGA_ENABLE_REASONING` | По умолчанию добавляет `reasoning_effort="high"` для GigaChat, если клиент не указал его явно |
| `GPT2GIGA_CORS_ALLOW_ORIGINS` | CORS origins в JSON-массиве |
| `GPT2GIGA_MAX_REQUEST_BODY_BYTES` | Глобальный лимит размера request body |
| `GPT2GIGA_TRUSTED_PROXY_CIDRS` | Reverse proxy IP/CIDR, от которых можно доверять `X-Forwarded-For` |

### GigaChat backend

| Переменная | Для чего нужна |
|---|---|
| `GIGACHAT_MODEL` | Модель GigaChat по умолчанию |
| `GIGACHAT_CREDENTIALS` | Authorization key / credentials |
| `GIGACHAT_SCOPE` | Scope для credentials |
| `GIGACHAT_ACCESS_TOKEN` | Альтернативная авторизация access token-ом |
| `GIGACHAT_USER`, `GIGACHAT_PASSWORD` | Альтернативная авторизация логином и паролем |
| `GIGACHAT_TIMEOUT` | Таймаут запросов к GigaChat |
| `GIGACHAT_VERIFY_SSL_CERTS` | Проверка TLS-сертификатов upstream GigaChat |
| `GIGACHAT_CA_BUNDLE_FILE` | Путь к PEM CA bundle для corporate/self-signed TLS chain |
| `GIGACHAT_MAX_CONNECTIONS` | Предел одновременных подключений |
| `GIGACHAT_MAX_RETRIES` | Retry count для временных ошибок |

### Продвинутые настройки

| Переменная | Для чего нужна |
|---|---|
| `GPT2GIGA_SCOPED_API_KEYS` | Scoped API keys с ограничениями по provider, endpoint и model |
| `GPT2GIGA_GOVERNANCE_LIMITS` | Fixed-window лимиты по запросам и токенам |
| `GPT2GIGA_LOGS_IP_ALLOWLIST` | Allowlist для admin surface в `DEV`; имя переменной сохранено для обратной совместимости конфигурации |

## Trusted proxy и `X-Forwarded-For`

По умолчанию `gpt2giga` не доверяет `X-Forwarded-For` и использует прямой peer IP от ASGI-сервера. Это означает, что прямой клиент не может подменить admin allowlist или observability-поля, просто прислав этот header.

Если proxy стоит за Nginx, Traefik или другим reverse proxy и вам нужно видеть исходный клиентский IP, явно перечислите доверенные proxy IP/CIDR:

```dotenv
GPT2GIGA_TRUSTED_PROXY_CIDRS=["10.0.0.0/24","127.0.0.1/32"]
```

После этого `X-Forwarded-For` учитывается только для запросов, пришедших от одного из этих доверенных proxy. Для прямых клиентов header по-прежнему игнорируется.

## Runtime switches

Чаще всего меняют именно эти переключатели:

```dotenv
# Только OpenAI-compatible routes + LiteLLM /model/info
GPT2GIGA_ENABLED_PROVIDERS=openai
GPT2GIGA_GIGACHAT_API_MODE=v1
```

```dotenv
# OpenAI + Gemini
GPT2GIGA_ENABLED_PROVIDERS=openai,gemini
GPT2GIGA_GIGACHAT_API_MODE=v1
```

```dotenv
# Полный набор provider-ов и backend v2
GPT2GIGA_ENABLED_PROVIDERS=all
GPT2GIGA_GIGACHAT_API_MODE=v2
```

За operational-смыслом этих переключателей лучше идти в [operator-guide.md](./operator-guide.md).

## API-key auth

Минимальная конфигурация:

```dotenv
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong_secret>"
```

Поддерживаемые способы передачи ключа:

- `x-api-key`;
- `Authorization: Bearer ...`;
- `x-goog-api-key` для Gemini-compatible клиентов;
- query-параметр `key` для Gemini-compatible клиентов.

Пример для OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="123")
```

Пример для Gemini SDK:

```python
from google import genai
from google.genai import types

client = genai.Client(
    api_key="123",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)
```

### Scoped API keys и governance limits

Если одного global API key мало, можно:

- завести scoped keys через `GPT2GIGA_SCOPED_API_KEYS`;
- ограничить burst/token quota через `GPT2GIGA_GOVERNANCE_LIMITS`.

Пример:

```dotenv
GPT2GIGA_SCOPED_API_KEYS=[{"name":"sdk-openai","key":"scoped-123","providers":["openai"],"endpoints":["chat/completions"],"models":["GigaChat-2-Max"]}]
GPT2GIGA_GOVERNANCE_LIMITS=[{"name":"openai-burst","scope":"api_key","providers":["openai"],"endpoints":["chat/completions"],"window_seconds":60,"max_requests":30}]
```

## Передача авторизации через `Authorization`

Если нужен режим, в котором клиенты передают учетные данные GigaChat напрямую, включите:

```dotenv
GPT2GIGA_PASS_TOKEN=True
```

Или запустите:

```bash
gpt2giga --proxy.pass-token true
```

Поддерживаемые форматы:

- `giga-cred-<credentials>:<scope>`;
- `giga-auth-<access_token>`;
- `giga-user-<user>:<password>`.

Пример:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8090",
    api_key="giga-cred-<credentials>:<scope>",
)
```

Если хотите, чтобы клиентская модель пробрасывалась в upstream без замены на `GIGACHAT_MODEL`, включите:

```dotenv
GPT2GIGA_PASS_MODEL=True
```

## HTTPS

Встроенный HTTPS можно включить прямо на proxy:

```dotenv
GPT2GIGA_USE_HTTPS=True
GPT2GIGA_HTTPS_KEY_FILE="/path/to/key.pem"
GPT2GIGA_HTTPS_CERT_FILE="/path/to/cert.pem"
```

Пример генерации self-signed сертификата:

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
  -keyout key.pem \
  -out cert.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Для production обычно удобнее терминировать TLS на reverse proxy. Готовый guide:

- [integrations/nginx/README.md](./integrations/nginx/README.md)

## CLI-флаги

Полный список аргументов смотрите в `gpt2giga --help`. На практике чаще нужны:

- `--env-path` — путь до `.env`;
- `--proxy.host`, `--proxy.port` — bind host/port;
- `--proxy.pass-model`, `--proxy.pass-token` — проброс модели и авторизации;
- `--proxy.embeddings` — модель для embeddings;
- `--proxy.enable-api-key-auth`, `--proxy.api-key` — защита endpoint-ов;
- `--gigachat.model`, `--gigachat.timeout`, `--gigachat.verify-ssl-certs` — upstream GigaChat параметры.

Пример:

```bash
gpt2giga \
  --proxy.host 127.0.0.1 \
  --proxy.port 8080 \
  --proxy.pass-model true \
  --proxy.pass-token true \
  --gigachat.model GigaChat-2-Max \
  --gigachat.timeout 300
```

Секреты лучше не передавать флагами: они видны в `ps aux`.

## Что доступно в `DEV` и `PROD`

| Endpoint / surface | `DEV` | `PROD` |
|---|---|---|
| `/docs`, `/redoc`, `/openapi.json` | Да | Нет |
| `/admin` и `/admin/api/*` | Да | Нет |
| `/admin/api/logs*` | Да | Нет |
| `/metrics` | Да | Да |
| Provider routes | Да | Да |

Если включен `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, `/metrics` и пользовательские endpoint-ы защищаются тем же API key.

## Production checklist

- Установите `GPT2GIGA_MODE=PROD`.
- Включите `GPT2GIGA_ENABLE_API_KEY_AUTH=True`.
- Используйте сильный `GPT2GIGA_API_KEY`.
- Не отключайте `GIGACHAT_VERIFY_SSL_CERTS`.
- Ограничьте `GPT2GIGA_CORS_ALLOW_ORIGINS` конкретными origin-ами.
- Не передавайте секреты через CLI-флаги.
- Используйте HTTPS или reverse proxy с TLS termination.
- Не держите `GPT2GIGA_LOG_LEVEL=DEBUG` в production.
