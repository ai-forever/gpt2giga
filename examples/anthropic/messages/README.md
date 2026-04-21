# Anthropic Messages examples

Эта папка содержит runnable-примеры для Anthropic Messages API (`/messages` и `/v1/messages`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/anthropic/messages/messages.py
```

## Файлы

- `messages.py`: базовый запрос без streaming
- `messages_stream.py`: streaming через `client.messages.stream(...)`
- `multi_turn.py`: многоходовый диалог
- `system_prompt.py`: системный промпт
- `function_calling.py`: tool use / function calling
- `reasoning.py`: extended thinking (`thinking`) → `reasoning_effort`
- `image_url.py`, `base64_image.py`: vision-входы через URL и base64
