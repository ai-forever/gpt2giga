# Changelog

Все значительные изменения в проекте gpt2giga документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

## [1.0.0rc3] - 2026-04-22
### Добавлено
- **Quality gates для admin frontend**: добавлены проверки синхронизации compiled admin assets, browser smoke tests и frontend unit baseline, чтобы source и packaged UI не расходились
- **Видимость runtime store в admin UI**: в setup/settings flow и в заголовке admin console теперь явно показывается и настраивается активный runtime backend хранения
- **Mypy в dev toolchain**: `mypy` добавлен в dev-зависимости и pre-commit, а типизация усилена в runtime wiring, provider adapters, responses mapping и request normalization
- **Architecture design notes**: добавлен `docs/design-notes.md` с зафиксированными решениями по frameworkless admin UI, committed admin assets и границе feature/provider layers

### Изменено
- **Версия продукта**: версия пакета поднята с `1.0.0rc2` до `1.0.0rc3`
- **Admin console internals**: setup/settings/runtime services и files/batches bindings переразложены на более мелкие модули с более явными границами ответственности
- **Конфигурация и runtime wiring**: выделены proxy settings helpers, ужесточена типизация runtime dependencies и admin settings DTO routed через стабильные facade-слои
- **CI и release automation**: обновлены GitHub workflows, labeler/release-drafter categories и добавлены guardrails против устаревших admin assets при публикации

### Исправлено
- **Совместимость legacy control-plane payloads**: admin settings теперь игнорируют устаревшие сохранённые поля вместо ошибки при загрузке конфигурации
- **Lifecycle responses service**: после рефакторинга восстановлена lazy initialization для responses service
- **Batch/admin artifact statuses**: нормализована проверка статусов batch output и связанных admin artifact flows
- **SQLite logging**: исправлено формирование logger metadata для sqlite runtime backend
- **Dependency hygiene**: обновлён `python-multipart` для закрытия dependabot alert и устранены типовые/runtime-регрессии, всплывшие во время рефакторинга

### Удалено
- **Legacy compatibility shims**: убраны старые logs/responses shim-модули и оставшиеся временные compatibility layers
- **Deprecated image toggle**: удалён больше не используемый флаг `enable_images`

## [1.0.0rc2] - 2026-04-22
### Добавлено
- **Примеры standalone batch validation**: добавлен каталог `examples/batch_validation/` с отдельными runnable-примерами для OpenAI-, Anthropic- и Gemini-форматов через `POST /batches/validate`
- **Ограничиваемые admin previews**: для admin content/output preview добавлена поддержка ограниченного размера ответа, чтобы большие файлы и batch outputs можно было безопасно открывать в UI

### Изменено
- **Версия продукта**: версия пакета поднята с `1.0.0rc1` до `1.0.0rc2`
- **Admin files/batches preview flow**: preview и download для файлов и batch output переведены на canonical normalized endpoints с более согласованным поведением между inventory и detail views
- **Документация batch validation**: уточнены примеры, ограничения и нюансы standalone validation endpoint-а

### Исправлено
- **Batch validation limits**: standalone validation теперь отклоняет payload-ы больше `100` строк вместо попытки прогонять слишком крупные inline batch inputs
- **Path normalization**: исправлена нормализация путей для standalone batch validation routes, включая `POST /batches/validate` и `POST /v1/batches/validate`
- **Upload-less validation**: batch uploads теперь можно валидировать без обязательного staging файла перед проверкой
- **Admin batch creation performance**: ускорены server-side validation и creation flows для files/batches в admin console
- **Batch revalidation flow**: восстановлен повторный запуск validation для batch inputs из admin UI
- **Provider batch routing в admin UI**: исправлен выбор provider-specific batch endpoints при создании и просмотре batch jobs
- **Batch output preview formatting**: admin preview больше не ломает исходный формат batch output и корректно работает с normalized output endpoints
- **Inline examples vs input files**: встроенные batch-примеры больше не затирают явно выбранный input file в admin composer
- **Traffic inspector handoff**: при открытии связанных batch/file preview снова корректно раскрывается traffic inspector для выбранного request-а
- **Playground model selection**: playground снова использует реально настроенную модель GigaChat вместо некорректного fallback-а
- **Secrets masking**: в setup/settings flow усилено маскирование GigaChat secret values, чтобы сохранённые секреты не утекали в UI preview

