# Архитектура нормализованных сообщений

Нормализованный слой — это внутренний контракт между публичными форматами API и
вышестоящими провайдерами. Он не является новым публичным API. Клиенты продолжают
посылать OpenAI Chat Completions, OpenAI Responses, Anthropic Messages или
Gemini GenerateContent, а шлюз приводит совместимые части полезной нагрузки к
каноническим моделям из `gpt2giga/protocols/normalized/`. Gemini GenerateContent
уже использует отдельный адаптер Gemini-в-нормализованное в основном пути выполнения.

## Текущий статус

- `GPT2GIGA_NORMALIZATION_MODE=off`: OpenAI Chat Completions идёт через прежние
  преобразования.
- `GPT2GIGA_NORMALIZATION_MODE=shadow`: OpenAI Chat строит нормализованный запрос
  рядом с прежним путём и сохраняет безопасный диагностический хеш формы без содержимого промпта.
- `GPT2GIGA_NORMALIZATION_MODE=on`: OpenAI Chat Completions исполняется через
  нормализованный путь и `GigaChatProviderAdapter`; до старта ответа доступен откат
  к прежнему через `GPT2GIGA_LEGACY_CHAT_FALLBACK=True`.
- OpenAI Responses и Anthropic Messages пока исполняются через прежние
  преобразования маршрута, но наблюдаемость и отладочная трансляция уже используют нормализованное
  представление там, где это возможно.
- Gemini GenerateContent и streamGenerateContent исполняются через
  `GeminiProtocolAdapter`, нормализованные модели и `GigaChatProviderAdapter`
  независимо от флагов нормализации OpenAI Chat.
- Debug-эндпоинты умеют переводить между форматами `openai`, `anthropic`, `normalized` и
  `gigachat` для защищённых admin-сценариев.

## Основные модели

Конверт нормализованного запроса:

- `NormalizedChatRequest`: `protocol`, `operation`, `model`, `stream`,
  `messages`, `tools`, `tool_choice`, `response_format`,
  `generation_config`, `user`, `metadata`.
- `NormalizedMessage`: `role`, `content`, `name`, `tool_call_id`,
  `tool_calls`.
- `NormalizedContentPart`: универсальная часть контента с `type`, `text`, `data`,
  `mime_type`, `detail`.
- `NormalizedTool`: уплощённый контракт инструмента/функции с `name`,
  `description`, `parameters`.
- `NormalizedGenerationConfig`: общие параметры генерации:
  `temperature`, `top_p`, `max_tokens`, penalties, `stop`, `seed`.

Нормализованный вывод:

- `NormalizedResponse`: ответ без потоковой передачи, не зависящий от провайдера:
  `choices`, `usage`, `error`, `metadata`, `provider_metadata`.
- `NormalizedChoice`: `message` или `delta`, `finish_reason`, `index`.
- `NormalizedUsage`: `input_tokens`, `output_tokens`, `total_tokens`.
- `NormalizedStreamEvent`: канонические события потока:
  `message_start`, `content_delta`, `reasoning_delta`, `tool_call_start`,
  `tool_call_delta`, `usage`, `message_end`, `error`, `heartbeat`.

Все нормализованные модели наследуют два набора расширений:

- `raw_extensions`: поля исходного публичного протокола, которые шлюз должен
  сохранить, но не поднимать в каноническую модель.
- `provider_metadata`: данные, специфичные для провайдера, например GigaChat
  `additional_fields` или безопасные метаданные из ответа вышестоящего сервиса.

## Поток OpenAI Chat

OpenAI Chat Completions в нормализованном режиме проходит так:

1. `gpt2giga/routers/openai/chat_completions.py` читает полезную нагрузку и контекст
   запроса.
2. `OpenAIProtocolAdapter` из `gpt2giga/protocols/openai/adapter.py` строит
   `NormalizedChatRequest`.
3. `GigaChatProviderAdapter` из `gpt2giga/providers/gigachat/adapter.py`
   исполняет нормализованный запрос через текущий путь GigaChat SDK.
4. Адаптер провайдера возвращает `NormalizedResponse` или
   `NormalizedStreamEvent`.
5. Адаптеры ответов OpenAI сопоставляют результат обратно в полезную нагрузку
   OpenAI Chat Completions или фрагменты SSE.
