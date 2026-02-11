# Changelog

Все значительные изменения в проекте gpt2giga документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

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

## [0.0.15.post1] - 2025-01-21

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

## [0.0.14] - 2024-12

### Добавлено
- Поддержка mTLS аутентификации
- Docker Compose конфигурация

### Изменено
- Обновлена документация README

## [0.0.13] - 2024-11

### Добавлено
- Базовая функциональность прокси-сервера
- Поддержка потоковой генерации (streaming)
- Поддержка эмбеддингов
- Поддержка функций (function calling)
- Поддержка структурированного вывода

---

[0.1.2b1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.1...v0.1.2b1
[0.1.1]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0...v0.1.1
[0.1.0b2]: https://github.com/ai-forever/gpt2giga/compare/v0.1.0b...v0.1.0b2
[0.1.0b]: https://github.com/ai-forever/gpt2giga/compare/v0.0.15.post1...v0.1.0b
[0.0.15.post1]: https://github.com/ai-forever/gpt2giga/compare/v0.0.14...v0.0.15.post1
[0.0.14]: https://github.com/ai-forever/gpt2giga/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/ai-forever/gpt2giga/releases/tag/v0.0.13
