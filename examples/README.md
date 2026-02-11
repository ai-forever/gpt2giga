# Примеры использования `gpt2giga`

В папке `examples/` собраны runnable-примеры, показывающие работу прокси с разными совместимыми SDK и эндпоинтами.

## Перед запуском

1. Запустите `gpt2giga` (локально или в Docker).
2. По умолчанию прокси слушает `http://localhost:8090` (если вы меняли порт через `GPT2GIGA_PORT` / `--proxy.port`, обновите `base_url` в примерах).
3. Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ключ как `api_key` (OpenAI SDK) или через заголовок `x-api-key`.

## Быстрые ссылки

- OpenAI Python SDK:
  - Chat Completions API: [`examples/chat_completions/README.md`](./chat_completions/README.md)
  - Responses API: [`examples/responses/README.md`](./responses/README.md)
- Anthropic Python SDK (Messages API): [`examples/anthropic/README.md`](./anthropic/README.md)

## Запуск примеров (из корня репозитория)

```bash
# Chat Completions
uv run python examples/chat_completions/chat_completion.py

# Responses API
uv run python examples/responses/single_prompt.py

# Anthropic Messages API
uv run python examples/anthropic/messages.py
```

## Дополнительно

- `examples/embeddings.py`: эмбеддинги (`/embeddings` или `/v1/embeddings`)
- `examples/models.py`: список моделей
- `examples/openai_agents.py`, `examples/weather_agent.py`: интеграции с OpenAI Agents SDK (потребуются доп. зависимости, см. `examples/AGENTS.md`)

