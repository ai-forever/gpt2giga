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

Env template для копирования: [.env.example](../.env.example).

## Основные proxy settings

| Переменная | Default | Назначение |
|---|---:|---|
| `GPT2GIGA_MODE` | `DEV` | `DEV` или `PROD`. `PROD` отключает `/docs`, `/redoc`, `/openapi.json` и `/logs*`. |
| `GPT2GIGA_HOST` | `localhost` | Host локального сервера. |
| `GPT2GIGA_PORT` | `8090` | Port локального сервера. |
| `GPT2GIGA_ENABLE_API_KEY_AUTH` | `False` | Требовать proxy API-key auth для публичных API routes. В `PROD` обязательно. |
| `GPT2GIGA_API_KEY` | empty | Proxy API key. Для общих окружений используйте сильное случайное значение. |
| `GPT2GIGA_PASS_MODEL` | `True` | Передавать `model` из запроса в GigaChat. Поставьте `False`, чтобы всегда использовать настроенную GigaChat model. |
| `GPT2GIGA_PASS_TOKEN` | `False` | Разбирать client `Authorization` как GigaChat credentials для per-request upstream auth. |
| `GPT2GIGA_EMBEDDINGS` | `EmbeddingsGigaR` | Default embeddings model, если model из запроса не используется. |
| `GPT2GIGA_MAX_REQUEST_BODY_BYTES` | `10485760` | Максимальный размер HTTP request body. |
| `GPT2GIGA_LOG_LEVEL` | `INFO` | Runtime log level. В production избегайте `DEBUG`. |

## GigaChat settings

Частые upstream settings:

| Переменная | Назначение |
|---|---|
| `GIGACHAT_CREDENTIALS` | Credentials authorization key. |
| `GIGACHAT_SCOPE` | GigaChat API scope. |
| `GIGACHAT_USER` / `GIGACHAT_PASSWORD` | Альтернативная user/password auth. |
| `GIGACHAT_ACCESS_TOKEN` | Альтернативная auth через готовый access token. |
| `GIGACHAT_MODEL` | Default model. |
| `GIGACHAT_VERIFY_SSL_CERTS` | В production держите `True`. |
| `GIGACHAT_TIMEOUT` | Upstream request timeout. |
| `GIGACHAT_MAX_CONNECTIONS` | Global SDK/HTTP connection cap. |
| `GIGACHAT_MAX_RETRIES` | SDK retry count для временных upstream errors. |

GigaChat также поддерживает TLS client certificate settings: `GIGACHAT_CA_BUNDLE_FILE`, `GIGACHAT_CERT_FILE`, `GIGACHAT_KEY_FILE`, `GIGACHAT_KEY_FILE_PASSWORD`.

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

## Backend API mode

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
GPT2GIGA_RESPONSES_API_MODE=inherit
```

| `GPT2GIGA_GIGACHAT_API_MODE` | `GPT2GIGA_RESPONSES_API_MODE` | `/chat/completions` backend | `/responses` backend |
|---|---|---|---|
| `v1` | `inherit` | `v1` | `v1` |
| `v2` | `inherit` | `v2` | `v2` |
| `v1` | `v2` | `v1` | `v2` |
| `v2` | `v1` | `v2` | `v1` |

Внешние OpenAI-compatible URLs не меняются. Эти flags управляют только внутренним способом вызова GigaChat.

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
