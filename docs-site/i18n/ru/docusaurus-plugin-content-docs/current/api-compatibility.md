# Совместимость API

`gpt2giga` — это прокси совместимости, а не полный клон OpenAI, Anthropic или Gemini. Он сосредоточен на тех частях API, которые обычно нужны SDK, редакторам и агентным инструментам, когда бэкендом выступает GigaChat.

## Что не работает напрямую с GigaChat

Ниже перечислены практические несовместимости, которые закрывает прокси.

| Ожидание клиента | Почему ломается без прокси | Что делает `gpt2giga` |
|---|---|---|
| OpenAI Chat Completions JSON | У GigaChat другие форматы сообщений, инструментов, вложений и ответов. | Конвертирует запросы и ответы, включая потоковые фрагменты (chunks). |
| OpenAI Responses API | У GigaChat нет такого же маршрута `/responses` и схемы для элементов вывода. | Принимает `/responses`, сопоставляет input/instructions/tools и нормализует элементы вывода там, где это возможно. |
| Anthropic Messages API | Блоки контента Anthropic, вызовы инструментов, `system`, `max_tokens` и события потока не совпадают с GigaChat. | Конвертирует полезную нагрузку Anthropic в чат-запросы, совместимые с GigaChat, и сопоставляет ответы обратно. |
| Gemini GenerateContent API | `contents`/`parts`, кандидаты, объявления функций, подсчёт токенов и потоковые фрагменты SSE в Gemini отличаются от OpenAI/Anthropic и GigaChat. | Принимает Gemini-подобные запросы в корне, под `/v1`, `/v2` и `/v1beta`, переводит их в нормализованные запросы chat/embeddings и сопоставляет ответы обратно в форму Gemini. |
| SDK `extra_headers`, `extra_query`, `extra_body` | SDK могут прислать транспортные поля или необязательные поля модели, которые GigaChat не принимает. | Фильтрует опасные заголовки, передаёт только разрешённые метаданные, пробрасывает специфичный для GigaChat `extra_body` и игнорирует известные неподдерживаемые необязательные поля. |
| Потоковая передача SSE | SDK OpenAI, Anthropic и Gemini ждут свои имена событий и формы дельт. | Генерирует SSE, совместимый с OpenAI, Anthropic и Gemini, из потоковых ответов GigaChat. |
| Инструменты и структурированный вывод | Схемы функций/инструментов и управление через JSON-схему отличаются между провайдерами и режимами бэкенда. | Сопоставляет локальные инструменты/функции и даёт запасной путь через вызов функции для структурированного вывода. |
| Расследование совместимости | До отправки реального запроса трудно понять, будет ли поле поддержано, проигнорировано, сохранено только для диагностики, приближённо обработано или отклонено. | Даёт защищённый endpoint [Compatibility Doctor](diagnostics.md) без upstream-вызова, который объясняет интерпретацию запроса и решения редактирования. |
| Авторизация | Клиенты OpenAI/Anthropic работают с API-ключами, а GigaChat требует другого механизма учётных данных и scope. | Разделяет аутентификацию по API-ключу прокси и авторизацию в вышестоящем GigaChat, при необходимости поддерживает сквозную передачу для каждого запроса. |
| Получение списка моделей | Ответы GigaChat о моделях не совпадают с формой OpenAI/Anthropic/Gemini/LiteLLM. | Переупаковывает список и описание моделей под нужный клиент. |
| Пакетные маршруты OpenAI/Anthropic/Gemini | У установленного SDK/бэкенда GigaChat нет полного цикла create/list/retrieve/cancel для пакетных API. | Держит роутеры Files/Batches отключёнными, пока они не смогут работать сквозным образом. |

## Подключённые маршруты

Публичные API-маршруты доступны в корне и под версионированными префиксами.
Правило выбора бэкенда одинаково для маршрутов, совместимых с OpenAI, Anthropic
и Gemini: `/v1` принудительно выбирает контракт GigaChat v1, `/v2` — контракт
GigaChat v2, а корневые маршруты без версионированного префикса используют
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Примеры:

- `/chat/completions`, `/v1/chat/completions` и `/v2/chat/completions`
- `/responses`, `/v1/responses` и `/v2/responses`
- `/messages`, `/v1/messages` и `/v2/messages`
- `/models/{model}:generateContent`, `/v1/models/{model}:generateContent`, `/v2/models/{model}:generateContent` и `/v1beta/models/{model}:generateContent`

