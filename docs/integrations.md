# Интеграции

`gpt2giga` рассчитан на клиентов, которые умеют указывать custom base URL для OpenAI-compatible, Anthropic-compatible или Gemini-compatible SDK и CLI.

## Base URLs

OpenAI-compatible clients обычно используют:

```text
http://localhost:8090/v1
```

Для GigaChat v2 features можно явно указать:

```text
http://localhost:8090/v2
```

Правило выбора backend одинаковое для всех совместимых клиентов: URL с `/v1`
принудительно идёт в GigaChat v1 contract, URL с `/v2` — в GigaChat v2
contract. Корневой URL без версии (`http://localhost:8090`) использует
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Anthropic-compatible clients обычно используют:

```text
http://localhost:8090
```

Gemini-compatible clients обычно используют корневой адрес:

```text
http://localhost:8090
```

Официальные Gemini SDK/CLI при таком base URL сами добавляют Gemini-style path,
например `/v1beta/models/{model}:generateContent`.

Если `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, используйте `GPT2GIGA_API_KEY` как client API key. Для Gemini clients поддерживается также заголовок
`x-goog-api-key`.

## Запускаемые примеры

- OpenAI examples: [examples/openai/](https://github.com/ai-forever/gpt2giga/tree/main/examples/openai)
- OpenAI Chat Completions: [examples/openai/chat_completions/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/chat_completions/README.md)
- OpenAI Responses: [examples/openai/responses/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/responses/README.md)
- Anthropic examples: [examples/anthropic/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/anthropic/README.md)
- Gemini examples: [examples/gemini/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/gemini/README.md)
- OpenAI Agents SDK: [examples/openai/agents/weather_handoff.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/agents/weather_handoff.py)

## Гайды по интеграциям

| Tool / client | Гайд |
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
| nginx reverse proxy | [integrations/nginx/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/nginx/README.md) |

## Проверенные apps и frameworks

| Название | URL | Примечание |
|---|---|---|
| OpenCode | https://opencode.ai/ | Open-source coding agent. |
| KiloCode | https://kilo.ai/ | Coding agent для JetBrains/VS Code. |
| OpenHands | https://openhands.dev/ | Development agent. |
| Zed | https://zed.dev/ | Editor AI assistant. |
| Cline | https://cline.bot/ | Developer agent. |
| OpenAI Codex | https://github.com/openai/codex | CLI coding agent. |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | Google CLI coding agent. |
| Aider | https://aider.chat/ | App-building coding assistant. |
| Langflow | https://github.com/langflow-ai/langflow | Low-code/no-code agent builder. |
| DeepAgentsCLI | https://github.com/langchain-ai/deepagents | Agent platform на LangChain/LangGraph. |
| CrewAI | https://github.com/crewAIInc/crewAI | Agent orchestration framework. |
| Qwen Agent | https://github.com/QwenLM/Qwen-Agent | Agent framework. |
| PydanticAI | https://github.com/pydantic/pydantic-ai | Pydantic-style GenAI agent framework. |
| Camel | https://github.com/camel-ai/camel | Multi-agent framework. |
| smolagents | https://github.com/huggingface/smolagents | Hugging Face agent framework. |
| Openclaw | https://openclaw.ai/ | Personal AI assistant. |
| Claude Code | https://code.claude.com/docs/en/overview | Anthropic CLI coding agent. |
| Claude Desktop App | https://claude.com/download | Desktop app for macOS and Windows. |
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | Agent SDK с function calling и handoffs. |
| Anthropic SDK | https://github.com/anthropics/anthropic-sdk-python | Официальный Anthropic Python SDK. |
| Cursor | https://cursor.com/ | AI editor. |
| Qwen Code | https://github.com/QwenLM/qwen-code | CLI coding agent. |
| Xcode | https://developer.apple.com/xcode/ | Apple Coding Intelligence и external agent tooling. |
