# Anthropic Messages API через `gpt2giga`

`gpt2giga` поддерживает эндпоинты `/v1/messages` и `/v2/messages`,
совместимые с [Anthropic Messages API](https://docs.anthropic.com/en/api/messages).
Это позволяет использовать Anthropic Python SDK для работы с GigaChat через
локальный прокси.

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

В Anthropic Python SDK нет отдельного `api_version` параметра для клиента.
Версия GigaChat backend contract выбирается через `base_url`: `/v1` всегда
идёт в GigaChat v1 contract, `/v2` всегда идёт в GigaChat v2 contract.
Root `base_url` без версии использует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

```python
api_version = "v1"
client = Anthropic(
    base_url=f"http://localhost:8090/{api_version}/",
    api_key="any-key",
)
```

Также можно указать `api_version = "v2"` для v2-compatible routes.

- `api_key="any-key"` (заглушка, прокси не требует “настоящего” Anthropic API key)

Если вы:

- поменяли порт прокси — обновите `base_url`;
- включили API key auth (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`) — используйте ваш ключ (например, через `x-api-key` на прокси).

## Запуск

```bash
uv run python examples/anthropic/messages/basic/messages.py
uv run python examples/anthropic/messages/basic/messages_stream.py
uv run python examples/anthropic/messages/basic/stateful.py
uv run python examples/anthropic/messages/structured_outputs/structured_output.py
uv run python examples/anthropic/messages/structured_outputs/structured_output_stream.py
uv run python examples/anthropic/message_batches/basic.py
uv run python examples/anthropic/message_batches/structured_output.py
```

`messages/basic/stateful.py` требует, чтобы proxy был запущен с
`GPT2GIGA_CONVERSATION_STITCHING_ENABLED=True`.

## Что есть в папке

- `messages/basic/messages.py`: базовый запрос (не стрим)
- `messages/basic/messages_stream.py`: streaming
- `messages/basic/multi_turn.py`: многоходовый диалог
- `messages/basic/stateful.py`: stateful диалог через `x-gpt2giga-conversation-id` и GigaChat v2 chat completions
- `messages/basic/system_prompt.py`: системный промпт
- `messages/tools/function_calling.py`: tool use / function calling
- `messages/reasoning/reasoning.py`: extended thinking (`thinking`) → `reasoning_effort`
- `messages/structured_outputs/structured_output.py`: structured output (`output_config.format`)
- `messages/structured_outputs/structured_output_stream.py`: streaming structured output
- `messages/multimodal/image_url.py`, `messages/multimodal/base64_image.py`: изображения (URL и base64)
- `message_batches/basic.py`: Message Batches API
- `message_batches/structured_output.py`: structured output в Message Batches API
- `count_tokens/basic.py`: Count Tokens API
