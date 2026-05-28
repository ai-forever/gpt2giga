# Совместимость параметров клиентов

Этот документ служит публичным справочником совместимости параметров клиентских
SDK OpenAI и Anthropic в gpt2giga. Он отражает текущую структуру исходного кода:

- роутеры OpenAI: `gpt2giga/routers/openai/`
- роутеры Anthropic: `gpt2giga/routers/anthropic/`
- общие политики запросов: `gpt2giga/common/client_params.py`
- классификация запросов OpenAI: `gpt2giga/protocol/request/params.py`
- классификация запросов Anthropic: `gpt2giga/protocol/anthropic/params.py`

Другие семейства клиентов в этой проверке совместимости не рассматриваются.

## Статусы совместимости

| Статус | Значение |
|---|---|
| `supported` | Параметр влияет на запрос или ответ и покрыт тестами. |
| `accepted_ignored` | Параметр принимается для совместимости с SDK, но не отправляется upstream. |
| `rejected` | Параметр нельзя корректно эмулировать, поэтому возвращается совместимая ошибка `400`. |
| `not_applicable` | Опция относится к клиентской настройке транспорта, а не к серверному параметру тела запроса. |

## Транспортные опции SDK

`base_url`, `api_key`, `timeout`, настройки повторных попыток, пользовательский
`http_client`, конфигурация прокси и низкоуровневые транспортные настройки
являются клиентскими опциями SDK. gpt2giga не назначает им серверную семантику.

Учетные данные и транспортные заголовки никогда не пересылаются в GigaChat как
произвольные upstream-метаданные. Это касается `Authorization`, `x-api-key`,
cookie, `host`, заголовков содержимого и передачи, `x-stainless-*`,
`openai-*` и `anthropic-*`.

## `extra_headers` и `extra_query`

Только эти диагностические заголовки могут попасть в upstream HTTP-запрос
GigaChat:

- `x-request-id`
- `x-correlation-id`
- `x-trace-id`
- `traceparent`

Список разрешенных upstream query-параметров по умолчанию пуст. Значения SDK
`extra_query` и обычные неизвестные query-параметры принимаются прокси там, где
это разрешает маршрут, но произвольные ключи не пересылаются в GigaChat.

## `extra_body`

SDK OpenAI и Anthropic обычно объединяют `extra_body` с исходящим JSON-телом как
поля верхнего уровня. HTTP-клиенты, работающие напрямую, также могут отправлять
буквальный объект `extra_body`. gpt2giga обрабатывает обе формы.

Разрешенные поля, специфичные для GigaChat:

- `flags`
- `function_ranker`
- `profanity_check`
- `repetition_penalty`
- `storage`
- `update_interval`

Для OpenAI Chat Completions, OpenAI Responses и Anthropic Messages эти поля
переносятся в GigaChat `additional_fields`. Неизвестные поля `extra_body`
отклоняются с ошибкой `400`.

OpenAI Embeddings отклоняет `extra_body`; на данный момент для embeddings нет
разрешенных полей, специфичных для GigaChat.

## Параметры тела OpenAI

| Эндпоинт | Поддерживается |
|---|---|
| Chat Completions | `model`, `messages`, `stream`, `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`, функциональные `tools`, `functions`, `function_call`, поддерживаемый `tool_choice`, `response_format`, `reasoning`, `reasoning_effort`, разрешенный `extra_body` |
| Responses | `model`, `input`, `instructions`, `stream`, `temperature`, `top_p`, `max_output_tokens`, функциональные `tools`, поддерживаемый `tool_choice`, `text.format`, `response_format`, `reasoning`, `reasoning_effort`, разрешенный `extra_body` |
| Embeddings | `input`, `model`, `dimensions`, `encoding_format`, `user`, `extra_headers`, `extra_query` |
| Models | `GET /models`, `GET /models/{model}` |

Поля метаданных OpenAI, такие как `user`, `metadata`, `service_tier`,
`safety_identifier`, `seed`, `prompt_cache_key` и `prompt_cache_retention`,
принимаются и игнорируются там, где они классифицированы.

Неподдерживаемые параметры OpenAI возвращают `400`, если присутствуют со
значимыми значениями. Примеры: `logprobs`, `top_logprobs`, `logit_bias`,
аудиовывод, `prediction`, `web_search_options`, встроенные инструменты,
`n > 1`, `parallel_tool_calls=true`, сохраненные запросы completions, а также
сохраняющие состояние возможности Responses, такие как `previous_response_id` и
`conversation`.

## Параметры тела Anthropic

| Эндпоинт | Поддерживается |
|---|---|
| Messages | `model`, `messages`, `system`, `max_tokens`, `stream`, `temperature`, `top_p`, `stop_sequences`, локальные функциональные `tools`, значения `tool_choice` `auto`/`none`/принудительный `tool`, `thinking`, `output_config.format`, `output_format`, разрешенный `extra_body` |
| Count Tokens | `model`, `messages`, `system`, `tools`, текст схемы structured output, совместимая валидация содержимого сообщений |
| Models | `GET /models`, `GET /models/{model_id}`, когда запрос содержит заголовки Anthropic SDK, например `anthropic-version` |

Anthropic `metadata`, `service_tier`, `top_k`, beta-заголовки и `betas`
принимаются и игнорируются там, где они классифицированы.

Неподдерживаемые параметры или возможности Anthropic возвращают `400`. Примеры:
`container`, `context_management`, `mcp_servers`, серверные инструменты,
веб-поиск, выполнение кода, управление компьютером, блоки содержимого
document/file, загрузки в container, блоки результатов поиска, citations, а
также входные блоки `thinking`/`redacted_thinking`.

Код Anthropic Message Batches существует, но публичный роутер не подключается,
пока в GigaChat SDK или backend не появится поддержка batch-операций.

## Область маршрутов

Подключенные маршруты доступны и в корне, и под `/v1` через роутер приложения.
Подготовленные, но отключенные маршруты OpenAI Files/Batches и Anthropic Message
Batches намеренно исключены из схемы OpenAPI по умолчанию.
