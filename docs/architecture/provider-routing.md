# Provider routing and model aliases

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owners: provider-profiles and integration lanes
- Schema revisions: `gpt2giga.provider-profiles.v1`, `gpt2giga.provider-profiles.v2`
- Execution-context revision: `gpt2giga.execution-context.v1`

## Context

The bridge must separate route configuration, public model identity, upstream
provider, provider-visible inventory, selected model, capability evidence, and
loss-matrix revision. Provider profiles are stable execution configuration;
they must not become the sole owner of dynamic model inventory.

## Decision

### Startup contract and precedence

The server accepts one bridge config path:

```text
gpt2giga --config <path>
GPT2GIGA_CONFIG=<path> gpt2giga
```

An explicit `--config` wins over `GPT2GIGA_CONFIG`. Supplying two different
paths is an `invalid_profile` error. When neither is present, 0.3 creates one
built-in GigaChat route from the existing `GIGACHAT_*` connection settings;
this preserves the current default installation but does not enable other
providers.

When a bridge config is present it is authoritative for provider destinations,
credentials, immutable aliases, route enablement, and route policy. Request
payloads and compatibility headers cannot add or mutate profiles. Dynamic
GigaChat inventory remains provider-discovered even when route aliases or a
default model are configured.

### Model catalog ownership

One `ModelCatalog` owns the model snapshot used by public `/models`
projections, `/bridge/models`, selected-model validation, and capability
admission. GigaChat discovery uses the authenticated provider models API. A
provider profile may define exact immutable aliases, but those aliases are
routes, not proof that the complete provider inventory contains only those
models.

`GIGACHAT_MODEL` is a default-model or explicitly documented forced-model
policy. It never replaces or filters the provider-visible catalog. A new model
returned by the provider remains visible even when its effective capabilities
are still `unknown`.

### Versioned schema

Version 1 remains the static-alias compatibility schema. Version 2 adds an
explicit dynamic inventory mode:

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
```

Unknown schema fields are rejected. `schema_version`, `profile_id`,
`provider_kind`, destination, policy references, and credential environment
name are required. Version 1 and static version 2 profiles require at least one
model alias. Version 2 permits `model_inventory: dynamic` only for one GigaChat
profile; its alias list is optional policy and never filters discovery.
Plaintext secret fields do not exist in the schema. `profile_id` and
`public_alias` are globally unique after Unicode and whitespace validation;
aliases are case-sensitive and are never guessed.

### Canonical digest and immutability

After validation the secret-free model is serialized as UTF-8 canonical JSON
with sorted object keys, compact separators, and source array order preserved.
Its revision is `sha256:<lowercase-hex>`. The loaded set is immutable for the
process lifetime. 0.3 does not hot-reload profiles.

The redacted execution context records:

```json
{
  "schema_version": "gpt2giga.execution-context.v1",
  "config_revision": "sha256:...",
  "profile_id": "anthropic-main",
  "public_alias": "anthropic/opus",
  "provider_kind": "anthropic",
  "upstream_model": "exact-provider-model-id",
  "capability_profile": "anthropic-opus-v1",
  "loss_matrix_revision": "sha256:..."
}
```

Credential names may appear in config inspection; values, hashes of values, and
authorization headers may not.

### Route and model resolution

Route and selected-model resolution complete before semantic admission and
provider execution:

```text
public model/alias -> exact provider route -> effective model
                   -> catalog revision -> effective capability revision
```

Unknown, ambiguous, disabled, or deprecated aliases do not select a replacement.
An unavailable model does not select a replacement. `/bridge/models` and every
protocol-specific `/models` projection derive from the same catalog snapshot
and expose its safe inventory revision.

### Validation errors

Startup/preflight uses stable codes: `invalid_profile_schema`,
`duplicate_profile_id`, `duplicate_model_alias`, `invalid_destination`,
`credential_unavailable`, and `invalid_policy_reference`. Runtime alias lookup
uses `unknown_model_alias`. No error contains a credential value.

## Migration and rollback

- Without a config path, the built-in GigaChat route retains the current
  connection defaults and documented public routes.
- Existing exact aliases in explicit bridge profiles retain their route
  identity; they do not narrow dynamic GigaChat discovery.
- Removing `--config` returns to the built-in GigaChat route on restart.
- Downgrading to 0.2.x ignores the standalone profile file and requires no data
  migration.
