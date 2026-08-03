# ADR: startup-owned provider profiles and public model aliases

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owners: provider-profiles and integration lanes
- Schema revision: `gpt2giga.provider-profiles.v1`
- Execution-context revision: `gpt2giga.execution-context.v1`

## Context

The bridge must separate client protocol, public model alias, upstream provider,
upstream model id, capability profile, and loss-matrix revision. A request may
choose only the public alias. Current GigaChat settings and `pass_model` behavior
do not provide that separation, and the internal OpenAI-compatible profile is
not yet a process-wide public registry.

## Decision

### Startup contract and precedence

The server accepts one bridge config path:

```text
gpt2giga --config <path>
GPT2GIGA_CONFIG=<path> gpt2giga
```

An explicit `--config` wins over `GPT2GIGA_CONFIG`. Supplying two different
paths is an `invalid_profile` error. When neither is present, 0.3 synthesizes one
legacy GigaChat profile from the existing `GIGACHAT_*` settings; this preserves
the current default installation but does not enable other providers.

When a bridge config is present it is authoritative for provider destinations,
credentials, models, capabilities, and aliases. Request payloads, compatibility
headers, and legacy `pass_model` cannot add or mutate profiles.

### Versioned schema

The logical YAML/JSON shape is:

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

Unknown schema fields are rejected. `schema_version`, `profile_id`,
`provider_kind`, destination, policy references, credential environment name,
and at least one model are required. Plaintext secret fields do not exist in the
schema. `profile_id` and `public_alias` are globally unique after Unicode and
whitespace validation; aliases are case-sensitive and are never guessed.

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

### Alias resolution

Alias resolution completes before semantic admission and provider I/O:

```text
public alias -> exact profile -> exact upstream model
             -> capability profile -> loss matrix revision
```

Unknown, ambiguous, disabled, or deprecated aliases do not select a replacement.
`/bridge/models` returns aliases in lexical order with provider kind, support
status, and safe revisions only. Protocol-specific `/models` projections derive
from the same registry.

### Validation errors

Startup/preflight uses stable codes: `invalid_profile_schema`,
`duplicate_profile_id`, `duplicate_model_alias`, `invalid_destination`,
`credential_unavailable`, and `invalid_policy_reference`. Runtime alias lookup
uses `unknown_model_alias`. No error contains a credential value.

## Migration and rollback

- Without a config path, the synthesized GigaChat profile retains the current
  environment/CLI defaults and documented public routes.
- `pass_model` remains a legacy-mode concern; it cannot alter bridge aliases.
- Removing `--config` returns to the synthesized GigaChat profile on restart.
- Downgrading to 0.2.x ignores the standalone profile file and requires no data
  migration.
