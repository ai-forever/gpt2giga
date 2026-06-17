# Gemini content-generation examples

Эта папка содержит runnable-примеры для Gemini content-generation сценариев
поверх локального `gpt2giga` proxy.

## Быстрый старт

```bash
uv run python examples/gemini/content/generate_content.py
uv run python examples/gemini/content/stream_generate_content.py
uv run python examples/gemini/content/stateful.py
uv run python examples/gemini/content/gigachat_tools/code_interpreter.py
uv run python examples/gemini/content/gigachat_tools/image_generate.py
```

`stateful.py` требует, чтобы proxy был запущен с
`GPT2GIGA_CONVERSATION_STITCHING_ENABLED=True`.

## Версия API

Выбор версии лежит в `types.HttpOptions`: `api_version="v1"` отправляет запросы
в GigaChat v1 contract, `api_version="v2"` — в GigaChat v2 contract. Если
`api_version` не указан, используется backend mode из
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

```python
api_version = "v1"
client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
    ),
)
```

## Файлы

- `generate_content.py`: базовый `models.generate_content(...)`
- `stream_generate_content.py`: streaming через `generate_content_stream(...)`
- `chat.py`: клиентский chat-session поверх `generateContent`
- `stateful.py`: stateful `generateContent` через `x-gpt2giga-conversation-id` и GigaChat v2 chat completions
- `function_calling.py`: function declarations и tool response
- `gigachat_tools/code_interpreter.py`: GigaChat v2 built-in code interpreter через typed `google-genai`
- `gigachat_tools/image_generate.py`: GigaChat v2 built-in image generation через raw Gemini-compatible request
- `structured_output.py`: JSON schema / structured output