## [1.0.0rc1] - 2026-04-21
### Добавлено
- **Gemini API surface**: добавлены Gemini-совместимые маршруты и модули `content`, `models`, `files`, `batches`, `request`, `response`, `streaming` и `openapi` в `gpt2giga/api/gemini/`
- **Translate API**: добавлен отдельный слой `gpt2giga/api/translate.py` и примеры `examples/translate/` для преобразования payload-форматов между OpenAI, Anthropic, Gemini и GigaChat
- **Provider-aware routing**: добавлена конфигурация `enabled_providers` и возможность поднимать только нужные provider groups с OpenAPI-схемой, зависящей от реально включённых поверхностей
- **Новый app-layer**: добавлены `gpt2giga/app/factory.py`, `lifespan.py`, `run.py`, `wiring.py`, `dependencies.py` и `cli.py` как новая точка сборки и wiring FastAPI-приложения
- **Control plane persistence**: добавлена подсистема `gpt2giga/core/config/_control_plane/` с bootstrap, crypto, paths, payloads, revisions и status-модулями
- **Runtime backends**: добавлен отдельный runtime backend слой в `gpt2giga/app/_runtime_backends/` с memory/sqlite реализациями и registry/contracts
- **Observability and telemetry**: добавлены подсистемы `gpt2giga/app/_observability/` и `gpt2giga/app/_telemetry/` с sink-ами built-in, OTLP, Phoenix, Prometheus и Langfuse
- **Prometheus metrics**: добавлены `/metrics` и `/admin/api/metrics` эндпоинты и связанная runtime-телеметрия
- **Admin runtime feeds**: добавлены recent requests/errors feed endpoints для операторской диагностики из admin console
- **Scoped API keys**: добавлена поддержка scoped API keys с ограничением по provider/endpoints
- **Governance limits**: добавлены policy/rate-limit ограничения для API ключей и route scopes
- **Admin UI как optional package**: добавлен `gpt2giga-ui` как optional dependency `gpt2giga[ui]` и установлен runtime source of truth для shipped UI assets
- **Новый admin frontend**: добавлен TypeScript frontend в `gpt2giga/frontend/admin/` и packaged runtime assets в `packages/gpt2giga-ui/src/gpt2giga_ui/`
- **Новый admin shell**: добавлены HTML shell, packaged static assets, favicon и page-based navigation для `/admin`
- **Admin pages**: добавлены и разложены по отдельным поверхностям страницы overview, setup, settings, providers, system, traffic, logs, playground, keys, files and batches
- **Files and batches inventory**: добавлены normalized admin uploads, batch creation flows, inventory-first layout и унифицированные content endpoints для файлов и батчей
- **Batch validation foundation**: добавлены primitives и provider-level validators для batch input validation и улучшена интеграция validation в batch creation flow
- **Gemini batch flows**: добавлены inline Gemini batch composer и Gemini batch examples
- **Примеры Gemini**: добавлен новый каталог `examples/gemini/` с content, embeddings, files, batches и count tokens сценариями
- **Примеры agents**: добавлен каталог `examples/agents/` для agent-oriented сценариев
- **Документационный hub**: добавлен `docs/README.md` как навигационный центр проекта
- **Новая базовая документация**: добавлены `docs/configuration.md`, `docs/operator-guide.md`, `docs/architecture.md`, `docs/api-compatibility.md` и `docs/how-to-add-provider.md`
- **Deploy documentation**: добавлен `deploy/README.md` и compose-сценарии для runtime backends (`postgres`, `redis`, `s3`) и observability-стеков
- **Новые тестовые слои**: добавлены крупные блоки unit, integration, smoke и compat тестов под новую архитектуру, включая golden fixtures для provider payload compatibility

