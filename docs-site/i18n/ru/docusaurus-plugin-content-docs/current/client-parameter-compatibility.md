# Совместимость параметров клиентов

Этот документ служит публичным справочником совместимости параметров клиентских
SDK OpenAI, Anthropic и Gemini-подобных клиентов в gpt2giga. Он отражает текущую
структуру исходного кода:

- роутеры OpenAI: `gpt2giga/routers/openai/`
- роутеры Anthropic: `gpt2giga/routers/anthropic/`
- роутеры Gemini: `gpt2giga/routers/gemini/`
- общие политики запросов: `gpt2giga/common/client_params.py`
- классификация запросов OpenAI: `gpt2giga/protocol/request/params.py`
- классификация запросов Anthropic: `gpt2giga/protocol/anthropic/params.py`
- адаптер Gemini: `gpt2giga/protocols/gemini/`

Другие семейства клиентов в этой проверке совместимости не рассматриваются.

Чтобы проверить, как будет классифицирован конкретный запрос без вызова GigaChat,
используйте [Compatibility Doctor](diagnostics.md). Он возвращает тот же публичный
язык статусов для полей, tools, backend mode, model selection и redaction.

## Статусы совместимости

| Статус | Значение |
|---|---|
| `supported` | Параметр влияет на запрос или ответ и покрыт тестами. |
| `accepted_ignored` | Параметр принимается для совместимости с SDK, но не отправляется в вышестоящий сервис. |
| `accepted_diagnostic_only` | Параметр сохраняется только для diagnostics, summaries наблюдаемости или будущего UI-объяснения. |
| `approximated` | Параметр или операция реализованы через документированное приближение, а не точную provider-семантику. |
| `rejected` | Запрос имеет неисполняемую форму, например отсутствует обязательный `input` или `extra_body` не является объектом. Необязательные клиентские флаги возможностей не используют этот статус. |
| `not_applicable` | Опция относится к клиентской настройке транспорта, а не к серверному параметру тела запроса. |

## Транспортные опции SDK

`base_url`, `api_key`, `timeout`, настройки повторных попыток, пользовательский
`http_client`, конфигурация прокси и низкоуровневые транспортные настройки
являются клиентскими опциями SDK. gpt2giga не назначает им серверную семантику.

Учётные данные и транспортные заголовки не пересылаются в GigaChat как
произвольные метаданные вышестоящего сервиса. Это касается `Authorization`,
`x-api-key`, cookie, `host`, заголовков содержимого и передачи, `x-stainless-*`,
`openai-*` и `anthropic-*`. Для намеренной передачи авторизации GigaChat
используйте отдельный режим `GPT2GIGA_PASS_TOKEN=True`.

## `extra_headers` и `extra_query`

`extra_headers` из SDK приходит на сервер как обычные HTTP-заголовки. gpt2giga
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
могут быть переданы как пользовательские заголовки. `Authorization`, `x-api-key`,
транспортные заголовки и внутренние заголовки SDK `x-stainless-*`, `openai-*`,
`anthropic-*` остаются заблокированными.

URL contextvars SDK, например `chat_url_cvar` и
`chat_completions_url_cvar`, не заполняются из `extra_headers`.

`extra_query` по умолчанию не пробрасывает произвольные query-параметры в
вышестоящий сервис: список разрешённых query-параметров для вышестоящего
сервиса пуст.

## `extra_body`

SDK OpenAI и Anthropic обычно объединяют `extra_body` с исходящим JSON-телом как
поля верхнего уровня. HTTP-клиенты, работающие напрямую, также могут отправлять
буквальный объект `extra_body`. gpt2giga обрабатывает обе формы.

Для OpenAI Chat Completions, OpenAI Responses и Anthropic Messages объект
`extra_body` переносится в GigaChat `additional_fields` целиком. Неизвестные
поля верхнего уровня в стиле SDK, которые появляются после разворачивания
`extra_body` клиентом, обрабатываются так же.

