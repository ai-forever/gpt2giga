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

Публичные API routes доступны в корне и под versioned prefixes. Правило выбора
backend одинаковое для OpenAI-, Anthropic- и Gemini-compatible routes:
`/v1` принудительно выбирает GigaChat v1 contract, `/v2` принудительно
выбирает GigaChat v2 contract, а root routes без versioned prefix используют
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Примеры:

- `/chat/completions`, `/v1/chat/completions` и `/v2/chat/completions`
- `/responses`, `/v1/responses` и `/v2/responses`
- `/messages`, `/v1/messages` и `/v2/messages`
- `/models/{model}:generateContent`, `/v1/models/{model}:generateContent`, `/v2/models/{model}:generateContent` и `/v1beta/models/{model}:generateContent`

## Сводная матрица

Короткая release-матрица также доступна отдельной страницей:
[Compatibility matrix](./compatibility.md).

| Surface | Non-stream | Stream | Tools | Structured output | Embeddings | Models | Token count |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenAI Chat | yes | yes | yes | yes | n/a | yes | n/a |
| OpenAI Responses | yes | yes | yes | yes | n/a | n/a | n/a |
| Anthropic Messages | yes | yes | yes | yes | n/a | yes | yes |
| Gemini generateContent | yes | yes | yes | yes | n/a | yes | yes |
| Gemini embeddings | n/a | n/a | n/a | n/a | yes | yes | n/a |
| LiteLLM model info | n/a | n/a | n/a | n/a | n/a | yes | n/a |

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
как остальные публичные API. Для клиентов, которые добавляют Gemini API
version к уже versioned base URL, также доступны `/v1/v1beta` и `/v2/v1beta`.
`/v1` и `/v1/v1beta` принудительно выбирают GigaChat v1 backend contract,
`/v2` и `/v2/v1beta` — GigaChat v2 backend contract. Корневые Gemini paths
`/...` и `/v1beta/...` без outer `/v1` или `/v2` используют
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Gemini model discovery в чистой Gemini форме всегда доступен под `/v1beta`,
`/v1/v1beta` и `/v2/v1beta`.
На общих `/models`, `/v1/models` и `/v2/models` прокси сохраняет OpenAI форму
по умолчанию, но возвращает Gemini форму для Google/Gemini-клиентов, например
при заголовках `X-Goog-Api-Client` или `X-Goog-Api-Key`, либо при query
параметре `?key=...`.

Если proxy API-key auth включен, Gemini-compatible клиенты могут передавать
ключ через `x-goog-api-key` или `?key=...`, помимо общих `Authorization:
Bearer ...`, `x-api-key` и `?x-api-key=...`. Для новых настроек
предпочтительнее header-based auth: query keys чаще попадают в access logs.

`supportedGenerationMethods` строится консервативно: known GigaChat/chat-like
models advertise `generateContent`, `streamGenerateContent` и `countTokens`;
embedding-like models advertise только `embedContent` и `batchEmbedContents`;
unknown/custom model ids advertise только `countTokens`, если backend metadata
не дает более точной информации.