6. Наблюдаемость получает нормализованные запрос/ответ и строит безопасные
   атрибуты спанов в стиле OpenInference.

Внутри `GigaChatProviderAdapter` нормализованный запрос сейчас реконструируется в
OpenAI-подобную полезную нагрузку, после чего используется существующий `RequestTransformer`
для GigaChat v1/v2 SDK. Это переходный слой: нормализованный контракт уже отделён от
роутера, но часть подготовки, специфичной для GigaChat, ещё переиспользует прежний код.

## Отличия от OpenAI Chat Completions

OpenAI Chat Completions — публичный сетевой формат (wire format). Нормализованные сообщения —
внутренний контракт шлюза.

Главные отличия:

- OpenAI хранит схемы инструментов как `{"type": "function", "function": {...}}`;
  нормализованный слой хранит `NormalizedTool` с плоскими `name`, `description`,
  `parameters`.
- OpenAI `tool_calls` содержит вложенные `function.arguments`; нормализованный слой хранит
  `NormalizedToolCall.name` и `arguments` напрямую, а вложенные провайдерские поля
  остаются в `raw_extensions`.
- части контента OpenAI используют конкретные поля вроде `text`, `image_url`,
  `file`; нормализованная часть контента имеет универсальное `data` и необязательные метаданные.
- параметры верхнего уровня OpenAI смешаны в одном объекте; нормализованный слой группирует
  параметры генерации в `generation_config`, структурированный вывод в
  `response_format`, а неизвестные поля и поля совместимости — в `raw_extensions`.
- использование токенов в OpenAI называется `prompt_tokens` и `completion_tokens`; нормализованный слой
  использует нейтральные к провайдеру `input_tokens` и `output_tokens`.
- `id`/`object`/`created`/`system_fingerprint` ответа OpenAI формируются только на
  выходе из адаптера нормализованного ответа.

## Отличия от OpenAI Responses

OpenAI Responses API имеет другой публичный контракт: `input`, `instructions`,
элементы `output`, `previous_response_id`, идентификаторы ответов с состоянием, события прогресса
встроенных инструментов и `text.format`.

Нормализованный слой сейчас описывает Responses как чат-подобный обмен только для
наблюдаемости:

- `responses_request_to_normalized()` строит `NormalizedChatRequest` с
  `operation="responses"`.
- `input` и `instructions` превращаются в нормализованные сообщения.
- `max_output_tokens` сопоставляется с `generation_config.max_tokens`.
- `text.format` сопоставляется с `NormalizedResponseFormat`.
- элементы вывода Responses сворачиваются в сообщение ассистента и вызовы инструментов для
  спанов LLM.

Исполнение `/responses` остаётся на прежнем пути маршрута:
`gpt2giga/routers/openai/responses.py` использует существующие преобразователи запросов
GigaChat v1/v2 и обработчик ответов. Поэтому нормализованный помощник Responses
сейчас нужен для согласованной наблюдаемости, а не для основного пути выполнения.

## Отличия от Gemini GenerateContent

Gemini GenerateContent — отдельный публичный протокол с `contents`, `parts`,
`systemInstruction`, `generationConfig`, `tools.functionDeclarations`,
`toolConfig.functionCallingConfig`, кандидатами и своей формой ответа SSE.

Нормализованный слой отличается так:

- `contents[].parts` превращаются в нормализованные сообщения/части контента.
- `systemInstruction` становится нормализованным system-сообщением.
- `generationConfig.temperature`, `topP`, `maxOutputTokens`, penalties, `seed` и
  `stopSequences` сопоставляются с `NormalizedGenerationConfig`.
- `functionDeclarations` превращаются в `NormalizedTool`; поддерживаемые провайдерские
  инструменты сохраняются как метаданные встроенных инструментов, совместимые с GigaChat, а
  неподдерживаемые инструменты остаются в `raw_extensions` для диагностики.
- `toolConfig.functionCallingConfig` применяется к объявлениям функций и не
  форсирует встроенные провайдерские инструменты.
- кандидаты Gemini, причины завершения и метаданные использования формируются на выходе из
  адаптеров нормализованного ответа/потока.

