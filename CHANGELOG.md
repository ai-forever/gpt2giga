# Changelog

Все значительные изменения в проекте gpt2giga документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

## [0.1.6] - 2026-05-20
### Добавлено
- **OpenAI Files API**: добавлены router-модули для `/files`, `/files/{file_id}` и `/files/{file_id}/content`, а также пример `examples/openai/files.py`; маршруты временно не монтируются в публичный OpenAI router до следующего релиза GigaChat SDK
- **OpenAI Batches API**: добавлены router-модули для `/batches` и `/batches/{batch_id}` вместе с примером `examples/openai/batches.py`; маршруты временно не монтируются в публичный OpenAI router до следующего релиза GigaChat SDK
- **Anthropic Message Batches API**: добавлены router-модули для `/v1/messages/batches`, `/v1/messages/batches/{message_batch_id}` и `/v1/messages/batches/{message_batch_id}/results`, а также пример `examples/anthropic/message_batches.py`; маршруты временно не монтируются в публичный Anthropic router до следующего релиза GigaChat SDK
- **Новые интеграции**: добавлены инструкции для Qwen Code и Xcode
- **CI и автоматизация**: добавлены `actionlint`, `CodeQL`, `dependency-review`, `docker-smoke`, `nightly-smoke`, `pr-labeler`, `release-drafter`, `stale-issues` и Dependabot-конфигурация
- **Reasoning / think tags**: добавлено извлечение `<think>...</think>` в reasoning/thinking content для OpenAI Chat Completions, OpenAI Responses и Anthropic Messages, включая streaming
- **Structured output mode**: добавлен режим `GPT2GIGA_STRUCTURED_OUTPUT_MODE` / `--proxy.structured-output-mode` с вариантами `function_call` и `native`; нативный режим прокидывает JSON Schema в `response_format` GigaChat SDK 0.2.1+
- **Anthropic structured output**: добавлена поддержка `output_config.format` и legacy `output_format` с `json_schema` для Anthropic Messages, streaming и Message Batches, включая новые runnable-примеры
- **Embeddings dimensions**: добавлена проверка параметра `dimensions` для известных embedding-моделей

### Изменено
- **Примеры**: OpenAI-примеры перенесены в `examples/openai/`, README и AGENTS выровнены под новую структуру
- **Примеры моделей**: runnable-примеры обновлены на `GigaChat-2-Max`, а пример embeddings теперь показывает `dimensions`, `float` и `base64`
- **OpenAPI**: схемы OpenAI и Anthropic вынесены в `gpt2giga/openapi_specs/`
- **LiteLLM router**: обработчик `/model/info` вынесен в отдельный пакет `gpt2giga/routers/litellm/`
- **Docker Compose**: структура compose-файлов выровнена под каталог `compose/` (`base.yaml`, `observability.yaml`, `nginx.yaml`, `observe-multiple.yaml`, `traefik.yaml`)
- **GitHub templates**: добавлены русскоязычные шаблоны issue и pull request
- **Model forwarding**: `GPT2GIGA_PASS_MODEL` теперь по умолчанию `True`; модель из запроса прокидывается в GigaChat для чата, Responses API и эмбеддингов, а `GPT2GIGA_EMBEDDINGS` используется как fallback для эмбеддингов
- **Зависимости**: обновлены `gigachat`, `python-dotenv`, `aiohttp`, `pillow`, `pytest` и `uv.lock` после Dependabot/security bump

### Исправлено
- **Path normalization**: исправлена нормализация путей для `/v1`, повторного `/v1/v1`, `files`, `batches`, `messages` и `model/info`
- **OpenAI payload mapping**: `extra_body` теперь корректно маппится в `additional_fields`
- **Batches**: исправлены `completion_window` и обработка дат для Python 3.10
- **Examples**: обновлены runnable-примеры OpenAI и Anthropic после реорганизации каталогов
- **Embeddings**: `encoding_format="base64"` теперь возвращает OpenAI-совместимые base64 float32 embeddings для прямого `/embeddings` и embeddings batches, а ответы нормализуются в OpenAI-совместимый envelope без GigaChat-специфичных полей
- **Embeddings input validation**: OpenAI-совместимая валидация теперь отклоняет пустой или смешанный `input`, неподдерживаемый `encoding_format`, некорректный `model` и token id inputs без модели, которую можно декодировать через `tiktoken`
- **Embeddings model routing**: `pass_model` теперь применяется к `/embeddings` и batch-запросам на `/v1/embeddings`
- **Model/top_p mapping**: исправлена передача `model` по умолчанию и предотвращена неявная установка `top_p=0`, когда клиент не передавал `temperature`
- **Unsupported Files/Batches routes**: временно отключены неподдерживаемые OpenAI Files/Batches и Anthropic Message Batches маршруты в default routers; они больше не попадают в OpenAPI-схему до появления поддержки в GigaChat SDK

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

[0.1.6]: https://github.com/ai-forever/gpt2giga/compare/v0.1.5...v0.1.6
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
