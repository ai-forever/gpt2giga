# Интеграции

`gpt2giga` рассчитан на клиентов, которые умеют указывать произвольный base URL для SDK и CLI, совместимых с OpenAI, Anthropic или Gemini.

## Базовые адреса

Клиенты, совместимые с OpenAI, обычно используют:

```text
http://localhost:8090/v1
```

Для возможностей GigaChat v2 можно явно указать:

```text
http://localhost:8090/v2
```

Правило выбора бэкенда одинаково для всех совместимых клиентов: URL с `/v1`
принудительно идёт в контракт GigaChat v1, URL с `/v2` — в контракт GigaChat v2.
Корневой URL без версии (`http://localhost:8090`) использует
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Клиенты, совместимые с Anthropic, обычно используют:

```text
http://localhost:8090
```

Клиенты, совместимые с Gemini, обычно используют корневой адрес:

```text
http://localhost:8090
```

Официальные SDK/CLI Gemini при таком base URL сами добавляют путь в стиле Gemini,
например `/v1beta/models/{model}:generateContent`.

Если `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, используйте `GPT2GIGA_API_KEY` как клиентский API-ключ. Для клиентов Gemini поддерживается также заголовок
`x-goog-api-key`.

## Запускаемые примеры

- OpenAI examples: [examples/openai/](https://github.com/ai-forever/gpt2giga/tree/main/examples/openai)
- OpenAI Chat Completions: [examples/openai/chat_completions/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/chat_completions/README.md)
- OpenAI Responses: [examples/openai/responses/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/responses/README.md)
- Anthropic examples: [examples/anthropic/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/anthropic/README.md)
- Gemini examples: [examples/gemini/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/gemini/README.md)
- OpenAI Agents SDK: [examples/openai/agents/weather_handoff.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/agents/weather_handoff.py)

## Руководства по интеграциям

| Инструмент / клиент | Руководство |
|---|---|
| OpenHands | [integrations/openhands/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/openhands/README.md) |
| OpenAI Codex | [integrations/codex/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/codex/README.md) |
| Aider | [integrations/aider/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/aider/README.md) |
| Claude Code | [integrations/claude-code/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/claude-code/README.md) |
| Claude Desktop App | [integrations/claude-desktop/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/claude-desktop/README.md) |
| Gemini CLI | [integrations/gemini/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/gemini/README.md) |
| Cursor | [integrations/cursor/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/cursor/README.md) |
| Qwen Code | [integrations/qwen-code/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/qwen-code/README.md) |
| Xcode | [integrations/xcode/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/xcode/README.md) |
| nginx (обратный прокси) | [integrations/nginx/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/nginx/README.md) |

## Записи о проверке

Слово «проверено» ниже означает, что в репозитории есть датированная ручная
проверка конкретной версии по связанному руководству. Это не обещание
совместимости с более новой версией клиента. После обновления клиента повторите
проверку и обновите запись.

| Клиент | Зафиксированная версия | Дата | Протокол и пути | Статус |
|---|---|---|---|---|
| OpenAI Codex | `codex-cli 0.142.1` | 2026-06-26 | OpenAI Chat, `/v1` и `/v2` | Проверено |
| Claude Code | `2.1.187` | 2026-06-26 | Anthropic Messages, `/v1` и `/v2` | Проверено |
| Gemini CLI | `gemini 0.46.0` | 2026-06-26 | Gemini content API, `/v1` и `/v2` | Проверено |
| Claude Desktop | `1.12603.1` с Claude Code `2.1.170` | 2026-06-13 | Anthropic Messages через 3p gateway | Beta-проверка |

Страницы OpenHands, Aider, Cursor, Qwen Code, Xcode и nginx поддерживаются как
инструкции по настройке, но пока не содержат актуальной датированной записи.
Считайте их воспроизводимыми рецептами и при подтверждении или регрессии
указывайте версию клиента и проверенный маршрут.

## Каталог совместимости

Следующие клиенты и фреймворки потенциально можно подключить, потому что они
принимают произвольный OpenAI-, Anthropic- или Gemini-совместимый base URL.
Наличие в каталоге само по себе не означает, что интеграция проверена.

| Категория | Проекты |
|---|---|
| Агенты и редакторы | [OpenCode](https://opencode.ai/), [KiloCode](https://kilo.ai/), [OpenHands](https://openhands.dev/), [Zed](https://zed.dev/), [Cline](https://cline.bot/), [Codex](https://github.com/openai/codex), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Aider](https://aider.chat/), [Claude Code](https://code.claude.com/docs/en/overview), [Cursor](https://cursor.com/), [Qwen Code](https://github.com/QwenLM/qwen-code), [Xcode](https://developer.apple.com/xcode/) |
| Агентные фреймворки | [Langflow](https://github.com/langflow-ai/langflow), [DeepAgents](https://github.com/langchain-ai/deepagents), [CrewAI](https://github.com/crewAIInc/crewAI), [Qwen Agent](https://github.com/QwenLM/Qwen-Agent), [PydanticAI](https://github.com/pydantic/pydantic-ai), [CAMEL](https://github.com/camel-ai/camel), [smolagents](https://github.com/huggingface/smolagents), [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) |
| SDK и desktop-клиенты | [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python), [Claude Desktop](https://claude.com/download) |

В полезном отчёте о проверке укажите версию клиента, ОС, версию gateway,
настроенный base URL, режим backend GigaChat, минимальный prompt, использование
streaming/tools и отредактированную ошибку или форму ответа.