Модули роутеров Gemini Files/Batches подготовлены, но не подключены в публичном
наборе API; они не являются частью текущего нормализованного пути выполнения.

## Отличия от формата GigaChat

GigaChat — формат вышестоящего провайдера, который шлюз вызывает через SDK. Его
контракты v1/v2, модели SDK, идентификаторы состояния вызова функций, вложения и
`additional_fields` отличаются от публичных форм OpenAI/Anthropic.

Нормализованный слой отличается так:

- не зависит от `gigachat.models.Messages` или v2 `ChatMessage`;
- хранит нейтральные к провайдеру роли/сообщения/инструменты/использование/ошибки;
- не раскрывает авторизацию GigaChat, contextvars SDK и детали транспорта;
- сохраняет специфичный для GigaChat проброс в `provider_metadata["gigachat"]`;
- фильтрует заголовки ответа перед переносом в метаданные и не сохраняет
  `authorization`, `x-api-key`, `cookie`;
- нормализует GigaChat `function_call` в `NormalizedToolCall` и причину завершения
  `function_call` в `tool_calls`.

Адаптер провайдера отвечает за обратную сторону: он берёт нормализованный запрос,
подготавливает полезную нагрузку GigaChat, вызывает вышестоящий сервис и возвращает нормализованные
ответ/события.

## Отличия от Anthropic Messages

Anthropic Messages — отдельный публичный протокол с `system` на верхнем уровне,
блоками контента, `max_tokens`, `stop_sequences`, `tool_use`, `tool_result`,
`thinking` и собственными именами событий потока.

Нормализованный слой отличается так:

- `system` становится обычным нормализованным `system`-сообщением.
- текстовые/графические блоки Anthropic переводятся в нормализованную строку
  `content` или части контента.
- `tool_use` становится `tool_calls` ассистента.
- `tool_result` становится нормализованным сообщением с `role="tool"` и
  `tool_call_id`.
- `max_tokens` хранится в `generation_config.max_tokens`, а `stop_sequences` —
  в `generation_config.stop`.
- содержимое `thinking`/рассуждений не является отдельным каноническим полем и
  сохраняется как контролируемое расширение, например `reasoning_content`.
- `usage.input_tokens` и `usage.output_tokens` в Anthropic уже совпадают с
  нормализованными именами, а `total_tokens` вычисляется при наличии обоих значений.

Сейчас путь выполнения Anthropic остаётся прежним:
полезная нагрузка Anthropic сначала приводится к OpenAI-подобной, затем используется
общее преобразование маршрута GigaChat. Отладочная трансляция и наблюдаемость могут строить
нормализованное представление поверх этого пути.

## Наблюдаемость

Наблюдаемость LLM намеренно строится поверх нормализованных форм:

- спаны Chat Completions получают атрибуты запроса/ответа из
  `NormalizedChatRequest` и `NormalizedResponse`.
- помощники Responses и Anthropic приводят свои публичные полезные нагрузки к
  нормализованному чат-подобному представлению перед построением атрибутов спанов, а
  вехи потока могут строиться из `NormalizedStreamEvent`.
- маршрут Gemini GenerateContent уже отдаёт наблюдаемость из нормализованных
  запроса/ответа и использует корневой спан `Gemini-Content`.
- вехи потока строятся из `NormalizedStreamEvent`, когда маршрут уже
  использует нормализованный потоковый путь.
- захват содержимого остаётся выключенным по умолчанию; сообщения, аргументы инструментов и
  ответы требуют отдельного включения и проходят маскирование.

Это позволяет добавлять новые протоколы/провайдеры без копирования всей логики
атрибутов OpenInference/Phoenix для каждого сетевого формата.

## Отладка

Для локальной проверки включите защищённую отладочную трансляцию:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Полезные эндпоинты:

- `POST /_debug/translate/openai-to-normalized`
- `POST /_debug/translate/anthropic-to-normalized`
- `POST /_debug/translate/normalized-to-gigachat`
- `POST /_debug/translate/gigachat-to-openai`
- `POST /_debug/translate` для универсального конверта `from`/`to`

Теневая диагностика (shadow) не пишет содержимое промптов или ответов. Она сохраняет маршрут,
статус, предупреждения/ошибки и хеш формы нормализованной полезной нагрузки.