Известные неподдерживаемые необязательные параметры клиентов принимаются и игнорируются, если
отправлены как поля верхнего уровня: например `logprobs`, `audio`, `container` или
`mcp_servers`. `previous_response_id` поддерживается для OpenAI Responses в
режиме GigaChat v2 и сопоставляется с `storage.thread_id`; в режиме Responses v1 он
принимается и игнорируется.
Если такой же ключ явно положить внутрь буквального `extra_body`, gpt2giga передаст
его в `additional_fields`, а итоговую поддержку определит вышестоящий GigaChat.

OpenAI Embeddings принимает и игнорирует `extra_body`, неизвестные поля верхнего
уровня и `dimensions`; на данный момент для эмбеддингов нет разрешённых полей,
специфичных для GigaChat.

## Параметры тела OpenAI

| Эндпоинт | Поддерживается |
|---|---|
| Chat Completions | `model`, `messages`, `stream`, `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`, функциональные `tools`, `functions`, `function_call`, поддерживаемый `tool_choice`, встроенные инструменты в режиме GigaChat v2 (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`), `response_format`, `reasoning`, `reasoning_effort`, проброс `extra_body` |
| Responses | `model`, `input`, `instructions`, `stream`, `temperature`, `top_p`, `max_output_tokens`, функциональные `tools`, встроенные инструменты в режиме GigaChat v2 (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`; нормализованные элементы вывода и события прогресса потока сейчас строятся для `web_search*` и `image_generation` / `image_generate`), поддерживаемый `tool_choice`, `text.format`, `response_format`, `reasoning`, `reasoning_effort`, проброс `extra_body` |
| Embeddings | `input`, `model`, `dimensions`, `encoding_format`, `user`, `extra_headers`, `extra_query` |
| Models | `GET /models`, `GET /models/{model}` |

Структурированный вывод поддерживается через `json_schema`. Режим JSON без схемы
(`response_format.type=json_object` у OpenAI или Gemini
`responseMimeType=application/json` без `responseJsonSchema` / `responseSchema`)
отклоняется, потому что вышестоящий GigaChat не поддерживает отдельный режим JSON.

При `GPT2GIGA_DISABLE_REASONING=True` прокси принимает `reasoning` и
`reasoning_effort`, но не передаёт их в полезную нагрузку, отправляемую в GigaChat.

При `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True` прокси принимает provider
built-in tools для совместимости, но не сопоставляет и не отправляет их в
GigaChat как executable tools. Пользовательские function tools продолжают
работать.

Поля метаданных OpenAI, такие как `user`, `metadata`, `service_tier`,
`safety_identifier`, `seed`, `prompt_cache_key` и `prompt_cache_retention`,
принимаются и игнорируются там, где они классифицированы.

Неподдерживаемые необязательные параметры OpenAI принимаются и игнорируются. Примеры:
`logprobs`, `top_logprobs`, `logit_bias`, аудиовывод, `prediction`,
`web_search_options`, встроенные инструменты вне режима GigaChat v2, `n > 1`,
`parallel_tool_calls=true`, сохранённые запросы completions, `conversation`, а
также `previous_response_id` в режиме Responses v1. `/chat/completions` v1
остаётся поддерживаемым маршрутом совместимости, но новые возможности
инструментов и встроенных инструментов развиваются для GigaChat `v2/chat/completions`.

## Параметры тела Anthropic

| Эндпоинт | Поддерживается |
|---|---|
| Messages | `model`, `messages`, `system`, `max_tokens`, `stream`, `temperature`, `top_p`, `stop_sequences`, локальные функциональные `tools`, провайдерские инструменты Anthropic в режиме GigaChat v2 (`web_search*`, `web_fetch*` как `url_content_extraction`, `code_execution*` как `code_interpreter`), значения `tool_choice` `auto`/`none`/принудительный `tool`, `thinking`, `output_config.format`, `output_format`, проброс `extra_body` |
| Count Tokens | `model`, `messages`, `system`, `tools`, текст схемы структурированного вывода, совместимая проверка содержимого сообщений |
| Models | `GET /models`, `GET /models/{model_id}`, когда запрос содержит заголовки Anthropic SDK, например `anthropic-version` |

Anthropic `metadata`, `service_tier`, `top_k`, beta-заголовки и `betas`
принимаются и игнорируются там, где они классифицированы.

