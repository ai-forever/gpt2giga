# Live-тесты интеграции с GigaChat

`tests/live/` содержит включаемые по запросу pytest-тесты, которые поднимают реальный
стек шлюза и вызывают настоящий вышестоящий GigaChat через SDK. Обычный запуск
`pytest tests/` остаётся герметичным: эти тесты пропускаются, пока их явно не
включили.

Набор live-тестов покрывает:

- получение списка/одной модели, Chat Completions, потоковый Chat
  Completions, Responses и Embeddings (совместимые с OpenAI);
- Messages, потоковый Messages и count_tokens (совместимые с Anthropic);
- получение списка/одной модели, GenerateContent, streamGenerateContent,
  countTokens и embedContent (совместимые с Gemini);
- model/info (совместимый с LiteLLM);
- профили заголовков клиентов в стиле Codex CLI, Claude Code и Gemini CLI.

## Настройка секретов

Создайте локальный, игнорируемый git файл `.env.live`:

```dotenv
GPT2GIGA_RUN_LIVE_TESTS=1

# Предпочтительный вариант для авторизации по логину и паролю.
GIGACHAT_USER=<your-gigachat-username>
GIGACHAT_PASSWORD=<your-gigachat-password>
GIGACHAT_BASE_URL=<your-gigachat-base-url>

GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True

# Необязательные переопределения настроек тестов.
GPT2GIGA_LIVE_MODEL=GigaChat-2-Max
GPT2GIGA_LIVE_EMBEDDINGS_MODEL=EmbeddingsGigaR
GPT2GIGA_LIVE_BACKEND_MODES=v1,v2
```

Также поддерживаются альтернативные варианты авторизации:

```dotenv
GIGACHAT_CREDENTIALS=<your-oauth-credentials>
# или
GIGACHAT_ACCESS_TOKEN=<your-access-token>
```

По умолчанию тесты загружают `.env.live`. Чтобы использовать другой файл:

```sh
GPT2GIGA_LIVE_ENV_FILE=/path/to/live.env uv run pytest tests/live -m live_gigachat
```

## Запуск

```sh
uv run pytest tests/live -m live_gigachat
```

По умолчанию набор live-тестов проверяет оба контракта бэкенда через версионированные
префиксы шлюза для OpenAI, Anthropic и Gemini:

```dotenv
GPT2GIGA_LIVE_BACKEND_MODES=v1,v2
```

Для более короткого smoke-прогона можно оставить только один контракт:

```dotenv
GPT2GIGA_LIVE_BACKEND_MODES=v1
```

Не коммитьте live-учётные данные. Используйте `.env.live`, переменные окружения из
shell или хранилище секретов вашей CI-системы.
