# Integrations

`gpt2giga` is designed for clients that can set a custom base URL for OpenAI-, Anthropic-, or Gemini-compatible SDKs and CLIs.

## Base URLs

OpenAI-compatible clients usually use:

```text
http://localhost:8090/v1
```

For GigaChat v2 features you can explicitly specify:

```text
http://localhost:8090/v2
```

The backend selection rule is the same for all compatible clients: a URL with
`/v1` is forced into the GigaChat v1 contract, a URL with `/v2` into the
GigaChat v2 contract. The root URL without a version (`http://localhost:8090`)
uses `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Anthropic-compatible clients usually use:

```text
http://localhost:8090
```

Gemini-compatible clients usually use the root address:

```text
http://localhost:8090
```

With this base URL, the official Gemini SDKs/CLIs append a Gemini-style path
themselves, for example `/v1beta/models/{model}:generateContent`.

If `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, use `GPT2GIGA_API_KEY` as the client API key. For Gemini clients, the `x-goog-api-key` header is also supported.

## Runnable examples

- OpenAI examples: [examples/openai/](https://github.com/ai-forever/gpt2giga/tree/main/examples/openai)
- OpenAI Chat Completions: [examples/openai/chat_completions/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/chat_completions/README.md)
- OpenAI Responses: [examples/openai/responses/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/responses/README.md)
- Anthropic examples: [examples/anthropic/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/anthropic/README.md)
- Gemini examples: [examples/gemini/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/gemini/README.md)
- OpenAI Agents SDK: [examples/openai/agents/weather_handoff.py](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/agents/weather_handoff.py)

## Integration guides

| Tool / client | Guide |
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
| nginx (reverse proxy) | [integrations/nginx/README.md](https://github.com/ai-forever/gpt2giga/blob/main/integrations/nginx/README.md) |

## Verified apps and frameworks

| Name | URL | Note |
|---|---|---|
| OpenCode | https://opencode.ai/ | Open-source coding agent. |
| KiloCode | https://kilo.ai/ | Coding agent for JetBrains/VS Code. |
| OpenHands | https://openhands.dev/ | Development agent. |
| Zed | https://zed.dev/ | Editor AI assistant. |
| Cline | https://cline.bot/ | Developer agent. |
| OpenAI Codex | https://github.com/openai/codex | CLI coding agent. |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | Google CLI coding agent. |
| Aider | https://aider.chat/ | App-building coding assistant. |
| Langflow | https://github.com/langflow-ai/langflow | Low-code/no-code agent builder. |
| DeepAgentsCLI | https://github.com/langchain-ai/deepagents | Agent platform on LangChain/LangGraph. |
| CrewAI | https://github.com/crewAIInc/crewAI | Agent orchestration framework. |
| Qwen Agent | https://github.com/QwenLM/Qwen-Agent | Agent framework. |
| PydanticAI | https://github.com/pydantic/pydantic-ai | Pydantic-style GenAI agent framework. |
| Camel | https://github.com/camel-ai/camel | Multi-agent framework. |
| smolagents | https://github.com/huggingface/smolagents | Hugging Face agent framework. |
| Openclaw | https://openclaw.ai/ | Personal AI assistant. |
| Claude Code | https://code.claude.com/docs/en/overview | Anthropic CLI coding agent. |
| Claude Desktop App | https://claude.com/download | Desktop app for macOS and Windows. |
| OpenAI Agents SDK | https://github.com/openai/openai-agents-python | Agent SDK with function calling and handoffs. |
| Anthropic SDK | https://github.com/anthropics/anthropic-sdk-python | Official Anthropic Python SDK. |
| Cursor | https://cursor.com/ | AI editor. |
| Qwen Code | https://github.com/QwenLM/qwen-code | CLI coding agent. |
| Xcode | https://developer.apple.com/xcode/ | Apple Coding Intelligence and external agent tooling. |
