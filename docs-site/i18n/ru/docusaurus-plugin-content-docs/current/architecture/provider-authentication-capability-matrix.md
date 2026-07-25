# Матрица возможностей аутентификации провайдеров

Статус: принято для среза G3-00 roadmap GigaLoom 26 июля 2026 года.

Матрица построена из пакетированных подтверждений схемы v1 и описывает только
принадлежащие провайдерам поверхности. Она не разрешает запуск login, чтение
учётных данных, открытие браузера или реализацию broker из G3-01.

## Зафиксированная матрица

| Провайдер | Версия CLI | Начало | Статус | Выход | Отзыв |
| --- | --- | --- | --- | --- | --- |
| Codex CLI | `0.144.3` | `codex login`, `account/login/start` в app-server | `account/read`, `account/updated` | `codex logout`, `account/logout` | В интерфейсе аккаунта или workspace провайдера |
| Claude Code | `2.1.212` | `claude auth login`, `/login` | `claude auth status`, `/status` | `claude auth logout`, `/logout` | В аккаунте, организации или выбранном cloud-провайдере |
| Gemini CLI | `0.46.0` | Интерактивный выбор аутентификации, `/auth` | Документированной машинной команды нет | Только интерактивный сброс у провайдера | В Google Account, API key или Google Cloud |

Codex поддерживает браузерный и device-code flow, но пользователь всё равно
завершает аутентификацию у OpenAI. Claude Code может потребовать перенос URL и
кода при работе через SSH, WSL или контейнер. Для нового headless-входа Gemini
CLI требует API key или Vertex AI; существующие credentials могут использоваться
только самим CLI.

## Контракт безопасности

- Credentials, refresh, logout и revoke принадлежат CLI или выбранному
  cloud-провайдеру.
- Наличие исполняемого файла и совместимой справки `--help` не доказывает
  готовность аккаунта.
- GigaLoom может хранить evidence возможностей, класс статуса, источник и
  рекомендации восстановления. Tokens, содержимое credential-файлов, browser
  callback и неотредактированный вывод команд сохранять нельзя.
- Любое расхождение версии блокирует использование контракта. Перед G3-01
  точная версия CLI проверяется заново.
- Нельзя извлекать или повторно использовать OAuth Gemini CLI из стороннего
  ПО. Допустимы только provider-owned интерактивная подсказка либо отдельно
  поддерживаемые API-key/Vertex пути.

## Допустимая проекция

### Codex CLI

Допустимы класс auth mode, plan type, признак необходимости OpenAI auth и класс
источника credentials. Метку аккаунта можно показать пользователю только
эфемерно; её нельзя сохранять в диагностике. Стабильные поля срока действия и
scopes не заявлены. App-server умеет отменять ожидающий managed ChatGPT login,
а будущий broker обязан добавить собственный timeout.

### Claude Code

Допустимы машинный auth status, класс активного источника credentials и
provider-reported состояние истечения. Метки аккаунта и организации можно
показывать эфемерно. Scopes нельзя выводить из косвенных признаков. Для
восстановления используются `claude auth logout`, затем `claude auth login`,
либо штатное восстановление Bedrock, Vertex или Foundry.

### Gemini CLI

Без документированной provider-owned машинной поверхности identity, status,
expiry и scopes остаются `unknown`. Для восстановления пользователь возвращается
в интерактивный выбор аутентификации либо настраивает API key или Vertex AI.
Отзыв и ротация выполняются в соответствующем Google-сервисе.

## Источники и review

Источники пересмотрены 26 июля 2026 года:

- Codex: [аутентификация](https://learn.chatgpt.com/docs/auth),
  [app-server](https://learn.chatgpt.com/docs/app-server) и
  [условия](https://openai.com/policies/terms-of-use/);
- Claude Code:
  [аутентификация](https://code.claude.com/docs/en/authentication),
  [CLI reference](https://code.claude.com/docs/en/cli-usage) и
  [условия](https://www.anthropic.com/legal/consumer-terms);
- Gemini CLI:
  [аутентификация](https://geminicli.com/docs/get-started/authentication/),
  [команды](https://geminicli.com/docs/reference/commands/) и
  [условия](https://geminicli.com/docs/resources/tos-privacy/).

G3-01 может использовать эту матрицу для проектирования ограниченного native
login broker. Этот срез не запускает provider-команды, не аутентифицируется, не
читает native homes и не связывает аккаунты с сессиями.
