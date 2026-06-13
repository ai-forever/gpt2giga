# Интеграция Claude Desktop App с GigaChat

> **Проверено:** 13 июня 2026 — `Claude Desktop 1.12603.1`, `Claude Code 2.1.170`
> **Статус:** beta testing. Интеграция экспериментальная; пока проверяю, как Claude Desktop работает с локальным gateway, моделями, tools и plugins.

[Claude Desktop](https://claude.com/download) — desktop-приложение Anthropic для macOS и Windows. Через 3p gateway-конфиг его можно направить в локальный `gpt2giga`, который принимает Anthropic Messages API и отправляет запросы в GigaChat.

Важно: это не тот же механизм, что Claude Code CLI. Claude Code читает `ANTHROPIC_BASE_URL` из окружения, а Claude Desktop App для chat-интерфейса использует локальный 3p-конфиг в профиле `Claude-3p`.

## Что работает

- Claude Desktop отправляет chat-запросы в `gpt2giga`.
- `gpt2giga` принимает путь Claude gateway вида `/v2/v1/messages` и обрабатывает его как `/v2/messages`.
- Имя модели Claude можно оставить клиентским alias; при `GPT2GIGA_PASS_MODEL=False` реальная GigaChat model берётся из `GIGACHAT_MODEL`.
- Plugins/MCP в 3p mode работают иначе, чем в обычном consumer Claude: публичный Directory может быть пустым, а плагины лучше подключать как `managedMcpServers` или org plugins.

## Где скачать

- Claude Desktop: [официальная страница загрузки Claude](https://claude.com/download)
- Claude Code CLI, если нужен отдельно: [официальная документация Claude Code setup](https://code.claude.com/docs/en/setup)

Скачивайте только с официальных доменов `claude.com`, `claude.ai`, `docs.claude.com` или `code.claude.com`. Поддельные installers для AI tools встречаются достаточно часто, поэтому не используйте рекламные ссылки из поиска.

## 1. Запуск gpt2giga

Настройте `.env`:

```ini
GIGACHAT_CREDENTIALS=<ваш_ключ_авторизации>
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-3-Ultra

GPT2GIGA_GIGACHAT_API_MODE=v2
GPT2GIGA_PASS_MODEL=False

# DEV: можно оставить auth выключенным
GPT2GIGA_ENABLE_API_KEY_AUTH=False

# Если включаете auth, задайте ключ и используйте его в Claude Desktop config
# GPT2GIGA_ENABLE_API_KEY_AUTH=True
# GPT2GIGA_API_KEY=<ваш_api_ключ>
```

Ключевые настройки:

- `GPT2GIGA_GIGACHAT_API_MODE=v2` — включает GigaChat v2 backend для versioned routes, включая `/v2/messages`.
- `GPT2GIGA_PASS_MODEL=False` — игнорирует Claude model id вроде `claude-opus-4` и использует `GIGACHAT_MODEL`.
- `GPT2GIGA_ENABLE_API_KEY_AUTH=False` удобно для локального beta-теста. Для удалённого сервера включайте API-key auth.

Запустите сервер:

```shell
uv run gpt2giga
# или, если пакет установлен глобально:
gpt2giga
```

По умолчанию сервер доступен по адресу `http://localhost:8090`.

## 2. Настройка Claude Desktop

Закройте Claude Desktop:

```shell
pkill -x Claude
```

Создайте каталог конфигурации:

```shell
mkdir -p "$HOME/Library/Application Support/Claude-3p/configLibrary"
```

Создайте файл:

```text
~/Library/Application Support/Claude-3p/configLibrary/_meta.json
```

Пример:

```json
{
  "appliedId": "11111111-1111-4111-8111-111111111111",
  "entries": [
    {
      "id": "11111111-1111-4111-8111-111111111111",
      "name": "gpt2giga local",
      "provider": "gateway"
    }
  ],
  "isManaged": false,
  "platform": "darwin"
}
```

Создайте файл:

```text
~/Library/Application Support/Claude-3p/configLibrary/11111111-1111-4111-8111-111111111111.json
```

Пример без API-key auth:

```json
{
  "inferenceProvider": "gateway",
  "inferenceCredentialKind": "static",
  "inferenceGatewayBaseUrl": "http://localhost:8090",
  "inferenceGatewayApiKey": "0",
  "inferenceGatewayAuthScheme": "x-api-key",
  "modelDiscoveryEnabled": false,
  "inferenceModels": [
    {
      "name": "claude-sonnet-4-5",
      "labelOverride": "GigaChat 3 Ultra"
    },
    {
      "name": "claude-opus-4",
      "labelOverride": "GigaChat 3 Ultra"
    },
    {
      "name": "claude-haiku-4-5",
      "labelOverride": "GigaChat 3 Ultra"
    }
  ],
  "chatTabEnabled": true
}
```

Если в `gpt2giga` включён `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, замените `inferenceGatewayApiKey` на значение `GPT2GIGA_API_KEY`.

Выставьте права на файлы:

```shell
chmod 600 "$HOME/Library/Application Support/Claude-3p/configLibrary/"*.json
```

Запустите Claude Desktop заново:

```shell
open -a Claude
```

## 3. Проверка

Проверьте, что `gpt2giga` отвечает на путь, который использует Claude Desktop gateway:

```shell
curl -sS http://localhost:8090/v2/v1/messages \
  -H 'content-type: application/json' \
  -d '{
    "model": "claude-opus-4",
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "ping"}]
  }'