| Route / group | Статус | Комментарий |
|---|---|---|
| `GET /v1beta/models`, `/v1/v1beta/models`, `/v2/v1beta/models` | Поддерживается | Список GigaChat models в Gemini `models/*` форме. |
| `GET /v1beta/models/{model}`, `/v1/v1beta/models/{model}`, `/v2/v1beta/models/{model}` | Поддерживается | Одна модель в Gemini `Model` форме. |
| `POST /models/{model}:generateContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Gemini `contents`/`parts`, `systemInstruction`, `generationConfig`, function declarations и multimodal parts маппятся в normalized chat request. |
| `POST /models/{model}:streamGenerateContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Возвращает `text/event-stream` с Gemini `GenerateContentResponse` chunks. |
| `POST /models/{model}:countTokens`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Считает текстовые части contents/system/tools через GigaChat token counting. |
| `POST /models/{model}:embedContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Возвращает Gemini `embedding.values`, используя GigaChat embeddings backend. |
| `POST /models/{model}:batchEmbedContents`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Возвращает Gemini `embeddings[]`, используя GigaChat embeddings backend. |
| `POST /v1beta/files`, `GET /v1beta/files*` | Отключено | Router-код подготовлен, но не смонтирован по умолчанию. |
| `POST /v1beta/models/{model}:batchGenerateContent`, `GET /v1beta/batches*` | Отключено | Router-код подготовлен, но не смонтирован до end-to-end batch execution. |

### Gemini function calling

`toolConfig.functionCallingConfig` маппится в ближайшую поддержанную
семантику normalized/OpenAI-like слоя:

- `mode=AUTO` оставляет вызов функций опциональным. Если задан
  `allowedFunctionNames`, upstream получает только эти объявленные функции.
- `mode=NONE` отключает function calling.
- `mode=ANY` поддерживается только когда после учета `allowedFunctionNames`
  остается ровно одна функция; она маппится в forced function call.
- `mode=ANY` без `allowedFunctionNames` также поддерживается, если объявлена
  ровно одна функция.
- `mode=ANY` с несколькими возможными функциями возвращает `400`, потому что
  GigaChat backend path сейчас не умеет честно выразить “обязательно вызвать
  одну из нескольких функций”.
- `allowedFunctionNames` валидируется против объявленных
  `functionDeclarations`; ссылки на необъявленные функции возвращают `400`.

### Gemini embeddings

`embedContent` и `batchEmbedContents` поддерживают только текстовые
`content.parts[].text`. Пустые `requests`, malformed batch entries и
non-text parts возвращают `400` до вызова GigaChat embeddings backend.

`outputDimensionality` принимается как compatibility metadata для normalized
request/observability, но не передается upstream как исполняемая настройка:
текущий GigaChat embeddings backend path не предоставляет управляемое
уменьшение размерности через этот параметр.

### Gemini release scope and validation

Это Gemini-compatible API surface, а не full Gemini API parity. Перед релизом
проверяйте именно заявленный scope:

- supported routes: `generateContent`, `streamGenerateContent`, `countTokens`,
  `embedContent`, `batchEmbedContents`, model discovery;
- supported prefixes: root, `/v1`, `/v2`, `/v1beta`, `/v1/v1beta`,
  `/v2/v1beta`;
- disabled routes: Gemini Files API и `batchGenerateContent` routers есть в
  коде, но не смонтированы публично до end-to-end upstream execution;
- partially supported fields: `safetySettings` и `cachedContent` принимаются
  для compatibility/diagnostics, но не enforced; `candidateCount`, `topK` и
  `responseModalities` accepted/observed but ignored by GigaChat execution;
- structured output: `generationConfig.responseMimeType=text/plain` считается
  дефолтным текстовым режимом, `application/json` маппится в JSON response
  format, а другие MIME types и `responseSchema` без `application/json`
  возвращают `400`;
- unsupported features: Gemini tools outside the GigaChat SDK built-in mapping
  (`fileSearch`, `googleMaps`, `computerUse`, MCP, RAG/retrieval/Vertex tools),
  full multimodal/file-backed Gemini flows, non-text embeddings content;
- approximations: `countTokens` считает извлеченный текст через GigaChat token
  counting, игнорирует non-text/file/cachedContent parts и не является точным
  Gemini tokenizer.

Copyable release checklist for PR description:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/test_protocol/test_gemini_adapter.py tests/test_router/test_gemini_router.py tests/integration/gemini/test_gemini_app_wiring.py

# Optional, requires live GigaChat credentials.
GPT2GIGA_RUN_LIVE_TESTS=1 uv run pytest tests/live/test_real_gigachat_integration.py -k gemini

# Optional release smoke for google-genai + Gemini CLI, auth on/off, and base URL matrix.
GPT2GIGA_RUN_GEMINI_SMOKE=1 GPT2GIGA_LIVE_ENV_FILE=.env.live uv run pytest tests/live/test_gemini_client_smoke.py
```

## Политика совместимости

`gpt2giga` намеренно принимает многие optional SDK fields, которые GigaChat не может исполнить. Это не даёт клиентам падать до того, как полезная часть запроса попадёт в модель.

Типичные поля, которые принимаются и игнорируются:

- Метаданные OpenAI и параметры тонкой настройки: `user`, `metadata`, `service_tier`, `seed`, `prompt_cache_key`, `logprobs`, `top_logprobs`, `logit_bias`, `prediction`, `web_search_options`, `n > 1`, `parallel_tool_calls=true`;
- Опциональные поля Anthropic: `metadata`, `service_tier`, `top_k`, `container`, `context_management`, `mcp_servers`, неподдержанные provider tools, citations, неподдержанные document/file content blocks. Совместимые provider tools (`web_search*`, `web_fetch*`, `code_execution*`) маппятся на встроенные инструменты GigaChat v2.
- Опциональные поля Gemini: `safetySettings`, `cachedContent`, `serviceTier`, игнорируемые controls `generationConfig`, например `candidateCount`/`topK`/`responseModalities`, и неподдержанные non-function tools принимаются и сохраняются для диагностики, но не применяются GigaChat. Совместимые provider tools Gemini маппятся на встроенные инструменты GigaChat v2: `googleSearch` / `googleSearchRetrieval` -> `web_search`, `urlContext` -> `url_content_extraction`, `codeExecution` -> `code_interpreter`; полный маппинг описан в [Встроенных инструментах](builtin-tools.md). Неподдержанные значения `responseMimeType` и `responseSchema` без `application/json` отклоняются.

Если поле намеренно игнорируется, оно не отправляется upstream как исполняемая GigaChat feature. Literal `extra_body` object может быть передан в GigaChat `additional_fields`; в таком случае поддержку определяет GigaChat API.

В observability ignored request extensions публикуются в redacted атрибуте
`llm.request.extensions`, а ignored Gemini generation controls остаются в
`llm.invocation_parameters`.

Справочник по каждому parameter: [Совместимость параметров клиентов](./client-parameter-compatibility.md).

Внутренний normalized слой, который отделяет public protocol formats от
provider execution, описан в [Normalized messages architecture](./architecture/normalized-messages.md).

## Backend modes

По умолчанию используется GigaChat root compatibility methods:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

Задайте `GPT2GIGA_GIGACHAT_API_MODE=v2`, чтобы root routes без `/v1` или
`/v2` использовали более новый GigaChat `v2/chat/completions` surface для
chat-like запросов. Для явного выбора на уровне клиента используйте `base_url`
с `/v1` или `/v2`: `/v1` всегда идёт в GigaChat v1 contract, `/v2` всегда
идёт в GigaChat v2 contract.

`/chat/completions` остаётся compatibility route и следует env. Новые
built-in-tool возможности развиваются преимущественно вокруг GigaChat v2 mode,
поэтому клиенты, которым они нужны, могут указывать `http://localhost:8090/v2`.
