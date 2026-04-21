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
uv run python examples/anthropic/messages/messages.py
uv run python examples/anthropic/messages/messages_stream.py
uv run python examples/anthropic/count_tokens/count_tokens.py
uv run python examples/anthropic/batches/message_batches.py
uv run python examples/anthropic/batches/message_batches_from_jsonl.py
```

## Структура по capability

| Capability | Каталог | Что внутри |
|---|---|---|
| `messages` | [messages/README.md](./messages/README.md) | Базовые запросы, streaming, multi-turn, system prompt, tools, vision, reasoning |
| `count_tokens` | [count_tokens/README.md](./count_tokens/README.md) | Подсчёт токенов для Messages payload |
| `message_batches` | [batches/README.md](./batches/README.md) | Создание batches и запуск из готового JSONL |

## Что сейчас недоступно

- Отдельного Anthropic-compatible embeddings endpoint в `gpt2giga` сейчас нет, поэтому embeddings-примера для Anthropic SDK в этой папке нет.