### Изменено
- **Версия продукта**: версия пакета поднята с `0.1.6a1` до `1.0.0rc1`
- **Архитектура проекта**: кодовая база переразложена из плоской структуры в слои `api/`, `app/`, `core/`, `features/`, `providers/`
- **OpenAI surface**: OpenAI-compatible endpoints вынесены в отдельный пакет `gpt2giga/api/openai/` с явным разделением `chat`, `responses`, `embeddings`, `files`, `batches`, `models` и `streaming`
- **Anthropic surface**: Anthropic-compatible handlers и маппинг вынесены в `gpt2giga/api/anthropic/` с отдельными `messages`, `batches`, `request_adapter`, `response`, `streaming` и `openapi`
- **Provider mapping**: provider-specific mapping и orchestration укреплены в `gpt2giga/providers/` и `gpt2giga/features/`, особенно для `providers/gigachat/responses/`
- **OpenAPI tags**: теги OpenAPI теперь группируются по `provider + capability`, а не только по capability
- **Admin console**: админка перестроена из вспомогательного UI в полноценную operator-facing control plane console
- **Playground UX**: playground стал центральной рабочей поверхностью, улучшены streaming diagnostics, parsed output errors и preset flows
- **Traffic и logs UX**: traffic и logs получили отдельные tool/data-first layouts и handoff по request id
- **Files and batches UX**: страницы files/batches переведены на normalized inventory model и более явный workflow для staged artifacts
- **Control plane bootstrap**: первичный setup для PROD теперь идёт через bootstrap/claim flow и может блокировать provider routes до завершения настройки
- **CORS policy в PROD**: PROD режим теперь автоматически ужесточает wildcard CORS конфигурацию
- **Admin/docs exposure policy**: поведение `/docs`, `/redoc`, `/openapi.json`, `/logs*` и admin routes стало строже и сильнее зависит от режима и auth
- **Структура документации**: подробные инструкции вынесены из корневого `README.md` в `docs/`
- **Интеграции**: каталог `integrations/` перенесён в `docs/integrations/`
- **Примеры**: examples переразложены по capability/provider каталогам вместо более плоской структуры
- **Deploy layout**: `compose/` перенесён в `deploy/compose/`, а `traefik/` в `deploy/traefik/`
- **Packaging**: обновлены зависимости, включая `starlette>=1.0.0,<2`, `fastapi>=0.135.3,<1`, `google-genai`, `cryptography`, `opentelemetry-proto`
- **CI/CD**: workflows адаптированы под frontend build, новый deploy layout и docker publish guardrails
- **Тестовая структура**: тесты переразложены по `unit/`, `integration/`, `smoke/`, `compat/`

### Исправлено
- **Admin auth/session flows**: усилена обработка bootstrap, session handling, API-key handoff и safety flows в admin console
- **Admin navigation**: исправлены проблемы с page-local hash navigation, direct-entry и handoff URL внутри `/admin`
- **Playground errors**: исправлено surfacing stream failures и backend/playground errors в response workspace
- **Files and batches state sync**: исправлены лишние refetch/delete сценарии и обновление inventory после мутаций
- **Gemini batch behavior**: исправлены Gemini file input, fallback model, completed statuses и inline batch defaults
- **Responses/GigaChat mode split**: исправлено разделение режимов GigaChat API для responses/chat compatibility
- **Admin readiness/auth alignment**: приведены в соответствие runtime auth policy и готовность admin console
- **Observability integrations**: исправлены сценарии Phoenix telemetry и связанная конфигурация observability sink-ов
- **OpenAI/Anthropic/Gemini compatibility edges**: закрыт ряд ошибок request mapping, streaming и transport normalization по новым protocol surfaces
- **Тестовый baseline**: стабилизированы integration assertions и добавлен отдельный smoke для Starlette 1.x

### Удалено
- **Старый app entrypoint**: удалён монолитный `gpt2giga/api_server.py` в пользу app factory
- **Плоские legacy-модули**: убраны или отодвинуты на второй план старые `app_state.py`, `auth.py`, `cli.py` и часть прежних flat imports
- **Старый layout deploy/docs**: старое расположение `compose/`, `traefik/` и `integrations/` заменено новым `deploy/` и `docs/` layout
- **Устаревшие тестовые файлы**: удалён заметный объём прежних плоских тестов после переноса на новую layered test-структуру

