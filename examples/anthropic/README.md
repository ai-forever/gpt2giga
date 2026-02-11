# Anthropic Messages API через `gpt2giga`

`gpt2giga` поддерживает эндпоинт `/v1/messages`, совместимый с [Anthropic Messages API](https://docs.anthropic.com/en/api/messages). Это позволяет использовать Anthropic Python SDK для работы с GigaChat через локальный прокси.

## Зависимости

Anthropic SDK не входит в обязательные зависимости пакета.

- Если вы работаете из исходников (uv):

  ```bash
  uv sync --group integrations
  ```

- Если вы ставили `gpt2giga` через `pip`, установите отдельно:

  ```bash
  pip install anthropic
  ```

## Базовая настройка

Во всех примерах используется:

- `base_url="http://localhost:8090/v1"`
- `api_key="any-key"` (заглушка, прокси не требует “настоящего” Anthropic API key)

Если вы:

- поменяли порт прокси — обновите `base_url`;
- включили API key auth (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`) — используйте ваш ключ (например, через `x-api-key` на прокси).

## Запуск

```bash
uv run python examples/anthropic/messages.py
uv run python examples/anthropic/messages_stream.py
```

## Что есть в папке

- `messages.py`: базовый запрос (не стрим)
- `messages_stream.py`: streaming
- `multi_turn.py`: многоходовый диалог
- `system_prompt.py`: системный промпт
- `function_calling.py`: tool use / function calling
- `reasoning.py`: extended thinking (`thinking`) → `reasoning_effort`
- `image_url.py`, `base64_image.py`: изображения (URL и base64)

