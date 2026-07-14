# gpt2giga

[![PyPI](https://img.shields.io/pypi/v/gpt2giga?style=flat-square&label=PyPI)](https://pypi.org/project/gpt2giga/)
[![Python](https://img.shields.io/pypi/pyversions/gpt2giga?style=flat-square)](https://pypi.org/project/gpt2giga/)
[![CI](https://img.shields.io/github/actions/workflow/status/ai-forever/gpt2giga/ci.yaml?style=flat-square)](https://github.com/ai-forever/gpt2giga/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-111827?style=flat-square)](https://ai-forever.github.io/gpt2giga/)
[![License](https://img.shields.io/github/license/ai-forever/gpt2giga?style=flat-square)](https://github.com/ai-forever/gpt2giga/blob/main/LICENSE)

`gpt2giga` — FastAPI-шлюз совместимости между OpenAI-, Anthropic- и
Gemini-совместимыми клиентами и GigaChat. Дистрибутив содержит только gateway:
команду `gpt2giga` и Python namespace `gpt2giga`.

Unified Harness поставляется отдельно в дистрибутиве `gpt2giga-harness` и не
устанавливается вместе с gateway.

## Установка

Для актуального prerelease:

```sh
uv tool install --prerelease allow gpt2giga
gpt2giga --help
```

Или в существующее окружение:

```sh
python -m pip install --pre gpt2giga
```

Поддерживается Python 3.10–3.14. Для Postgres, OpenSearch или Phoenix добавьте
соответствующую extra-зависимость, например:

```sh
python -m pip install --pre "gpt2giga[postgres]"
```

## Минимальная конфигурация

Создайте `.env`:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_HOST=127.0.0.1
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<local-proxy-api-key>"

GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

Запустите gateway и проверьте health endpoint:

```sh
gpt2giga --env-path .env
curl http://127.0.0.1:8090/health
```

В `DEV` интерактивная OpenAPI-документация доступна на
`http://127.0.0.1:8090/docs`. В `PROD` она отключена.

## Первый запрос

OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8090/v1",
    api_key="<local-proxy-api-key>",
)
response = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[{"role": "user", "content": "Кратко объясни SSE"}],
)
print(response.choices[0].message.content)
```

Anthropic SDK:

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="http://127.0.0.1:8090/v1",
    api_key="<local-proxy-api-key>",
)
response = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=512,
    messages=[{"role": "user", "content": "Кратко объясни SSE"}],
)
print(response.content[0].text)
```

Gemini SDK добавляет Gemini-пути самостоятельно, поэтому ему передают корневой
URL `http://127.0.0.1:8090` и тот же локальный API key.

## Маршруты и версии backend

Основная публичная поверхность:

- OpenAI: `GET /models`, `POST /chat/completions`, `POST /responses`,
  `POST /embeddings`;
- Anthropic: `POST /messages`, `POST /messages/count_tokens`;
- Gemini: `generateContent`, `streamGenerateContent`, `countTokens`,
  `embedContent`, `batchEmbedContents` и model discovery;
- LiteLLM: `GET /model/info`;
- служебные: `GET /health`, `GET|POST /ping`.

Префикс `/v1` принудительно выбирает upstream-контракт GigaChat v1, `/v2` —
GigaChat v2. Маршруты без такого префикса следуют
`GPT2GIGA_GIGACHAT_API_MODE`. Files/Batches для OpenAI, Anthropic и Gemini
намеренно не смонтированы, пока upstream не поддерживает их end-to-end.

## Безопасность

- Включайте `GPT2GIGA_ENABLE_API_KEY_AUTH=True` для любого общего окружения;
- храните GigaChat credentials на сервере, а не в клиентских настройках;
- не передавайте секреты через CLI flags: они могут быть видны в списке
  процессов;
- оставляйте `GIGACHAT_VERIFY_SSL_CERTS=True`;
- не включайте захват payload без политики редактирования, доступа и retention.

`GPT2GIGA_API_KEY` защищает локальный gateway и не является GigaChat credential.
Per-request GigaChat authorization через клиентский `Authorization` доступна
только при явном `GPT2GIGA_PASS_TOKEN=True`.

## Документация

- [Quickstart](https://ai-forever.github.io/gpt2giga/quickstart)
- [API compatibility](https://ai-forever.github.io/gpt2giga/api-compatibility)
- [Configuration reference](https://ai-forever.github.io/gpt2giga/configuration)
- [Integrations](https://ai-forever.github.io/gpt2giga/integrations)
- [Deployment](https://ai-forever.github.io/gpt2giga/deployment)
- [Operations](https://ai-forever.github.io/gpt2giga/operations)
- [Examples](https://github.com/ai-forever/gpt2giga/tree/main/examples)
- [Gateway changelog (RU)](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga/CHANGELOG.md)
- [Gateway changelog (EN)](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga/CHANGELOG_en.md)

## Разработка из исходников

Из корня репозитория:

```sh
uv sync --all-packages --all-extras --dev
uv run gpt2giga
uv build --package gpt2giga --no-sources
```

Полный репозиторный workflow, правила contribution и тестирования описаны в
[CONTRIBUTING](https://ai-forever.github.io/gpt2giga/contributing) и корневом
[README](https://github.com/ai-forever/gpt2giga#readme).
