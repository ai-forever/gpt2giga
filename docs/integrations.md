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

## Проверенные приложения и фреймворки

| Название | URL | Примечание |
|---|---|---|
| OpenCode | https://opencode.ai/ | Опенсорсный агент для кода. |
| KiloCode | https://kilo.ai/ | Агент для кода для JetBrains/VS Code. |
| OpenHands | https://openhands.dev/ | Агент для разработки. |
| Zed | https://zed.dev/ | ИИ-ассистент в редакторе. |
| Cline | https://cline.bot/ | Агент для разработчиков. |
| OpenAI Codex | https://github.com/openai/codex | CLI-агент для кода. |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | CLI-агент для кода от Google. |
| Aider | https://aider.chat/ | Ассистент для создания приложений. |
| Langflow | https://github.com/langflow-ai/langflow | Конструктор агентов в low-code/no-code. |
| DeepAgentsCLI | https://github.com/langchain-ai/deepagents | Платформа агентов на LangChain/LangGraph. |
| CrewAI | https://github.com/crewAIInc/crewAI | Фреймворк оркестрации агентов. |
| Qwen Agent | https://github.com/QwenLM/Qwen-Agent | Фреймворк агентов. |
| PydanticAI | https://github.com/pydantic/pydantic-ai | Фреймворк GenAI-агентов в стиле Pydantic. |
| Camel | https://github.com/camel-ai/camel | Мультиагентный фреймворк. |
| smolagents | https://github.com/huggingface/smolagents | Фреймворк агентов от Hugging Face. |
| Openclaw | https://openclaw.ai/ | Персональный ИИ-ассистент. |
| Claude Code | https://code.claude.com/docs/en/overview | CLI-агент для кода от Anthropic. |
| Claude Desktop App | https://claude.com/download | Десктопное приложение для macOS и Windows. |
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | SDK для агентов с вызовом функций и передачей управления (handoffs). |
| Anthropic SDK | https://github.com/anthropics/anthropic-sdk-python | Официальный Python SDK от Anthropic. |
| Cursor | https://cursor.com/ | ИИ-редактор. |
| Qwen Code | https://github.com/QwenLM/qwen-code | CLI-агент для кода. |
| Xcode | https://developer.apple.com/xcode/ | Apple Coding Intelligence и инструменты для внешних агентов. |
