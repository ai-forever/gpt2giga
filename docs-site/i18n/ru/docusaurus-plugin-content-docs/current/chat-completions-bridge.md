# Codex, Claude Code и Gemini CLI через сервер Chat Completions

Эта инструкция подключает один неизменяемый OpenAI-совместимый сервер
`/v1/chat/completions` сразу к трём клиентским протоколам:

```text
Codex (Responses) ───────────┐
Claude Code (Messages) ──────┼─> gpt2giga ─> /v1/chat/completions
Gemini CLI (GenerateContent) ┘
```

Маршрут имеет статус technical preview. gpt2giga переводит только проверенное
чат-подобное подмножество, а запрос с непереносимым смыслом отклоняет до
обращения к вышестоящему серверу. Шлюз не выдаёт Chat Completions за полную
реализацию Responses, Messages или GenerateContent.

## Требования к вышестоящему серверу

Понадобятся:

- точный Chat Completions endpoint либо базовый URL API;
- точный идентификатор модели на сервере;
- реальные лимиты контекста, входных и выходных токенов;
- при необходимости bearer-токен;
- обычный JSON-ответ Chat Completions;
- Chat Completions SSE с завершающим кадром `data: [DONE]`;
- function tools и tool calls, если кодовые агенты должны вызывать локальные
  инструменты.

В потоковом запросе шлюз передаёт
`stream_options: {"include_usage": true}`. Если сервер не вернул usage,
gpt2giga не придумывает значения токенов.

## 1. Опишите upstream

Создайте `providers.yaml` вне репозитория:

```yaml
schema_version: gpt2giga.provider-profiles.v3
profiles:
  - profile_id: chat-only-upstream
    provider_kind: openai_compatible
    base_url: https://inference.example/v1/chat/completions
    credential_env: CHAT_UPSTREAM_API_KEY
    network_policy_ref: public-openai
    tls_policy_ref: system-default
    models:
      - public_alias: bridge/chat-only
        upstream_model: exact-upstream-model-id
        capability_profile: chat-only-coding-v1
        capabilities:
          features:
            - roles
            - ordered_content_parts
            - text
            - generation_controls
            - function_tools
            - tool_choice
            - parallel_tool_calls
            - tool_results
            - stream_deltas
            - stream_terminal_events
            - stop_reason
            - usage
            - model_identity
            - request_error_classes
            - cancellation
            - context_token_limits
          limits:
            context_window: 32768
            max_input_tokens: 28672
            max_output_tokens: 4096
        support_status: technical_preview
```

Замените endpoint, модель и лимиты. `public_alias` — имя модели, которое будут
использовать все три клиента. В `upstream_model` оно преобразуется только
внутри шлюза.

Если сервер намеренно работает без ключа, удалите `credential_env`. Когда поле
задано, gpt2giga читает указанную переменную при запуске и отправляет её
значение как bearer-токен. Клиент не может подменить адрес, внутреннюю модель
или учётные данные upstream.

Список `features` — это список реально проверенных возможностей, а не
пожеланий. Добавляйте `json_schema_output` или `image_references` только после
проверки конкретной модели. Не добавляйте `count_tokens`: у одного Chat
Completions endpoint нет точной операции подсчёта токенов.

Можно указать и базу `https://inference.example/v1`: тогда gpt2giga добавит
`chat/completions`. Полный адрес, заканчивающийся на `/chat/completions`,
используется без изменения.

### Локальный upstream

Для сервера на той же машине используйте явное исключение для loopback:

```yaml
    base_url: http://127.0.0.1:8001/v1/chat/completions
    allow_loopback: true
    network_policy_ref: loopback-development
```

Прямые адреса из частных, link-local и metadata-сетей отклоняются. Если сервер
доступен только через VPN или частную подсеть, поднимите SSH-туннель или его
аналог на loopback и укажите локальный адрес в профиле.

## 2. Запустите gpt2giga

Из рабочей копии репозитория:

```sh
export CHAT_UPSTREAM_API_KEY='<upstream-bearer-token>'
export GPT2GIGA_CONFIG=/absolute/path/to/providers.yaml
export GPT2GIGA_ENABLE_API_KEY_AUTH=True
export GPT2GIGA_API_KEY='<local-gateway-key>'

uv run gpt2giga
```

Для upstream без ключа не задавайте `CHAT_UPSTREAM_API_KEY`. Если пакет уже
установлен, запускайте `gpt2giga` вместо `uv run gpt2giga`.

Проверьте готовность и статический алиас модели — эти два запроса не обращаются
к inference-серверу:

```sh
curl -fsS http://127.0.0.1:8090/ready
curl -fsS \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  http://127.0.0.1:8090/v1/models
```

Затем проверьте реальный перевод:

```sh
curl -fsS http://127.0.0.1:8090/v1/responses \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"bridge/chat-only","input":"Reply only OK"}'
```

## 3. Подключите Codex

Добавьте провайдера в `~/.codex/config.toml`:

