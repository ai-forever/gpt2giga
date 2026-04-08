# Gemini Developer API через `gpt2giga`

`gpt2giga` поддерживает Gemini Developer API-совместимые эндпоинты под префиксом `/v1beta`. Это позволяет использовать официальный Python SDK [`google-genai`](https://github.com/googleapis/python-genai) поверх локального прокси.

## Зависимости

Gemini-примеры находятся в группе `integrations`:

```bash
uv sync --group integrations
```

## Базовая настройка

Во всех примерах используется:

- `api_key="0"` как заглушка;
- `http_options=types.HttpOptions(base_url="http://localhost:8090")`.

Если у вас включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), подставьте ваш ключ вместо `"0"`.

## Запуск

```bash
uv run python examples/gemini/generate_content.py
uv run python examples/gemini/stream_generate_content.py
uv run python examples/gemini/chat.py
uv run python examples/gemini/function_calling.py
uv run python examples/gemini/structured_output.py
uv run python examples/gemini/count_tokens.py
uv run python examples/gemini/embeddings.py
```

## Что есть в папке

- `generate_content.py`: базовый `models.generate_content(...)`
- `stream_generate_content.py`: streaming через `generate_content_stream(...)`
- `chat.py`: клиентский chat-session поверх `generateContent`
- `function_calling.py`: function declarations и tool response
- `structured_output.py`: JSON schema / structured output
- `count_tokens.py`: `models.count_tokens(...)`
- `embeddings.py`: `models.embed_content(...)`

## Нюансы

- Генерация использует реальные GigaChat model ids, например `GigaChat-2-Max`.
- Эмбеддинги используют модель, настроенную на стороне proxy. По умолчанию это `EmbeddingsGigaR`; если вы поменяли `GPT2GIGA_EMBEDDINGS`, обновите `model=...` в примере.
- Совместимость в этой итерации сфокусирована на text + function calling. Файлы, мультимодальные parts и built-in Gemini tools пока не поддерживаются.
