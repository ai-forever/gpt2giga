# Интеграция Xcode с GigaChat

[Xcode](https://developer.apple.com/xcode/) поддерживает Coding Intelligence и, начиная с линейки Xcode 26.3, умеет работать как с встроенными провайдерами, так и с внешними моделями, совместимыми с Chat Completions API. С помощью `gpt2giga` можно подключить GigaChat к Xcode в качестве кастомного провайдера, а при необходимости использовать внутри Xcode и агентный режим через Codex или Claude Agent.

## Подключение Xcode к GigaChat

Для работы Xcode с GigaChat используется утилита `gpt2giga`, которая предоставляет OpenAI-совместимые эндпоинты, включая `/v1/models` и `/v1/chat/completions`.

### Предварительные требования

- Mac с Apple silicon
- Xcode 26 / 26.3+ с разделом **Settings** -> **Intelligence**
- Запущенный прокси-сервер `gpt2giga`
- Учётные данные GigaChat (`GIGACHAT_CREDENTIALS`)

> **Важно:** по материалам Apple функции coding intelligence доступны не во всех регионах и не на всех языках. Если в Xcode нет раздела **Intelligence**, сначала проверьте системные требования и доступность функции на вашей конфигурации macOS/Xcode.

---

## 1. Запуск gpt2giga

Настройте переменные окружения в файле `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Запустите прокси-сервер:

```shell
gpt2giga
```

По умолчанию сервер будет доступен по адресу `http://localhost:8090`.

---

## 2. Настройка кастомного провайдера в Xcode

Это самый простой способ подключить GigaChat к встроенному чату и командам Coding Intelligence в Xcode.

1. Откройте **Xcode** -> **Settings** -> **Intelligence**.
2. Нажмите **Add a Provider...**
3. Выберите **Locally hosted**
4. Укажите произвольное имя, например `gpt2giga` и порт (по умолчанию `8090`)
5. После успешной проверки выберите модель `GigaChat-2-Max` или другую доступную модель GigaChat.
### Проверка

После добавления провайдера откройте чат в Xcode и отправьте тестовый запрос, например:

```text
Explain this file and suggest a small refactor.
```

Если настройка выполнена корректно, Xcode отправит запрос через `gpt2giga` в GigaChat API.

---
## 3. Использование удалённого сервера

Если `gpt2giga` развёрнут на удалённом сервере (например, за nginx с TLS), укажите адрес сервера в настройках провайдера:

```text
https://ваш-сервер.example.com/
```

В поле API key укажите значение `GPT2GIGA_API_KEY`, настроенное на сервере.

Подробнее о развёртывании с nginx и TLS — в [integrations/nginx/README.md](../nginx/README.md).

---

## 4. Codex и Claude Agent внутри Xcode

Apple отдельно поддерживает агентный режим через Codex и Claude Agent. Для этого сначала нужно настроить сам агент на работу с `gpt2giga`, а затем положить его конфигурацию в директорию, которую использует Xcode.

### Codex в Xcode

1. Сначала настройте Codex по инструкции из [integrations/codex/README.md](../codex/README.md).
2. Скопируйте конфигурацию Codex в директорию Xcode:

```shell
mkdir -p ~/Library/Developer/Xcode/CodingAssistant/codex
cp ~/.codex/config.toml ~/Library/Developer/Xcode/CodingAssistant/codex/config.toml
```

3. При необходимости положите туда же дополнительные инструкции для агента, например `AGENTS.md`.

### Claude Agent в Xcode

1. Сначала настройте Claude Code по инструкции из [integrations/claude-code/README.md](../claude-code/README.md).
2. Скопируйте конфигурацию Claude Code в директорию Xcode:

```shell
mkdir -p ~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig
cp ~/.claude/settings.json ~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/settings.json
```

3. При необходимости положите туда же дополнительные инструкции для агента, например `CLAUDE.md`.

### Что ещё важно для агентного режима

- В Xcode нужно отдельно включить и авторизовать `Codex` или `Claude Agent` в **Settings** -> **Intelligence**.
- По материалам Apple, Xcode использует собственные директории `~/Library/Developer/Xcode/CodingAssistant/codex` и `~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig` для кастомизации этих агентов.
- Если нужен только встроенный чат и команды редактирования в Xcode, обычно достаточно сценария с кастомным провайдером из раздела выше.

---

## Доступные модели

| Модель в Xcode   | Модель GigaChat |
|------------------|-----------------|
| `GigaChat-2-Max` | GigaChat-2-Max  |
| `GigaChat-2-Pro` | GigaChat-2-Pro  |
| `GigaChat-2`     | GigaChat-2      |

---

## Полезные ссылки

- [Apple: Setting up coding intelligence](https://developer.apple.com/documentation/xcode/setting-up-coding-intelligence)
- [Apple: Writing code with intelligence in Xcode](https://developer.apple.com/documentation/xcode/writing-code-with-intelligence-in-xcode)
- [Apple: Giving external agentic coding tools access to Xcode](https://developer.apple.com/documentation/xcode/giving-agentic-coding-tools-access-to-xcode)
- [Apple Developer Forums: Coding intelligence tag](https://developer.apple.com/forums/tags/coding-intelligence)
- [Документация GigaChat API](https://developers.sber.ru/docs/ru/gigachat/overview)
