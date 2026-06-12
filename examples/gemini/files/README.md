# Gemini Files examples

Эта папка содержит prepared-пример для Gemini Files API. Router-код реализован,
но default public app пока не монтирует Files routes.

## Быстрый старт

```bash
uv run python examples/gemini/files/files.py
```

## Что показывает пример

- upload файла;
- `files.get(...)`;
- `files.list(...)`;
- download содержимого;
- delete загруженного файла.
