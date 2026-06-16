# Gemini embeddings example

Эта папка содержит runnable-пример для Gemini-compatible embeddings routes.

## Быстрый старт

```bash
uv run python examples/gemini/embeddings/embeddings.py
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

## Что показывает пример

- вызов `models.embed_content(...)`;
- передачу списка `contents=[...]` в одном запросе;
- вывод превью embedding-вектора для каждой строки.
