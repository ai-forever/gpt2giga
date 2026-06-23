# Интеграция Claude Code с GigaChat

> **Проверено:** 17 июня 2026 — `claude-cli/2.1.179`
> **Проверенные GigaChat paths:** `/v1/chat/completions`, `/v2/chat/completions`

[Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview) — CLI-агент от Anthropic для написания кода. С помощью `gpt2giga` можно использовать модели GigaChat в Claude Code, направив запросы Anthropic Messages API через прокси-сервер.

Если нужен Claude Desktop App, а не CLI, используйте отдельный beta guide: [integrations/claude-desktop/README.md](../claude-desktop/README.md).

## Подключение Claude Code к GigaChat

Для работы Claude Code с GigaChat используется утилита `gpt2giga`, которая преобразует запросы в формате Anthropic Messages API в вызовы GigaChat API.

### Предварительные требования

- Установленный [Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview)
- Запущенный прокси-сервер `gpt2giga`

---

## 1. Запуск gpt2giga

Настройте переменные окружения в файле `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

Запустите прокси-сервер:

```shell
gpt2giga
```

По умолчанию сервер будет доступен по адресу `http://localhost:8090`.

---

## 2. Настройка Claude Code

Перед запуском Claude Code задайте переменные окружения, указывающие на прокси-сервер `gpt2giga`:

```shell
export ANTHROPIC_BASE_URL=http://localhost:8090
export ANTHROPIC_API_KEY=0
```

- `ANTHROPIC_BASE_URL` — адрес прокси-сервера `gpt2giga`. Утилита принимает запросы на эндпоинт `/v1/messages`, совместимый с Anthropic Messages API. Root URL без `/v1` или `/v2` следует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`; URL с `/v1` принудительно выбирает GigaChat v1 contract, URL с `/v2` — GigaChat v2 contract.
- `ANTHROPIC_API_KEY` — любое непустое значение (например, `0`). Реальный ключ Anthropic не нужен — все запросы проксируются через `gpt2giga` в GigaChat.

### Запуск

```shell
claude --model GigaChat-2-Max
```

Claude Code будет отправлять запросы через `gpt2giga` в GigaChat API.

---

## 3. Headless / print mode

Для одноразового запуска без интерактивного UI используйте `-p` / `--print`:

```shell
export ANTHROPIC_BASE_URL=http://localhost:8090
export ANTHROPIC_API_KEY=0

claude -p --model GigaChat-2-Max "Что ты умеешь?"
```

Если нужно получить машинно-читаемый ответ, добавьте `--output-format json` или
`--output-format stream-json`:

```shell
claude -p \
  --model GigaChat-2-Max \
  --output-format json \
  "Суммируй архитектуру текущего проекта"
```

Полезные флаги для автоматизации:

- `--max-turns <N>` — ограничить количество agentic turns.
- `--no-session-persistence` — не сохранять сессию на диск.
- `--permission-mode plan` — запустить в read-only planning mode.
- `--permission-mode bypassPermissions` — разрешить действия без prompts только
  в изолированной среде, где это действительно безопасно.

В print mode Claude Code всегда использует `ANTHROPIC_API_KEY`, если эта
переменная задана. Поэтому при включённой авторизации на `gpt2giga` укажите в
ней реальный `GPT2GIGA_API_KEY`.

---

## 4. Использование с API-ключом gpt2giga

Если на прокси-сервере включена авторизация по API-ключу (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передайте значение `GPT2GIGA_API_KEY` через переменную `ANTHROPIC_API_KEY`:

```shell
export ANTHROPIC_BASE_URL=http://localhost:8090
export ANTHROPIC_API_KEY=<ваш_GPT2GIGA_API_KEY>
```

---

## 5. Использование удалённого сервера

Если `gpt2giga` развёрнут на удалённом сервере (например, за nginx с TLS), укажите адрес сервера:

```shell
export ANTHROPIC_BASE_URL=https://ваш-сервер.example.com
export ANTHROPIC_API_KEY=<ваш_api_ключ>
claude
```

Подробнее о развёртывании с nginx и TLS — в [integrations/nginx/README.md](../nginx/README.md).

---

## 6. Настройка через скрипт

Чтобы не задавать переменные окружения вручную при каждом запуске, добавьте их в профиль оболочки (`~/.bashrc`, `~/.zshrc` и т.д.):

```shell
# GigaChat через gpt2giga для Claude Code
export ANTHROPIC_BASE_URL=http://localhost:8090
export ANTHROPIC_API_KEY=0
```

Или создайте скрипт-обёртку:

```shell
#!/bin/bash
export ANTHROPIC_BASE_URL=http://localhost:8090
export ANTHROPIC_API_KEY=0
exec claude "$@"
```

---

## Доступные модели

Claude Code выбирает модель самостоятельно. `gpt2giga` перенаправляет все запросы в модель GigaChat, заданную через `GIGACHAT_MODEL` в `.env` или через аргумент `--gigachat.model`.

| Модель GigaChat  | Описание                                        |
|------------------|-------------------------------------------------|
| `GigaChat-2-Max` | Максимальная версия — рекомендована для агентов |
| `GigaChat-2-Pro` | Промежуточная версия                            |
| `GigaChat-2`     | Базовая версия                                  |

---

## Полезные ссылки

- [Claude Code + GigaFusion](fusion.md)
- [Документация Claude Code](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview)
- [Документация GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
- [Примеры Anthropic API через gpt2giga](../../examples/anthropic/)
