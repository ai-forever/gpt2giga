# ADR: startup-профили провайдеров и публичные model aliases

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владельцы решения: направления provider-profiles и integration
- Ревизия схемы: `gpt2giga.provider-profiles.v1`
- Ревизия execution context: `gpt2giga.execution-context.v1`

## Контекст

Bridge должен разделять клиентский протокол, публичный alias, upstream provider,
upstream model id, capability profile и loss-matrix revision. Запрос выбирает
только публичный alias. Текущие GigaChat settings и `pass_model` такой границы
не дают.

## Решение

### Startup-контракт и приоритет

```text
gpt2giga --config <path>
GPT2GIGA_CONFIG=<path> gpt2giga
```

Явный `--config` приоритетнее `GPT2GIGA_CONFIG`; два разных пути дают
`invalid_profile`. Без обоих источников 0.3 создаёт один legacy-профиль GigaChat
из существующих `GIGACHAT_*` settings. Config является единственным владельцем
destinations, credentials, models, capabilities и aliases; payload, headers и
`pass_model` их не изменяют.

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

### Разрешение aliases

До semantic admission и I/O выполняется точная цепочка:

```text
public alias -> exact profile -> exact upstream model
             -> capability profile -> loss matrix revision
```

Unknown, ambiguous, disabled и deprecated aliases не выбирают замену.
`/bridge/models` выдаёт лексически отсортированные aliases с безопасными
metadata/revisions; protocol-specific `/models` строятся из того же registry.

Startup/preflight использует коды `invalid_profile_schema`,
`duplicate_profile_id`, `duplicate_model_alias`, `invalid_destination`,
`credential_unavailable`, `invalid_policy_reference`; runtime lookup —
`unknown_model_alias`. Credential values в ошибках запрещены.

## Миграция и откат

- Без config сохраняется текущая установка через synthesized GigaChat profile.
- `pass_model` остаётся только legacy-механизмом и не меняет bridge aliases.
- Удаление `--config` после restart возвращает synthesized profile.
- 0.2.x игнорирует отдельный profile file; миграция данных не нужна.
