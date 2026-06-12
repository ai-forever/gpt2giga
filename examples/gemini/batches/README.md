# Gemini batches examples

Эта папка содержит prepared-пример для Gemini-compatible batch flows. Router-код
реализован, но default public app пока не монтирует batch routes.

## Быстрый старт

```bash
uv run python examples/gemini/batches/batches.py
```

## Файлы

- `batches.py`: `batchGenerateContent` через uploaded JSONL source
- `batch_generate_content.jsonl`: готовые JSONL-строки для входного batch-файла
