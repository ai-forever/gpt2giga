# OpenAI Responses API через `gpt2giga`

Эта папка содержит примеры для OpenAI Responses API (`/responses`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите любой пример:

```bash
uv run python examples/openai/responses/single_prompt.py
```

## Про `base_url`

В примерах встречаются оба варианта:

- `OpenAI(base_url="http://localhost:8090", ...)`
- `OpenAI(base_url="http://localhost:8090/v1", ...)`

Оба варианта работают; если вы поменяли порт прокси, обновите `base_url` соответственно.

Если включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передавайте ваш ключ как `api_key`.

## Что поддерживается в `/responses`

- native `previous_response_id` и `conversation.id` для продолжения диалога поверх in-memory thread state;
- `text.format` / `json_schema` без fake-function обходных путей;
- function tools и built-in tools в best-effort режиме: `web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`.

Примеры built-in tools через OpenAI SDK:

```python
response = client.responses.create(
    model="gpt-5",
    input="Курс доллара на сегодня",
    tools=[{"type": "web_search"}],
    store=False,
)
```

Расширенная конфигурация `web_search` в GigaChat-стиле тоже прокидывается:

```python
response = client.responses.create(
    model="gpt-5",
    input="Что нового в мире ИИ?",
    tools=[
        {
            "type": "web_search",
            "web_search": {
                "type": "actual_info_web_search",
                "indexes": ["news"],
                "flags": ["gopro"],
            },
        }
    ],
    store=False,
)
```

GigaChat-only built-ins можно вызывать так же:

```python
response = client.responses.create(
    model="gpt-5",
    input="Открой и кратко перескажи содержимое https://developers.sber.ru",
    tools=[{"type": "url_content_extraction"}],
    store=False,
)
```

`previous_response_id` и `conversation.id` работают только пока жив процесс `gpt2giga`: после рестарта thread state не сохраняется.

## Файлы

- `single_prompt.py`: минимальный пример
- `multi_turn_previous_response.py`: multi-turn диалог через `previous_response_id`
- `reasoning.py`: reasoning в стиле Responses API
- `with_instructions.py`: instructions/system
- `function_calling.py`: tool use / function calling
- `structured_output.py`, `structured_output_nested.py`: Structured Outputs
- `json_schema.py`: JSON Schema
- `image_url.py`, `base64_image.py`: изображения
