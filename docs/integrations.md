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

## Verification records

“Verified” below means the repository contains a dated, versioned manual check
for the linked guide. It does not promise compatibility with newer client
versions. Re-run the guide after a client upgrade and update its record.

| Client | Recorded version | Date | Protocol and paths | Status |
|---|---|---|---|---|
| OpenAI Codex | `codex-cli 0.142.1` | 2026-06-26 | OpenAI Chat, `/v1` and `/v2` | Verified record |
| Claude Code | `2.1.187` | 2026-06-26 | Anthropic Messages, `/v1` and `/v2` | Verified record |
| Gemini CLI | `gemini 0.46.0` | 2026-06-26 | Gemini content API, `/v1` and `/v2` | Verified record |
| Claude Desktop | `1.12603.1` with Claude Code `2.1.170` | 2026-06-13 | Anthropic Messages through a 3p gateway | Beta record |

The OpenHands, Aider, Cursor, Qwen Code, Xcode, and nginx pages are maintained
setup guides, but they do not yet contain a current dated verification record.
Treat them as reproducible recipes and report the client version and tested
route when confirming or reporting a regression.

## Compatibility directory

The following clients and frameworks are plausible integration targets because
they expose a custom OpenAI-, Anthropic-, or Gemini-compatible base URL. An
entry in this directory is not a verification claim.

| Category | Projects |
|---|---|
| Coding agents and editors | [OpenCode](https://opencode.ai/), [KiloCode](https://kilo.ai/), [OpenHands](https://openhands.dev/), [Zed](https://zed.dev/), [Cline](https://cline.bot/), [Codex](https://github.com/openai/codex), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Aider](https://aider.chat/), [Claude Code](https://code.claude.com/docs/en/overview), [Cursor](https://cursor.com/), [Qwen Code](https://github.com/QwenLM/qwen-code), [Xcode](https://developer.apple.com/xcode/) |
| Agent frameworks | [Langflow](https://github.com/langflow-ai/langflow), [DeepAgents](https://github.com/langchain-ai/deepagents), [CrewAI](https://github.com/crewAIInc/crewAI), [Qwen Agent](https://github.com/QwenLM/Qwen-Agent), [PydanticAI](https://github.com/pydantic/pydantic-ai), [CAMEL](https://github.com/camel-ai/camel), [smolagents](https://github.com/huggingface/smolagents), [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) |
| SDKs and desktop clients | [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python), [Claude Desktop](https://claude.com/download) |

For a useful verification report, include the client version, operating system,
gateway version, configured base URL, GigaChat backend mode, minimal prompt,
whether streaming/tools were used, and the redacted error or response shape.
