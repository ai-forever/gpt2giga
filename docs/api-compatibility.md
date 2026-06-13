# Совместимость API

`gpt2giga` — compatibility proxy, а не полный клон OpenAI или Anthropic. Он фокусируется на API-поверхностях, которые обычно нужны SDK, редакторам и агентным инструментам при backend GigaChat.

## Что не работает напрямую с GigaChat

Ниже перечислены практические несовместимости, которые закрывает прокси.

| Ожидание клиента | Почему ломается без прокси | Что делает `gpt2giga` |
|---|---|---|
| OpenAI Chat Completions JSON | У GigaChat другие форматы messages, tools, attachments и responses. | Конвертирует requests/responses, включая streaming chunks. |
| OpenAI Responses API | У GigaChat нет такой же `/responses` route и schema для output items. | Принимает `/responses`, маппит input/instructions/tools и нормализует output items там, где это возможно. |
| Anthropic Messages API | Anthropic content blocks, tool use, `system`, `max_tokens` и stream events не совпадают с GigaChat. | Конвертирует Anthropic payloads в GigaChat-compatible chat requests и маппит ответы обратно. |
| Gemini GenerateContent API | Gemini `contents`/`parts`, candidates, function declarations, token counting и SSE chunks отличаются от OpenAI/Anthropic и GigaChat. | Принимает Gemini-like requests в корне, под `/v1`, `/v2` и `/v1beta`, переводит их в normalized chat/embeddings requests и маппит ответы обратно в Gemini shape. |
| SDK `extra_headers`, `extra_query`, `extra_body` | SDK могут прислать transport-поля или optional model-поля, которые GigaChat не принимает. | Фильтрует опасные headers, передаёт только разрешённые metadata, прокидывает GigaChat-specific `extra_body` и игнорирует известные unsupported optional fields. |
| Streaming SSE | OpenAI и Anthropic SDK ждут свои event names и delta shapes. | Генерирует OpenAI/Anthropic-compatible SSE из GigaChat streaming responses. |
| Tools и structured output | Function/tool schemas и JSON-schema controls отличаются между провайдерами и backend modes. | Маппит local tools/functions и даёт function-call fallback для structured outputs. |
| Авторизация | OpenAI/Anthropic клиенты работают с API keys, а GigaChat требует другой credentials/scope механизм. | Разделяет proxy API-key auth и upstream GigaChat auth, при необходимости поддерживает per-request pass-through. |
| Model discovery | GigaChat model responses не совпадают с OpenAI/Anthropic/LiteLLM shape. | Переупаковывает список и описание моделей под нужный клиент. |
| OpenAI/Anthropic/Gemini batch routes | У установленного GigaChat SDK/backend нет полного create/list/retrieve/cancel flow для batch APIs. | Держит Files/Batches routers отключёнными, пока они не смогут работать end-to-end. |

## Смонтированные routes

Публичные API routes доступны в корне и под versioned prefixes. Root routes
используют backend mode из env, `/v1` принудительно выбирает GigaChat v1
contract, `/v2` принудительно выбирает GigaChat v2 contract.

Примеры:

- `/chat/completions`, `/v1/chat/completions` и `/v2/chat/completions`
- `/responses`, `/v1/responses` и `/v2/responses`
- `/messages`, `/v1/messages` и `/v2/messages`
- `/models/{model}:generateContent`, `/v1/models/{model}:generateContent`, `/v2/models/{model}:generateContent` и `/v1beta/models/{model}:generateContent`

## OpenAI-compatible routes

| Route / group | Статус | Комментарий |
|---|---|---|
| `GET /models` | Поддерживается | Список GigaChat models в OpenAI-compatible форме. |
| `GET /models/{model}` | Поддерживается | Одна модель в OpenAI-compatible форме. |
| `POST /chat/completions` | Поддерживается | Non-streaming и streaming chat, tools/function calling, structured output, attachments where supported. |
| `POST /responses` | Поддерживается | Маппит Responses input/instructions/tools в GigaChat. GigaChat v2 mode даёт более богатый built-in-tool path. |
| `POST /embeddings` | Поддерживается | Использует model из запроса или proxy default для embeddings, в зависимости от конфигурации. |
| `GET /model/info` | Поддерживается | LiteLLM-compatible model info endpoint. |
| `POST /files`, `GET /files*` | Отключено | Router-код есть, но не смонтирован: files без batches дают неполный OpenAI batch flow. |
| `POST /batches`, `GET /batches*` | Отключено | Отключено до появления batch create/list/retrieve/cancel в GigaChat SDK/backend. |
| Stored chat-completion routes | Не реализовано | Stored completions сейчас вне scope. |
| Legacy `POST /completions` | Не реализовано | Legacy text completions сейчас вне scope. |
| Images, audio, moderations, uploads | Не реализовано | Эти OpenAI route families прокси не реализует. |
| Fine-tuning, assistants, threads, runs, vector stores | Не реализовано | Сейчас вне scope. |
| Realtime/WebSocket API | Не реализовано | Сейчас вне scope. |

## Anthropic-compatible routes

