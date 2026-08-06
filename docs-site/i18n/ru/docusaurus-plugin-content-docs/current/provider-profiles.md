# Настройка провайдеров и моделей

Файл профилей нужен, когда один экземпляр gpt2giga должен работать с
несколькими провайдерами: GigaChat, OpenAI-совместимым API, Anthropic или
Gemini. В нём задаются адреса, ссылки на учётные данные и публичные имена
моделей.

Если вы используете только GigaChat, файл не обязателен: шлюз продолжит читать
обычные переменные `GIGACHAT_*`.

## Выбор файла

Передайте YAML- или JSON-файл в кодировке UTF-8:

```sh
gpt2giga --config /etc/gpt2giga/providers.yaml
```

Путь также можно задать через окружение:

```dotenv
GPT2GIGA_CONFIG=/etc/gpt2giga/providers.yaml
```

Если указаны оба варианта, пути должны совпадать. Два разных пути считаются
ошибкой: gpt2giga не объединяет несколько файлов. Конфигурация читается один
раз при запуске и не обновляется до перезапуска процесса.

## Пример с четырьмя провайдерами

В примере указаны только **имена** переменных окружения. Замените условные
идентификаторы моделей и политик значениями, проверенными для вашей установки.

```yaml
schema_version: gpt2giga.provider-profiles.v3
profiles:
  - profile_id: gigachat-main
    provider_kind: gigachat
    base_url: https://api.giga.chat/v1
    credential_env: GIGACHAT_CREDENTIALS
    network_policy_ref: public-gigachat
    tls_policy_ref: system-default
    model_inventory: dynamic

  - profile_id: openai-compatible-main
    provider_kind: openai_compatible
    base_url: https://gateway.example.com/v1
    credential_env: OPENAI_COMPATIBLE_API_KEY
    network_policy_ref: public-openai
    tls_policy_ref: system-default
    models:
      - public_alias: openai-compatible/default
        upstream_model: exact-reviewed-model-id
        capability_profile: openai-compatible-default-v1
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

  - profile_id: anthropic-main
    provider_kind: anthropic
    base_url: https://api.anthropic.com
    credential_env: ANTHROPIC_API_KEY
    network_policy_ref: public-anthropic
    tls_policy_ref: system-default
    models:
      - public_alias: anthropic/opus
        upstream_model: exact-reviewed-anthropic-model-id
        capability_profile: anthropic-opus-v1
        support_status: technical_preview

  - profile_id: gemini-main
    provider_kind: gemini
    base_url: https://generativelanguage.googleapis.com/v1beta
    credential_env: GEMINI_API_KEY
    network_policy_ref: public-gemini
    tls_policy_ref: system-default
    models:
      - public_alias: gemini/pro
        upstream_model: models/exact-reviewed-gemini-model-id
        capability_profile: gemini-pro-v1
        support_status: technical_preview
```

Сами секреты передавайте отдельно — например, через менеджер секретов или
защищённое окружение службы:

```dotenv
GIGACHAT_CREDENTIALS=<secret-from-service-manager>
OPENAI_COMPATIBLE_API_KEY=<secret-from-service-manager>
ANTHROPIC_API_KEY=<secret-from-service-manager>
GEMINI_API_KEY=<secret-from-service-manager>
```

Не добавляйте в профиль `api_key`, bearer-токены, произвольные заголовки,
клиентские сертификаты или флаги отключения TLS. Схема их не принимает. Если
`credential_env` задан, он должен содержать имя переменной окружения в верхнем
регистре. При отсутствии значения включённый профиль не пройдёт предварительную
проверку. В схеме v3 поле можно не указывать для намеренно открытого upstream
без ключа.

## Поля профиля

