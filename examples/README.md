# Примеры использования `gpt2giga`

В папке `examples/` собраны runnable-примеры, показывающие работу прокси с разными совместимыми SDK и эндпоинтами.

## Перед запуском

1. Запустите `gpt2giga` (локально или в Docker).
2. По умолчанию прокси слушает `http://localhost:8090` (если вы меняли порт через `GPT2GIGA_PORT` / `--proxy.port`, обновите `base_url` в примерах).
3. Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ключ как `api_key` (OpenAI SDK) или через заголовок `x-api-key`.

## Быстрые ссылки

- OpenAI Python SDK:
  - Chat Completions API: [`examples/openai/chat_completions/README.md`](openai/chat_completions/README.md)
  - Responses API: [`examples/openai/responses/README.md`](openai/responses/README.md)
- Anthropic Python SDK (Messages API): [`examples/anthropic/README.md`](./anthropic/README.md)
- Gemini Python SDK (`google-genai`): [`examples/gemini/README.md`](./gemini/README.md)

## Запуск примеров (из корня репозитория)

```bash
# Chat Completions
uv run python examples/openai/chat_completions/chat_completion.py

# Files API
uv run python examples/openai/files.py

# Batches API
uv run python examples/openai/batches.py

# Responses API
uv run python examples/openai/responses/single_prompt.py

# Anthropic Messages API
uv run python examples/anthropic/messages.py

# Anthropic Message Batches API
uv run python examples/anthropic/message_batches.py

# Gemini Developer API
uv run python examples/gemini/generate_content.py
uv run python examples/gemini/structured_output.py

# Additional Responses API example
uv run python examples/responses/parallel_tool_call.py
```

## Дополнительно

- `examples/openai/embeddings.py`: эмбеддинги (`/embeddings` или `/v1/embeddings`)
- `examples/openai/models.py`: список моделей
- `examples/openai/files.py`: OpenAI Files API
- `examples/openai/batches.py`: OpenAI Batches API
- `examples/anthropic/message_batches.py`: Anthropic Message Batches API
- `examples/gemini/`: Gemini Developer API через официальный `google-genai` SDK
- `examples/responses/parallel_tool_call.py`: параллельные tool calls через Responses API
- `examples/openai_agents.py`: интеграция с OpenAI Agents SDK (потребуются доп. зависимости, см. `examples/AGENTS.md`)
