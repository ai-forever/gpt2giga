# Normalized messages architecture

Normalized слой - внутренний контракт между публичными API-форматами и
upstream providers. Он не является новым публичным API. Клиенты продолжают
посылать OpenAI Chat Completions, OpenAI Responses, Anthropic Messages или
Gemini GenerateContent, а gateway приводит совместимые части payload к
каноническим моделям из `gpt2giga/protocols/normalized/`. Gemini GenerateContent
уже использует отдельный Gemini-to-normalized adapter в основном execution path.

## Текущий статус

- `GPT2GIGA_NORMALIZATION_MODE=off`: OpenAI Chat Completions идёт через legacy
  transforms.
- `GPT2GIGA_NORMALIZATION_MODE=shadow`: OpenAI Chat строит normalized request
  рядом с legacy path и сохраняет safe diagnostic shape hash без prompt content.
- `GPT2GIGA_NORMALIZATION_MODE=on`: OpenAI Chat Completions исполняется через
  normalized path и `GigaChatProviderAdapter`; до старта ответа доступен legacy
  fallback через `GPT2GIGA_LEGACY_CHAT_FALLBACK=True`.
- OpenAI Responses и Anthropic Messages пока исполняются через legacy route
  transforms, но observability и debug translation уже используют normalized
  представление там, где это возможно.
- Gemini GenerateContent и streamGenerateContent исполняются через
  `GeminiProtocolAdapter`, normalized models и `GigaChatProviderAdapter`
  независимо от OpenAI Chat normalization flags.
- Debug endpoints умеют переводить между `openai`, `anthropic`, `normalized` и
  `gigachat` форматами для protected admin workflows.

## Основные модели

Normalized request envelope:

- `NormalizedChatRequest`: `protocol`, `operation`, `model`, `stream`,
  `messages`, `tools`, `tool_choice`, `response_format`,
  `generation_config`, `user`, `metadata`.
- `NormalizedMessage`: `role`, `content`, `name`, `tool_call_id`,
  `tool_calls`.
- `NormalizedContentPart`: generic content part с `type`, `text`, `data`,
  `mime_type`, `detail`.
- `NormalizedTool`: flattened tool/function contract с `name`,
  `description`, `parameters`.
- `NormalizedGenerationConfig`: common generation knobs:
  `temperature`, `top_p`, `max_tokens`, penalties, `stop`, `seed`.

Normalized output:

- `NormalizedResponse`: provider-independent non-streaming response:
  `choices`, `usage`, `error`, `metadata`, `provider_metadata`.
- `NormalizedChoice`: `message` или `delta`, `finish_reason`, `index`.
- `NormalizedUsage`: `input_tokens`, `output_tokens`, `total_tokens`.
- `NormalizedStreamEvent`: canonical stream events:
  `message_start`, `content_delta`, `reasoning_delta`, `tool_call_start`,
  `tool_call_delta`, `usage`, `message_end`, `error`, `heartbeat`.

Все normalized модели наследуют две extension buckets:

- `raw_extensions`: поля исходного public protocol, которые gateway должен
  сохранить, но не поднимать в каноническую модель.
- `provider_metadata`: provider-specific данные, например GigaChat
  `additional_fields` или безопасная metadata из upstream response.

## Поток OpenAI Chat

OpenAI Chat Completions в normalized mode проходит так:

1. `gpt2giga/routers/openai/chat_completions.py` читает payload и request
   context.
2. `OpenAIProtocolAdapter` из `gpt2giga/protocols/openai/adapter.py` строит
   `NormalizedChatRequest`.
3. `GigaChatProviderAdapter` из `gpt2giga/providers/gigachat/adapter.py`
   исполняет normalized request через текущий GigaChat SDK path.
4. Provider adapter возвращает `NormalizedResponse` или
   `NormalizedStreamEvent`.
5. OpenAI response adapters маппят результат обратно в OpenAI Chat
   Completions payload или SSE chunks.
6. Observability получает normalized request/response и строит безопасные
   OpenInference-style span attributes.

Внутри `GigaChatProviderAdapter` normalized request сейчас реконструируется в
OpenAI-like payload, после чего используется существующий `RequestTransformer`
для GigaChat v1/v2 SDK. Это переходный слой: normalized contract уже отделён от
роутера, но часть GigaChat-specific подготовки ещё переиспользует legacy код.

## Отличия от OpenAI Chat Completions

OpenAI Chat Completions - публичный wire format. Normalized messages - внутренний
gateway contract.

Главные отличия:

- OpenAI хранит tool schemas как `{"type": "function", "function": {...}}`;
  normalized хранит `NormalizedTool` с плоскими `name`, `description`,
  `parameters`.
- OpenAI `tool_calls` содержит nested `function.arguments`; normalized хранит
  `NormalizedToolCall.name` и `arguments` напрямую, а nested provider поля
  остаются в `raw_extensions`.
- OpenAI content parts используют конкретные поля вроде `text`, `image_url`,
  `file`; normalized content part имеет generic `data` и optional metadata.
- OpenAI top-level параметры смешаны в одном object; normalized группирует
  generation knobs в `generation_config`, structured output в
  `response_format`, а unknown/compatibility поля - в `raw_extensions`.
- OpenAI usage называется `prompt_tokens` и `completion_tokens`; normalized
  использует provider-neutral `input_tokens` и `output_tokens`.
- OpenAI response id/object/created/system_fingerprint формируются только на
  выходе из normalized response adapter.

## Отличия от OpenAI Responses