```toml
[model_providers.gpt2giga_chat]
name = "gpt2giga Chat bridge"
base_url = "http://127.0.0.1:8090/v1"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

Создайте отдельный файл профиля `~/.codex/chat-bridge.config.toml`:

```toml
model = "bridge/chat-only"
model_provider = "gpt2giga_chat"
model_context_window = 32768
model_auto_compact_token_limit = 24576
model_supports_reasoning_summaries = false
model_reasoning_summary = "none"
web_search = "disabled"
```

Экспортируйте локальный ключ и выберите профиль:

```sh
export GPT2GIGA_API_KEY='<local-gateway-key>'
codex --profile chat-bridge
```

### Минимальная команда Codex для бенчмарка

Для герметичного CLI-бенчмарка отключите пользовательские MCP, приложения,
плагины и multi-agent, а настройки моста передайте явно:

```sh
codex -a never exec --json \
  --ignore-user-config \
  --strict-config \
  --skip-git-repo-check \
  --ephemeral \
  --sandbox workspace-write \
  --disable apps \
  --disable plugins \
  --disable multi_agent \
  --disable apply_patch_freeform \
  -m bridge/chat-only \
  -c model_provider=gpt2giga_chat \
  -c model_providers.gpt2giga_chat.name=gpt2giga_chat \
  -c model_providers.gpt2giga_chat.base_url=http://127.0.0.1:8090/v1 \
  -c model_providers.gpt2giga_chat.env_key=GPT2GIGA_API_KEY \
  -c model_providers.gpt2giga_chat.wire_api=responses \
  -c model_providers.gpt2giga_chat.supports_websockets=false \
  -c model_reasoning_effort=none \
  -c web_search=disabled \
  'Выполни задачу бенчмарка.'
```

Эту же строку можно передать в runner, например в `harness_bench run-cli`.
Codex CLI 0.146.0 проверен с таким минимальным набором:
`exec_command`, `write_stdin`, `update_plan`, `request_user_input` и
`view_image`. Все они передаются как обычные function tools. В живой
двухходовой проверке Codex получил потоковый `exec_command`, выполнил его,
вернул результат и получил финальный ответ модели через upstream Chat
Completions.

Responses custom/freeform tools намеренно не входят в поддержанное подмножество.
В частности, не включайте `apply_patch_freeform`. Для неизвестного публичного
алиаса из примера текущий Codex редактирует файлы через `exec_command` и не
выставляет `apply_patch`. Если бенчмарк проверяет именно wire-контракт custom
`apply_patch`, нужен нативный Responses upstream или отдельно рассмотренное
расширение для custom tools.

Codex работает по Responses API. Шлюз принимает его stateless-envelope,
переводит сообщения `developer` в `system` для Chat Completions, разворачивает
namespace tools перед вызовом upstream и восстанавливает namespace в
вернувшихся function calls. Он принимает служебные item id, которые Codex
повторяет в истории, и сохраняет идентификатор вызова до следующего
`function_call_output`.

Текущий Codex CLI может предупредить, что `/v1/models` не содержит расширенных
метаданных собственного каталога Codex. gpt2giga намеренно возвращает
стандартный OpenAI-формат списка моделей, а Codex использует явные значения из
профиля выше. Предупреждение не блокирует запросы.

Поля конфигурации и приоритет файлов профилей описаны в
[официальной справке Codex](https://learn.chatgpt.com/docs/config-file/config-basic).

## 4. Подключите Claude Code

Оставьте Claude Code в stateless-подмножестве Messages и синхронизируйте лимиты
с профилем провайдера:

```sh
export ANTHROPIC_BASE_URL=http://127.0.0.1:8090
export ANTHROPIC_API_KEY="$GPT2GIGA_API_KEY"
export ANTHROPIC_MODEL=bridge/chat-only
export ANTHROPIC_SMALL_FAST_MODEL=bridge/chat-only

export CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096
export MAX_THINKING_TOKENS=0
export CLAUDE_CODE_DISABLE_THINKING=1
export DISABLE_PROMPT_CACHING=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

claude --model bridge/chat-only
```

Через `ANTHROPIC_API_KEY` Claude Code отправляет локальный ключ шлюза в
`x-api-key`. gpt2giga также принимает bearer-аутентификацию.

Thinking и prompt caching отключены, потому что Chat Completions не может
сохранить эту семантику Anthropic. Значение
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` не должно превышать
`capabilities.limits.max_output_tokens`: для неизвестной Claude-модели клиент
по умолчанию запрашивает существенно больший ответ. Обычные function tools и
потоковые Messages events через этот маршрут работают.

Некоторые сценарии Claude Code вызывают `/v1/messages/count_tokens`. Мост
отклоняет такую операцию вместо неточной оценки. Основной чат и вызовы tools не
требуют отдельного count-token endpoint, но зависимая от него функция останется
недоступна.

