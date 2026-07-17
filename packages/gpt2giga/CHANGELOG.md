# Changelog

Все значительные изменения в проекте gpt2giga документированы в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

## [0.2.4a2] - 2026-07-17

### Добавлено
- **LAR-1 семантическая маршрутизация**: опциональный классификатор metadata.lar1 для POST /v1/chat/completions. Прокси автоматически выбирает tier GigaChat (gigachat-fast, gigachat-pro, local) на основе confidence, evidence и time сигналов от агента. Отключается через LAR1_ENABLED=false. Включает lar1_router.py, lar1.py модель, интеграцию в openai/chat_completions.py и lifecycle.

## [0.2.4a1] - 2026-07-16

### Исправлено
- **История OpenAI Responses**: текстовые части `output_text` из предыдущих turns теперь преобразуются вместе с `input_text`, поэтому Codex app-server не теряет продолжение разговора и контекст subagents.
- **CPU-нагрузка request context**: тяжёлый PBKDF2 для корреляционных отпечатков IP и API-ключа заменён на быстрый keyed HMAC-SHA256, чтобы middleware не блокировал event loop двумя вычислениями по 100 000 итераций на каждый запрос.
- **Скрытая сериализация DEBUG payload**: подготовка и маскирование payload теперь полностью пропускаются при стандартном уровне `INFO`, включая response и streaming paths.
- **Ресурсы `PASS_TOKEN`**: credential-specific клиенты GigaChat переиспользуются ограниченным LRU-пулом, остаются активными до завершения stream и закрываются при вытеснении или остановке.
- **Неблокирующие sinks**: JSONL traffic log пакетируется через фоновую очередь, а экспорт observability вынесен из request path в ограниченную очередь с управляемым backpressure.
- **Накладные расходы middleware**: request-id, validation, path normalization и pass-token middleware переведены с `BaseHTTPMiddleware` на чистый ASGI; три вложенных response-итератора заменены одним перехватчиком ASGI `send`.

## [0.2.3a2] - 2026-07-14

### Исправлено
- **Закрепление модели Claude Code**: доверенные запросы Claude CLI из Harness теперь сохраняют выбранную upstream-модель GigaChat для Anthropic Messages и `count_tokens` в режимах GigaChat v1/v2 и при учёте лимитов конкурентности, не меняя модель в публичном Anthropic-ответе.

## [0.2.3a1] - 2026-07-13

### Добавлено
- **Codex ImageGen handoff**: OpenAI Responses теперь распознаёт объявленный клиентом плоский или namespaced ImageGen tool и возвращает результат GigaChat `image_generate` как совместимый `function_call` с исходным именем инструмента в streaming и non-streaming ответах.
- **Harness-aware Gemini model pinning**: доверенные запросы Gemini CLI из Harness могут закрепить настроенную upstream-модель для `generateContent`, `streamGenerateContent` и `countTokens`, когда передача клиентской модели отключена.

### Изменено
- **Независимый gateway-пакет**: `gpt2giga` перенесён в `packages/gpt2giga/` как самостоятельный member `uv` workspace; дистрибутив сохраняет namespace `gpt2giga` и одноимённую CLI-команду, но больше не включает Harness namespace, команды и package data.
- **Раздельные build/release-контракты**: CI собирает и проверяет gateway независимо от `gpt2giga-harness`, а публикация gateway привязана к тегам вида `v<version>`.
- **Документация установки**: README, quickstart и architecture docs разделяют установку compatibility gateway и локального control plane.

### Исправлено
- **Gemini sources**: source markers и `inline_data.sources` теперь отображаются в Gemini-compatible ответах как видимый список источников.
- **Docker workspace layout**: Docker-сборка и deploy-пути обновлены под package layout, чтобы образ содержал установленный gateway после переноса в workspace.
