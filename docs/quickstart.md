# Быстрый старт

Этот документ помогает быстро запустить OpenAI/Anthropic-compatible прокси к GigaChat.

## Требования

- Python 3.10–3.14 для локального запуска.
- `uv` для локальной разработки.
- Docker с Compose plugin для контейнерного запуска.
- GigaChat credentials и scope для нужного аккаунта.

## Настройка credentials

Создайте локальный env-файл:

```sh
cp .env.example .env
```

Минимально заполните:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<local-proxy-api-key>"
GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

Настройки GigaChat SDK используют префикс `GIGACHAT_`. Настройки прокси используют префикс `GPT2GIGA_`.

## Запуск через Docker Compose

DEV profile:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

PROD profile:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

В `PROD` compose-файл по умолчанию привязывает service только к `127.0.0.1`. Для внешнего доступа поставьте nginx, Traefik, Caddy или другой reverse proxy.

Проверка:

```sh
curl http://localhost:8090/health
```

## Локальный запуск

Установить как tool:

```sh
uv tool install gpt2giga
gpt2giga
```

Или запустить из репозитория:

```sh
uv sync --all-extras --dev
uv run gpt2giga
```

В `DEV` FastAPI docs доступны на `http://localhost:8090/docs`. В `PROD` они отключены.

## OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090/v1", api_key="<local-proxy-api-key>")

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[{"role": "user", "content": "Кратко объясни SSE"}],
)
print(completion.choices[0].message.content)
```

## Anthropic SDK

```python
from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090", api_key="<local-proxy-api-key>")

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=512,
    messages=[{"role": "user", "content": "Кратко объясни SSE"}],
)
print(message.content[0].text)
```

## GigaChat auth для каждого request

Если клиент должен передавать GigaChat auth через `Authorization`, включите:

```dotenv
GPT2GIGA_PASS_TOKEN=True
```

Поддержанные значения заголовка:

- `giga-cred-<credentials>:<scope>` для GigaChat authorization key credentials;
- `giga-auth-<access_token>` для готового access token;
- `giga-user-<user>:<password>` для user/password auth.

Для типовых deployment-сценариев предпочтительнее серверные `GIGACHAT_*` credentials. Включайте `GPT2GIGA_PASS_TOKEN=True`, только если нужны client-specific upstream credentials.

## Примеры

- OpenAI Chat Completions: [examples/openai/chat_completions/README.md](../examples/openai/chat_completions/README.md)
- OpenAI Responses: [examples/openai/responses/README.md](../examples/openai/responses/README.md)
- Anthropic Messages: [examples/anthropic/README.md](../examples/anthropic/README.md)
- Все примеры: [examples/README.md](../examples/README.md)