Актуальный список клиентских переменных находится в
[официальной справке Claude Code](https://code.claude.com/docs/en/env-vars).

## 5. Подключите Gemini CLI

Для неизвестной модели Gemini CLI применяет встроенную конфигурацию
`chat-base`, которая сейчас добавляет `topK` и `thinkingConfig`. У этих
параметров нет точного представления в Chat Completions, поэтому мост их
отклоняет. Нужен минимальный пользовательский алиас с ключом, точно совпадающим
с публичным id модели.

Добавьте этот блок в `~/.gemini/settings.json`, не удаляя остальные настройки:

```json
{
  "security": {
    "auth": {
      "selectedType": "gemini-api-key"
    }
  },
  "modelConfigs": {
    "customAliases": {
      "bridge/chat-only": {
        "modelConfig": {
          "model": "bridge/chat-only",
          "generateContentConfig": {
            "temperature": 1,
            "topP": 0.95,
            "maxOutputTokens": 4096
          }
        }
      }
    }
  }
}
```

Не наследуйтесь от `chat-base` и не добавляйте `topK` либо `thinkingConfig` для
этого маршрута. Ключ алиаса должен оставаться `bridge/chat-only`: после вызова
инструмента Gemini CLI продолжает работу с разрешённым id модели, поэтому алиас
с другим именем повлияет только на первый запрос.

Запускайте Gemini CLI с публичным id модели:

```sh
export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8090
export GEMINI_API_KEY="$GPT2GIGA_API_KEY"
export GEMINI_MODEL=bridge/chat-only
export OTEL_SDK_DISABLED=true

gemini --model bridge/chat-only
```

Gemini передаёт `GEMINI_API_KEY` в Google-совместимой форме, которую шлюз
принимает как свой локальный API key. Профиль провайдера затем связывает
публичный id с точной моделью upstream. Синтетический маркер Gemini CLI
`skip_thought_signature_validator` принимается только как клиентский no-op;
настоящая thought signature остаётся неподдержанной.

Если задан `GEMINI_CLI_HOME`, Gemini CLI считает его корнем домашней папки.
Глобальные настройки должны находиться в
`$GEMINI_CLI_HOME/.gemini/settings.json`, а не прямо в `$GEMINI_CLI_HOME`.

Если алиас хранится в проектном `.gemini/settings.json`, сначала доверьте
рабочую папку клиенту. Для headless-запуска задайте
`GEMINI_CLI_TRUST_WORKSPACE=true` до старта Gemini CLI, чтобы проектные настройки
были загружены.

Формат описан в
[официальной справке Gemini CLI по model configuration](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/generation-settings.md).

## Поддержанное подмножество и ограничения

Мост поддерживает текстовые роли, общие параметры генерации, function tools и
их результаты, tool choice там, где целевой протокол умеет его выразить,
потоковые ответы, terminal stop reasons, usage при наличии в upstream,
отмену и заявленные лимиты контекста.

Поддержан полный stateless-цикл инструмента: клиент передаёт определения
функций, получает потоковый или обычный вызов, выполняет его локально и в
следующем запросе повторяет вызов вместе с результатом. Мост сохраняет call id
и переводит следующий ход обратно в Chat Completions. Сценарий проверен для
Responses, Anthropic Messages и Gemini GenerateContent.

Мост не эмулирует:

- состояние Responses: `previous_response_id`, conversations, background jobs
  и долговременный `store`;
- reasoning/thinking и reasoning summaries;
- семантику prompt cache и точный cached-token accounting;
- hosted web search, computer use, code execution и provider-native tools;
- Responses custom/freeform tools, например `apply_patch`;
- files, audio и неподдерживаемые мультимодальные данные;
- точный подсчёт токенов;
- Gemini safety settings, cached content, `topK` и thinking configuration.

Проверенные служебные no-op поля клиентов принимаются, если они не меняют
переведённый запрос. Семантическое поле вне заявленного подмножества возвращает
`unsupported_semantic` до обращения к upstream.

## Диагностика

| Симптом | Что делать |
|---|---|
| `unknown_model_alias` | Используйте точный `public_alias` с тем же регистром и знаками. |
| `credential_unavailable` при запуске | Задайте переменную из `credential_env` или удалите поле для намеренно открытого upstream. |
| `unsupported_semantic` | Клиент запросил смысл, который нельзя сохранить в Chat Completions. Отключите эту функцию; не добавляйте capability без реальной проверки upstream. |
| Отказ по токенным лимитам | Синхронизируйте context/output клиента с точными значениями профиля. |
| В запросе Gemini есть `topK` или `thinkingConfig` | Задайте минимальный пользовательский алиас под точным публичным id `bridge/chat-only`: алиас с другим именем действует только на первый запрос tool-loop. |
| Claude вызывает `count_tokens` | Для upstream только с Chat Completions эта операция намеренно не поддерживается. |
| Codex предупреждает о метаданных модели | Оставьте явные context/compaction значения в профиле Codex; обычные запросы продолжат работу. |
| `provider_protocol_error` в потоке | Проверьте корректный Chat Completions SSE, terminal choice, порядок optional usage и завершающий `[DONE]`. |

Полная схема находится в разделе
[«Профили провайдеров и алиасы моделей»](provider-profiles.md), а правила
семантического допуска — в разделе
[«Совместимость провайдеров»](bridge-compatibility.md).
