# AGENTS.md — examples/

## Package Identity

- **What:** Runnable examples for using `gpt2giga` through OpenAI-, Anthropic-, and Gemini-compatible SDKs
- **Audience:** Users validating proxy behavior or copying starter integrations
- **Default target:** `http://localhost:8090`

## Directory Layout

| Path | Purpose |
|---|---|
| `examples/openai/chat_completions/` | OpenAI Chat Completions examples |
| `examples/openai/responses/` | OpenAI Responses API examples |
| `examples/openai/*/{basic,tools,multimodal,structured_outputs,...}/` | OpenAI examples grouped by capability |
| `examples/openai/files/` | OpenAI Files API examples; router code exists but is not mounted in this release |
| `examples/openai/batches/` | OpenAI Batches API examples; router code exists but is not mounted in this release |
| `examples/openai/embeddings/` | Embeddings usage |
| `examples/openai/models/` | Model listing/retrieval |
| `examples/openai/agents/` | OpenAI Agents SDK examples |
| `examples/anthropic/messages/` | Anthropic Messages API examples grouped by capability |
| `examples/anthropic/message_batches/` | Anthropic Message Batches examples; router code exists but is not mounted in this release |
| `examples/anthropic/count_tokens/` | Anthropic Count Tokens examples |
| `examples/gemini/` | Gemini-compatible GenerateContent, streaming, count tokens, embeddings and prepared Files/Batches examples |
| `examples/README.md` | Example index |

### Notable Example Files

- `chat_completions/basic/chat_completion.py`: basic streaming chat
- `chat_completions/reasoning/chat_reasoning.py`: reasoning mode
- `chat_completions/tools/function_calling.py`: tool calling
- `chat_completions/files/documents.py`: document/file-style input
- `chat_completions/concurrency/per_model_max_connections_async.py`: model-level upstream concurrency behavior
- `responses/reasoning/reasoning.py`: Responses API reasoning example
- `responses/structured_outputs/structured_output.py`: structured outputs
- `responses/tools/multiple_tool_calls.py`: multiple tool call handling
- `responses/tools/gigachat_tools/image_generate.py`: GigaChat-specific built-in tool passthrough
- `responses/tools/gigachat_tools/code_interpreter.py`: GigaChat-specific code interpreter passthrough
- `anthropic/messages/basic/messages.py`: basic Messages API call
- `anthropic/message_batches/basic.py`: Anthropic Message Batches API; router code exists but is not mounted in this release
- `anthropic/messages/basic/messages_stream.py`: streaming Messages API
- `anthropic/count_tokens/basic.py`: token counting endpoint
- `anthropic/messages/structured_outputs/structured_output_stream.py`: streaming structured output fallback
- `gemini/content/generate_content.py`: Gemini-compatible GenerateContent
- `gemini/content/stream_generate_content.py`: Gemini-compatible streaming
- `gemini/count_tokens/count_tokens.py`: Gemini-compatible countTokens
- `gemini/embeddings/embeddings.py`: Gemini-compatible embedContent and batch embeddings

## Patterns & Conventions

- Keep examples self-contained and runnable with repo dependencies.
- Use real SDK clients (`openai`, `anthropic`, `google-genai`, `openai-agents`) rather than importing internal `gpt2giga` modules.
- Default to `api_key="0"` or another placeholder unless the example is specifically about proxy API-key auth.
- Prefer `GigaChat-2-Max` in examples unless the example is about model selection.
- Print or stream visible output so users can confirm behavior quickly.
- Keep comments short and focused on what the example demonstrates.
- Keep file/batch examples clearly marked as prepared but currently not runnable against the mounted public API.
- Keep base URLs aligned with local defaults: OpenAI examples may use `http://localhost:8090`, `http://localhost:8090/v1`, or `http://localhost:8090/v2` depending on whether they need env-selected, explicit v1, or explicit v2 behavior; Anthropic examples can use `http://localhost:8090` unless they need an explicit backend contract; Gemini examples should use `google-genai` `HttpOptions` and the supported root, `/v1`, `/v2`, or `/v1beta` paths documented in `examples/gemini/README.md`.

## Setup & Run

```bash
# Install repo dependencies
uv sync --all-extras --dev

# For the OpenAI Agents example
uv sync --group integrations

# Start the proxy in another terminal
uv run gpt2giga

# Run an example
uv run python examples/openai/chat_completions/basic/chat_completion.py
uv run python examples/openai/responses/basic/single_prompt.py
uv run python examples/anthropic/messages/basic/messages.py
uv run python examples/gemini/content/generate_content.py
```

## Quick Find Commands

```bash
# Find streaming examples
rg -n "stream=True" examples

# Find tool/function calling examples
rg -n "tools|tool_choice|function" examples

# Find reasoning examples
rg -n "reasoning|thinking" examples

# Find image/document examples
rg -n "image_url|base64|document" examples

# Find examples for currently unmounted APIs
rg -n "files|batches|message_batches" examples
```

## Common Gotchas

- `examples/openai/agents/weather_handoff.py` needs the `integrations` dependency group.
- Anthropic examples use the `anthropic` SDK directly, not the OpenAI client.
- OpenAI examples are grouped under `examples/openai/` by API and capability; keep README links and run commands aligned with that layout.
- Gemini examples are grouped under `examples/gemini/` by capability; keep prepared Files/Batches examples marked as unmounted.
- Examples are excluded from coverage and are not the canonical place to implement application logic.
- Each API-style folder has its own `README.md`; update those alongside code examples when behavior changes.
- OpenAI Files/Batches, Anthropic Message Batches, and Gemini Files/Batches examples document intended client usage, but the current API aggregators do not mount those routers.
