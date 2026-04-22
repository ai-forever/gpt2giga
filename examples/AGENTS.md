# AGENTS.md — examples/

## Package Identity

- **What:** Runnable examples for using `gpt2giga` through OpenAI, Anthropic, Gemini, Agents SDK, batch-validation, and provider-translation flows
- **Audience:** Users validating proxy behavior or copying starter integrations
- **Default target:** `http://localhost:8090`

## Directory Layout

| Path | Purpose |
|---|---|
| `examples/openai/chat/` | OpenAI Chat Completions examples |
| `examples/openai/responses/` | OpenAI Responses API examples |
| `examples/openai/files/` | OpenAI Files API example |
| `examples/openai/batches/` | OpenAI Batches API example |
| `examples/openai/embeddings/` | OpenAI embeddings example |
| `examples/openai/models/` | OpenAI models listing/retrieval example |
| `examples/batch_validation/` | Standalone batch validation examples |
| `examples/anthropic/messages/` | Anthropic Messages API examples |
| `examples/anthropic/count_tokens/` | Anthropic Messages token counting example |
| `examples/anthropic/batches/` | Anthropic Message Batches API examples |
| `examples/gemini/content/` | Gemini content-generation examples |
| `examples/gemini/count_tokens/` | Gemini token counting example |
| `examples/gemini/files/` | Gemini Files API example |
| `examples/gemini/batches/` | Gemini batchGenerateContent example |
| `examples/gemini/embeddings/` | Gemini embeddings example |
| `examples/agents/` | OpenAI Agents SDK example |
| `examples/translate/` | Provider-to-provider translation examples for `/translate` |
| `examples/README.md` | Example index |

### Notable Example Files

- `openai/chat/chat_completion.py`: basic streaming chat
- `openai/chat/chat_reasoning.py`: reasoning mode
- `openai/chat/function_calling.py`: tool calling
- `openai/chat/documents.py`: document/file-style input
- `openai/responses/reasoning.py`: Responses API reasoning example
- `openai/responses/structured_output.py`: structured outputs
- `openai/files/files.py`: Files API upload/list/content/delete flow
- `openai/batches/batches.py`: Batches API end-to-end flow
- `batch_validation/openai_validate.py`: standalone batch validation for OpenAI rows
- `batch_validation/anthropic_validate.py`: standalone batch validation for Anthropic rows
- `batch_validation/gemini_validate.py`: standalone batch validation for Gemini rows
- `anthropic/messages/messages.py`: basic Messages API call
- `anthropic/messages/messages_stream.py`: streaming Messages API
- `anthropic/batches/message_batches.py`: Anthropic Message Batches API
- `anthropic/count_tokens/count_tokens.py`: token counting endpoint
- `gemini/content/generate_content.py`: basic Gemini `generate_content`
- `gemini/files/files.py`: Gemini file upload/list/download flow
- `gemini/batches/batches.py`: Gemini `batchGenerateContent` via JSONL file
- `gemini/content/function_calling.py`: Gemini function declarations / tool responses
- `gemini/content/structured_output.py`: Gemini JSON schema output
- `agents/openai_agents.py`: OpenAI Agents SDK handoffs and tools
- `translate/openai_to_gigachat.py`: offline OpenAI chat payload translation into GigaChat format
- `translate/gemini_to_openai.py`: Gemini-to-OpenAI payload translation
- `translate/anthropic_to_gemini.py`: Anthropic-to-Gemini payload translation

## Patterns & Conventions

- Keep examples self-contained and runnable with repo dependencies.
- Use real SDK clients (`openai`, `anthropic`, `google-genai`, `openai-agents`) rather than importing internal `gpt2giga` modules.
- Default to `api_key="0"` or another placeholder unless the example is specifically about proxy API-key auth.
- Prefer `GigaChat-2-Max` in examples unless the example is about model selection.
- Print or stream visible output so users can confirm behavior quickly.
- Keep comments short and focused on what the example demonstrates.
- Keep provider-level folders organized by capability (`chat`, `responses`, `messages`, `count_tokens`, `files`, `batches`, `embeddings`, `models`).

## Setup & Run

```bash
# Install repo dependencies
uv sync --all-extras --dev

# For Agents SDK and Gemini examples
uv sync --group integrations

# Start the proxy in another terminal
uv run gpt2giga

# Run representative examples
uv run python examples/openai/chat/chat_completion.py
uv run python examples/openai/responses/single_prompt.py
uv run python examples/openai/files/files.py
uv run python examples/openai/batches/batches.py
uv run python examples/batch_validation/openai_validate.py
uv run python examples/anthropic/messages/messages.py
uv run python examples/gemini/content/generate_content.py
uv run python examples/agents/openai_agents.py
uv run python examples/translate/openai_to_gigachat.py
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

- `examples/agents/openai_agents.py` needs the `integrations` dependency group.
- Anthropic examples use the `anthropic` SDK directly, not the OpenAI client.
- Gemini examples use the official `google-genai` SDK and also need the `integrations` dependency group.
- `examples/translate/` targets the proxy `/translate` endpoint and is useful even when you do not have upstream credentials configured.
- Examples are excluded from coverage and are not the canonical place to implement application logic.
- Each capability folder should keep its local `README.md` aligned with runnable file paths.
