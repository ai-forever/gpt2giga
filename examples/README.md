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

## Запуск примеров (из корня репозитория)

```bash
# Chat Completions
uv run python examples/openai/chat_completions/chat_completion.py

# Embeddings API
uv run python examples/openai/embeddings.py

# Responses API
uv run python examples/openai/responses/single_prompt.py

# Anthropic Messages API
uv run python examples/anthropic/messages.py

# Anthropic structured output
uv run python examples/anthropic/structured_output.py

# Additional Responses API examples
uv run python examples/openai/responses/function_calling.py
```

Files API, OpenAI Batches API и Anthropic Message Batches API примеры уже подготовлены, но соответствующие router-модули временно не смонтированы в этом релизе.

## Дополнительно

- `examples/openai/embeddings.py`: эмбеддинги (`/embeddings` или `/v1/embeddings`)
- `examples/openai/models.py`: список моделей
- `examples/openai/files.py`: OpenAI Files API (router подготовлен, но временно не смонтирован)
- `examples/openai/batches.py`: OpenAI Batches API (router подготовлен, но временно не смонтирован)
- `examples/anthropic/structured_output.py`: Anthropic Messages structured output
- `examples/anthropic/structured_output_stream.py`: Anthropic streaming structured output
- `examples/anthropic/structured_output_batches.py`: Anthropic Message Batches structured output
- `examples/anthropic/message_batches.py`: Anthropic Message Batches API (router подготовлен, но временно не смонтирован)
- `examples/openai/responses/function_calling.py`: function calling через Responses API
- `examples/openai_agents.py`: интеграция с OpenAI Agents SDK (потребуются доп. зависимости, см. `examples/AGENTS.md`)
