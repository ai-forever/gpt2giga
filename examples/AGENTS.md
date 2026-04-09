# AGENTS.md — examples/

## Package Identity

- **What:** Runnable examples for using `gpt2giga` through OpenAI and Anthropic-compatible SDKs
- **What:** Runnable examples for using `gpt2giga` through OpenAI, Anthropic, and Gemini-compatible SDKs
- **Audience:** Users validating proxy behavior or copying starter integrations
- **Default target:** `http://localhost:8090`

## Directory Layout

| Path | Purpose |
|---|---|
| `examples/openai/chat_completions/` | OpenAI Chat Completions examples |
| `examples/openai/responses/` | OpenAI Responses API examples |
| `examples/anthropic/` | Anthropic Messages API examples |
| `examples/gemini/` | Gemini Developer API examples |
| `examples/openai/files.py` | OpenAI Files API example |
| `examples/openai/batches.py` | OpenAI Batches API example |
| `examples/openai/embeddings.py` | Embeddings usage |
| `examples/openai/models.py` | Model listing/retrieval |
| `examples/openai_agents.py` | OpenAI Agents SDK example |
| `examples/responses/parallel_tool_call.py` | Additional Responses API example |
| `examples/README.md` | Example index |

### Notable Example Files

- `chat_completions/chat_completion.py`: basic streaming chat
- `chat_completions/chat_reasoning.py`: reasoning mode
- `chat_completions/function_calling.py`: tool calling
- `chat_completions/documents.py`: document/file-style input
- `responses/reasoning.py`: Responses API reasoning example
- `responses/structured_output.py`: structured outputs
- `anthropic/messages.py`: basic Messages API call
- `anthropic/message_batches.py`: Anthropic Message Batches API
- `anthropic/messages_stream.py`: streaming Messages API
- `anthropic/count_tokens.py`: token counting endpoint
- `gemini/generate_content.py`: basic Gemini `generate_content`
- `gemini/function_calling.py`: Gemini function declarations / tool responses
- `gemini/structured_output.py`: Gemini JSON schema output

## Patterns & Conventions

- Keep examples self-contained and runnable with repo dependencies.
- Use real SDK clients (`openai`, `anthropic`, `google-genai`, `openai-agents`) rather than importing internal `gpt2giga` modules.
- Default to `api_key="0"` or another placeholder unless the example is specifically about proxy API-key auth.
- Prefer `GigaChat-2-Max` in examples unless the example is about model selection.
- Print or stream visible output so users can confirm behavior quickly.
- Keep comments short and focused on what the example demonstrates.

## Setup & Run

```bash
# Install repo dependencies
uv sync --all-extras --dev

# For the OpenAI Agents example
uv sync --group integrations

# Start the proxy in another terminal
uv run gpt2giga

# Run an example
uv run python examples/openai/chat_completions/chat_completion.py
uv run python examples/openai/responses/single_prompt.py
uv run python examples/anthropic/messages.py
uv run python examples/gemini/generate_content.py
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
```

## Common Gotchas

- `examples/openai_agents.py` needs the `integrations` dependency group.
- Anthropic examples use the `anthropic` SDK directly, not the OpenAI client.
- Gemini examples use the official `google-genai` SDK and also need the `integrations` dependency group.
- OpenAI examples were moved under `examples/openai/`; keep README links and run commands aligned with that layout.
- Examples are excluded from coverage and are not the canonical place to implement application logic.
- Each API-style folder has its own `README.md`; update those alongside code examples when behavior changes.