Неподдерживаемые необязательные параметры или возможности Anthropic принимаются и
игнорируются. Примеры: `container`, `context_management`, `mcp_servers`,
неподдерживаемые провайдерские инструменты (`advisor`, `tool_search`, `mcp_toolset`, `memory`,
`bash`, `text_editor`, `computer`), управление компьютером, блоки контента
document/file, загрузки в container, блоки результатов поиска, цитаты (citations), а
также входные блоки `thinking`/`redacted_thinking`.

Код Anthropic Message Batches существует, но публичный роутер не подключается,
пока в SDK или бэкенде GigaChat не появится поддержка пакетных операций.

## Параметры тела Gemini

Gemini-подобные операционные маршруты доступны в корне, под `/v1`, `/v2` и `/v1beta`,
например `/v1/models/{model}:generateContent`. Также поддержаны пути SDK/CLI
Gemini `/v1/v1beta/...` и `/v2/v1beta/...`, когда клиент сам добавляет
`/v1beta` к версионированному base URL. `/v1` и `/v1/v1beta` принудительно выбирают
контракт бэкенда GigaChat v1, `/v2` и `/v2/v1beta` — контракт бэкенда GigaChat v2.
Корневые пути без `/v1` или `/v2`, включая `/v1beta/...`, выбирают
бэкенд по `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

| Эндпоинт | Поддерживается |
|---|---|
| Generate Content | `contents`, `systemInstruction`, `generationConfig.temperature`, `generationConfig.topP`, `generationConfig.maxOutputTokens`, `generationConfig.stopSequences`, `generationConfig.seed`, `generationConfig.presencePenalty`, `generationConfig.frequencyPenalty`, функциональные `tools.functionDeclarations`, провайдерские инструменты Gemini в режиме GigaChat v2 (`googleSearch` / `googleSearchRetrieval` как `web_search`, `urlContext` как `url_content_extraction`, `codeExecution` как `code_interpreter`), базовый `toolConfig.functionCallingConfig`, части text/image/file |
| Stream Generate Content | Те же поля, что у Generate Content; ответ отдаётся как фрагменты SSE Gemini `GenerateContentResponse`. |
| Count Tokens | Текстовые части `contents`, `systemInstruction` и имена/описания объявлений функций. |
| Embeddings | `content.parts[].text`, `requests[].content.parts[].text` для пакетных эмбеддингов, `outputDimensionality` принимается как метаданные совместимости. |
| Models | `GET /v1beta/models`, `GET /v1/v1beta/models`, `GET /v2/v1beta/models` и `{model}` variants; общие `/models`, `/v1/models`, `/v2/models` возвращают форму Gemini для запросов Google/Gemini, например с `X-Goog-Api-Client` |

Gemini `safetySettings`, `cachedContent`, `serviceTier`, `store` и
неподдерживаемые подполя `generationConfig` принимаются и сохраняются в нормализованных расширениях
для диагностики, но не передаются в GigaChat как исполняемые параметры и не
применяются прокси. Провайдерские инструменты, не являющиеся функциями, которые не соответствуют
встроенным инструментам GigaChat SDK (`fileSearch`, `googleMaps`, `computerUse`,
MCP, инструменты RAG/retrieval/Vertex), также сохраняются только для диагностики.
Полный список канонических встроенных инструментов и провайдерских псевдонимов описан во
[Встроенных инструментах](builtin-tools.md).

Код Gemini Files и Batches существует, но публичный роутер не подключается,
пока выполнение файлов/пакетов не будет проверено сквозным образом.

## Область маршрутов

Подключённые операционные маршруты OpenAI, Anthropic, LiteLLM и Gemini доступны в
корне, под `/v1` и под `/v2` через роутер приложения. Маршруты, совместимые с Gemini,
также доступны под `/v1beta`, `/v1/v1beta` и `/v2/v1beta`.
`/v1` всегда выбирает контракт бэкенда GigaChat v1, `/v2` — контракт бэкенда
GigaChat v2, а корень без версионированного префикса следует
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.
Подготовленные, но отключённые маршруты OpenAI Files/Batches, Anthropic Message
Batches и Gemini Files/Batches намеренно исключены из схемы OpenAPI по умолчанию.
