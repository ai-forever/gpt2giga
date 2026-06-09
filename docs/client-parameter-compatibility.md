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
| `rejected` | Запрос имеет неисполняемую форму, например отсутствует обязательный `input` или `extra_body` не является объектом. Optional client feature-флаги не используют этот статус. |
| `not_applicable` | Опция относится к клиентской настройке транспорта, а не к серверному параметру тела запроса. |

## Транспортные опции SDK

`base_url`, `api_key`, `timeout`, настройки повторных попыток, пользовательский
`http_client`, конфигурация прокси и низкоуровневые транспортные настройки
являются клиентскими опциями SDK. gpt2giga не назначает им серверную семантику.

Учетные данные и транспортные заголовки не пересылаются в GigaChat как
произвольные upstream-метаданные. Это касается `Authorization`, `x-api-key`,
cookie, `host`, заголовков содержимого и передачи, `x-stainless-*`,
`openai-*` и `anthropic-*`. Для намеренной передачи авторизации GigaChat
используйте отдельный режим `GPT2GIGA_PASS_TOKEN=True`.

## `extra_headers` и `extra_query`

`extra_headers` из SDK приходит на сервер как обычные HTTP headers. gpt2giga
переносит безопасные заголовки в request-scoped contextvars SDK GigaChat:

- `x-request-id`
- `x-session-id`
- `x-service-id`
- `x-operation-id`
- `x-client-id`
- `x-trace-id`
- `x-agent-id`

Остальные безопасные пользовательские заголовки передаются через
`custom_headers_cvar`. Диагностические `x-correlation-id` и `traceparent` также
могут быть переданы как custom headers. `Authorization`, `x-api-key`, transport
headers и SDK-internal заголовки `x-stainless-*`, `openai-*`, `anthropic-*`
остаются заблокированными.

URL contextvars SDK, например `chat_url_cvar` и
`chat_completions_url_cvar`, не заполняются из `extra_headers`.

`extra_query` по умолчанию не прокидывает произвольные query-параметры upstream:
список разрешенных upstream query-параметров пуст.

## `extra_body`

SDK OpenAI и Anthropic обычно объединяют `extra_body` с исходящим JSON-телом как
поля верхнего уровня. HTTP-клиенты, работающие напрямую, также могут отправлять
буквальный объект `extra_body`. gpt2giga обрабатывает обе формы.

Для OpenAI Chat Completions, OpenAI Responses и Anthropic Messages объект
`extra_body` переносится в GigaChat `additional_fields` целиком. SDK-style
unknown top-level поля, которые появляются после разворачивания `extra_body`
клиентом, обрабатываются так же.

Известные unsupported optional параметры клиентов принимаются и игнорируются, если
отправлены как top-level поля: например `logprobs`, `audio`, `container` или
`mcp_servers`. `previous_response_id` поддерживается для OpenAI Responses в
GigaChat v2 mode и маппится в `storage.thread_id`; в Responses v1 mode он
принимается и игнорируется.
Если такой же ключ явно положить внутрь literal `extra_body`, gpt2giga передаст
его в `additional_fields`, а итоговую поддержку определит GigaChat upstream.

OpenAI Embeddings принимает и игнорирует `extra_body`, неизвестные top-level
поля и `dimensions`; на данный момент для embeddings нет разрешенных полей,
специфичных для GigaChat.

## Параметры тела OpenAI

| Эндпоинт | Поддерживается |
|---|---|
| Chat Completions | `model`, `messages`, `stream`, `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`, функциональные `tools`, `functions`, `function_call`, поддерживаемый `tool_choice`, built-in tools в GigaChat v2 mode (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`), `response_format`, `reasoning`, `reasoning_effort`, `extra_body` passthrough |
| Responses | `model`, `input`, `instructions`, `stream`, `temperature`, `top_p`, `max_output_tokens`, функциональные `tools`, built-in tools в GigaChat v2 mode (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`; нормализованные output items и stream progress events сейчас строятся для `web_search*` и `image_generation` / `image_generate`), поддерживаемый `tool_choice`, `text.format`, `response_format`, `reasoning`, `reasoning_effort`, `extra_body` passthrough |
| Embeddings | `input`, `model`, `dimensions`, `encoding_format`, `user`, `extra_headers`, `extra_query` |
| Models | `GET /models`, `GET /models/{model}` |

Поля метаданных OpenAI, такие как `user`, `metadata`, `service_tier`,
`safety_identifier`, `seed`, `prompt_cache_key` и `prompt_cache_retention`,
принимаются и игнорируются там, где они классифицированы.

Неподдерживаемые optional параметры OpenAI принимаются и игнорируются. Примеры:
`logprobs`, `top_logprobs`, `logit_bias`, аудиовывод, `prediction`,
`web_search_options`, built-in tools вне GigaChat v2 mode, `n > 1`,
`parallel_tool_calls=true`, сохраненные запросы completions, `conversation`, а
также `previous_response_id` в Responses v1 mode. `/chat/completions` v1
остаётся поддержанным compatibility route, но новые tool/built-in-tool
возможности развиваются для GigaChat `v2/chat/completions`.

## Параметры тела Anthropic

| Эндпоинт | Поддерживается |
|---|---|
| Messages | `model`, `messages`, `system`, `max_tokens`, `stream`, `temperature`, `top_p`, `stop_sequences`, локальные функциональные `tools`, значения `tool_choice` `auto`/`none`/принудительный `tool`, `thinking`, `output_config.format`, `output_format`, `extra_body` passthrough |
| Count Tokens | `model`, `messages`, `system`, `tools`, текст схемы structured output, совместимая валидация содержимого сообщений |
| Models | `GET /models`, `GET /models/{model_id}`, когда запрос содержит заголовки Anthropic SDK, например `anthropic-version` |

Anthropic `metadata`, `service_tier`, `top_k`, beta-заголовки и `betas`
принимаются и игнорируются там, где они классифицированы.

Неподдерживаемые optional параметры или возможности Anthropic принимаются и
игнорируются. Примеры: `container`, `context_management`, `mcp_servers`,
серверные инструменты, веб-поиск, выполнение кода, управление компьютером,
блоки содержимого document/file, загрузки в container, блоки результатов
поиска, citations, а также входные блоки `thinking`/`redacted_thinking`.

Код Anthropic Message Batches существует, но публичный роутер не подключается,
пока в GigaChat SDK или backend не появится поддержка batch-операций.

## Область маршрутов

Подключенные маршруты доступны и в корне, и под `/v1` через роутер приложения.
Подготовленные, но отключенные маршруты OpenAI Files/Batches и Anthropic Message
Batches намеренно исключены из схемы OpenAPI по умолчанию.