| Route / group | Статус | Комментарий |
|---|---|---|
| `GET /models` | Поддерживается | Возвращается в Anthropic shape, когда запрос содержит headers Anthropic SDK. |
| `GET /models/{model_id}` | Поддерживается | Возвращается в Anthropic shape, когда запрос содержит headers Anthropic SDK. |
| `POST /messages` | Поддерживается | Messages API, streaming, local tools, GigaChat v2 mapping for compatible Anthropic provider tools, structured-output fallback. |
| `POST /messages/count_tokens` | Поддерживается | Считает message, system, tool и structured-output text через GigaChat token counting. |
| `POST /messages/batches`, `GET /messages/batches*` | Отключено | Router-код есть, но не смонтирован до появления batch methods в GigaChat SDK/backend. |
| Files API beta | Не реализовано | Сейчас вне scope. |
| Skills API beta | Не реализовано | Сейчас вне scope. |
| Agents, Sessions, Environments, Admin beta APIs | Не реализовано | Сейчас вне scope. |

## Gemini-compatible routes

Gemini operation routes монтируются в корне, под `/v1`, `/v2` и `/v1beta`,
как остальные публичные API. `/v1` принудительно выбирает GigaChat v1 backend
contract, `/v2` — GigaChat v2 backend contract.

Gemini model discovery в чистой Gemini форме всегда доступен под `/v1beta`.
На общих `/models`, `/v1/models` и `/v2/models` прокси сохраняет OpenAI форму
по умолчанию, но возвращает Gemini форму для Google/Gemini-клиентов, например
при заголовке `X-Goog-Api-Client`.

| Route / group | Статус | Комментарий |
|---|---|---|
| `GET /v1beta/models` | Поддерживается | Список GigaChat models в Gemini `models/*` форме. |
| `GET /v1beta/models/{model}` | Поддерживается | Одна модель в Gemini `Model` форме. |
| `POST /models/{model}:generateContent`, `/v1/...`, `/v2/...`, `/v1beta/...` | Поддерживается | Gemini `contents`/`parts`, `systemInstruction`, `generationConfig`, function declarations и multimodal parts маппятся в normalized chat request. |
| `POST /models/{model}:streamGenerateContent`, `/v1/...`, `/v2/...`, `/v1beta/...` | Поддерживается | Возвращает `text/event-stream` с Gemini `GenerateContentResponse` chunks. |
| `POST /models/{model}:countTokens`, `/v1/...`, `/v2/...`, `/v1beta/...` | Поддерживается | Считает текстовые части contents/system/tools через GigaChat token counting. |
| `POST /models/{model}:embedContent`, `/v1/...`, `/v2/...`, `/v1beta/...` | Поддерживается | Возвращает Gemini `embedding.values`, используя GigaChat embeddings backend. |
| `POST /models/{model}:batchEmbedContents`, `/v1/...`, `/v2/...`, `/v1beta/...` | Поддерживается | Возвращает Gemini `embeddings[]`, используя GigaChat embeddings backend. |
| `POST /v1beta/files`, `GET /v1beta/files*` | Отключено | Router-код подготовлен, но не смонтирован по умолчанию. |
| `POST /v1beta/models/{model}:batchGenerateContent`, `GET /v1beta/batches*` | Отключено | Router-код подготовлен, но не смонтирован до end-to-end batch execution. |

## Политика совместимости

`gpt2giga` намеренно принимает многие optional SDK fields, которые GigaChat не может исполнить. Это не даёт клиентам падать до того, как полезная часть запроса попадёт в модель.

Типичные accepted-and-ignored поля:

- OpenAI metadata и tuning knobs: `user`, `metadata`, `service_tier`, `seed`, `prompt_cache_key`, `logprobs`, `top_logprobs`, `logit_bias`, `prediction`, `web_search_options`, `n > 1`, `parallel_tool_calls=true`;
- Anthropic optional fields: `metadata`, `service_tier`, `top_k`, `container`, `context_management`, `mcp_servers`, unsupported provider tools, citations, unsupported document/file content blocks. Compatible provider tools (`web_search*`, `web_fetch*`, `code_execution*`) map to GigaChat v2 built-ins.
- Gemini optional fields: `safetySettings`, `cachedContent`, `serviceTier`, unsupported `generationConfig` subfields and non-function built-in tools are accepted/preserved for diagnostics but are not enforced by GigaChat.

Если поле намеренно игнорируется, оно не отправляется upstream как исполняемая GigaChat feature. Literal `extra_body` object может быть передан в GigaChat `additional_fields`; в таком случае поддержку определяет GigaChat API.

Справочник по каждому parameter: [Совместимость параметров клиентов](./client-parameter-compatibility.md).

Внутренний normalized слой, который отделяет public protocol formats от
provider execution, описан в [Normalized messages architecture](./architecture/normalized-messages.md).

## Backend modes

По умолчанию используется GigaChat root compatibility methods:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

Задайте `GPT2GIGA_GIGACHAT_API_MODE=v2`, чтобы root routes использовали более новый GigaChat `v2/chat/completions` surface для chat-like запросов. Для явного выбора на уровне клиента используйте `base_url` с `/v1` или `/v2`.

`/chat/completions` остаётся compatibility route и следует env. Новые built-in-tool возможности развиваются преимущественно вокруг GigaChat v2 mode, поэтому клиенты, которым они нужны, могут указывать `http://localhost:8090/v2`.
