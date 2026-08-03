# Профили провайдеров и алиасы моделей

Профили провайдеров — это принадлежащая процессу startup-конфигурация
маршрутизации universal bridge 0.3. Клиентский запрос выбирает проверенный
публичный алиас или model id из dynamic GigaChat inventory. До исполнения
gateway разрешает эту identity в один provider profile и effective model.

Используйте режим профилей, когда один процесс gateway должен открыть
проверенные GigaChat, OpenAI-compatible, Anthropic или Gemini upstream. Если
файл профилей не указан, существующие настройки `GIGACHAT_*` остаются
compatibility default.

## Выбор одного конфигурационного файла

Передайте UTF-8 YAML- или JSON-файл явно:

```sh
gpt2giga --config /etc/gpt2giga/providers.yaml
```

или выберите его через окружение:

```dotenv
GPT2GIGA_CONFIG=/etc/gpt2giga/providers.yaml
```

Одинаковый путь в обоих источниках допустим. Два разных пути приводят к ошибке
старта; gateway никогда не объединяет документы профилей. Файл читается,
проверяется и фиксируется один раз на всё время жизни процесса. В версии 0.3
hot reload отсутствует.

## Безопасный пример четырёх провайдеров

Пример содержит **имена** переменных окружения, а не credentials. Замените
иллюстративные upstream model id и policy references на проверенные для вашего
развёртывания значения.

```yaml
schema_version: gpt2giga.provider-profiles.v2
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
    network_policy_ref: public-openai-compatible
    tls_policy_ref: system-default
    models:
      - public_alias: openai-compatible/default
        upstream_model: exact-reviewed-model-id
        capability_profile: openai-compatible-default-v1
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

Передайте значения отдельно, предпочтительно через secrets manager или
защищённое окружение service manager:

```dotenv
GIGACHAT_CREDENTIALS=<secret-from-service-manager>
OPENAI_COMPATIBLE_API_KEY=<secret-from-service-manager>
ANTHROPIC_API_KEY=<secret-from-service-manager>
GEMINI_API_KEY=<secret-from-service-manager>
```

Не добавляйте в профиль `api_key`, bearer tokens, произвольные headers,
клиентские сертификаты или флаги отключения TLS. Таких полей нет в схеме, и
startup завершится ошибкой. `credential_env` должен быть именем переменной
окружения в верхнем регистре; если у неё нет значения, включённый профиль не
проходит preflight.

## Справочник схемы

| Поле | Контракт |
|---|---|
| `schema_version` | `gpt2giga.provider-profiles.v1` или `gpt2giga.provider-profiles.v2`; для новых файлов используйте v2. |
| `profile_id` | Уникальный проверенный идентификатор в нижнем регистре. |
| `provider_kind` | `gigachat`, `openai_compatible`, `anthropic` или `gemini`. |
| `base_url` | Канонический публичный HTTPS destination без userinfo, query или fragment. |
| `credential_env` | Имя переменной окружения с credential, но никогда не её значение. |
| `network_policy_ref` | Идентификатор из проверенного каталога network policies приложения. |
| `tls_policy_ref` | Идентификатор из проверенного каталога TLS policies приложения. |
| `allow_loopback` | По умолчанию `false`; разрешает только явный HTTP loopback development profile. |
| `model_inventory` | Только v2. `dynamic` разрешён только для одного GigaChat profile; отсутствие поля означает static aliases. |
| `models` | Точные привязки public aliases. Обязательны для static profiles; опциональны как aliases для dynamic GigaChat. |
| `public_alias` | Глобально уникальное, регистрозависимое имя модели для клиентов. |
| `upstream_model` | Точный provider-owned model id; клиент не может его переопределить. |
| `capability_profile` | Проверенный набор семантик для admission. |
| `support_status` | `stable`, `technical_preview` или `blocked`. |
| `enabled` | По умолчанию `true`; отключённый алиас не разрешается. |
| `deprecated` | По умолчанию `false`; помечает алиас без скрытого remap. |

Неизвестные поля, дубли ключей YAML/JSON, дубли `profile_id` и алиасов
отклоняются. Размер файла ограничен 1 MiB. Production destinations требуют
публичный HTTPS. Private, link-local, metadata и loopback addresses запрещены,
кроме явного HTTP loopback development exception. Redirect и переданный в
request destination не являются механизмами маршрутизации.

Версия 1 остаётся валидной без изменений: каждый profile требует непустой
`models`, а `model_inventory` не принимается. Версия 2 явно задаёт provider
discovery: `model_inventory: dynamic` снимает требование перечислять все
credential-visible GigaChat models. Если `models` всё же заданы, они остаются
точными aliases и не фильтруют inventory. Static profiles внешних providers
по-прежнему требуют хотя бы один alias.

## Поведение алиасов и ревизий

Поиск алиаса точный. Изменение регистра, внешние пробелы, отсутствующий или
отключённый алиас возвращают `unknown_model_alias`; похожая модель или другой
провайдер никогда не выбираются. Deprecated-алиас продолжает разрешаться только
в объявленную upstream-модель, пока после рестарта он не будет отключён или
удалён.

Gateway канонизирует документ без секретов и назначает полной конфигурации и
каждому профилю ревизии `sha256:<lowercase-hex>`. Model discovery и execution
evidence привязываются к этим ревизиям. Значения credentials не участвуют в
ревизии и не возвращаются в model/capability manifests.

Решение о поддержке каждой комбинации client protocol/provider описано в
[Совместимости bridge, потерях и ошибках](bridge-compatibility.md).
Startup preflight, supervisor lifecycle, migration и rollback описаны в
[Миграции 0.3 и supervisor integration](migration-0-3.md).
