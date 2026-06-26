# Конфигурация

`gpt2giga` читает две группы настроек:

- настройки прокси с префиксом `GPT2GIGA_`;
- настройки GigaChat SDK с префиксом `GIGACHAT_`.

Секреты храните в `.env`, переменных окружения или менеджере секретов. Не передавайте учётные данные через флаги CLI в production: аргументы процесса могут быть видны через `ps`.

## Источники настроек

CLI принимает явный env-файл:

```sh
gpt2giga --env-path .env
```

Можно передавать структурированные флаги CLI:

```sh
gpt2giga \
  --proxy.host 127.0.0.1 \
  --proxy.port 8090 \
  --proxy.pass-model true \
  --gigachat.model GigaChat-2-Max
```

Полный справочник CLI:

```sh
gpt2giga --help
```

Шаблон env для копирования: [.env.example](https://github.com/ai-forever/gpt2giga/blob/main/.env.example).

## Как читать этот документ

`.env.example` намеренно остаётся шаблоном для копирования: там удобно видеть все
ключи рядом, но не всегда видны компромиссы. Этот документ — справочник по
смыслу настроек и безопасным сочетаниям.

Практическое правило:

- для локального запуска начните с минимального блока `GPT2GIGA_*` и `GIGACHAT_*`;
- для production сначала настройте безопасность, потом режим бэкенда, потом при
  необходимости журналы трафика, метрики и наблюдаемость;
- экспериментальные, admin- и debug-флаги включайте только когда понимаете, кто имеет к
  ним доступ и где будут храниться полезные нагрузки.

## Быстрые профили

Минимальный локальный `.env`:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<local-proxy-api-key>"

GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

Минимум для production:

```dotenv
GPT2GIGA_MODE=PROD
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong-random-secret>"
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://your-app.example.com"]'
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_REDACT_SENSITIVE=True

GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

Явный выбор GigaChat v2 на стороне клиента:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

При таком значении корневые маршруты без `/v1` или `/v2` остаются на v1, а клиент может
выбрать v2 через `base_url="http://localhost:8090/v2"`. `/v1` всегда
принудительно выбирает контракт GigaChat v1, `/v2` — контракт GigaChat v2.
Если хотите, чтобы корневые маршруты тоже использовали v2, задайте
`GPT2GIGA_GIGACHAT_API_MODE=v2`.

## Формат значений

Pydantic Settings читает имена переменных окружения без учёта регистра, но в документации и
примерах используется верхний регистр.

Списки и словари задавайте JSON-строками:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://app.example.com"]'
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS='["customer_token"]'
```

`GPT2GIGA_TRAFFIC_LOG_SINKS` принимает JSON-массив или список через запятую:

```dotenv
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
```

Флаги CLI удобны для несекретных локальных переопределений. Для секретов используйте
`.env`, переменные окружения или менеджер секретов, потому что аргументы CLI
могут быть видны другим процессам.

## Основные настройки прокси

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `GPT2GIGA_MODE` | `DEV` | `DEV` или `PROD`. `PROD` отключает `/docs`, `/redoc`, `/openapi.json` и `/logs*`. |
| `GPT2GIGA_HOST` | `localhost` | Хост локального сервера. |
| `GPT2GIGA_PORT` | `8090` | Порт локального сервера. |
| `GPT2GIGA_USE_HTTPS` | `False` | Встроенный HTTPS. Для production обычно лучше TLS на обратном прокси. |
| `GPT2GIGA_HTTPS_KEY_FILE` / `GPT2GIGA_HTTPS_CERT_FILE` | empty | Локальные файлы ключа/сертификата для встроенного HTTPS. |
| `GPT2GIGA_ENABLE_API_KEY_AUTH` | `False` | Требовать аутентификацию по API-ключу прокси для публичных API-маршрутов. В `PROD` обязательно. |
| `GPT2GIGA_API_KEY` | empty | API-ключ прокси. Для общих окружений используйте сильное случайное значение. |
| `GPT2GIGA_PASS_MODEL` | `True` | Передавать `model` из запроса в GigaChat. Поставьте `False`, чтобы всегда использовать настроенную модель GigaChat. |
| `GPT2GIGA_PASS_TOKEN` | `False` | Разбирать клиентский `Authorization` как учётные данные GigaChat для авторизации в вышестоящем сервисе для каждого запроса. |
| `GPT2GIGA_EMBEDDINGS` | `EmbeddingsGigaR` | Модель эмбеддингов по умолчанию, если модель из запроса не используется. |
| `GPT2GIGA_MAX_REQUEST_BODY_BYTES` | `10485760` | Максимальный размер тела HTTP-запроса. |
| `GPT2GIGA_LOG_LEVEL` | `INFO` | Уровень журналов выполнения. В production избегайте `DEBUG`. |
| `GPT2GIGA_LOG_FILENAME` | `gpt2giga.log` | Файл журналов выполнения. |
| `GPT2GIGA_LOG_MAX_SIZE` | `10485760` | Максимальный размер файла журнала перед ротацией. |
| `GPT2GIGA_LOG_REDACT_SENSITIVE` | `True` | Маскировать секреты в журналах выполнения. |

## Аутентификация и безопасность

API-ключ прокси защищает публичные API-маршруты (`/chat/completions`, `/responses`,
`/messages`, `/models`, `/embeddings`, `/model/info`, versioned variants).
Клиенты могут передавать ключ двумя способами:

```http
Authorization: Bearer <GPT2GIGA_API_KEY>
x-api-key: <GPT2GIGA_API_KEY>
```

`MODE=PROD` требует заданного API-ключа и отключает интерактивную документацию и
маршруты логов. Admin- и debug-эндпоинты используют отдельный `GPT2GIGA_ADMIN_API_KEY`.

`GPT2GIGA_PASS_TOKEN=True` нужен только для сценариев, где каждый клиент должен
передавать свои учётные данные GigaChat. Поддерживаются такие префиксы в
`Authorization`:

- `giga-cred-<credentials>:<scope>` для учётных данных по ключу авторизации GigaChat;
- `giga-auth-<access_token>` для готового access-токена;
- `giga-user-<user>:<password>` для авторизации по логину и паролю.

Для обычного развёртывания проще и безопаснее держать учётные данные вышестоящего
сервиса на сервере через `GIGACHAT_*`.

## Настройки GigaChat

Частые настройки вышестоящего сервиса:

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `GIGACHAT_CREDENTIALS` | empty | Ключ авторизации (учётные данные). |
| `GIGACHAT_SCOPE` | SDK default | Scope GigaChat API, например `GIGACHAT_API_PERS`. |
| `GIGACHAT_USER` / `GIGACHAT_PASSWORD` | empty | Альтернативная авторизация по логину и паролю. |
| `GIGACHAT_ACCESS_TOKEN` | empty | Альтернативная авторизация через готовый access-токен. |
| `GIGACHAT_MODEL` | SDK default | Модель по умолчанию, если прокси не передаёт клиентскую модель или `GPT2GIGA_PASS_MODEL=False`. |
| `GIGACHAT_PROFANITY_CHECK` | SDK default | Флаг проверки на нецензурную лексику в вышестоящем сервисе. |
| `GIGACHAT_VERIFY_SSL_CERTS` | SDK default | В production держите `True`. |
| `GIGACHAT_TIMEOUT` | SDK default | Таймаут запроса к вышестоящему сервису. |
| `GIGACHAT_MAX_CONNECTIONS` | SDK default | Глобальное ограничение числа соединений SDK/HTTP. |
| `GIGACHAT_MAX_RETRIES` | SDK default | Число повторных попыток SDK для временных ошибок вышестоящего сервиса. |

GigaChat также поддерживает настройки клиентского TLS-сертификата: `GIGACHAT_CA_BUNDLE_FILE`, `GIGACHAT_CERT_FILE`, `GIGACHAT_KEY_FILE`, `GIGACHAT_KEY_FILE_PASSWORD`.

`GPT2GIGA_PASS_MODEL=False` часто полезен для клиентов, совместимых с OpenAI,
которые отправляют имя модели не из GigaChat. Тогда модель вышестоящего сервиса берётся из
`GIGACHAT_MODEL`.

## Рассуждения и структурированный вывод

Рассуждения:

```dotenv
GPT2GIGA_ENABLE_REASONING=False
GPT2GIGA_DISABLE_REASONING=False
```

- `GPT2GIGA_ENABLE_REASONING=True` добавляет `reasoning_effort="high"`, если клиент не передал явную настройку рассуждений.
- `GPT2GIGA_DISABLE_REASONING=True` удаляет `reasoning` и `reasoning_effort`, включая явные клиентские поля и проброс `extra_body`.

Структурированный вывод:

```dotenv
GPT2GIGA_STRUCTURED_OUTPUT_MODE=function_call
```

Значения:

- `function_call`: запасной путь совместимости через вызов функций;
- `native`: передаёт JSON Schema через GigaChat `response_format`, если это поддерживают модель/API.

Оба режима рассчитаны на структурированный вывод на основе схемы. OpenAI
`response_format.type=json_object` и Gemini `responseMimeType=application/json`
без `responseJsonSchema` / `responseSchema` не проксируются в GigaChat, потому
что вышестоящий сервис не поддерживает отдельный режим JSON без схемы.

## Режим API бэкенда

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

| `GPT2GIGA_GIGACHAT_API_MODE` | бэкенд `/chat/completions` | бэкенд `/responses` |
|---|---|---|
| `v1` | `v1` | `v1` |
| `v2` | `v2` | `v2` |

Корневые URL (`/chat/completions`, `/responses`, `/messages`) без `/v1` или `/v2`
используют этот флаг.
Версионированные префиксы — это явное переопределение для каждого запроса:

- `/v1/chat/completions`, `/v1/responses`, `/v1/messages` используют контракт GigaChat v1;
- `/v2/chat/completions`, `/v2/responses`, `/v2/messages` используют контракт GigaChat v2.

Сопоставление built-in tools можно выключить отдельно:

```dotenv
GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=False
```

Когда значение `True`, OpenAI/Anthropic/Gemini provider built-in tools
(`web_search*`, `code_execution*`, `urlContext` и похожие) не сопоставляются со
встроенными инструментами GigaChat v2 и игнорируются. Пользовательские
function/local tools остаются включены.

## Флаги нормализованного слоя

Экспериментальные флаги управляют нормализованным путём OpenAI Chat Completions и по
умолчанию сохраняют прежнее поведение для этого маршрута:

```dotenv
GPT2GIGA_EXPERIMENTAL_NORMALIZED_LAYER=False
GPT2GIGA_NORMALIZATION_MODE=off
GPT2GIGA_LEGACY_CHAT_FALLBACK=True
```

- `off`: OpenAI Chat Completions идёт через прежний путь;
- `shadow`: строит нормализованную диагностику рядом с прежней обработкой OpenAI Chat без изменения ответов клиенту;
- `on`: переводит OpenAI Chat на нормализованный путь, с откатом к прежнему до старта ответа, если откат включён.

Gemini GenerateContent использует свой выделенный адаптер Gemini-в-нормализованное и
путь провайдера GigaChat независимо от этих флагов OpenAI Chat. OpenAI Responses и
Anthropic Messages остаются на прежних путях выполнения, но используют нормализованное
представление для наблюдаемости и отладочных помощников там, где это возможно.

Подробное описание моделей и текущих путей выполнения: [Нормализованные сообщения](./architecture/normalized-messages.md).

## Склейка диалогов (conversation stitching)

Склейка диалогов — это включаемое по запросу состояние в памяти для
чат-подобных клиентов без состояния, которые передают стабильный идентификатор
диалога. По умолчанию выключена и не влияет на совместимость.
Поддержаны OpenAI Chat Completions, Anthropic Messages и Gemini GenerateContent.
Идентификатор диалога берётся из `conversation`, `metadata.conversation_id`,
`x-gpt2giga-conversation-id` или, если включено, `x-session-id`.

```dotenv
GPT2GIGA_CONVERSATION_STITCHING_ENABLED=False
GPT2GIGA_CONVERSATION_TTL_SECONDS=3600
GPT2GIGA_CONVERSATION_MAX_MESSAGES=40
GPT2GIGA_CONVERSATION_USE_SESSION_ID=False
GPT2GIGA_CONVERSATION_ON_DIVERGENCE=client_wins
```

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `GPT2GIGA_CONVERSATION_STITCHING_ENABLED` | `False` | Включить локальное состояние склейки. |
| `GPT2GIGA_CONVERSATION_TTL_SECONDS` | `3600` | Сколько хранить простаивающее состояние диалога. |
| `GPT2GIGA_CONVERSATION_MAX_MESSAGES` | `40` | Максимум сохраняемых сообщений, отправляемых в вышестоящий сервис. |
| `GPT2GIGA_CONVERSATION_USE_SESSION_ID` | `False` | Разрешить `x-session-id` как ключ диалога, если явного ключа нет. |
| `GPT2GIGA_CONVERSATION_ON_DIVERGENCE` | `client_wins` | `client_wins` заменяет состояние после успеха, `fork` создаёт ветку с суффиксом ревизии. |

Состояние хранится в памяти процесса. При нескольких воркерах/подах используйте привязку
сессий (sticky routing) или не включайте склейку.

## Параллелизм по моделям

`GIGACHAT_MAX_CONNECTIONS` — глобальное ограничение SDK/HTTP. Прокси также умеет ограничивать число одновременных вызовов модели в вышестоящем сервисе по фактической модели:

```dotenv
GIGACHAT_MAX_CONNECTIONS=7
GPT2GIGA_MODEL_MAX_CONNECTIONS='{"GigaChat-2-Max":5}'
GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=30
```

Семантика:

- пустой `GPT2GIGA_MODEL_MAX_CONNECTIONS` и пустое значение по умолчанию выключают ограничитель;
- явный лимит модели важнее значения по умолчанию;
- `GPT2GIGA_MODEL_MAX_CONNECTIONS_ACQUIRE_TIMEOUT=0` сразу возвращает локальный `429`;
- потоковые вызовы удерживают слот до завершения потока или отключения клиента;
- лимиты работают внутри одного процесса, поэтому воркеры/поды умножают фактическую пропускную способность.

## CORS

Значения по умолчанию удобны для локальной разработки:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["*"]'
GPT2GIGA_CORS_ALLOW_METHODS='["*"]'
GPT2GIGA_CORS_ALLOW_HEADERS='["*"]'
```

В production задайте конкретные источники (origins) и заголовки:

```dotenv
GPT2GIGA_CORS_ALLOW_ORIGINS='["https://your-app.example.com"]'
GPT2GIGA_CORS_ALLOW_METHODS='["GET","POST","OPTIONS"]'
GPT2GIGA_CORS_ALLOW_HEADERS='["authorization","content-type","x-api-key"]'
```

## Лимиты тела HTTP и вложений

Глобальный лимит тела проверяется до разбора JSON:

```dotenv
GPT2GIGA_MAX_REQUEST_BODY_BYTES=10485760
```

Дополнительные лимиты защищают обработку вложений:

| Переменная | Назначение |
|---|---|
| `GPT2GIGA_MAX_AUDIO_FILE_SIZE_BYTES` | Максимальный размер одного аудиофайла. |
| `GPT2GIGA_MAX_IMAGE_FILE_SIZE_BYTES` | Максимальный размер одного изображения. |
| `GPT2GIGA_MAX_TEXT_FILE_SIZE_BYTES` | Максимальный размер одного текстового файла. |
| `GPT2GIGA_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES` | Суммарный лимит аудио и изображений в одном запросе. |

Уменьшайте эти значения, если прокси доступен широкому кругу клиентов или стоит
перед дорогим путём хранения/загрузки.

## Журналы выполнения и `/logs*`

Журналы выполнения пишутся в stdout и файл журнала:

```dotenv
GPT2GIGA_LOG_LEVEL=INFO
GPT2GIGA_LOG_FILENAME=gpt2giga.log
GPT2GIGA_LOG_MAX_SIZE=10485760
GPT2GIGA_LOG_REDACT_SENSITIVE=True
```

`/logs/{last_n_lines}`, `/logs/stream` и `/logs/html` доступны только в `DEV`.
В `PROD` они не подключаются. Если включена аутентификация по API-ключу, `/logs*` также требует
ключ прокси.

Список разрешённых IP для `/logs*`:

```dotenv
GPT2GIGA_LOGS_IP_ALLOWLIST='["10.0.0.1"]'
```

Не используйте `GPT2GIGA_LOG_LEVEL=DEBUG` в production: отладочный вывод может
содержать операционный контекст, который не должен попадать в общие логи.

## Журналы трафика

Журналы трафика — это структурированные записи запросов и ответов. Они выключены по умолчанию:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=False
GPT2GIGA_TRAFFIC_LOG_SINK=noop
```

Локальный JSONL:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=jsonl
GPT2GIGA_TRAFFIC_LOG_JSONL_PATH=traffic_logs.jsonl
```

Postgres:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINK=postgres
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
```

Postgres плюс зеркало OpenSearch:

```dotenv
GPT2GIGA_TRAFFIC_LOG_ENABLED=True
GPT2GIGA_TRAFFIC_LOG_SINKS=postgres,opensearch
GPT2GIGA_TRAFFIC_LOG_POSTGRES_DSN=postgresql://user:password@localhost:5432/gpt2giga
GPT2GIGA_OPENSEARCH_URL=http://localhost:9200
```

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `GPT2GIGA_TRAFFIC_LOG_SINK` | `noop` | Единый приёмник (sink): `noop`, `jsonl`, `postgres`, `opensearch`. |
| `GPT2GIGA_TRAFFIC_LOG_SINKS` | `[]` | Упорядоченные зеркальные приёмники, например `postgres,opensearch`. Если пусто, используется единый приёмник. |
| `GPT2GIGA_TRAFFIC_LOG_CAPTURE_CONTENT` | `False` | Сохранять тела запросов и ответов после маскирования. |
| `GPT2GIGA_TRAFFIC_LOG_QUEUE_SIZE` | `10000` | Максимум событий в очереди. |
| `GPT2GIGA_TRAFFIC_LOG_BATCH_SIZE` | `500` | Максимум событий в пакете записи в хранилище. |
| `GPT2GIGA_TRAFFIC_LOG_FLUSH_INTERVAL_MS` | `2000` | Интервал сброса по возможности (best-effort). |
| `GPT2GIGA_TRAFFIC_LOG_DROP_ON_BACKPRESSURE` | `True` | Отбрасывать события, а не блокировать путь запроса, когда очередь заполнена. |
| `GPT2GIGA_TRAFFIC_LOG_REDACT_SENSITIVE` | `True` | Маскировать чувствительные поля перед записью в хранилище. |
| `GPT2GIGA_TRAFFIC_LOG_REDACT_EXTRA_KEYS` | `[]` | Дополнительные ключи (без учёта регистра) для маскирования. |
| `GPT2GIGA_TRAFFIC_LOG_RETENTION_DAYS` | `30` | Срок хранения журналов трафика в Postgres. |
| `GPT2GIGA_TRAFFIC_LOG_PURGE_INTERVAL_SECONDS` | `3600` | Интервал очистки по сроку хранения (best-effort). |

Захват содержимого включайте только после решения вопросов шифрования хранилища,
срока хранения, маскирования и доступа к admin-эндпоинтам.

## Вспомогательные переменные Postgres и OpenSearch

Профили Compose используют несколько вспомогательных переменных, которые не являются
непосредственными полями `ProxySettings`, но нужны для сервисов хранилища:

| Переменная | Назначение |
|---|---|
| `GPT2GIGA_POSTGRES_DB` | Имя базы данных для `deploy/postgres.yaml`. |
| `GPT2GIGA_POSTGRES_USER` | Пользователь Postgres для сервиса compose. |
| `GPT2GIGA_POSTGRES_PASSWORD` | Пароль Postgres. Задавайте сильное значение. |
| `GPT2GIGA_POSTGRES_PORT` | Хост-порт для локального Postgres. |
| `GPT2GIGA_OPENSEARCH_PORT` | Хост-порт для локального OpenSearch. |

Настройки выполнения OpenSearch:

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `GPT2GIGA_OPENSEARCH_URL` | `http://localhost:9200` | Эндпоинт OpenSearch. |
| `GPT2GIGA_OPENSEARCH_USERNAME` / `GPT2GIGA_OPENSEARCH_PASSWORD` | empty | Необязательная авторизация. |
| `GPT2GIGA_OPENSEARCH_INDEX` | `gpt2giga-traffic` | Имя индекса или потока данных. |
| `GPT2GIGA_OPENSEARCH_DATA_STREAM` | `True` | Использовать семантику массового создания в потоке данных. |
| `GPT2GIGA_OPENSEARCH_BULK_SIZE` | `500` | Размер массового пакета. |
| `GPT2GIGA_OPENSEARCH_FLUSH_INTERVAL_MS` | `2000` | Интервал сброса по возможности (best-effort). |

## Метрики

Эндпоинт, совместимый с Prometheus, выключен по умолчанию:

```dotenv
GPT2GIGA_METRICS_ENABLED=False
GPT2GIGA_METRICS_PATH=/metrics
```

Когда включён, эндпоинт подключается по пути `GPT2GIGA_METRICS_PATH`. Если включена
аутентификация по API-ключу прокси, эндпоинт метрик тоже требует ключ прокси.

Метки метрик ограничены конечным набором операционных полей и не включают промпт,
содержимое ответа, API-ключи, идентификаторы запросов или трейсов.

## Наблюдаемость / Phoenix

Наблюдаемость через OpenTelemetry/OpenInference выключена по умолчанию:

```dotenv
GPT2GIGA_OBSERVABILITY_ENABLED=False
GPT2GIGA_OBSERVABILITY_BACKEND=phoenix
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=gpt2giga
PHOENIX_API_KEY=
```

Флаги захвата независимы и выключены по умолчанию:

```dotenv
GPT2GIGA_OBSERVABILITY_SAMPLE_RATE=1.0
GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=False
GPT2GIGA_OBSERVABILITY_CAPTURE_MESSAGES=False
GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=False
GPT2GIGA_OBSERVABILITY_CAPTURE_RESPONSES=False
GPT2GIGA_OBSERVABILITY_MAX_CONTENT_LENGTH=8000
GPT2GIGA_OBSERVABILITY_REDACTION_ENABLED=True
```

Содержимое полезной нагрузки попадает в спаны только при явном включении соответствующих
флагов захвата. Для production обычно оставляют захват выключенным или включают
его на короткое время под контролем доступа.

Вспомогательные переменные Compose для Phoenix и mitmproxy:

| Переменная | Назначение |
|---|---|
| `PHOENIX_PORT` | Хост-порт для интерфейса Phoenix. |
| `PHOENIX_GRPC_PORT` | Хост-порт для коллектора OTLP gRPC. |
| `MITMPROXY_PORT` | Хост-порт для слушателя прокси mitmproxy в наложении (overlay) compose. |
| `MITMPROXY_WEB_PORT` | Хост-порт для веб-интерфейса mitmproxy в наложении compose. |

Подробности по отправляемым спанам и именам метрик: [Операции](./operations.md).

## Admin- и debug-эндпоинты

Admin API выключен по умолчанию:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=False
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Когда включён, эндпоинты `/_admin/logs*` используют `GPT2GIGA_ADMIN_API_KEY`, а
не публичный ключ прокси. Для повтора (replay) нужно отдельное включение:

```dotenv
GPT2GIGA_REPLAY_ENABLED=True
```

Эндпоинты отладочной трансляции включаются отдельно:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Эти эндпоинты предназначены для локальной отладки и защищённых admin-сценариев.
Не включайте их публично без средств контроля на обратном прокси и отдельного admin-ключа.

`GPT2GIGA_UI_ENABLED` зарезервирован для будущего встроенного интерфейса. Сейчас не
используйте его как средство контроля безопасности.
