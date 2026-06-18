# Быстрый старт

Этот документ помогает быстро запустить прокси к GigaChat, совместимый с OpenAI и Anthropic.

## Требования

- Python 3.10–3.14 для локального запуска.
- `uv` для локальной разработки.
- Docker с плагином Compose для контейнерного запуска.
- Учётные данные и scope GigaChat для нужного аккаунта.

## Настройка учётных данных

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

Профиль DEV:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

Профиль PROD:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

В `PROD` compose-файл по умолчанию привязывает сервис только к `127.0.0.1`. Для внешнего доступа поставьте nginx, Traefik, Caddy или другой обратный прокси.

Проверка:

```sh
curl http://localhost:8090/health
```

## Локальный запуск

Установить как инструмент:

```sh
uv tool install gpt2giga
gpt2giga
```

Или запустить из репозитория:

```sh
uv sync --all-extras --dev
uv run gpt2giga
```

В `DEV` документация FastAPI доступна на `http://localhost:8090/docs`. В `PROD` она отключена.

## OpenAI SDK

```python
from openai import OpenAI

api_version = "v1"
client = OpenAI(
    base_url=f"http://localhost:8090/{api_version}/",
    api_key="<local-proxy-api-key>",
)

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[{"role": "user", "content": "Кратко объясни SSE"}],
)
print(completion.choices[0].message.content)
```

Для явного выбора контракта бэкенда GigaChat используйте `api_version = "v1"`
или `api_version = "v2"` и подставляйте его в `base_url`. `/v1` всегда
выбирает контракт GigaChat v1, `/v2` — контракт GigaChat v2.
`http://localhost:8090` без версии следует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

## Anthropic SDK

```python
from anthropic import Anthropic

api_version = "v1"
client = Anthropic(
    base_url=f"http://localhost:8090/{api_version}/",
    api_key="<local-proxy-api-key>",
)

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=512,
    messages=[{"role": "user", "content": "Кратко объясни SSE"}],
)
print(message.content[0].text)
```

## Авторизация GigaChat для каждого запроса

Если клиент должен передавать авторизацию GigaChat через `Authorization`, включите:

```dotenv
GPT2GIGA_PASS_TOKEN=True
```

Поддерживаемые значения заголовка:

- `giga-cred-<credentials>:<scope>` для учётных данных по ключу авторизации GigaChat;
- `giga-auth-<access_token>` для готового access-токена;
- `giga-user-<user>:<password>` для авторизации по логину и паролю.

Для типовых сценариев развёртывания предпочтительнее серверные учётные данные `GIGACHAT_*`. Включайте `GPT2GIGA_PASS_TOKEN=True`, только если нужны учётные данные вышестоящего сервиса, специфичные для клиента.

## Примеры

- OpenAI Chat Completions: [examples/openai/chat_completions/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/chat_completions/README.md)
- OpenAI Responses: [examples/openai/responses/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/responses/README.md)
- Anthropic Messages: [examples/anthropic/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/anthropic/README.md)
- Все примеры: [examples/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/README.md)