```

Ожидается Anthropic-compatible JSON-ответ с `type: "message"`. Внутри `gpt2giga` путь `/v2/v1/messages` нормализуется в `/v2/messages`, поэтому запрос идёт через GigaChat v2 backend.

Если включён API-key auth:

```shell
curl -sS http://localhost:8090/v2/v1/messages \
  -H 'content-type: application/json' \
  -H 'x-api-key: <ваш_GPT2GIGA_API_KEY>' \
  -d '{
    "model": "claude-opus-4",
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "ping"}]
  }'
```

## 4. Plugins, MCP и Directory

В 3p gateway mode Claude Desktop ведёт себя не как обычный consumer app. Обычный публичный Directory/Marketplace может показывать пустое состояние вроде:

```text
Your organization hasn't provided plugins.
```

Это ожидаемо для текущего beta-теста: 3p mode использует enterprise/org-механику plugins.

Для MCP-серверов можно добавить `managedMcpServers` в тот же gateway config:

```json
{
  "managedMcpServers": [
    {
      "name": "my-local-mcp",
      "transport": "stdio",
      "command": "/absolute/path/to/mcp-server",
      "args": [],
      "env": {}
    }
  ]
}
```

Для HTTP MCP:

```json
{
  "managedMcpServers": [
    {
      "name": "my-http-mcp",
      "transport": "http",
      "url": "http://localhost:3000/mcp"
    }
  ]
}
```

Для `.claude-plugin` / `.dxt` org plugins Claude Desktop на macOS смотрит в системный каталог:

```text
/Library/Application Support/Claude/org-plugins
```

Пример структуры:

```text
/Library/Application Support/Claude/org-plugins/my-plugin/.claude-plugin/plugin.json
```

Запись в `/Library/Application Support` требует admin-доступа. Для ручной записи без `sudo vim` используйте `sudo tee`, например:

```shell
sudo mkdir -p "/Library/Application Support/Claude/org-plugins"

sudo tee "/Library/Application Support/Claude/org-plugins/test.txt" >/dev/null <<'EOF'
hello
EOF
```

## Диагностика

- **`Configured model not available`, `HTTP 404`, `requestUrl: http://localhost:8090/v2/v1/messages`** — нужна версия `gpt2giga`, где поддержана нормализация `/v2/v1/messages -> /v2/messages`. Перезапустите `gpt2giga` после обновления кода.
- **Gateway rejected model `claude-opus-4`** — проверьте `GPT2GIGA_PASS_MODEL=False`. Тогда Claude model id будет только client-side alias, а upstream model возьмётся из `GIGACHAT_MODEL`.
- **Claude всё ещё показывает обычные Sonnet/Opus/Haiku и не использует gateway** — проверьте путь `~/Library/Application Support/Claude-3p/configLibrary`, а не `/Library/Application Support/Claude-3p/configLibrary`; затем полностью перезапустите Claude.
- **401/403 от `gpt2giga`** — если включён `GPT2GIGA_ENABLE_API_KEY_AUTH=True`, значение `inferenceGatewayApiKey` должно совпадать с `GPT2GIGA_API_KEY`.
- **Directory plugins пустой** — это ограничение 3p mode. Используйте `managedMcpServers` или org plugins; поведение пока считается beta testing.

## Полезные ссылки

- [Claude Desktop download](https://claude.com/download)
- [Claude Code setup](https://code.claude.com/docs/en/setup)
- [Claude Code через gpt2giga](../claude-code/README.md)
- [Anthropic examples через gpt2giga](../../examples/anthropic/)
