# Интеграции

В этом разделе собраны инструкции для инструментов, которые умеют работать с OpenAI-, Anthropic- или Gemini-совместимым API и поэтому могут быть подключены к GigaChat через `gpt2giga`.

## Готовые гайды

| Инструмент / сценарий | Документ |
|---|---|
| OpenAI Codex | [codex/README.md](./codex/README.md) |
| Cursor | [cursor/README.md](./cursor/README.md) |
| Aider | [aider/README.md](./aider/README.md) |
| Claude Code | [claude-code/README.md](./claude-code/README.md) |
| Qwen Code | [qwen-code/README.md](./qwen-code/README.md) |
| OpenHands | [openhands/README.md](./openhands/README.md) |
| Xcode | [xcode/README.md](./xcode/README.md) |
| nginx reverse proxy | [nginx/README.md](./nginx/README.md) |

## Как выбирать guide

- Нужен локальный coding agent или редактор: начинайте с guide под конкретный инструмент.
- Нужен удалённый instance с TLS: сначала настройте [nginx/README.md](./nginx/README.md) или используйте Compose/Traefik сценарии из [../operator-guide.md](../operator-guide.md).
- Нужны SDK-примеры, а не editor integration: переходите в [../../examples/README.md](../../examples/README.md).

## Известные совместимые инструменты

Ниже перечислены инструменты и фреймворки, которые используются с `gpt2giga` через совместимые API surface. Для части из них есть отдельные README, для части достаточно общего OpenAI-compatible `base_url`.

| Инструмент | Тип интеграции | Комментарий |
|---|---|---|
| [OpenCode](https://opencode.ai/) | OpenAI-compatible | Работает через кастомный `base_url` |
| [KiloCode](https://kilo.ai/) | OpenAI-compatible | IDE/agent сценарий |
| [OpenHands](https://openhands.dev/) | OpenAI-compatible | Подробный guide: [openhands/README.md](./openhands/README.md) |
| [Zed](https://zed.dev/) | OpenAI-compatible | Editor/assistant сценарий |
| [Cline](https://cline.bot/) | OpenAI-compatible | Agent workflow |
| [OpenAI Codex](https://github.com/openai/codex) | OpenAI-compatible | Подробный guide: [codex/README.md](./codex/README.md) |
| [Aider](https://aider.chat/) | OpenAI-compatible | Подробный guide: [aider/README.md](./aider/README.md) |
| [Cursor](https://cursor.com/) | OpenAI-compatible | Подробный guide: [cursor/README.md](./cursor/README.md) |
| [Claude Code](https://code.claude.com/docs/en/overview) | Anthropic/OpenAI-compatible | Подробный guide: [claude-code/README.md](./claude-code/README.md) |
| [Qwen Code](https://github.com/QwenLM/qwen-code) | OpenAI-compatible | Подробный guide: [qwen-code/README.md](./qwen-code/README.md) |
| [Xcode](https://developer.apple.com/xcode/) | OpenAI-compatible | Подробный guide: [xcode/README.md](./xcode/README.md) |
| [Langflow](https://github.com/langflow-ai/langflow) | OpenAI-compatible | Low-code сценарии |
| [DeepAgentsCLI](https://github.com/langchain-ai/deepagents) | OpenAI-compatible | Agent orchestration |
| [CrewAI](https://github.com/crewAIInc/crewAI) | OpenAI-compatible | Multi-agent orchestration |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | OpenAI-compatible | Agent framework |
| [Camel](https://github.com/camel-ai/camel) | OpenAI-compatible | Multi-agent framework |
| [smolagents](https://github.com/huggingface/smolagents) | OpenAI-compatible | Lightweight agent framework |
| [Openclaw](https://openclaw.ai/) | OpenAI-compatible | Personal assistant сценарии |

## SDK и runnable-примеры

Для официальных SDK и коротких воспроизводимых примеров используйте:

- [../../examples/openai/](../../examples/openai/)
- [../../examples/anthropic/](../../examples/anthropic/)
- [../../examples/gemini/](../../examples/gemini/)
- [../../examples/agents/](../../examples/agents/)

Общий индекс примеров: [../../examples/README.md](../../examples/README.md).
