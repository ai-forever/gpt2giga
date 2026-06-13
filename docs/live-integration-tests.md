# Live-интеграционные тесты GigaChat

`tests/live/` содержит opt-in pytest-тесты, которые поднимают реальный gateway
stack и вызывают настоящий upstream GigaChat через SDK. Обычный запуск
`pytest tests/` остаётся герметичным: эти тесты пропускаются, пока их явно не
включили.

Live-набор покрывает:

- OpenAI-compatible models, Chat Completions, streaming Chat Completions,
  Responses и Embeddings;
- Anthropic-compatible Messages и streaming Messages;
- Gemini-compatible GenerateContent, streamGenerateContent, countTokens и
  embedContent;
- header-профили клиентов в стиле Codex CLI, Claude Code и Gemini CLI.

## Настройка Секретов

Создайте локальный, игнорируемый git файл `.env.live`:

```dotenv
GPT2GIGA_RUN_LIVE_TESTS=1

# Предпочтительный вариант для user/password auth.
GIGACHAT_USER=<your-gigachat-username>
GIGACHAT_PASSWORD=<your-gigachat-password>
GIGACHAT_BASE_URL=<your-gigachat-base-url>

GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True

# Опциональные override-настройки тестов.
GPT2GIGA_LIVE_MODEL=GigaChat-2-Max
GPT2GIGA_LIVE_EMBEDDINGS_MODEL=EmbeddingsGigaR
GPT2GIGA_LIVE_BACKEND_MODES=v1
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

Чтобы проверить оба backend contract через versioned gateway prefixes:

```dotenv
GPT2GIGA_LIVE_BACKEND_MODES=v1,v2
```

Не коммитьте live credentials. Используйте `.env.live`, переменные окружения из
shell или secret store вашей CI-системы.
