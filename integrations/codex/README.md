# Интеграция OpenAI Codex с GigaChat

> **Проверено:** 9 июня 2026 — `codex-cli 0.138.0`
> **Codex App для macOS:** `codex-cli 0.137.0-alpha.4`

[OpenAI Codex](https://github.com/openai/codex) — агент для работы с кодом из терминала и Codex App. Через `gpt2giga` Codex можно подключить к моделям GigaChat как к OpenAI-совместимому провайдеру.

`gpt2giga` принимает запросы Codex в формате OpenAI API, преобразует их в запросы GigaChat API и возвращает ответы обратно в совместимом формате.

## Предварительные требования

- Установленный [OpenAI Codex](https://github.com/openai/codex)
- Запущенный прокси-сервер `gpt2giga`
- Учётные данные GigaChat (`GIGACHAT_CREDENTIALS`)

---

## 1. Запуск gpt2giga

Настройте переменные окружения в файле `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-3-Ultra

GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
GPT2GIGA_GIGACHAT_API_MODE=v2
GPT2GIGA_PASS_MODEL=False
GPT2GIGA_DISABLE_REASONING=True
```

Рекомендуемые параметры для Codex:

- `GPT2GIGA_GIGACHAT_API_MODE=v2` — включает режим `v2`, который нужен для встроенных инструментов GigaChat, например `web_search` и `image_generate`.
- `GPT2GIGA_PASS_MODEL=False` — заставляет прокси использовать модель из `GIGACHAT_MODEL`, даже если Codex передал в запросе имя модели OpenAI.
- `GPT2GIGA_DISABLE_REASONING=True` — удаляет `reasoning` и `reasoning_effort` из запроса к GigaChat, чтобы клиентские reasoning-поля не мешали обработке.

Запустите прокси-сервер:

```shell
gpt2giga
```

По умолчанию сервер будет доступен по адресу `http://localhost:8090`.

---

## 2. Настройка Codex

Отредактируйте файл конфигурации Codex:

- **macOS / Linux:** `~/.codex/config.toml`
- **Windows:** `%USERPROFILE%\.codex\config.toml`

Добавьте провайдер `gpt2giga`:

```toml
model = "GigaChat-3-Ultra"
model_provider = "gpt2giga"
model_reasoning_effort = "none"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "http://localhost:8090/v2"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
supports_websockets = false
```

Ключевые настройки:

- `model` — имя модели, которое будет отображаться и передаваться в Codex.
- `base_url` — OpenAI-совместимый адрес `gpt2giga`; для Codex с built-in tools указывайте путь с `/v2`.
- `env_key` — имя переменной окружения, из которой Codex берёт API-ключ.
- `wire_api = "responses"` — использовать OpenAI Responses API, который поддерживается `gpt2giga`.

### Переменная окружения

Задайте API-ключ, соответствующий значению `GPT2GIGA_API_KEY` на сервере:

```shell
export GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Если на локальном прокси отключена авторизация по API-ключу, можно использовать любое непустое значение, например:

```shell
export GPT2GIGA_API_KEY=0
```

### Запуск Codex

```shell
codex
```

Codex будет отправлять запросы через `gpt2giga` в GigaChat API.

---

## 3. Codex App на macOS

Если Codex App не видит `GPT2GIGA_API_KEY`, добавьте переменную в профиль вашей оболочки. Узнать текущую оболочку можно командой:

```shell
echo $SHELL
```

Для `zsh` добавьте строку в `~/.zshrc`:

```shell
export GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Для `bash` используйте `~/.bashrc` или `~/.bash_profile`. После изменения профиля перезапустите терминал или перечитайте нужный файл:

```shell
source ~/.zshrc
# или
source ~/.bashrc
```

Если локальный `gpt2giga` запущен без авторизации по API-ключу, вместо реального ключа можно указать `0`.

---

## 4. Использование удалённого сервера

Если `gpt2giga` развёрнут на удалённом сервере, например за nginx с TLS, укажите адрес сервера в `config.toml`:

```toml
model = "GigaChat-3-Ultra"
model_provider = "gpt2giga"
model_reasoning_effort = "none"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "https://ваш-сервер.example.com/v2"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
supports_websockets = false
```

Подробнее о развёртывании с nginx и TLS — в [integrations/nginx/README.md](../nginx/README.md).

---

## 5. Доверенные проекты

Codex требует явно доверять проектам перед выполнением команд. Обычно Codex предлагает добавить проект автоматически, но это можно сделать вручную в `config.toml`:

```toml
[projects."/path/to/your/project"]
trust_level = "trusted"
```

---

## 6. Пример полного `config.toml`

```toml
model = "GigaChat-3-Ultra"
model_provider = "gpt2giga"
model_reasoning_effort = "none"

[model_providers.gpt2giga]
name = "gpt2giga"
base_url = "http://localhost:8090/v2"
# base_url = "https://ваш-сервер.example.com/v2"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
supports_websockets = false

[projects."/Users/USER/code_projects/MY_PROJECT"]
trust_level = "trusted"
```

---

## Диагностика

- **Codex получает 401/403** — проверьте, что `GPT2GIGA_API_KEY` в окружении Codex совпадает со значением на сервере `gpt2giga`.
- **Codex пытается вызвать OpenAI-модель** — оставьте `GPT2GIGA_PASS_MODEL=False`, чтобы прокси использовал модель из `GIGACHAT_MODEL`.
- **Появляются ошибки вокруг `reasoning` или `reasoning_effort`** — проверьте `model_reasoning_effort = "none"` в `config.toml` и `GPT2GIGA_DISABLE_REASONING=True` в `.env`.

---

## Доступные модели

| Модель GigaChat    | Описание                                         |
|--------------------|--------------------------------------------------|
| `GigaChat-3-Ultra` | Максимальная версия, рекомендована для агентов   |
| `GigaChat-2-Max`   | Предыдущее поколение максимальной версии         |
| `GigaChat-2-Pro`   | Промежуточная версия                             |

---

## Полезные ссылки

- [Документация OpenAI Codex](https://github.com/openai/codex)
- [Документация GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
