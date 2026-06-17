# Gemini Files examples

Эта папка содержит prepared-пример для Gemini Files API. Router-код реализован,
но default public app пока не монтирует Files routes.

## Быстрый старт

```bash
uv run python examples/gemini/files/files.py
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

- upload файла;
- `files.get(...)`;
- `files.list(...)`;
- download содержимого;
- delete загруженного файла.
