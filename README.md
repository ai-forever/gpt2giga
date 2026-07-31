# gpt2giga

[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/ai-forever/gpt2giga/ci.yaml?&style=flat-square)](https://github.com/ai-forever/gpt2giga/actions/workflows/ci.yaml)
[![PyPI](https://img.shields.io/pypi/v/gpt2giga?style=flat-square&label=PyPI)](https://pypi.org/project/gpt2giga/)
[![Python](https://img.shields.io/pypi/pyversions/gpt2giga?style=flat-square)](https://pypi.org/project/gpt2giga/)
[![GitHub License](https://img.shields.io/github/license/ai-forever/gpt2giga?style=flat-square)](https://opensource.org/licenses/MIT)
[![PyPI Downloads](https://img.shields.io/pypi/dm/gpt2giga?style=flat-square)](https://pypistats.org/packages/gpt2giga)
[![GitHub Repo stars](https://img.shields.io/github/stars/ai-forever/gpt2giga?style=flat-square)](https://star-history.com/#ai-forever/gpt2giga)
[![GitHub Open Issues](https://img.shields.io/github/issues-raw/ai-forever/gpt2giga?style=flat-square)](https://github.com/ai-forever/gpt2giga/issues)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-111827?style=flat-square)](https://ai-forever.github.io/gpt2giga/)
[![GigaLoom](https://img.shields.io/badge/agentic_workbench-GigaLoom-7c3aed?style=flat-square)](https://github.com/krakenalt/gigaloom)

![Gateway coverage](https://raw.githubusercontent.com/ai-forever/gpt2giga/main/badges/coverage.svg)

`gpt2giga` — FastAPI-прокси, который принимает OpenAI-, Anthropic- и Gemini-like запросы и отправляет их в GigaChat. Он нужен, когда клиент, редактор, агентный фреймворк или SDK умеет работать с OpenAI/Anthropic/Gemini API, а реальный backend должен быть GigaChat.

Локальный адрес по умолчанию: `http://localhost:8090`.

> GigaLoom, локальный agentic workbench и бывший Unified Harness, развивается
> отдельно в [`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom).
> Этот репозиторий и пакет `gpt2giga` содержат только compatibility gateway.
> Старые ссылки собраны в [уведомлении о переносе](https://ai-forever.github.io/gpt2giga/gigaloom-migration).

## Зачем Нужен

GigaChat не является drop-in заменой OpenAI или Anthropic API. Прямое подключение существующих SDK часто ломается на формате запросов, streaming-событиях, tool schemas, model discovery, авторизации и optional-параметрах клиентов.

`gpt2giga` закрывает практические несовместимости:

- переводит OpenAI Chat Completions, OpenAI Responses, OpenAI Embeddings, Anthropic Messages и Gemini GenerateContent в вызовы GigaChat;
- маппит tools/function calling, structured output, изображения, reasoning flags и SSE streaming там, где GigaChat поддерживает базовую возможность;
- принимает и безопасно игнорирует optional-поля OpenAI/Anthropic, которые SDK присылают, но GigaChat не понимает;
- фильтрует транспортные SDK headers, клиентские API keys, cookies и другие небезопасные метаданные перед upstream;
- отделяет клиентскую API-key авторизацию прокси от GigaChat credentials;
- отдаёт список моделей в OpenAI-, Anthropic-, Gemini- и LiteLLM-совместимом виде;
- держит batch/file routes отключёнными, пока их нельзя выполнить end-to-end через GigaChat SDK/backend.

Подробная матрица поддержки и список реальных ограничений вынесены в [API Compatibility](https://ai-forever.github.io/gpt2giga/api-compatibility).

## Быстрый Старт

Создайте `.env` из шаблона и заполните GigaChat credentials:

```sh
cp .env.example .env
```

Запуск через Docker Compose:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

Или локальная установка gateway:

```sh
uv tool install gpt2giga
gpt2giga --help
```

Для установки в существующее окружение:

```sh
python -m pip install gpt2giga
```

Поддерживается Python 3.10–3.14. Для Postgres, OpenSearch или Phoenix добавьте
соответствующую extra-зависимость, например:

```sh
python -m pip install "gpt2giga[postgres]"
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

Больше вариантов запуска — в [Quickstart](https://ai-forever.github.io/gpt2giga/quickstart).

## Документация

Полная документация публикуется на [GitHub Pages](https://ai-forever.github.io/gpt2giga/).

Локально проверить docs можно через Docusaurus wrapper в `docs-site/`:

```sh
make docs-install
make docs
```

После `make docs` сайт доступен на `http://127.0.0.1:3000/` и включает локали `en`/`ru`.
Для быстрой разработки с hot reload:

```sh
make docs-dev
```

Docusaurus dev server обслуживает одну локаль за запуск. Для русского dev preview:

```sh
make docs-dev-ru
```

Чтобы проверить переключатель языков между `en` и `ru`, используйте full preview через `make docs` или `make docs-preview`.

| Тема | Документ |
|---|---|
| Быстрый запуск и первые запросы | [Quickstart](https://ai-forever.github.io/gpt2giga/quickstart) |
| Что поддерживается, отключено или намеренно игнорируется | [API compatibility](https://ai-forever.github.io/gpt2giga/api-compatibility) |
| Совместимость SDK `extra_*` и параметров клиентов | [Client parameter compatibility](https://ai-forever.github.io/gpt2giga/client-parameter-compatibility) |
| Встроенные инструменты GigaChat и маппинг OpenAI/Anthropic/Gemini | [Built-in tools](https://ai-forever.github.io/gpt2giga/builtin-tools) |
| Переменные окружения, CLI flags, backend modes | [Configuration](https://ai-forever.github.io/gpt2giga/configuration) |
| Docker Compose, Traefik, Postgres, OpenSearch, Phoenix, production hardening | [Deployment](https://ai-forever.github.io/gpt2giga/deployment) |
| Logs, metrics, traffic logs, admin API, debug translation | [Operations](https://ai-forever.github.io/gpt2giga/operations) |
| Live GigaChat integration tests | [Live integration tests](https://ai-forever.github.io/gpt2giga/live-integration-tests) |
| Внутренняя архитектура normalized messages | [Normalized messages](https://ai-forever.github.io/gpt2giga/architecture/normalized-messages) |
| Checklist для добавления provider/protocol | [How to add a provider](https://ai-forever.github.io/gpt2giga/architecture/how-to-add-provider) |
| Редакторы, агенты, SDK examples, reverse proxies | [Integrations](https://ai-forever.github.io/gpt2giga/integrations) |
| Runnable-примеры | [Examples](https://github.com/ai-forever/gpt2giga/tree/main/examples) |
| История изменений gateway | [RU](https://github.com/ai-forever/gpt2giga/blob/main/CHANGELOG.md) · [EN](https://github.com/ai-forever/gpt2giga/blob/main/CHANGELOG_en.md) |
| GigaLoom и старые Harness URL | [Уведомление о переносе](https://ai-forever.github.io/gpt2giga/gigaloom-migration) |

## Текущая API-Поверхность

Смонтированные routes доступны в корне и под versioned prefixes. Root routes
используют `GPT2GIGA_GIGACHAT_API_MODE`, `/v1` принудительно выбирает GigaChat
v1 contract, `/v2` принудительно выбирает GigaChat v2 contract. Например:
`/chat/completions`, `/v1/chat/completions` и `/v2/chat/completions`.

Поддерживается:

- OpenAI-compatible `GET /models`, `GET /models/{model}`, `POST /chat/completions`, `POST /responses`, `POST /embeddings`;
- Anthropic-compatible `POST /messages`, `POST /messages/count_tokens`, а также Anthropic-shaped model responses для model-вызовов Anthropic SDK;
- Gemini-compatible `/v1beta/models/{model}:generateContent`, `:streamGenerateContent`, `:countTokens`, `:embedContent`, `:batchEmbedContents`, а также `/v1beta/models`;
- LiteLLM-compatible `GET /model/info`;
- системные endpoints `GET /health` и `GET|POST /ping`.

Отключено до появления нужных batch methods в GigaChat SDK/backend:

- OpenAI-compatible Files API и Batches API;
- Anthropic Message Batches API.
- Gemini-compatible Files API и Batch GenerateContent API.

Сейчас не является целью проекта:

- полная OpenAI parity для audio, image generation/editing, fine-tuning, assistants, threads, runs, vector stores, uploads, moderations, realtime;
- полная Anthropic parity для Files beta, Skills beta, Agents beta, Sessions, Environments или Admin API;
- полная Gemini parity для Files, batchGenerateContent, cached content, Vertex/RAG tools и non-text embeddings content.

## Деплой

Docker Compose manifests лежат в [deploy/](https://github.com/ai-forever/gpt2giga/tree/main/deploy):

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

Compose profiles, reverse proxies, TLS и hardening описаны в [Deployment](https://ai-forever.github.io/gpt2giga/deployment).

## Структура Репозитория

| Path | Назначение |
|---|---|
| `src/gpt2giga/` | FastAPI app, routers, protocol transforms, config, middleware |
| `tests/` | Unit, router, protocol, sink и integration tests |
| `examples/` | Runnable OpenAI, Anthropic, Gemini, embeddings and agents examples; files/batches examples are prepared but not mounted |
| `docs/` | Markdown-контент пользовательской документации и architecture notes |
| `docs-site/` | Docusaurus wrapper, sidebar/theme config и npm tooling для GitHub Pages |
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

Сборка дистрибутива выполняется явно:

```sh
uv build
```

Проверки перед PR:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

Live-тесты с реальными вызовами GigaChat запускаются отдельно и требуют
локальных секретов: см. [Live GigaChat Integration Tests](https://ai-forever.github.io/gpt2giga/live-integration-tests).

Используйте Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`) и сверяйтесь с [PR template](https://github.com/ai-forever/gpt2giga/blob/main/.github/PULL_REQUEST_TEMPLATE.md).