## [0.1.6a1] - 2026-03-24
### Добавлено
- **OpenAI Files API**: добавлены эндпоинты `/files`, `/files/{file_id}` и `/files/{file_id}/content`, а также пример `examples/openai/files.py`
- **OpenAI Batches API**: добавлены эндпоинты `/batches` и `/batches/{batch_id}` вместе с примером `examples/openai/batches.py`
- **Anthropic Message Batches API**: добавлены эндпоинты `/v1/messages/batches`, `/v1/messages/batches/{message_batch_id}` и `/v1/messages/batches/{message_batch_id}/results`, а также пример `examples/anthropic/message_batches.py`
- **Новые интеграции**: добавлены инструкции для Qwen Code и Xcode
- **CI и автоматизация**: добавлены `actionlint`, `CodeQL`, `dependency-review`, `docker-smoke`, `nightly-smoke`, `pr-labeler`, `release-drafter`, `stale-issues` и Dependabot-конфигурация

### Изменено
- **Примеры**: OpenAI-примеры перенесены в `examples/openai/`, README и AGENTS выровнены под новую структуру
- **OpenAPI**: схемы OpenAI и Anthropic вынесены в `gpt2giga/openapi_specs/`
- **LiteLLM router**: обработчик `/model/info` вынесен в отдельный пакет `gpt2giga/routers/litellm/`
- **Docker Compose**: структура compose-файлов выровнена под каталог `compose/` (`base.yaml`, `observability.yaml`, `nginx.yaml`, `observe-multiple.yaml`, `traefik.yaml`)
- **GitHub templates**: добавлены русскоязычные шаблоны issue и pull request

### Исправлено
- **Path normalization**: исправлена нормализация путей для `/v1`, `files`, `batches`, `messages` и `model/info`
- **OpenAI payload mapping**: `extra_body` теперь корректно маппится в `additional_fields`
- **Batches**: исправлены `completion_window` и обработка дат для Python 3.10
- **Examples**: обновлены runnable-примеры OpenAI и Anthropic после реорганизации каталогов

## [0.1.5] - 2026-03-10
### Добавлено
- **Model info endpoint**: Добавлен `GET /model/info` для совместимости с автодополнением в Kilo Code и клиентами в стиле LiteLLM

### Изменено
- **GitHub Actions**: Workflow `ci.yaml`, `docker_image.yaml` и `publish-ghcr.yml` теперь запускаются только при изменениях релевантных файлов

### Исправлено
- **CI для Pull Request**: Тестовый workflow больше не запускается для draft PR

## [0.1.4.post1] - 2026-02-27
### Добавлено
- **Интеграция Cursor**: Добавлен `integrations/cursor/README.md` — инструкция по использованию GigaChat в Cursor через кастомную модель
- **Интеграция Codex**: Добавлен `integrations/codex/README.md` — настройка OpenAI Codex через `config.toml` с кастомным провайдером gpt2giga
- **Интеграция Claude Code**: Добавлен `integrations/claude-code/README.md` — настройка Claude Code через `ANTHROPIC_BASE_URL`
- **Документация AGENTS.md**: Обновлены все `AGENTS.md` файлы для соответствия актуальной структуре кодовой базы

### Изменено
- **Асинхронность**: Блокирующие операции ввода-вывода в обработчиках маршрутов перенесены в рабочие потоки через `anyio.to_thread.run_sync`:
  - `logs_router.py` — чтение файлов логов и HTML-шаблона
  - `api_router.py` — инициализация `tiktoken.encoding_for_model()`

## [0.1.4] - 2026-02-26

