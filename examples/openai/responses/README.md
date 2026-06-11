# OpenAI Responses API через `gpt2giga`

Эта папка содержит примеры для OpenAI Responses API (`/responses`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/openai/responses/basic/single_prompt.py
```

## Про `base_url`

В примерах встречаются оба варианта:

- `OpenAI(base_url="http://localhost:8090", ...)`
- `OpenAI(base_url="http://localhost:8090/v1", ...)`
- `OpenAI(base_url="http://localhost:8090/v2", ...)`

Root `base_url` следует `GPT2GIGA_RESPONSES_API_MODE` /
`GPT2GIGA_GIGACHAT_API_MODE`; `/v1` и `/v2` явно выбирают соответствующий
GigaChat backend contract. Если вы поменяли порт прокси, обновите `base_url`
соответственно.

Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ваш ключ как `api_key`.

## Файлы

- `basic/single_prompt.py`: минимальный пример
- `basic/stateful.py`: stateful Responses через `store` и `previous_response_id` (нужен Responses v2)
- `basic/with_instructions.py`: instructions/system
- `reasoning/reasoning.py`: reasoning в стиле Responses API
- `tools/function_calling.py`: tool use / function calling
- `tools/multiple_tool_calls.py`: несколько tool calls в одном сценарии
- `tools/gigachat_tools/`: GigaChat-specific built-in tools passthrough
- `structured_outputs/structured_output.py`, `structured_outputs/structured_output_nested.py`: Structured Outputs
- `structured_outputs/json_schema.py`: JSON Schema
- `multimodal/image_url.py`, `multimodal/base64_image.py`: изображения
