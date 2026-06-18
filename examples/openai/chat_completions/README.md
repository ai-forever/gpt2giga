# OpenAI Chat Completions API через `gpt2giga`

Эта папка содержит примеры для OpenAI-style Chat Completions (`/chat/completions`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/openai/chat_completions/basic/chat_completion.py
```

## Про `base_url`

В примерах версия выбирается явно через строку `api_version`:

```python
api_version = "v1"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
```

`/v1` всегда выбирает GigaChat v1 backend contract, `/v2` всегда выбирает
GigaChat v2 backend contract. Root `base_url` без версии тоже поддерживается и
следует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`, но runnable-примеры показывают
явный contract. Если вы поменяли порт прокси, обновите `base_url`
соответственно.

Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ваш ключ как `api_key`.

## Файлы

- `basic/chat_completion.py`: базовый streaming
- `fusion/fusion_chat_completion.py`: локальный GigaFusion alias `gpt2giga/fusion-code`
- `concurrency/per_model_max_connections_async.py`: async-проверка per-model max connections
- `reasoning/chat_reasoning.py`: reasoning/chain-of-thought режимы (если поддерживаются моделью)
- `tools/function_calling.py`: tool use / function calling
- `structured_outputs/structured_output.py`, `structured_outputs/structured_output_nested.py`: Structured Outputs
- `structured_outputs/json_schema.py`: JSON Schema
- `multimodal/image_url.py`, `multimodal/base64_image.py`: изображения
- `files/documents.py`: документы/вложения
