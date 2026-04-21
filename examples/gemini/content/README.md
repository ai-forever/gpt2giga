# Gemini content-generation examples

Эта папка содержит runnable-примеры для Gemini content-generation сценариев поверх `/v1beta/models/*`.

## Быстрый старт

```bash
uv run python examples/gemini/content/generate_content.py
uv run python examples/gemini/content/stream_generate_content.py
```

## Файлы

- `generate_content.py`: базовый `models.generate_content(...)`
- `stream_generate_content.py`: streaming через `generate_content_stream(...)`
- `chat.py`: клиентский chat-session поверх `generateContent`
- `function_calling.py`: function declarations и tool response
- `structured_output.py`: JSON schema / structured output
