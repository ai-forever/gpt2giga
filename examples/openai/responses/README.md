# OpenAI Responses API через `gpt2giga`

Эта папка содержит примеры для OpenAI Responses API (`/responses`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/openai/responses/basic/single_prompt.py
```

## Про `base_url`

В примерах версия выбирается явно через строку `api_version`:

```python
api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
```

`/v1` всегда выбирает GigaChat v1 backend contract, `/v2` всегда выбирает
GigaChat v2 backend contract. Root `base_url` без версии тоже поддерживается и
следует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`, но runnable-примеры показывают
явный contract.
GigaChat-specific built-in tools в `tools/gigachat_tools/` оставлены на `/v2`,
потому что этот passthrough требует v2-compatible behavior. Если вы поменяли
порт прокси, обновите `base_url` соответственно.

Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ваш ключ как `api_key`.

## Файлы

- `basic/single_prompt.py`: минимальный пример
- `basic/stateful.py`: stateful Responses через `store` и `previous_response_id` (нужен Responses v2)
- `basic/with_instructions.py`: instructions/system
- `reasoning/reasoning.py`: reasoning в стиле Responses API
- `tools/function_calling.py`: tool use / function calling
- `tools/multiple_tool_calls.py`: несколько tool calls в одном сценарии
- `tools/gigachat_tools/`: GigaChat-specific built-in tools passthrough
- `structured_outputs/structured_output.py`, `structured_outputs/structured_output_nested.py`: Structured Outputs
- `structured_outputs/json_schema.py`: JSON Schema
- `multimodal/image_url.py`, `multimodal/base64_image.py`: изображения

## Контракты 0.3.1a1

[Обязательные вызовы в потоке](tools/required_parallel_stream.py) показывают
`tool_choice="required"`, `parallel_tool_calls`, сбор финального `response.completed`
и возврат всех результатов по `call_id`. Даже одинаковые имена функций не смешиваются.
Общий `tools_state_id` берётся из metadata шлюза и переносится отдельно от ID вызова.
Финальный запрос использует `tool_choice="none"`, чтобы не требовать новый вызов.

[Stateful-пример](basic/stateful.py) использует явный `/v2` независимо от настройки
прокси. Сохраните `response.id` на клиенте: `GET /responses/{id}` не реализован.
В v1 `store=true` и `previous_response_id` возвращают 400. Отсутствие `store`
отображается как `false`; неуказанные `temperature` и `top_p` — как `null`.
