# Интеграция Gemini CLI с GigaChat

> **Проверено:** 17 июня 2026 — официальный `@google/gemini-cli`, `GeminiCLI-tui/0.46.0/`
> **Проверенные GigaChat paths:** `/v1/chat/completions`, `/v2/chat/completions`

[Gemini CLI](https://github.com/google-gemini/gemini-cli) — CLI-агент от
Google. Через `gpt2giga` его можно подключить к GigaChat, направив Gemini API
requests в локальный proxy.

`gpt2giga` принимает Gemini-compatible `generateContent`,
`streamGenerateContent`, `countTokens`, `embedContent`, `batchEmbedContents` и
model discovery routes, переводит их в вызовы GigaChat и возвращает ответ в
Gemini-совместимом формате.

Это Gemini-compatible integration, а не full Gemini API parity. Public routes
доступны в root, `/v1`, `/v2`, `/v1beta`, `/v1/v1beta` и `/v2/v1beta`.
`/v1` и `/v1/v1beta` всегда выбирают GigaChat v1 contract, `/v2` и
`/v2/v1beta` всегда выбирают GigaChat v2 contract. Root paths без outer
`/v1` или `/v2`, включая `/v1beta`, используют
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.
Gemini Files API и `batchGenerateContent` подготовлены в коде, но не
смонтированы публично; built-in Gemini tools, safety enforcement,
`cachedContent`, full multimodal/file-backed flows и non-text embeddings content
остаются вне текущего release scope. `countTokens` использует GigaChat token
counting по извлеченному тексту, поэтому это compatibility approximation.

## Предварительные требования

- Установленный Node.js и доступ к `npx` или установленный `gemini` CLI.
- Запущенный прокси-сервер `gpt2giga`.
- Учётные данные GigaChat (`GIGACHAT_CREDENTIALS`).

---

## 1. Запуск gpt2giga

Настройте переменные окружения в файле `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

Если хотите защитить proxy API-ключом, добавьте:

```ini
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Запустите прокси-сервер:

```shell
gpt2giga
```

По умолчанию сервер будет доступен по адресу `http://localhost:8090`.

---

## 2. Настройка Gemini CLI

Для локального `gpt2giga` задайте Gemini API base URL и ключ:

```shell
export GOOGLE_GEMINI_BASE_URL="http://localhost:8090"
export GEMINI_API_KEY="0"
export GEMINI_MODEL="GigaChat-2-Max"
```

- `GOOGLE_GEMINI_BASE_URL` — адрес `gpt2giga`. Gemini CLI разрешает HTTP для
  `localhost`, `127.0.0.1` и `[::1]`; для удалённых серверов нужен HTTPS.
  Root URL без `/v1` или `/v2` следует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`;
  укажите `/v1` или `/v2`, если нужен явный GigaChat backend contract.
- `GEMINI_API_KEY` — любое непустое значение, если авторизация на `gpt2giga`
  отключена. Если включена `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, укажите здесь
  значение `GPT2GIGA_API_KEY`.
- `GEMINI_MODEL` — модель по умолчанию для Gemini CLI.

### Запуск через npx

```shell
npx @google/gemini-cli -m GigaChat-2-Max -p "Что ты умеешь?"
```

### Запуск установленного CLI

```shell
gemini -m GigaChat-2-Max -p "Что ты умеешь?"
```

Gemini CLI будет отправлять запросы через `gpt2giga` в GigaChat API.

---

## 3. Headless mode

Gemini CLI переходит в headless mode при запуске без TTY или с флагом
`-p` / `--prompt`. Это удобно для скриптов и CI:

```shell
export GOOGLE_GEMINI_BASE_URL="http://localhost:8090"
export GEMINI_API_KEY="0"
export GEMINI_MODEL="GigaChat-2-Max"
export GEMINI_CLI_TRUST_WORKSPACE=true

npx @google/gemini-cli \
  -m GigaChat-2-Max \
  -p "Суммируй архитектуру текущего проекта"
```

Для машинно-читаемого вывода используйте `--output-format json` или
`--output-format stream-json`:

```shell
npx @google/gemini-cli \
  -m GigaChat-2-Max \
  -p "Суммируй архитектуру текущего проекта" \
  --output-format json
```

Полезные флаги:

- `-m` / `--model` — выбрать модель для текущего запуска.
- `-p` / `--prompt` — передать prompt и не открывать interactive UI.
- `--output-format text|json|stream-json` — формат вывода.
- `--skip-trust` — доверять текущей рабочей папке на время запуска.
- `--approval-mode=plan` — read-only planning mode.
- `--approval-mode=yolo` — авто-approve действий; используйте только в
  изолированной среде.

---

## 4. Использование с API-ключом gpt2giga

Если на прокси-сервере включена авторизация по API-ключу
(`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), передайте `GPT2GIGA_API_KEY` через
`GEMINI_API_KEY`:

```shell
export GOOGLE_GEMINI_BASE_URL="http://localhost:8090"
export GEMINI_API_KEY="<ваш_GPT2GIGA_API_KEY>"
export GEMINI_MODEL="GigaChat-2-Max"

gemini -m GigaChat-2-Max -p "Проверь, что интеграция отвечает"
```

Gemini CLI передаст это значение как `x-goog-api-key`, а `gpt2giga` примет его
как client API key.

Для Gemini-compatible клиентов `gpt2giga` также принимает API key в query
параметре `?key=...`, потому что часть Gemini tooling использует такой формат.
Для новых настроек предпочтительнее `x-goog-api-key`/`GEMINI_API_KEY`: query
ключи чаще попадают в shell history, proxy logs и shared URLs.

---

## 5. Использование удалённого сервера

Для удалённого `gpt2giga`, например за nginx с TLS, укажите HTTPS URL:

```shell
export GOOGLE_GEMINI_BASE_URL="https://ваш-сервер.example.com"
export GEMINI_API_KEY="<ваш_api_ключ>"
export GEMINI_MODEL="GigaChat-2-Max"

gemini -m GigaChat-2-Max -p "Что ты умеешь?"
```

Подробнее о развёртывании с nginx и TLS — в
[integrations/nginx/README.md](../nginx/README.md).

---

## 6. Настройка через `.env`

Gemini CLI автоматически загружает `.env` из текущей директории, родительских
директорий до root проекта и затем `~/.env`. Для проекта можно добавить:

```env
GOOGLE_GEMINI_BASE_URL=http://localhost:8090
GEMINI_API_KEY=0
GEMINI_MODEL=GigaChat-2-Max
GEMINI_CLI_TRUST_WORKSPACE=true
```

Не коммитьте `.env`, если в нём лежит реальный `GPT2GIGA_API_KEY`.

---

## 7. Release smoke suite

Перед релизом Gemini-compatible API можно запустить opt-in smoke suite против
реального GigaChat upstream:

```shell
GPT2GIGA_RUN_GEMINI_SMOKE=1 \
GPT2GIGA_LIVE_ENV_FILE=.env.live \
uv run pytest tests/live/test_gemini_client_smoke.py
```

`.env.live` должен содержать один из поддержанных наборов upstream credentials:

```env
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GPT2GIGA_EMBEDDINGS=EmbeddingsGigaR
```

или `GIGACHAT_ACCESS_TOKEN`, либо
`GIGACHAT_USER` + `GIGACHAT_PASSWORD` + `GIGACHAT_BASE_URL`.

Smoke suite:

- стартует локальный `gpt2giga` server на свободном `127.0.0.1` port;
- прогоняет `google-genai` `generateContent` для base URL matrix: root, `/v1`,
  `/v2`, `/v1beta`, `/v1/v1beta`, `/v2/v1beta`;
- прогоняет `google-genai` `streamGenerateContent`;
- повторяет проверки с выключенной и включенной proxy API-key auth; для auth-on
  `x-goog-api-key` берется из `GPT2GIGA_GEMINI_SMOKE_API_KEY` или
  `gemini-smoke-key`;
- запускает Gemini CLI basic prompt и `--output-format json`, если CLI найден.

Опциональные переменные:

| Переменная | Назначение |
|---|---|
| `GPT2GIGA_GEMINI_SMOKE_MODEL` | Модель для generate/stream smoke. По умолчанию `GPT2GIGA_LIVE_MODEL`, `GIGACHAT_MODEL` или `GigaChat`. |
| `GPT2GIGA_GEMINI_SMOKE_API_KEY` | Proxy API key для auth-on smoke. |
| `GPT2GIGA_GEMINI_CLI_COMMAND` | Команда Gemini CLI. По умолчанию `gemini`; можно указать `npx @google/gemini-cli`. |
| `GPT2GIGA_GEMINI_CLI_TIMEOUT` | Timeout CLI запуска в секундах, по умолчанию `120`. |

Если `GPT2GIGA_RUN_GEMINI_SMOKE` или GigaChat credentials не заданы, тесты
будут skipped. Если Gemini CLI не установлен, CLI-кейсы будут skipped, а
`google-genai` smoke останется runnable.

---

## Диагностика

- **Gemini CLI ходит в Google, а не в `gpt2giga`** — проверьте
  `GOOGLE_GEMINI_BASE_URL` и убедитесь, что используется Gemini API key auth.
  Если у вас уже есть cached Google auth, для чистой проверки можно временно
  указать отдельный `GEMINI_CLI_HOME`.
- **Получаете 401/403 от `gpt2giga`** — проверьте, что `GEMINI_API_KEY`
  совпадает со значением `GPT2GIGA_API_KEY` на сервере, если авторизация
  включена.
- **Remote URL не принимается** — Gemini CLI требует HTTPS для нелокальных
  `GOOGLE_GEMINI_BASE_URL`; `http://` разрешён только для localhost-style
  адресов.
- **Headless запуск ждёт trust prompt** — добавьте
  `GEMINI_CLI_TRUST_WORKSPACE=true` или флаг `--skip-trust`.

---

## Доступные модели

| Модель GigaChat  | Описание                                        |
|------------------|-------------------------------------------------|
| `GigaChat-2-Max` | Максимальная версия — рекомендована для агентов |
| `GigaChat-2-Pro` | Промежуточная версия                            |
| `GigaChat-2`     | Базовая версия                                  |

---

## Полезные ссылки

- [Gemini CLI](https://github.com/google-gemini/gemini-cli)
- [Gemini CLI headless mode](https://geminicli.com/docs/cli/headless/)
- [Gemini CLI configuration reference](https://geminicli.com/docs/reference/configuration/)
- [Примеры Gemini API через gpt2giga](../../examples/gemini/)
