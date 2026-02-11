# AGENTS.md — examples/

## Package Identity

- **What:** Runnable usage examples demonstrating gpt2giga proxy capabilities
- **Audience:** Users integrating with gpt2giga via the OpenAI Python SDK
- **Prerequisite:** A running gpt2giga proxy server (default `http://localhost:8090`)

## Directory Structure

| Directory/File | What It Demonstrates |
|---|---|
| **`chat_completions/`** | **OpenAI Chat Completions API** |
| `chat_completions/chat_completion.py` | Basic streaming chat completion |
| `chat_completions/chat_reasoning.py` | Reasoning / chain-of-thought modes |
| `chat_completions/function_calling.py` | Tool/function calling |
| `chat_completions/structured_output.py` | JSON schema structured output |
| `chat_completions/structured_output_nested.py` | Nested structured output |
| `chat_completions/json_schema.py` | Raw JSON schema response format |
| `chat_completions/base64_image.py` | Base64-encoded image input |
| `chat_completions/image_url.py` | Image URL input |
| `chat_completions/documents.py` | Document processing |
| **`responses/`** | **OpenAI Responses API** |
| `responses/single_prompt.py` | Simple Responses API call |
| `responses/with_instructions.py` | Responses API with system instructions |
| `responses/function_calling.py` | Responses API with tools |
| `responses/structured_output.py` | Responses API with structured output |
| `responses/structured_output_nested.py` | Nested structured output |
| `responses/structured_output_pydantic_complex.py` | Complex nested Pydantic models |
| `responses/json_schema.py` | JSON schema response format |
| `responses/base64_image.py` | Responses API with base64 image |
| `responses/image_url.py` | Responses API with image URL |
| **`anthropic/`** | **Anthropic Messages API** |
| `anthropic/messages.py` | Basic non-streaming request |
| `anthropic/messages_stream.py` | Streaming messages |
| `anthropic/multi_turn.py` | Multi-turn conversation |
| `anthropic/system_prompt.py` | System prompt usage |
| `anthropic/function_calling.py` | Tool use / function calling |
| `anthropic/reasoning.py` | Extended thinking (`thinking` → `reasoning_effort`) |
| `anthropic/image_url.py` | Image URL input |
| `anthropic/base64_image.py` | Base64 image input |
| **Root examples** | **Standalone** |
| `embeddings.py` | Embeddings endpoint usage |
| `models.py` | Model listing and retrieval |
| `openai_agents.py` | OpenAI Agents SDK integration (multi-agent triage) |
| `weather_agent.py` | Agent with async weather tool |

## Patterns & Conventions

### Standard Example Template

Every example follows this pattern:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

# API call here
completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[{"role": "user", "content": "..."}],
)
```

```
✅ DO: Use `base_url="http://localhost:8090"` (default proxy port)
✅ DO: Use `api_key="0"` as placeholder (proxy doesn't require real OpenAI key)
✅ DO: Use `model="GigaChat-2-Max"` as default model in examples
✅ DO: Copy `chat_completions/chat_completion.py` as starting template for new examples
✅ DO: Copy `chat_completions/function_calling.py` as template for tool-use examples
❌ DON'T: Use real API keys in example code
❌ DON'T: Hardcode non-localhost URLs (some legacy examples have internal IPs — don't copy those)
```

### Adding a New Example

1. Choose the right directory: `chat_completions/` for Chat API, `responses/` for Responses API, `anthropic/` for Anthropic Messages API, root for standalone.
2. Name the file descriptively: `<feature_being_demonstrated>.py`.
3. Keep it self-contained — no imports from `gpt2giga` source (examples use only `openai` or `anthropic` SDK).
4. Add a brief comment at the top explaining what the example demonstrates.
5. Print the result so users can see output.

### Three API Styles

| API | Directory | Endpoint | SDK |
|---|---|---|---|
| Chat Completions API | `chat_completions/` | `POST /chat/completions` | `openai` |
| Responses API | `responses/` | `POST /responses` | `openai` |
| Anthropic Messages API | `anthropic/` | `POST /messages` | `anthropic` |

For each new feature, provide examples for **all applicable** API styles.

## Running Examples

```bash
# Start the proxy server first
uv run gpt2giga

# In another terminal, run an example
uv run python examples/chat_completions/chat_completion.py
uv run python examples/embeddings.py
```

## JIT Search Hints

```bash
# Find all examples using streaming
rg -n "stream=True" examples/

# Find all examples using tools/functions
rg -n "tools|functions" examples/

# Find all examples using structured output
rg -n "response_format|json_schema" examples/

# Find all examples using images
rg -l "base64|image_url" examples/

# Find Anthropic-specific examples
rg -l "anthropic" examples/anthropic/

# Find examples using reasoning/thinking
rg -n "reasoning|thinking" examples/
```

## Common Gotchas

- Examples are **not** part of test coverage (excluded in `pyproject.toml`).
- Some legacy examples have hardcoded internal IP addresses — always use `localhost:8090` for new examples.
- The `openai_agents.py` and `weather_agent.py` require the `integrations` dependency group: `uv sync --group integrations`.
- Anthropic examples use the `anthropic` SDK (not `openai`) — requires `uv sync --group integrations`.
- Each sub-directory has its own `README.md` with usage details.
