# Gemini embeddings example

Эта папка содержит runnable-пример для Gemini-compatible embeddings routes.

## Быстрый старт

```bash
uv run python examples/gemini/embeddings/embeddings.py
```

## Что показывает пример

- вызов `models.embed_content(...)`;
- передачу списка `contents=[...]` в одном запросе;
- вывод превью embedding-вектора для каждой строки.
