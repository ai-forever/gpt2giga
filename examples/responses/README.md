# OpenAI Responses API через `gpt2giga`

Эта папка содержит примеры для OpenAI Responses API (`/responses`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/responses/single_prompt.py
```

## Про `base_url`

В примерах встречаются оба варианта:

- `OpenAI(base_url="http://localhost:8090", ...)`
- `OpenAI(base_url="http://localhost:8090/v1", ...)`

Оба варианта работают; если вы поменяли порт прокси, обновите `base_url` соответственно.

Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ваш ключ как `api_key`.

## Файлы

- `single_prompt.py`: минимальный пример
- `with_instructions.py`: instructions/system
- `function_calling.py`: tool use / function calling
- `structured_output.py`, `structured_output_nested.py`: Structured Outputs
- `json_schema.py`: JSON Schema
- `image_url.py`, `base64_image.py`: изображения

