# ADR: machine contract для внешних supervisors

- Дата: 2026-08-03
- Статус: принято для gpt2giga 0.3
- Владелец решения: направление integration
- Схемы: `gpt2giga.inspect.v1`, `gpt2giga.readiness.v1`,
  `gpt2giga.bridge-models.v1`, `gpt2giga.bridge-capabilities.v1`,
  `gpt2giga.error.v1`

## Контекст

Внешний supervisor, например GigaLoom, запускает и останавливает gpt2giga как
установленный artifact. Он не импортирует private Python modules и не выводит
readiness из log text. Liveness, route readiness, model discovery и capability
truth являются разными фактами.

## Решение

### CLI и preflight

```text
gpt2giga --config <path>
gpt2giga --config <path> --inspect-config
```

Preflight использует тот же parser, не открывает socket и не обращается к
provider. При валидных config, credential references, destinations, aliases,
capability profiles и matrix revisions он печатает один redacted JSON в stdout
и выходит с `0`; при ошибке — `gpt2giga.error.v1` и код `2`. Logs идут в stderr,
credential values не разрешаются в документ и не печатаются.

### HTTP endpoints

| Endpoint | Успех | Ошибка | Смысл |
|---|---:|---:|---|
| `GET /health` | 200 empty | process unavailable | Существующий liveness contract. |
| `GET /ready` | 200 JSON | 503 JSON | Config/aliases/routes/clients готовы. |
| `GET /bridge/models` | 200 JSON | 503 JSON | Детерминированные aliases и safe metadata. |
| `GET /bridge/capabilities` | 200 JSON | 503 JSON | Полный content-free manifest из 16 ячеек. |

Endpoints не вызывают upstream. Arrays лексически отсортированы, JSON keys
стабильны, документы содержат применимые schema/config/matrix revisions.
`/health` остаётся доступным при false readiness. Readiness становится true
только после immutable registry и всех enabled adapter clients; startup failure
происходит до публикации listening socket.

Machine endpoints используют bounded content-free envelope:

```json
{
  "schema_version": "gpt2giga.error.v1",
  "error": {
    "code": "gateway_not_ready",
    "message": "Gateway routes are not ready.",
    "details": [{"reason_id": "registry_not_loaded"}]
  }
}
```

Public protocol routes сохраняют native envelope и те же stable codes, где это
возможно.

### Shutdown

SIGTERM/interrupt выполняет порядок:

1. readiness false и отказ новым model requests;
2. прекращение новых connections;
3. drain active requests до deadline;
4. отмена оставшейся upstream work;
5. закрытие provider clients, sinks и stores;
6. non-zero exit только при нарушении cleanup bound.

SIGKILL допустим лишь после documented deadline. Machine contract не содержит
prompt content или secrets.

## Миграция и откат

- `/health` и текущие protocol routes совместимы.
- Supervisors должны gate traffic по `/ready`.
- Без `--config` активируется только synthesized GigaChat profile.
- Откат 0.2.x убирает новые endpoints без persistent-state migration.
