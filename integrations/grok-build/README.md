# Интеграция Grok Build с GigaChat

> **Формат конфигурации проверен:** 15 июля 2026 — `grok 0.2.101`
> **Проверенный gateway path:** `/v2/responses`
> **Статус:** конфигурация и локальные Responses/tool-call контракты проверены;
> live-запуск с реальными GigaChat credentials пока не зафиксирован.

[Grok Build](https://docs.x.ai/build/overview) — coding agent с интерактивным
TUI и headless-режимом. Он поддерживает custom/BYOK-модели через
OpenAI Responses API, поэтому его можно направить в `gpt2giga`, а фактической
моделью будет GigaChat.

## Предварительные требования

- установленный Grok Build;
- запущенный `gpt2giga`;
- учётные данные GigaChat на стороне `gpt2giga`;
- API-ключ локального gateway, если включена его API-key авторизация.

Проверьте версии:

```shell
grok version
gpt2giga --help
```

## 1. Запуск gpt2giga

Настройте `.env`, используя безопасные локальные значения:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max

GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_локальный_api_ключ>
GPT2GIGA_PASS_MODEL=True
```

Для конфигурации с несколькими моделями важно оставить
`GPT2GIGA_PASS_MODEL=True`. При `False` gateway игнорирует модель из запроса и
все записи Grok фактически используют одну модель из `GIGACHAT_MODEL`.

Запустите gateway из установленного пакета:

```shell
gpt2giga
```

Или из checkout репозитория:

```shell
uv sync --all-extras --dev
uv run gpt2giga
```

Проверьте health и список моделей, доступных текущим GigaChat credentials:

```shell
curl -fsS http://127.0.0.1:8090/health

curl -fsS \
  -H "Authorization: Bearer <ваш_локальный_api_ключ>" \
  http://127.0.0.1:8090/v2/models
```

Используйте в Grok только те точные model ids, которые вернул `/v2/models`.
Набор моделей зависит от GigaChat credentials, scope и доступности backend.

## 2. Настройка нескольких моделей Grok Build

Модельные настройки Grok Build относятся к user scope. Добавьте их в:

- macOS / Linux: `~/.grok/config.toml`;
- Windows: `%USERPROFILE%\.grok\config.toml`;
- при заданном `GROK_HOME`: `$GROK_HOME/config.toml`.

Не помещайте `[model.*]` в репозиторный `.grok/config.toml`: project scope
поддерживает только MCP servers, plugins и permission rules.

Ниже пример с четырьмя отдельными model aliases:

```toml
[models]
default = "giga-ultra"

[model.giga-ultra]
model = "GigaChat-3-Ultra"
base_url = "http://127.0.0.1:8090/v2"
name = "GigaChat 3 Ultra via gpt2giga"
description = "GigaChat-3-Ultra for agentic coding"
env_key = "GPT2GIGA_API_KEY"
api_backend = "responses"
supports_backend_search = false

[model.giga-max]
model = "GigaChat-2-Max"
base_url = "http://127.0.0.1:8090/v2"
name = "GigaChat 2 Max via gpt2giga"
env_key = "GPT2GIGA_API_KEY"
api_backend = "responses"
supports_backend_search = false

[model.giga-pro]
model = "GigaChat-2-Pro"
base_url = "http://127.0.0.1:8090/v2"
name = "GigaChat 2 Pro via gpt2giga"
env_key = "GPT2GIGA_API_KEY"
api_backend = "responses"
supports_backend_search = false

[model.giga-base]
model = "GigaChat-2"
base_url = "http://127.0.0.1:8090/v2"
name = "GigaChat 2 via gpt2giga"
env_key = "GPT2GIGA_API_KEY"
api_backend = "responses"
supports_backend_search = false
```

Здесь имя секции после `model.` — локальный alias Grok, а значение `model` —
точный id, отправляемый в `gpt2giga`. Удалите недоступные вашему аккаунту
модели и выберите существующий alias в `models.default`.

Если в `config.toml` уже есть секция `[models]`, добавьте поля в неё, а не
создавайте вторую секцию с таким же именем.

### API-ключ

Перед запуском Grok экспортируйте тот же локальный ключ, который настроен в
`GPT2GIGA_API_KEY` у gateway:

```shell
export GPT2GIGA_API_KEY=<ваш_локальный_api_ключ>
```

Если API-key авторизация `gpt2giga` отключена, Grok всё равно требует
непустое значение для `env_key`; можно использовать локальную заглушку:

```shell
export GPT2GIGA_API_KEY=0
```

Не записывайте реальный ключ напрямую в `api_key` внутри `config.toml`.

## 3. Проверка и выбор модели

Проверьте, откуда Grok прочитал конфигурацию и какие aliases доступны:

```shell
grok inspect
grok models
```

Запуск интерактивного TUI с конкретной моделью:

```shell
grok -m giga-ultra
grok -m giga-max
grok -m giga-pro
```

Внутри TUI модель можно переключить командой:

```text
/model giga-max
```

Headless-пример:

```shell
grok -p "Объясни архитектуру этого проекта" \
  -m giga-ultra \
  --output-format streaming-json
```

## Что означает supports_backend_search

`supports_backend_search` — capability flag конкретного model endpoint. Он
сообщает Grok Build, поддерживает ли endpoint Grok-hosted server-side search
tools, то есть инструменты поиска, исполняемые самим xAI backend.

Для `gpt2giga` рекомендуется:

```toml
supports_backend_search = false
```

`gpt2giga` не является xAI inference backend и не обещает полный контракт
Grok-hosted search tools. Значение `false` не отключает локальные coding tools
Grok Build — чтение и изменение файлов, shell, grep, MCP и обычные function
calls продолжают работать.

У `gpt2giga` есть отдельный механизм built-in tools GigaChat v2, включая
совместимые варианты `web_search` и `code_interpreter`. Он управляется gateway
route `/v2` и параметром `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING`, а не флагом
Grok `supports_backend_search`. Не выставляйте `true`, пока конкретный поток
server-side search не проверен end-to-end.

## Почему используется /v2 и Responses API

```toml
base_url = "http://127.0.0.1:8090/v2"
api_backend = "responses"
```

Grok Build использует Responses API для agent loop. `gpt2giga` предоставляет
`/v2/responses`, поддерживает streaming, function tools, возврат
`function_call`, следующий запрос с `function_call_output` и stateful
`previous_response_id`. Префикс `/v2` также выбирает более полный путь
built-in tools GigaChat v2.

## Удалённый gateway

Для `gpt2giga`, опубликованного через HTTPS reverse proxy, замените `base_url`
во всех моделях:

```toml
base_url = "https://gpt2giga.example.com/v2"
```

Не подключайте Grok Build к удалённому gateway по открытому HTTP. Настройка
TLS и reverse proxy описана в [nginx integration](../nginx/README.md).

## Ограничения

- Доступность каждой модели определяется GigaChat backend, а не локальным
  списком aliases Grok.
- `parallel_tool_calls=true` принимается `gpt2giga` для совместимости, но не
  гарантирует параллельное исполнение upstream.
- xAI-specific `x_search`, hosted collections/file search и полный набор
  Grok-hosted server-side tools не заявлены как совместимые.
- OpenAI Files, Batches и Realtime/WebSocket API не являются частью этой
  интеграции.
- Успех agent loop зависит не только от HTTP-совместимости, но и от способности
  выбранной модели стабильно следовать tool schemas Grok Build.

## Диагностика

- **Все aliases используют одну модель** — проверьте
  `GPT2GIGA_PASS_MODEL=True` и перезапустите gateway.
- **Модель видна в `grok models`, но upstream отвечает ошибкой** — сравните
  значение `model` с точным id из `GET /v2/models` и проверьте доступ аккаунта.
- **401/403 от gateway** — значение экспортированного `GPT2GIGA_API_KEY` должно
  совпадать с ключом на стороне `gpt2giga`.
- **Ошибка endpoint или tool loop** — проверьте одновременно
  `base_url = ".../v2"` и `api_backend = "responses"`.
- **Grok не видит конфигурацию** — выполните `grok inspect` и убедитесь, что
  `[model.*]` находится в user config, а не в project `.grok/config.toml`.

## Полезные ссылки

- [Grok Build overview](https://docs.x.ai/build/overview)
- [Grok Build settings](https://docs.x.ai/build/settings)
- [Grok Build settings reference](https://docs.x.ai/build/settings/reference)
- [GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
- [gpt2giga API compatibility](../../docs/api-compatibility.md)
