# gpt2giga

[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/ai-forever/gpt2giga/ci.yaml?&style=flat-square)](https://github.com/ai-forever/gpt2giga/actions/workflows/ci.yaml)
[![GitHub License](https://img.shields.io/github/license/ai-forever/gpt2giga?style=flat-square)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://img.shields.io/pypi/dm/gpt2giga?style=flat-square)](https://pypistats.org/packages/gpt2giga)
[![GitHub Repo stars](https://img.shields.io/github/stars/ai-forever/gpt2giga?style=flat-square)](https://star-history.com/#ai-forever/gpt2giga)
[![GitHub Open Issues](https://img.shields.io/github/issues-raw/ai-forever/gpt2giga?style=flat-square)](https://github.com/ai-forever/gpt2giga/issues)
[![Telegram](https://img.shields.io/badge/Telegram-chat-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://t.me/krakenalt)

![Coverage](./badges/coverage.svg)

`gpt2giga` — FastAPI-прокси, который принимает OpenAI-совместимые и Anthropic-совместимые запросы и отправляет их в GigaChat. Он нужен, когда клиент, редактор, агентный фреймворк или SDK умеет работать с OpenAI/Anthropic API, а реальный backend должен быть GigaChat.

Локальный адрес по умолчанию: `http://localhost:8090`.

## Зачем Нужен

GigaChat не является drop-in заменой OpenAI или Anthropic API. Прямое подключение существующих SDK часто ломается на формате запросов, streaming-событиях, tool schemas, model discovery, авторизации и optional-параметрах клиентов.

`gpt2giga` закрывает практические несовместимости:

- переводит OpenAI Chat Completions, OpenAI Responses, OpenAI Embeddings и Anthropic Messages в вызовы GigaChat;
- маппит tools/function calling, structured output, изображения, reasoning flags и SSE streaming там, где GigaChat поддерживает базовую возможность;
- принимает и безопасно игнорирует optional-поля OpenAI/Anthropic, которые SDK присылают, но GigaChat не понимает;
- фильтрует транспортные SDK headers, клиентские API keys, cookies и другие небезопасные метаданные перед upstream;
- отделяет клиентскую API-key авторизацию прокси от GigaChat credentials;
- отдаёт список моделей в OpenAI-, Anthropic- и LiteLLM-совместимом виде;
- держит batch/file routes отключёнными, пока их нельзя выполнить end-to-end через GigaChat SDK/backend.

Подробная матрица поддержки и список реальных ограничений вынесены в [API Compatibility](./docs/api-compatibility.md).

## Быстрый Старт

Создайте `.env` из шаблона и заполните GigaChat credentials:

```sh
cp .env.example .env
```

Запуск через Docker Compose:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

Или локальный запуск:

```sh
uv tool install gpt2giga
gpt2giga
```

Минимальный OpenAI SDK вызов:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090/v1", api_key="<GPT2GIGA_API_KEY>")

response = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[{"role": "user", "content": "Привет"}],
)
print(response.choices[0].message.content)
```

Минимальный Anthropic SDK вызов:

```python
from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090", api_key="<GPT2GIGA_API_KEY>")

response = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=256,
    messages=[{"role": "user", "content": "Привет"}],
)
print(response.content[0].text)
```

Больше вариантов запуска — в [Quickstart](./docs/quickstart.md).

## Документация

| Тема | Документ |
|---|---|
| Быстрый запуск и первые запросы | [docs/quickstart.md](./docs/quickstart.md) |
| Что поддерживается, отключено или намеренно игнорируется | [docs/api-compatibility.md](./docs/api-compatibility.md) |
| Совместимость SDK `extra_*` и параметров клиентов | [docs/client-parameter-compatibility.md](./docs/client-parameter-compatibility.md) |
| Переменные окружения, CLI flags, backend modes | [docs/configuration.md](./docs/configuration.md) |
| Docker Compose, Traefik, Postgres, OpenSearch, Phoenix, production hardening | [docs/deployment.md](./docs/deployment.md) |
| Logs, metrics, traffic logs, admin API, debug translation | [docs/operations.md](./docs/operations.md) |
| Внутренняя архитектура normalized messages | [docs/architecture/normalized-messages.md](./docs/architecture/normalized-messages.md) |
| Checklist для добавления provider/protocol | [docs/architecture/how-to-add-provider.md](./docs/architecture/how-to-add-provider.md) |
| Редакторы, агенты, SDK examples, reverse proxies | [docs/integrations.md](./docs/integrations.md) |
| Runnable-примеры | [examples/README.md](./examples/README.md) |

## Текущая API-Поверхность

Смонтированные routes доступны и в корне, и под `/v1`, например `/chat/completions` и `/v1/chat/completions`.

Поддерживается:

- OpenAI-compatible `GET /models`, `GET /models/{model}`, `POST /chat/completions`, `POST /responses`, `POST /embeddings`;
- Anthropic-compatible `POST /messages`, `POST /messages/count_tokens`, а также Anthropic-shaped model responses для model-вызовов Anthropic SDK;
- LiteLLM-compatible `GET /model/info`;
- системные endpoints `GET /health` и `GET|POST /ping`.

Отключено до появления нужных batch methods в GigaChat SDK/backend:

- OpenAI-compatible Files API и Batches API;
- Anthropic Message Batches API.

Сейчас не является целью проекта:

- полная OpenAI parity для audio, image generation/editing, fine-tuning, assistants, threads, runs, vector stores, uploads, moderations, realtime;
- полная Anthropic parity для Files beta, Skills beta, Agents beta, Sessions, Environments или Admin API.

## Деплой

Docker Compose manifests лежат в [deploy/](./deploy/):

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

Production mode требует API key и отключает `/docs`, `/redoc`, `/openapi.json` и `/logs*`:

```dotenv
GPT2GIGA_MODE=PROD
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong-random-secret>"
GIGACHAT_VERIFY_SSL_CERTS=True
```

Compose profiles, reverse proxies, TLS и hardening описаны в [Deployment](./docs/deployment.md).

## Структура Репозитория

| Path | Назначение |
|---|---|
| `gpt2giga/` | FastAPI app, routers, protocol transforms, config, middleware |
| `tests/` | Unit, router, protocol, sink и integration tests |
| `examples/` | Runnable OpenAI, Anthropic, embeddings, files/batches, agents examples |
| `docs/` | Пользовательская документация и architecture notes |
| `integrations/` | Editor/agent/reverse-proxy integration guides |
| `deploy/` | Docker Compose deployment manifests |
| `traefik/` | Traefik config для `deploy/traefik.yaml` |
| `.github/` | CI, release, Docker publish, PR/issue templates |

## Разработка

Установить зависимости:

```sh
uv sync --all-extras --dev
```

Запустить сервис:

```sh
uv run gpt2giga
```

Проверки перед PR:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

Используйте Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`) и сверяйтесь с `.github/PULL_REQUEST_TEMPLATE.md`.
