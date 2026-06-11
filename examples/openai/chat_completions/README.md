# OpenAI Chat Completions API через `gpt2giga`

Эта папка содержит примеры для OpenAI-style Chat Completions (`/chat/completions`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/openai/chat_completions/basic/chat_completion.py
```

## Про `base_url`

В примерах чаще используется:

- `OpenAI(base_url="http://localhost:8090", api_key="0")`

Некоторые примеры используют `.../v1` или `.../v2`. Root `base_url`
следует `GPT2GIGA_GIGACHAT_API_MODE`; `/v1` и `/v2` явно выбирают
соответствующий GigaChat backend contract. Если вы поменяли порт прокси,
обновите `base_url` соответственно.

Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ваш ключ как `api_key`.

## Файлы

- `basic/chat_completion.py`: базовый streaming
- `concurrency/per_model_max_connections_async.py`: async-проверка per-model max connections
- `reasoning/chat_reasoning.py`: reasoning/chain-of-thought режимы (если поддерживаются моделью)
- `tools/function_calling.py`: tool use / function calling
- `structured_outputs/structured_output.py`, `structured_outputs/structured_output_nested.py`: Structured Outputs
- `structured_outputs/json_schema.py`: JSON Schema
- `multimodal/image_url.py`, `multimodal/base64_image.py`: изображения
- `files/documents.py`: документы/вложения
