# ADR: startup-профили провайдеров и публичные model aliases

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: направления provider-profiles и integration
- Ревизия схемы: `gpt2giga.provider-profiles.v1`
- Ревизия execution context: `gpt2giga.execution-context.v1`

## Контекст

Bridge должен разделять route configuration, public model identity, upstream
provider, provider-visible inventory, selected model, capability evidence и
loss-matrix revision. Provider profiles владеют стабильной execution
configuration, но не полным динамическим model inventory.

## Решение

### Startup-контракт и приоритет

```text
gpt2giga --config <path>
GPT2GIGA_CONFIG=<path> gpt2giga
```

Явный `--config` приоритетнее `GPT2GIGA_CONFIG`; два разных пути дают
`invalid_profile`. Без обоих источников 0.3 создаёт built-in GigaChat route из
существующих `GIGACHAT_*` connection settings. Config владеет destinations,
credentials, immutable aliases, route enablement и route policy; payload и
headers их не изменяют. Dynamic GigaChat inventory остаётся provider-discovered
даже при настроенных aliases или default model.

### Владелец model catalog

Один `ModelCatalog` владеет snapshot для public `/models`, `/bridge/models`,
selected-model validation и capability admission. GigaChat discovery использует
authenticated provider models API. Exact aliases в profile являются routes, а
не доказательством полного provider inventory.

`GIGACHAT_MODEL` задаёт default-model или явно документированную forced-model
policy. Он не заменяет и не фильтрует provider-visible catalog. Новая model
остаётся видимой, даже если её effective capabilities пока `unknown`.

### Версионированная схема

```yaml
schema_version: gpt2giga.provider-profiles.v1
profiles:
  - profile_id: anthropic-main
    provider_kind: anthropic
    base_url: https://api.anthropic.com
    credential_env: ANTHROPIC_API_KEY
    network_policy_ref: public-anthropic
    tls_policy_ref: system-default
    models:
      - public_alias: anthropic/opus
        upstream_model: exact-provider-model-id
        capability_profile: anthropic-opus-v1
        support_status: technical_preview
```

Неизвестные поля отклоняются. Все показанные identity/destination/policy поля и
хотя бы одна model обязательны. Plaintext secret-полей нет. `profile_id` и
`public_alias` глобально уникальны после Unicode/whitespace validation; aliases
регистрозависимы и не угадываются.

### Canonical digest и неизменяемость

Secret-free модель сериализуется в UTF-8 canonical JSON с sorted object keys,
compact separators и сохранением порядка arrays. Ревизия имеет вид
`sha256:<lowercase-hex>`. Registry неизменяем на время процесса; hot reload в
0.3 отсутствует.

Execution context `gpt2giga.execution-context.v1` хранит `config_revision`,
`profile_id`, `public_alias`, `provider_kind`, `upstream_model`,
`capability_profile` и `loss_matrix_revision`. Разрешено показывать имена env
переменных, но не values, их hashes или authorization headers.

### Разрешение route и model

До semantic admission и provider execution выполняется точная цепочка:

```text
public model/alias -> exact provider route -> effective model
                   -> catalog revision -> effective capability revision
```

Unknown, ambiguous, disabled и deprecated aliases не выбирают замену.
Unavailable model также не выбирает замену. `/bridge/models` и все
protocol-specific `/models` строятся из одного catalog snapshot и публикуют его
safe inventory revision.

Startup/preflight использует коды `invalid_profile_schema`,
`duplicate_profile_id`, `duplicate_model_alias`, `invalid_destination`,
`credential_unavailable`, `invalid_policy_reference`; runtime lookup —
`unknown_model_alias`. Credential values в ошибках запрещены.

## Миграция и откат

- Без config сохраняется текущая установка через built-in GigaChat route.
- Existing exact aliases сохраняют route identity и не сужают dynamic discovery.
- Удаление `--config` после restart возвращает built-in GigaChat route.
- 0.2.x игнорирует отдельный profile file; миграция данных не нужна.