| Поле | Назначение |
|---|---|
| `schema_version` | Версия схемы: `gpt2giga.provider-profiles.v1`, `.v2` или `.v3`. Для исполняемых OpenAI-compatible профилей используйте v3. |
| `profile_id` | Уникальный идентификатор профиля в нижнем регистре. |
| `provider_kind` | Тип провайдера: `gigachat`, `openai_compatible`, `anthropic` или `gemini`. |
| `base_url` | Канонический публичный HTTPS-адрес без `userinfo`, строки запроса и фрагмента. В OpenAI-compatible профиле можно указать базу API или полный `/chat/completions` endpoint. |
| `credential_env` | Имя переменной окружения с секретом, но не сам секрет. Обязательно в v1/v2 и необязательно в v3 для upstream без ключа. |
| `network_policy_ref` | Идентификатор разрешённой сетевой политики приложения. |
| `tls_policy_ref` | Идентификатор разрешённой политики TLS. |
| `allow_loopback` | По умолчанию `false`. Разрешает HTTP только для явно заданного локального профиля разработки. |
| `model_inventory` | Для v2 и v3. Значение `dynamic` разрешено одному профилю GigaChat; без поля используются статические алиасы. |
| `models` | Точные привязки публичных алиасов. Обязательны для статических профилей и необязательны для динамического профиля GigaChat. |
| `public_alias` | Уникальное и регистрозависимое имя модели, которое видит клиент. |
| `upstream_model` | Точный идентификатор модели у провайдера. Клиент не может его изменить. |
| `capability_profile` | Проверенный набор поддерживаемых возможностей. |
| `capabilities` | Проверенный контракт исполнения v3. Обязателен для каждого включённого алиаса `openai_compatible`. |
| `capabilities.features` | Точный список возможностей, проверенных для этой модели upstream. Неподдерживаемые возможности не указываются. |
| `capabilities.limits` | Точный `context_window` и необязательные `max_input_tokens` и `max_output_tokens`. |
| `support_status` | Статус `stable`, `technical_preview` или `blocked`. |
| `enabled` | По умолчанию `true`. Отключённый алиас недоступен. |
| `deprecated` | По умолчанию `false`. Помечает устаревший алиас, но не перенаправляет его на другую модель. |

Неизвестные поля, повторяющиеся ключи YAML/JSON, одинаковые `profile_id` и
алиасы отклоняются. Размер файла ограничен 1 МиБ. Для рабочих профилей нужен
публичный HTTPS-адрес. Частные, локальные и служебные адреса запрещены, кроме
явно включённого loopback-профиля разработки. Редиректы и адрес из клиентского
запроса не участвуют в маршрутизации.

### Отличия схем v1, v2 и v3

Схема v1 остаётся совместимой: в каждом профиле должен быть непустой список
`models`, а поле `model_inventory` не поддерживается.

В схеме v2 `model_inventory: dynamic` позволяет не перечислять все модели,
доступные учётной записи GigaChat. Если список `models` всё же задан, его алиасы
не фильтруют каталог провайдера. Для остальных провайдеров по-прежнему нужен
хотя бы один статический алиас.

Схема v3 добавляет проверенные для каждого алиаса `capabilities` и токенные
лимиты. Этот контракт обязателен для исполняемого OpenAI-compatible маршрута.
Также v3 разрешает профиль upstream без ключа. Статическому профилю по-прежнему
нужен хотя бы один алиас.

Полная настройка сервера только с Chat Completions для Codex, Claude Code и
Gemini CLI приведена в разделе
[«Мост Chat Completions»](chat-completions-bridge.md).

## Алиасы и ревизии

Алиас ищется по точному совпадению. Другой регистр, лишние пробелы, отключённый
или отсутствующий алиас дают ошибку `unknown_model_alias`. Шлюз не подбирает
похожую модель и не переключается на другого провайдера. Устаревший алиас
по-прежнему ведёт только к объявленной модели, пока его не отключат или не
удалят с последующим перезапуском.

После проверки gpt2giga приводит конфигурацию без секретов к каноническому виду
и вычисляет ревизии формата `sha256:<lowercase-hex>` для всего файла и каждого
профиля. К этим ревизиям привязываются каталог моделей и диагностические
записи. Значения секретов в хеш не входят и не возвращаются в API.

Статусы отдельных маршрутов описаны в
[матрице совместимости провайдеров](bridge-compatibility.md). Проверка перед
запуском, обновление и откат — в разделе
[Переход на gpt2giga 0.3](migration-0-3.md).