## Маршруты, совместимые с OpenAI

| Маршрут / группа | Статус | Комментарий |
|---|---|---|
| `GET /models` | Поддерживается | Список моделей GigaChat в форме, совместимой с OpenAI. |
| `GET /models/{model}` | Поддерживается | Одна модель в форме, совместимой с OpenAI. |
| `POST /chat/completions` | Поддерживается | Чат без потоковой передачи и потоковый, инструменты/вызов функций, структурированный вывод, вложения там, где поддерживаются. |
| `POST /responses` | Поддерживается | Сопоставляет input/instructions/tools из Responses с GigaChat. Режим GigaChat v2 даёт более богатый путь для встроенных инструментов. |
| `POST /embeddings` | Поддерживается | Использует модель из запроса или модель прокси по умолчанию для эмбеддингов, в зависимости от конфигурации. |
| `GET /model/info` | Поддерживается | Эндпоинт информации о модели, совместимый с LiteLLM. |
| `POST /files`, `GET /files*` | Отключено | Код роутера есть, но он не подключён: files без batches дают неполный пакетный цикл OpenAI. |
| `POST /batches`, `GET /batches*` | Отключено | Отключено до появления create/list/retrieve/cancel для пакетов в SDK/бэкенде GigaChat. |
| Маршруты сохранённых chat-completion | Не реализовано | Сохранённые completions сейчас вне области поддержки. |
| Устаревший `POST /completions` | Не реализовано | Устаревшие текстовые completions сейчас вне области поддержки. |
| Изображения, аудио, модерация, загрузки | Не реализовано | Эти семейства маршрутов OpenAI прокси не реализует. |
| Fine-tuning, assistants, threads, runs, vector stores | Не реализовано | Сейчас вне области поддержки. |
| Realtime/WebSocket API | Не реализовано | Сейчас вне области поддержки. |

## Маршруты, совместимые с Anthropic

| Маршрут / группа | Статус | Комментарий |
|---|---|---|
| `GET /models` | Поддерживается | Возвращается в форме Anthropic, когда запрос содержит заголовки Anthropic SDK. |
| `GET /models/{model_id}` | Поддерживается | Возвращается в форме Anthropic, когда запрос содержит заголовки Anthropic SDK. |
| `POST /messages` | Поддерживается | Messages API, потоковая передача, локальные инструменты, сопоставление с GigaChat v2 для совместимых провайдерских инструментов Anthropic, запасной путь для структурированного вывода. |
| `POST /messages/count_tokens` | Поддерживается | Считает текст сообщений, system, инструментов и структурированного вывода через подсчёт токенов GigaChat. |
| `POST /messages/batches`, `GET /messages/batches*` | Отключено | Код роутера есть, но он не подключён до появления пакетных методов в SDK/бэкенде GigaChat. |
| Files API beta | Не реализовано | Сейчас вне области поддержки. |
| Skills API beta | Не реализовано | Сейчас вне области поддержки. |
| Agents, Sessions, Environments, Admin beta APIs | Не реализовано | Сейчас вне области поддержки. |

## Маршруты, совместимые с Gemini

Операционные маршруты Gemini подключаются в корне, под `/v1`, `/v2` и `/v1beta`,
как остальные публичные API. Для клиентов, которые добавляют версию Gemini API
к уже версионированному base URL, также доступны `/v1/v1beta` и `/v2/v1beta`.
`/v1` и `/v1/v1beta` принудительно выбирают контракт бэкенда GigaChat v1,
`/v2` и `/v2/v1beta` — контракт бэкенда GigaChat v2. Корневые пути Gemini
`/...` и `/v1beta/...` без внешнего `/v1` или `/v2` используют
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Получение списка моделей Gemini в чистой форме Gemini всегда доступно под
`/v1beta`, `/v1/v1beta` и `/v2/v1beta`.
На общих `/models`, `/v1/models` и `/v2/models` прокси по умолчанию сохраняет
форму OpenAI, но возвращает форму Gemini для клиентов Google/Gemini, например
при заголовках `X-Goog-Api-Client` или `X-Goog-Api-Key`, либо при
query-параметре `?key=...`.

Если включена аутентификация по API-ключу прокси, клиенты, совместимые с
Gemini, могут передавать ключ через `x-goog-api-key` или `?key=...`, помимо
общих `Authorization: Bearer ...`, `x-api-key` и `?x-api-key=...`. Для новых
настроек предпочтительнее аутентификация через заголовок: ключи в
query-параметрах чаще попадают в журналы доступа.

