# Примеры использования `gpt2giga`

В папке `examples/` собраны runnable-примеры, показывающие работу прокси с разными совместимыми SDK, capability-эндпоинтами и agent-style сценариями.

## Перед запуском

1. Запустите `gpt2giga` (локально или в Docker).
2. По умолчанию прокси слушает `http://localhost:8090` (если вы меняли порт через `GPT2GIGA_PORT` / `--proxy.port`, обновите `base_url` в примерах).
3. Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ключ как `api_key` (OpenAI SDK) или через заголовок `x-api-key`.

## Быстрые ссылки

- OpenAI Python SDK:
  - Chat Completions API: [`examples/openai/chat/README.md`](openai/chat/README.md)
  - Responses API: [`examples/openai/responses/README.md`](openai/responses/README.md)
  - Files API: [`examples/openai/files/README.md`](openai/files/README.md)
  - Batches API: [`examples/openai/batches/README.md`](openai/batches/README.md)
  - Embeddings API: [`examples/openai/embeddings/README.md`](openai/embeddings/README.md)
  - Models API: [`examples/openai/models/README.md`](openai/models/README.md)
- Anthropic Python SDK (Messages API): [`examples/anthropic/README.md`](./anthropic/README.md)
- Gemini Python SDK (`google-genai`): [`examples/gemini/README.md`](./gemini/README.md)
- Translation examples: [`examples/translate/README.md`](translate/README.md)
- Agents SDK examples: [`examples/agents/README.md`](agents/README.md)

## Запуск примеров (из корня репозитория)

```bash
# OpenAI Chat Completions
uv run python examples/openai/chat/chat_completion.py

# OpenAI Responses API
uv run python examples/openai/responses/single_prompt.py

# OpenAI Files API
uv run python examples/openai/files/files.py

# OpenAI Batches API
uv run python examples/openai/batches/batches.py

# OpenAI Embeddings API
uv run python examples/openai/embeddings/embeddings.py

# OpenAI Models API
uv run python examples/openai/models/models.py

# Anthropic Messages API
uv run python examples/anthropic/messages.py

# Anthropic Message Batches API
uv run python examples/anthropic/message_batches.py
uv run python examples/anthropic/message_batches_from_jsonl.py

# Gemini Developer API
uv run python examples/gemini/generate_content.py
uv run python examples/gemini/files.py
uv run python examples/gemini/batches.py
uv run python examples/gemini/structured_output.py
uv run python examples/gemini/embeddings.py

# Provider-to-provider translation
uv run python examples/translate/openai_to_anthropic.py
uv run python examples/translate/openai_to_gemini.py
uv run python examples/translate/openai_to_gigachat.py
uv run python examples/translate/anthropic_to_openai.py
uv run python examples/translate/anthropic_to_gemini.py
uv run python examples/translate/anthropic_to_gigachat.py
uv run python examples/translate/gemini_to_openai.py
uv run python examples/translate/gemini_to_anthropic.py
uv run python examples/translate/gemini_to_gigachat.py

# Agents SDK examples
uv sync --group integrations
uv run python examples/agents/openai_agents.py
WEATHER_API_KEY=... uv run python examples/agents/weather_agent.py
```

## Структура

- `examples/openai/chat/`: Chat Completions examples
- `examples/openai/responses/`: Responses API examples
- `examples/openai/files/`: Files API example
- `examples/openai/batches/`: Batches API example
- `examples/openai/embeddings/`: embeddings example
- `examples/openai/models/`: models listing/retrieval example
- `examples/anthropic/`: Anthropic Messages and Message Batches examples
- `examples/gemini/`: Gemini Developer API examples
- `examples/translate/`: provider-to-provider translation examples
- `examples/agents/`: OpenAI Agents SDK and tool-driven weather agent examples

## Дополнительно

- `examples/agents/openai_agents.py` и `examples/agents/weather_agent.py` требуют `uv sync --group integrations`.
- `examples/agents/weather_agent.py` дополнительно использует `WEATHER_API_KEY`.
- `examples/gemini/`: Gemini Developer API через официальный `google-genai` SDK.
- OpenAI examples покрывают и `batches`, и `embeddings`.
- Anthropic examples покрывают `messages` и `message batches`; embeddings-совместимого route в проекте сейчас нет.
- Gemini examples покрывают и `batchGenerateContent`, и embeddings.
