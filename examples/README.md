# Примеры использования `gpt2giga`

В папке `examples/` собраны runnable-примеры, показывающие работу прокси с разными совместимыми SDK и эндпоинтами.

## Перед запуском

1. Запустите `gpt2giga` (локально или в Docker).
2. По умолчанию прокси слушает `http://localhost:8090` (если вы меняли порт через `GPT2GIGA_PORT` / `--proxy.port`, обновите `base_url` в примерах).
3. Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ключ как `api_key` (OpenAI SDK) или через заголовок `x-api-key`.

OpenAI и Anthropic SDK выбирают GigaChat backend contract через версионный
`base_url`: `http://localhost:8090/v1` всегда идёт в GigaChat v1 contract,
`http://localhost:8090/v2` всегда идёт в GigaChat v2 contract.
Root `base_url` без версии (`http://localhost:8090`) использует
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.
Gemini-примеры используют нативный для `google-genai` вариант:
`types.HttpOptions(base_url="http://localhost:8090", ...)` с
`api_version="v1"` или `api_version="v2"`.

В runnable-примерах версия вынесена отдельной строкой, например:

```python
api_version = "v1"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
```

## Быстрые ссылки

- OpenAI Python SDK:
  - Chat Completions API: [`examples/openai/chat_completions/README.md`](openai/chat_completions/README.md)
  - Responses API: [`examples/openai/responses/README.md`](openai/responses/README.md)
- Anthropic Python SDK (Messages API): [`examples/anthropic/README.md`](./anthropic/README.md)
- Gemini-like REST API: [`examples/gemini/README.md`](./gemini/README.md)

## Логика папок

Примеры сгруппированы сначала по SDK/API (`openai`, `anthropic`, `gemini`, `chat_completions`, `responses`, `messages`), а внутри — по capability: `basic`, `tools`, `batches`, `files`, `multimodal`, `structured_outputs`, `reasoning`, `concurrency`.

## Запуск примеров (из корня репозитория)

```bash
# Chat Completions
uv run python examples/openai/chat_completions/basic/chat_completion.py

# Embeddings API
uv run python examples/openai/embeddings/basic.py

# Responses API
uv run python examples/openai/responses/basic/single_prompt.py

# Anthropic Messages API
uv run python examples/anthropic/messages/basic/messages.py

# Anthropic structured output
uv run python examples/anthropic/messages/structured_outputs/structured_output.py

# Gemini-like GenerateContent
uv run python examples/gemini/content/generate_content.py

# Gemini-like streaming
uv run python examples/gemini/content/stream_generate_content.py

# Additional Responses API examples
uv run python examples/openai/responses/tools/function_calling.py
```

Files API, OpenAI Batches API, Anthropic Message Batches API и Gemini Files/Batches API примеры уже подготовлены, но соответствующие router-модули временно не смонтированы в этом релизе.

## Дополнительно

- `examples/openai/embeddings/basic.py`: эмбеддинги (`/embeddings` или `/v1/embeddings`)
- `examples/openai/models/basic.py`: список моделей
- `examples/openai/files/basic.py`: OpenAI Files API (router подготовлен, но временно не смонтирован)
- `examples/openai/batches/basic.py`: OpenAI Batches API (router подготовлен, но временно не смонтирован)
- `examples/anthropic/messages/structured_outputs/structured_output.py`: Anthropic Messages structured output
- `examples/anthropic/messages/structured_outputs/structured_output_stream.py`: Anthropic streaming structured output
- `examples/anthropic/message_batches/structured_output.py`: Anthropic Message Batches structured output
- `examples/anthropic/message_batches/basic.py`: Anthropic Message Batches API (router подготовлен, но временно не смонтирован)
- `examples/openai/responses/tools/function_calling.py`: function calling через Responses API
- `examples/openai/agents/weather_handoff.py`: интеграция с OpenAI Agents SDK (потребуются доп. зависимости, см. `examples/AGENTS.md`)
- `examples/gemini/content/generate_content.py`: Gemini-like `generateContent`
- `examples/gemini/content/stream_generate_content.py`: Gemini-like `streamGenerateContent`
- `examples/gemini/content/chat.py`: Gemini chat-session через официальный SDK
- `examples/gemini/content/function_calling.py`: Gemini-like function declarations
- `examples/gemini/content/structured_output.py`: Gemini-like structured output
- `examples/gemini/count_tokens/count_tokens.py`: Gemini-like `countTokens`
- `examples/gemini/embeddings/embeddings.py`: Gemini-like `embedContent` и batch-style embeddings
- `examples/gemini/files/files.py`: Gemini Files API (router подготовлен, но временно не смонтирован)
- `examples/gemini/batches/batches.py`: Gemini Batch API (router подготовлен, но временно не смонтирован)