### Добавлено
- **Nginx**: Добавлен конфиг `gpt2giga.conf` и README для развёртывания nginx `integrations/nginx/`
- **Docker Compose**: Обновлён compose (#77) — mitmproxy в `compose/observability.yaml`, пароль для mitmproxy
- **Роутер логов**: Вынесен отдельный `logs_router.py`, разделение system router на два

### Изменено
- Обновлён `.env.example`
- Обновлён README для nginx

### Исправлено
- **Giga-auth**: Исправлено поведение giga-auth (#74)

## [0.1.3.post1] - 2026-02-20

### Добавлено
- **Traefik**: Добавлена интеграция Traefik
- **MITMProxy**: Добавлен mitmproxy в `compose/observability.yaml`
- **Reasoning toggle**: Добавлена переменная окружения `GPT2GIGA_ENABLE_REASONING`

### Изменено
- **Docker Compose профили**: Профиль `dev` установлен как профиль по умолчанию в `compose/base.yaml`

## [0.1.3] - 2026-02-17

### Добавлено
- **Режим DEV/PROD**: Добавлена поддержка режимов разработки и продакшена
- **Настраиваемый CORS**: Добавлена возможность конфигурации CORS через переменные окружения
- **Graceful shutdown**: Добавлено корректное завершение работы сервера
- **Gitleaks**: Добавлен gitleaks в pre-commit для проверки секретов
- **OpenAPI для count_tokens**: Добавлена OpenAPI документация для эндпоинта count_tokens
- **Профили в Docker**: Добавлены профили DEV и PROD в `compose/base.yaml`

### Изменено
- **Рефакторинг структуры**: Разделение больших файлов на модули:
  - `gpt2giga/common/` — общие утилиты (exceptions, json_schema, streaming, tools)
  - `gpt2giga/models/` — модели конфигурации и безопасности
  - `gpt2giga/protocol/attachment/` — обработка вложений
  - `gpt2giga/protocol/request/` — трансформация запросов
  - `gpt2giga/protocol/response/` — обработка ответов
- **Улучшено логирование**: Политика редактирования логов, отключено логирование полных payload'ов

### Исправлено
- **Безопасность CLI**: Исправлены проблемы с аргументами командной строки
- **Привязка портов**: Исправлены проблемы с привязкой портов и редиректами
- **SSRF защита**: Усилена защита от SSRF в обработке вложений
- **Аутентификация**: Переход на `secrets.compare_digest` для сравнения ключей
- **Лимиты вложений**: Добавлены лимиты для вложений
- **Название внутренних функций**: Исправлена ошибка с внутренней функцией `web_search`, которая могла ломать function_call

## [0.1.2.post1] - 2026-02-13

### Добавлено
- **OpenAPI документация**: Добавлена полная OpenAPI документация для всех эндпоинтов
- **Count tokens для Anthropic**: Добавлен эндпоинт `/v1/messages/count_tokens` для подсчёта токенов в формате Anthropic
- **Пример count_tokens**: Добавлен пример `examples/anthropic/count_tokens.py`
- **Версия при инициализации**: Отображение версии при запуске сервера

### Изменено
- **Path normalizer**: Улучшен нормализатор путей для responses и messages

### Исправлено
- **Ошибка 405**: Исправлена ошибка 405 при некоторых запросах
- **Безопасное чтение запросов**: Улучшена обработка чтения тела запроса

## [0.1.2] - 2026-02-11

### Добавлено
- **Anthropic Messages API**: Новый эндпоинт `POST /v1/messages` для совместимости с Anthropic Messages API
  - Поддержка стриминга (SSE) в формате Anthropic (`message_start`, `content_block_delta`, `message_stop` и др.)
  - Конвертация сообщений Anthropic (text, image, tool_use, tool_result) в формат GigaChat
  - Конвертация инструментов Anthropic (`input_schema`) в формат GigaChat functions
  - Поддержка `tool_choice` (auto, tool, none)
  - Поддержка системного промпта (`system`) в виде строки или массива контент-блоков
  - Маппинг `stop_reason` (end_turn, tool_use, max_tokens)
- **Extended Thinking (Reasoning)**: Поддержка параметра `thinking` из Anthropic API
  - Конвертация `thinking.budget_tokens` в `reasoning_effort` для GigaChat (high/medium/low)
  - Конвертация `reasoning_content` из ответа GigaChat в блок `thinking` формата Anthropic
  - Поддержка reasoning в стриминге (`thinking_delta`)
- **Примеры Anthropic API**: Добавлены примеры в `examples/anthropic/`:
  - `messages.py` — базовый запрос
  - `messages_stream.py` — стриминг
  - `system_prompt.py` — системный промпт
  - `multi_turn.py` — многоходовый диалог
  - `function_calling.py` — вызов функций (tool use)
  - `image_url.py` — изображение по URL
  - `base64_image.py` — изображение в base64
  - `reasoning.py` — extended thinking

## [0.1.1] - 2026-02-06

### Добавлено
- **Шаблоны GitHub**: Добавлены шаблоны для Pull Request и Issue (bug report) для улучшения процесса (#58)
- **Разрешение $ref в схемах**: Добавлена функция `_resolve_schema_refs` для обработки JSON Schema ссылок (#57)
- **Обработка пропущенных properties**: Реализована корректная обработка схем без поля `properties`

### Изменено
- **Рефакторинг request_mapper.py**: Логика разделена на отдельные модули для лучшей поддерживаемости:
  - `content_utils.py` — утилиты для работы с контентом
  - `message_utils.py` — утилиты для работы с сообщениями
  - `schema_utils.py` — утилиты для работы со схемами
- **Расширено тестовое покрытие**: Добавлены тесты для стриминга и конвертации инструментов

### Исправлено
- **Стриминг Responses API**: Исправлена потоковая передача ответов в Responses API (#60)
- **Function calling в стриминге**: Исправлена обработка вызовов функций при потоковой передаче в Responses API

## [0.1.0b2] - 2025-01-21

### Добавлено
- Поддержка Python 3.14
- Обновлена библиотека tiktoken

### Изменено
- Рефакторинг тестов
- Обновлены зависимости библиотек

### Исправлено
- Создание нового экземпляра GigaChat при pass_token=True

## [0.1.0b] - 2025-12-26

### Добавлено
- **Pydantic v2**: Полный переход проекта на Pydantic v2.
- **Управление зависимостями**: Миграция проекта и CI на использование `uv`.
- **Конфигурация**: Добавлена библиотека `pydantic-settings` для удобного управления настройками через CLI и переменные окружения.
- **Обработка ошибок**: Реализован маппинг ошибок для корректной обработки исключений.
- **Структурированный вывод**: Добавлена поддержка структурированного вывода (structured output) в виде функции.
- **Интеграция GigaChat**: Добавлена интеграция с пакетом `gigachat`.
- **Тесты**: Значительно расширено покрытие тестами.

### Изменено
- **Рефакторинг протокола**: Логика `protocol.py` разделена на модули `request_mapper.py`, `response_mapper.py` и `attachments.py`.
- **Разделение логики**: Полностью разделена логика `chat_completion` и `responses`.
- **Примеры**: Обновлены порты в примерах использования.

### Исправлено
- **Стриминг**: Исправлены проблемы с потоковой передачей ответов.
- **API ответов**: Устранены ошибки в API ответов.
- **CI/CD**: Исправлена ошибка SSL в GitHub Actions.
- **Безопасность**: Устранены уязвимости в зависимостях.

## [0.0.15.post1] - 2025-12-22

### Добавлено
- Авторизация по API-ключу с поддержкой различных способов передачи (query параметр, заголовок x-api-key, Bearer token)
- Логирование с использованием библиотеки loguru
- Системные эндпоинты для мониторинга (/health, /ping, /logs)
- HTML-страница для просмотра логов в реальном времени
- Поддержка парсинга файлов
- Workflow для публикации в GHCR
- Workflow для публикации в PyPI

### Изменено
- Миграция на FastAPI
- Переход на loguru для логирования

### Исправлено
- Исправлена обработка исключений при декодировании байтов
- Исправлена ошибка валидации для роли developer
- Исправлены версии Python в workflows

## [0.0.14] - 2025-10-28

### Добавлено
- Поддержка mTLS аутентификации
- Docker Compose конфигурация

### Изменено
- Обновлена документация README

## [0.0.13] - 2025-09-19

### Добавлено
- Базовая функциональность прокси-сервера
- Поддержка потоковой генерации (streaming)
- Поддержка эмбеддингов
- Поддержка функций (function calling)
- Поддержка структурированного вывода

---

[0.1.6a1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.5...HEAD
[0.1.5]: https://github.com/ai-forever/gpt2giga/compare/v0.1.4.post1...v0.1.5
[0.1.4.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.4...v0.1.4.post1
[0.1.4]: https://github.com/ai-forever/gpt2giga/compare/v0.1.3.post1...v0.1.4
[0.1.3.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.3...v0.1.3.post1
[0.1.3]: https://github.com/ai-forever/gpt2giga/compare/v0.1.2.post1...v0.1.3
[0.1.2.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.2...v0.1.2.post1
[0.1.2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0...v0.1.1
[0.1.0b2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0b...v0.1.0b2
[0.1.0b]: https://github.com/ai-forever/gpt2giga/compare/v0.0.15.post1...v0.1.0b
[0.0.15.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.0.14...v0.0.15.post1
[0.0.14]: https://github.com/ai-forever/gpt2giga/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/ai-forever/gpt2giga/releases/tag/v0.0.13
