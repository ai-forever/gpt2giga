# Gemini content-generation examples

Эта папка содержит runnable-примеры для Gemini content-generation сценариев
поверх локального `gpt2giga` proxy.

## Быстрый старт

```bash
uv run python examples/gemini/content/generate_content.py
uv run python examples/gemini/content/stream_generate_content.py
```

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
- `function_calling.py`: function declarations и tool response
- `structured_output.py`: JSON schema / structured output