`supportedGenerationMethods` строится консервативно: известные чат-подобные
модели GigaChat объявляют `generateContent`, `streamGenerateContent` и
`countTokens`; модели типа эмбеддингов объявляют только `embedContent` и
`batchEmbedContents`; неизвестные/пользовательские идентификаторы моделей
объявляют только `countTokens`, если метаданные бэкенда не дают более точной
информации.

| Маршрут / группа | Статус | Комментарий |
|---|---|---|
| `GET /v1beta/models`, `/v1/v1beta/models`, `/v2/v1beta/models` | Поддерживается | Список моделей GigaChat в форме Gemini `models/*`. |
| `GET /v1beta/models/{model}`, `/v1/v1beta/models/{model}`, `/v2/v1beta/models/{model}` | Поддерживается | Одна модель в форме Gemini `Model`. |
| `POST /models/{model}:generateContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | `contents`/`parts`, `systemInstruction`, `generationConfig`, объявления функций и мультимодальные части Gemini сопоставляются с нормализованным чат-запросом. |
| `POST /models/{model}:streamGenerateContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Возвращает `text/event-stream` с фрагментами Gemini `GenerateContentResponse`. |
| `POST /models/{model}:countTokens`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Считает текстовые части contents/system/tools через подсчёт токенов GigaChat. |
| `POST /models/{model}:embedContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Возвращает Gemini `embedding.values`, используя бэкенд эмбеддингов GigaChat. |
| `POST /models/{model}:batchEmbedContents`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Поддерживается | Возвращает Gemini `embeddings[]`, используя бэкенд эмбеддингов GigaChat. |
| `POST /v1beta/files`, `GET /v1beta/files*` | Отключено | Код роутера подготовлен, но по умолчанию не подключён. |
| `POST /v1beta/models/{model}:batchGenerateContent`, `GET /v1beta/batches*` | Отключено | Код роутера подготовлен, но не подключён до сквозного выполнения пакетов. |

### Вызов функций в Gemini

`toolConfig.functionCallingConfig` сопоставляется с ближайшей поддерживаемой
семантикой нормализованного/OpenAI-подобного слоя:

- `mode=AUTO` оставляет вызов функций необязательным. Если задан
  `allowedFunctionNames`, вышестоящий сервис получает только эти объявленные функции.
- `mode=NONE` отключает вызов функций.
- `mode=ANY` поддерживается только когда после учёта `allowedFunctionNames`
  остаётся ровно одна функция; она сопоставляется с принудительным вызовом функции.
- `mode=ANY` без `allowedFunctionNames` также поддерживается, если объявлена
  ровно одна функция.
- `mode=ANY` с несколькими возможными функциями возвращает `400`, потому что
  путь бэкенда GigaChat сейчас не умеет честно выразить «обязательно вызвать
  одну из нескольких функций».
- `allowedFunctionNames` проверяется по объявленным
  `functionDeclarations`; ссылки на необъявленные функции возвращают `400`.

### Эмбеддинги в Gemini

`embedContent` и `batchEmbedContents` поддерживают только текстовые
`content.parts[].text`. Пустые `requests`, некорректные элементы пакета и
нетекстовые части возвращают `400` до вызова бэкенда эмбеддингов GigaChat.

`outputDimensionality` принимается как метаданные совместимости для
нормализованного запроса и наблюдаемости, но не передаётся в вышестоящий сервис
как исполняемая настройка: текущий путь бэкенда эмбеддингов GigaChat не
предоставляет управляемое уменьшение размерности через этот параметр.

### Область поддержки и проверка Gemini

Это API, совместимый с Gemini, а не полный паритет с Gemini API. Перед релизом
проверяйте именно заявленную область поддержки:

- поддерживаемые маршруты: `generateContent`, `streamGenerateContent`, `countTokens`,
  `embedContent`, `batchEmbedContents`, получение списка моделей;
- поддерживаемые префиксы: корень, `/v1`, `/v2`, `/v1beta`, `/v1/v1beta`,
  `/v2/v1beta`;
- отключённые маршруты: роутеры Gemini Files API и `batchGenerateContent` есть в
  коде, но не подключены публично до сквозного выполнения в вышестоящем сервисе;
- частично поддерживаемые поля: `safetySettings` и `cachedContent` принимаются
  для совместимости и диагностики, но не применяются; `candidateCount`, `topK` и
  `responseModalities` принимаются и фиксируются, но игнорируются при выполнении в GigaChat;
- структурированный вывод: `generationConfig.responseMimeType=text/plain` считается
  текстовым режимом по умолчанию, `application/json` сопоставляется с форматом ответа
  JSON, а другие MIME-типы и `responseSchema` без `application/json`
  возвращают `400`;
- неподдерживаемые возможности: инструменты Gemini вне встроенного сопоставления
  GigaChat SDK (`fileSearch`, `googleMaps`, `computerUse`, MCP, инструменты RAG/retrieval/Vertex),
  полностью мультимодальные/файловые сценарии Gemini, нетекстовое содержимое эмбеддингов;
- приближения: `countTokens` считает извлечённый текст через подсчёт токенов GigaChat,
  игнорирует части non-text/file/cachedContent и не является точным
  токенизатором Gemini.

Чек-лист для копирования в описание PR:

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

`gpt2giga` намеренно принимает многие необязательные поля SDK, которые GigaChat не может исполнить. Это не даёт клиентам падать до того, как полезная часть запроса попадёт в модель.

Типичные поля, которые принимаются и игнорируются:

- Метаданные OpenAI и параметры тонкой настройки: `user`, `metadata`, `service_tier`, `seed`, `prompt_cache_key`, `logprobs`, `top_logprobs`, `logit_bias`, `prediction`, `web_search_options`, `n > 1`, `parallel_tool_calls=true`;
- Необязательные поля Anthropic: `metadata`, `service_tier`, `top_k`, `container`, `context_management`, `mcp_servers`, неподдерживаемые провайдерские инструменты, цитаты (citations), неподдерживаемые блоки контента document/file. Совместимые провайдерские инструменты (`web_search*`, `web_fetch*`, `code_execution*`) сопоставляются со встроенными инструментами GigaChat v2, если не включён `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True`.
- Необязательные поля Gemini: `safetySettings`, `cachedContent`, `serviceTier`, игнорируемые настройки `generationConfig`, например `candidateCount`/`topK`/`responseModalities`, и неподдерживаемые инструменты, не являющиеся функциями, принимаются и сохраняются для диагностики, но не применяются GigaChat. Совместимые провайдерские инструменты Gemini сопоставляются со встроенными инструментами GigaChat v2: `googleSearch` / `googleSearchRetrieval` -> `web_search`, `urlContext` -> `url_content_extraction`, `codeExecution` -> `code_interpreter`, если не включён `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True`; полное сопоставление описано во [Встроенных инструментах](builtin-tools.md). Неподдерживаемые значения `responseMimeType` и `responseSchema` без `application/json` отклоняются.

Если поле намеренно игнорируется, оно не отправляется в вышестоящий сервис как исполняемая возможность GigaChat. Буквальный объект `extra_body` может быть передан в GigaChat `additional_fields`; в таком случае поддержку определяет API GigaChat.

В наблюдаемости проигнорированные расширения запроса публикуются в маскированном
атрибуте `llm.request.extensions`, а проигнорированные настройки генерации Gemini
остаются в `llm.invocation_parameters`.

Справочник по каждому параметру: [Совместимость параметров клиентов](./client-parameter-compatibility.md).

Чтобы проверить конкретный request envelope без вызова GigaChat, используйте
[Compatibility Doctor](./diagnostics.md). Он сообщает supported, ignored,
diagnostic-only, approximated и rejected поля, а также решения по tool mapping и
redaction.

Внутренний нормализованный слой, который отделяет публичные форматы протоколов от
выполнения у провайдера, описан в [Нормализованных сообщениях](./architecture/normalized-messages.md).

## Режимы бэкенда

По умолчанию используются корневые методы совместимости GigaChat:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

Задайте `GPT2GIGA_GIGACHAT_API_MODE=v2`, чтобы корневые маршруты без `/v1` или
`/v2` использовали более новый интерфейс GigaChat `v2/chat/completions` для
чат-подобных запросов. Для явного выбора на уровне клиента используйте `base_url`
с `/v1` или `/v2`: `/v1` всегда идёт в контракт GigaChat v1, `/v2` — в контракт
GigaChat v2.

`/chat/completions` остаётся маршрутом совместимости и следует переменной
окружения. Новые возможности встроенных инструментов развиваются преимущественно
вокруг режима GigaChat v2, поэтому клиенты, которым они нужны, могут указывать
`http://localhost:8090/v2`.
