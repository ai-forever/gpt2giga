# Anthropic Message Batches examples

Эта папка содержит runnable-примеры для Anthropic Message Batches API (`/messages/batches` и `/v1/messages/batches`).

## Быстрый старт

```bash
uv run python examples/anthropic/batches/message_batches.py
uv run python examples/anthropic/batches/message_batches_from_jsonl.py
```

## Файлы

- `message_batches.py`: создаёт batch из встроенного списка `requests`
- `message_batches_from_jsonl.py`: читает входные данные из готового JSONL
- `message_batches.jsonl`: готовые строки в формате `custom_id` + `params`
