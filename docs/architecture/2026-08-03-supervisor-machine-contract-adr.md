# ADR: machine contract for external supervisors

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owner: integration lane
- Inspect schema: `gpt2giga.inspect.v1`
- Readiness schema: `gpt2giga.readiness.v1`
- Model schema: `gpt2giga.bridge-models.v1`
- Capability schema: `gpt2giga.bridge-capabilities.v1`
- Catalog schema: `gpt2giga.model-catalog.v1`
- Effective capability schema: `gpt2giga.effective-capabilities.v1`
- Error schema: `gpt2giga.error.v1`

## Context

An external supervisor such as GigaLoom must start and stop gpt2giga as an
installed artifact. It may not import private Python modules or infer readiness
from log text. Liveness, route readiness, model discovery, and bridge capability
truth are distinct facts.

## Decision

### CLI and preflight

The server invocation is:

```text
gpt2giga --config <path>
```

Preflight uses the same parser without binding a socket or contacting a
provider:

```text
gpt2giga --config <path> --inspect-config
```

It writes one redacted JSON document to stdout and exits `0` when config,
credential references, destinations, aliases, capability profiles, and matrix
revisions are valid. It exits `2` with `gpt2giga.error.v1` on validation failure.
Logs go to stderr. Credential values are neither resolved into the document nor
printed.

### HTTP endpoints

| Endpoint | Success | Failure | Meaning |
|---|---:|---:|---|
| `GET /health` | 200 empty body | process unavailable | Process liveness; existing contract retained. |
| `GET /ready` | 200 JSON | 503 JSON | Route, client, and model-catalog readiness. |
| `GET /models` | 200 JSON | protocol error | Protocol projection of the shared model catalog. |
| `GET /bridge/models` | 200 JSON | 503 JSON | Machine projection of the same catalog snapshot. |
| `GET /bridge/capabilities` | 200 JSON | 503 JSON | Coarse content-free 16-cell route manifest. |
| `GET /bridge/capabilities?model=...&protocol=...&api_mode=...` | 200 JSON | 400/404/503 JSON | Effective tri-state capabilities for one selected model and route. |

Preflight, `/health`, and the coarse route matrix do not call upstream
providers. Model endpoints use the bounded `ModelCatalog`, which may refresh
through provider discovery and reports whether the returned snapshot is fresh
or stale. Arrays are lexically ordered, JSON keys are stable, and every
document carries its applicable config, inventory, matrix, and capability
revision. `/health` remains usable while readiness is false.

Readiness distinguishes process liveness, route configuration, adapter state,
fresh inventory, stale-but-usable inventory, and discovery unavailability. A
temporary refresh failure does not fabricate a model or kill unrelated
already-admitted work. During shutdown readiness becomes false before new
requests are rejected.

### Stable error envelope

Machine endpoints and preflight use:

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

`details` is bounded and content-free. Public protocol routes keep their native
error envelope but use the same stable codes where representable.

### Shutdown

SIGTERM and interrupt perform this order:

1. mark readiness false and reject new model requests;
2. stop accepting new connections;
3. drain active requests up to the configured shutdown deadline;
4. cancel remaining upstream work;
5. close every owned provider client, sink, and store;
6. exit non-zero only when cleanup violates its bound.

The supervisor may send SIGKILL only after the documented deadline. No shutdown
step writes prompt content or secrets to the machine contract.

## Migration and rollback

- `/health` and current public protocol routes remain compatible.
- Supervisors should gate traffic on `/ready`, not replace liveness checks.
- Removing `--config` activates only the built-in native GigaChat route.
- A 0.2.x rollback loses the new inspect/readiness/bridge endpoints but requires
  no persistent-state conversion.
