# 0.3 migration and supervisor integration

Version 0.3 adds the universal provider bridge without requiring a persistent
data migration. Existing GigaChat-only deployments can upgrade without a
provider file. Multi-provider deployments opt in with one immutable,
startup-owned profile document.

This page is also the process contract for an external supervisor such as
GigaLoom. A supervisor starts the installed `gpt2giga` artifact, uses public CLI
and HTTP contracts, and never imports private gateway modules.

## Choose the migration mode

| Mode | Configuration | Behavior |
|---|---|---|
| Existing GigaChat compatibility | No `--config` and no `GPT2GIGA_CONFIG` | The gateway synthesizes one GigaChat profile from the existing `GIGACHAT_*` and proxy settings. Existing public routes remain available. |
| Universal provider bridge | `--config <path>` or `GPT2GIGA_CONFIG=<path>` | The profile file is authoritative for provider destinations, credentials, aliases, models, and capabilities. Requests cannot add or alter routes. |
| Temporary legacy Responses | `GPT2GIGA_LEGACY_RESPONSES=true`, no provider file | The old direct GigaChat Responses path is selected explicitly. This mode is deprecated in 0.3 and is never an automatic fallback. |

Legacy Responses mode cannot be combined with `--config` or
`GPT2GIGA_CONFIG`. Such a combination fails startup. An error after normalized
admission or after response bytes begin never switches to the legacy path or a
different provider.

The provider path contract is exact:

```text
gpt2giga --config /etc/gpt2giga/providers.yaml
GPT2GIGA_CONFIG=/etc/gpt2giga/providers.yaml gpt2giga
```

The same path through both sources is valid. Different paths fail validation;
documents are never merged. See [Provider profiles and model aliases](provider-profiles.md)
for the schema and secure examples.

## Preflight before binding a socket

Use the same config parser in inspect mode:

```sh
gpt2giga --config /etc/gpt2giga/providers.yaml --inspect-config
```

Successful preflight writes one `gpt2giga.inspect.v1` JSON document to stdout
and exits `0`. It validates the schema, destination and policy references,
credential availability, aliases, capability profiles, and matrix revision. It
does not bind a socket or contact a provider. The document may identify a
`credential_env` name but never includes its value, hash, or authorization
header.

Validation failure writes a bounded `gpt2giga.error.v1` document, writes logs to
stderr, and exits `2`. Treat non-JSON stdout, content-bearing details, or a zero
exit with `valid != true` as a failed preflight.

## Runtime machine contract

After successful preflight, start the same installed artifact normally and use
these endpoints:

| Endpoint | Ready response | Not-ready behavior | Purpose |
|---|---:|---:|---|
| `GET /health` | `200` | Process unavailable | Liveness only. Do not use it as a traffic-readiness signal. |
| `GET /ready` | `200` `gpt2giga.readiness.v1` | `503` with the same versioned shape | Registry loaded, routes mounted, and all enabled provider clients initialized. |
| `GET /bridge/models` | `200` `gpt2giga.bridge-models.v1` | `503` | Lexically ordered public aliases and safe provider/capability/profile metadata. |
| `GET /bridge/capabilities` | `200` `gpt2giga.bridge-capabilities.v1` | `503` | Complete content-free 16-cell protocol/provider manifest. |

These endpoints never perform provider network calls. Cache a document only
with its `config_revision` and `matrix_revision`; a revision change after a
process restart invalidates earlier route planning. Details of the 16-cell
manifest are in [Bridge compatibility, loss, and errors](bridge-compatibility.md).

Readiness is stricter than liveness. Common content-free reason ids include
`registry_not_loaded`, `provider_clients_not_ready`, and
`gateway_shutting_down`. A supervisor should keep the process for diagnostics
while `/health` is live but `/ready` is false, subject to its own bounded startup
deadline.

## Sidecar startup sequence

For a GigaLoom-compatible or other external supervisor:

1. install a pinned wheel in the sidecar environment; do not use an editable
   sibling checkout;
2. write the profile document to a supervisor-owned protected path and inject
   credential values through the protected process environment;
3. run `--inspect-config` and accept only exit `0` plus valid redacted JSON;
4. start `gpt2giga --config <same-path>` without shell interpolation of secret
   values;
5. wait for `/health`, then require `/ready.ready == true` within a bounded
   deadline;
6. fetch `/bridge/models` and `/bridge/capabilities`, verify their schema and
   matching revisions, then route client traffic;
7. retain only content-free revisions/statuses in supervisor evidence unless a
   separate content-capture policy explicitly permits more.

GigaLoom owns its project/session/workbench state and process supervision.
`gpt2giga` owns the provider profile validation, public protocol routes,
admission decisions, and provider clients inside the gateway process. Neither
product imports the other's internal Python modules.

## Graceful shutdown

On SIGTERM or interrupt, the 0.3 contract is:

1. set readiness false and reject new model requests;
2. stop accepting new connections;
3. drain active requests up to the configured shutdown deadline;
4. cancel remaining upstream work;
5. close every owned provider client, sink, store, iterator, and network
   authorization;
6. exit non-zero only when cleanup violates its bound.

Wait for graceful exit before sending SIGKILL. A supervisor may use SIGKILL only
after its deadline. Shutdown must not trigger a retry through another alias,
provider, model, account, or credential.

## Rollback

No profile migration writes application or conversation state. Rollback is
therefore configuration/package based:

1. stop new traffic and terminate the 0.3 process gracefully;
2. either remove the profile path and restart 0.3 in synthesized GigaChat mode,
   or reinstall the pinned 0.2.x artifact;
3. restore the previously pinned client base URL and environment settings;
4. verify liveness and the legacy public route before restoring traffic.

Profile YAML/JSON files remain inert when not selected. Downgrading to 0.2.x
does not interpret them. Removing or disabling an alias must produce an unknown
alias error after restart; it must never silently remap traffic. A failed 0.3
startup must not expose a partially configured server, so no data repair is
needed after correcting the file and restarting.

The 0.2.x rollback does remove 0.3-only inspect, readiness, bridge-models, and
bridge-capabilities contracts. Supervisors must switch back to their pinned
0.2.x health/routing procedure rather than treating absent 0.3 endpoints as
provider failure.
