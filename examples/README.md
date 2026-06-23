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

# OpenAI Responses API через GigaFusion
uv run python examples/openai/responses/fusion/fusion_response.py

# Anthropic Messages API
uv run python examples/anthropic/messages/basic/messages.py

# Anthropic Messages API через GigaFusion
uv run python examples/anthropic/messages/fusion/fusion_message.py

# Anthropic stateful Messages API
uv run python examples/anthropic/messages/basic/stateful.py

# Anthropic structured output
uv run python examples/anthropic/messages/structured_outputs/structured_output.py

# Anthropic GigaChat built-in tools through v2 chat completions
uv run python examples/anthropic/messages/tools/gigachat_tools/code_interpreter.py
uv run python examples/anthropic/messages/tools/gigachat_tools/image_generate.py

# Gemini-like GenerateContent
uv run python examples/gemini/content/generate_content.py

# Gemini-like stateful GenerateContent
uv run python examples/gemini/content/stateful.py

# Gemini-like streaming
uv run python examples/gemini/content/stream_generate_content.py

# Gemini-like GigaChat built-in tools through v2 chat completions
uv run python examples/gemini/content/gigachat_tools/code_interpreter.py
uv run python examples/gemini/content/gigachat_tools/image_generate.py

# Additional Responses API examples
uv run python examples/openai/responses/tools/function_calling.py
```

## E2E smoke всех runnable-примеров

Для быстрой проверки примеров на локально запущенном прокси используйте:

```bash
uv run python scripts/run_examples_smoke.py --api-versions v1,v2 -n 4
```

Скрипт запускает каждый runnable `examples/**/*.py` отдельным процессом,
подставляет `api_version` из матрицы `v1/v2`, проверяет
`http://localhost:8090/health` перед стартом и в конце группирует ошибки по
версии API и файлу. Флаг `-n` / `--concurrency` задает количество одновременно
запущенных examples. Чтобы сохранить отчет:

```bash
uv run python scripts/run_examples_smoke.py \
  --api-versions v1,v2 \
  --concurrency 4 \
  --report-json .local/examples-smoke-report.json
```

По умолчанию пропускаются подготовленные, но пока не смонтированные Files/Batches
examples, OpenAI Agents example с внешними HTTP API и Fusion examples, которым
нужен `GPT2GIGA_FUSION_ENABLED=True`. Для принудительного запуска всего набора
добавьте `--include-known-unsupported`.

Для отдельной проверки Fusion после запуска прокси с
`GPT2GIGA_FUSION_ENABLED=True` используйте:

```bash
uv run python scripts/run_fusion_smoke.py --routes models,responses
```

Files API, OpenAI Batches API, Anthropic Message Batches API и Gemini Files/Batches API примеры уже подготовлены, но соответствующие router-модули временно не смонтированы в этом релизе.

Stateful Anthropic/Gemini examples require the proxy process to be started with
`GPT2GIGA_CONVERSATION_STITCHING_ENABLED=True`.

## Дополнительно

- `examples/openai/embeddings/basic.py`: эмбеддинги (`/embeddings` или `/v1/embeddings`)
- `examples/openai/chat_completions/fusion/fusion_chat_completion.py`: Chat Completions через локальный GigaFusion alias
- `examples/openai/responses/fusion/fusion_response.py`: Responses API через локальный GigaFusion alias
- `examples/anthropic/messages/fusion/fusion_message.py`: Anthropic Messages через локальный GigaFusion alias
- `examples/openai/models/basic.py`: список моделей
- `examples/openai/files/basic.py`: OpenAI Files API (router подготовлен, но временно не смонтирован)
- `examples/openai/batches/basic.py`: OpenAI Batches API (router подготовлен, но временно не смонтирован)
- `examples/anthropic/messages/structured_outputs/structured_output.py`: Anthropic Messages structured output
- `examples/anthropic/messages/structured_outputs/structured_output_stream.py`: Anthropic streaming structured output
- `examples/anthropic/messages/tools/gigachat_tools/code_interpreter.py`: Anthropic Messages GigaChat built-in code interpreter через v2 chat completions
- `examples/anthropic/messages/tools/gigachat_tools/image_generate.py`: Anthropic Messages GigaChat built-in image generation через v2 chat completions
- `examples/anthropic/messages/basic/stateful.py`: Anthropic stateful Messages через conversation stitching
- `examples/anthropic/message_batches/structured_output.py`: Anthropic Message Batches structured output
- `examples/anthropic/message_batches/basic.py`: Anthropic Message Batches API (router подготовлен, но временно не смонтирован)
- `examples/openai/responses/tools/function_calling.py`: function calling через Responses API
- `examples/openai/agents/weather_handoff.py`: интеграция с OpenAI Agents SDK (потребуются доп. зависимости, см. `examples/AGENTS.md`)
- `examples/gemini/content/generate_content.py`: Gemini-like `generateContent`
- `examples/gemini/content/stream_generate_content.py`: Gemini-like `streamGenerateContent`
- `examples/gemini/content/chat.py`: Gemini chat-session через официальный SDK
- `examples/gemini/content/stateful.py`: Gemini-like stateful `generateContent` через conversation stitching
- `examples/gemini/content/function_calling.py`: Gemini-like function declarations
- `examples/gemini/content/gigachat_tools/code_interpreter.py`: Gemini-like GigaChat built-in code interpreter через v2 chat completions
- `examples/gemini/content/gigachat_tools/image_generate.py`: Gemini-like GigaChat built-in image generation через v2 chat completions
- `examples/gemini/content/structured_output.py`: Gemini-like structured output
- `examples/gemini/count_tokens/count_tokens.py`: Gemini-like `countTokens`
- `examples/gemini/embeddings/embeddings.py`: Gemini-like `embedContent` и batch-style embeddings
- `examples/gemini/files/files.py`: Gemini Files API (router подготовлен, но временно не смонтирован)
- `examples/gemini/batches/batches.py`: Gemini Batch API (router подготовлен, но временно не смонтирован)