OpenAI Responses API имеет другой публичный contract: `input`, `instructions`,
`output` items, `previous_response_id`, stateful response ids, built-in tool
progress events и `text.format`.

Normalized слой сейчас описывает Responses как chat-like exchange только для
observability:

- `responses_request_to_normalized()` строит `NormalizedChatRequest` с
  `operation="responses"`.
- `input` и `instructions` превращаются в normalized messages.
- `max_output_tokens` маппится в `generation_config.max_tokens`.
- `text.format` маппится в `NormalizedResponseFormat`.
- Responses output items сворачиваются в assistant message и tool calls для
  LLM spans.

Исполнение `/responses` остаётся в legacy route path:
`gpt2giga/routers/openai/responses.py` использует existing GigaChat v1/v2
request transformers и response processor. Поэтому normalized Responses helper
сейчас нужен для consistent observability, а не для основного execution path.

## Отличия от Gemini GenerateContent

Gemini GenerateContent - отдельный публичный protocol с `contents`, `parts`,
`systemInstruction`, `generationConfig`, `tools.functionDeclarations`,
`toolConfig.functionCallingConfig`, candidates и своим SSE response shape.

Normalized слой отличается так:

- `contents[].parts` превращаются в normalized messages/content parts.
- `systemInstruction` становится normalized system message.
- `generationConfig.temperature`, `topP`, `maxOutputTokens`, penalties, `seed` и
  `stopSequences` маппятся в `NormalizedGenerationConfig`.
- `functionDeclarations` превращаются в `NormalizedTool`; supported provider
  tools сохраняются как GigaChat-compatible built-in tool metadata, а
  unsupported tools остаются в `raw_extensions` для диагностики.
- `toolConfig.functionCallingConfig` применяется к function declarations и не
  форсирует встроенные provider tools.
- Gemini candidates, finish reasons и usage metadata формируются на выходе из
  normalized response/stream adapters.

Gemini Files/Batches router modules подготовлены, но не смонтированы в публичной
API surface; они не являются частью текущего normalized execution path.

## Отличия от GigaChat формата

GigaChat - upstream provider format, который gateway вызывает через SDK. Его
v1/v2 contracts, SDK models, function-call state ids, attachments и
`additional_fields` отличаются от публичных OpenAI/Anthropic shapes.

Normalized слой отличается так:

- не зависит от `gigachat.models.Messages` или v2 `ChatMessage`;
- хранит provider-neutral roles/messages/tools/usage/errors;
- не раскрывает GigaChat auth, SDK contextvars и transport details;
- сохраняет GigaChat-specific passthrough в `provider_metadata["gigachat"]`;
- фильтрует response headers перед переносом в metadata и не сохраняет
  `authorization`, `x-api-key`, `cookie`;
- нормализует GigaChat `function_call` в `NormalizedToolCall` и finish reason
  `function_call` в `tool_calls`.

Provider adapter отвечает за обратную сторону: он берёт normalized request,
подготавливает GigaChat payload, вызывает upstream и возвращает normalized
response/events.

## Отличия от Anthropic Messages

Anthropic Messages - отдельный публичный protocol с `system` на top-level,
content blocks, `max_tokens`, `stop_sequences`, `tool_use`, `tool_result`,
`thinking` и собственными streaming event names.

Normalized слой отличается так:

- `system` становится обычным normalized `system` message.
- Anthropic text/image blocks переводятся в normalized `content` string или
  content parts.
- `tool_use` становится assistant `tool_calls`.
- `tool_result` становится normalized message с `role="tool"` и
  `tool_call_id`.
- `max_tokens` хранится в `generation_config.max_tokens`, а `stop_sequences` -
  в `generation_config.stop`.
- `thinking`/reasoning content не является отдельным canonical field и
  сохраняется как controlled extension, например `reasoning_content`.
- Anthropic `usage.input_tokens` и `usage.output_tokens` уже совпадают с
  normalized naming, а `total_tokens` вычисляется при наличии обоих значений.

Сейчас Anthropic execution path остаётся legacy:
Anthropic payload сначала приводится к OpenAI-like payload, затем используется
общий GigaChat route transform. Debug translation и observability могут строить
normalized representation поверх этого пути.

## Observability

LLM observability намеренно строится поверх normalized shapes:

- Chat Completions spans получают request/response attributes из
  `NormalizedChatRequest` и `NormalizedResponse`.
- Responses и Anthropic helpers приводят свои public payloads к normalized
  chat-like representation перед построением span attributes.
- Gemini GenerateContent route уже отдаёт observability из normalized
  request/response и использует root span `Gemini-Content`.
- Streaming milestones строятся из `NormalizedStreamEvent`, когда route уже
  использует normalized stream path.
- Content capture остаётся выключенным по умолчанию; messages, tool args и
  responses требуют отдельного opt-in и проходят redaction.

Это позволяет добавлять новые protocols/providers без копирования всей логики
OpenInference/Phoenix attributes для каждого wire format.

## Debugging

Для локальной проверки включите protected debug translation:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Полезные endpoints:

- `POST /_debug/translate/openai-to-normalized`
- `POST /_debug/translate/anthropic-to-normalized`
- `POST /_debug/translate/normalized-to-gigachat`
- `POST /_debug/translate/gigachat-to-openai`
- `POST /_debug/translate` для generic `from`/`to` envelope

Shadow diagnostics не пишут prompt или response content. Они сохраняют route,
status, warnings/errors и hash формы normalized payload.
