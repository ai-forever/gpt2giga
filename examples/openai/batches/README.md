# OpenAI Batches API через `gpt2giga`

Эта папка содержит runnable-пример для OpenAI Batches API (`/batches`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите пример:

```bash
uv run python examples/openai/batches/batches.py
```

## Что показывает пример

- создание входного `.jsonl` файла;
- загрузку файла через Files API;
- создание batch-задачи;
- чтение batch metadata и output file.

## Ограничения

- На текущем этапе OpenAI-compatible batch pipeline поддерживает только `/v1/chat/completions`.
- Batch-примера для `/v1/embeddings` нет, потому что этот endpoint пока не поддерживается в `POST /batches`.

## Готовый JSONL

- [`chat_completions_batch.jsonl`](./chat_completions_batch.jsonl): готовый OpenAI Batch input для `/v1/chat/completions`.
