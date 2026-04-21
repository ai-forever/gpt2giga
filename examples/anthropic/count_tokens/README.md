# Anthropic count_tokens example

Эта папка содержит пример для Anthropic-compatible `POST /messages/count_tokens`.

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите пример:

```bash
uv run python examples/anthropic/count_tokens/count_tokens.py
```

## Что показывает пример

- подсчёт токенов для простого сообщения;
- подсчёт с `system`;
- подсчёт с tool definitions;
- подсчёт для multi-turn payload.
