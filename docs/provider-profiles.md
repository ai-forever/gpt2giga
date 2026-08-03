# Provider profiles and model aliases

Provider profiles are the startup-owned routing configuration for the 0.3
universal bridge. A client request selects either a reviewed public alias or a
model returned by the dynamic GigaChat inventory. The gateway resolves that
identity to one provider profile and effective model before execution.

Use profile mode when one gateway process must expose reviewed GigaChat,
OpenAI-compatible, Anthropic, or Gemini upstreams. The existing `GIGACHAT_*`
settings remain the compatibility default when no profile file is configured.

## Select one configuration file

Pass a UTF-8 YAML or JSON file explicitly:

```sh
gpt2giga --config /etc/gpt2giga/providers.yaml
```

or select it through the environment:

```dotenv
GPT2GIGA_CONFIG=/etc/gpt2giga/providers.yaml
```

Supplying the same path through both sources is valid. Two different paths are
a startup error; the gateway never merges profile documents. The file is read,
validated, and frozen once for the process lifetime. Version 0.3 does not
hot-reload it.

## Secure four-provider example

This example contains credential environment **names**, not credentials. Replace
the illustrative upstream model ids and policy references with values reviewed
for your deployment.

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

Provide the values separately, preferably through a secrets manager or the
service manager's protected environment:

```dotenv
GIGACHAT_CREDENTIALS=<secret-from-service-manager>
OPENAI_COMPATIBLE_API_KEY=<secret-from-service-manager>
ANTHROPIC_API_KEY=<secret-from-service-manager>
GEMINI_API_KEY=<secret-from-service-manager>
```

Do not add `api_key`, bearer tokens, arbitrary headers, client certificates, or
TLS-disable flags to the profile file. They are not schema fields and make
startup fail. `credential_env` must be an uppercase environment-variable name;
the enabled profile fails preflight when that variable has no value.

## Schema reference

| Field | Contract |
|---|---|
| `schema_version` | `gpt2giga.provider-profiles.v1` or `gpt2giga.provider-profiles.v2`; new files should use v2. |
| `profile_id` | Unique lowercase reviewed identifier. |
| `provider_kind` | `gigachat`, `openai_compatible`, `anthropic`, or `gemini`. |
| `base_url` | Canonical public HTTPS destination without userinfo, query, or fragment. |
| `credential_env` | Name of the environment variable holding the credential; never its value. |
| `network_policy_ref` | Identifier from the application's reviewed network-policy catalog. |
| `tls_policy_ref` | Identifier from the application's reviewed TLS-policy catalog. |
| `allow_loopback` | Defaults to `false`; permits only an explicit HTTP loopback development profile. |
| `model_inventory` | v2-only. `dynamic` is allowed only for one GigaChat profile; omitted means static aliases. |
| `models` | Exact public-alias bindings. Required for static profiles; optional aliases for dynamic GigaChat. |
| `public_alias` | Globally unique, case-sensitive model name accepted from clients. |
| `upstream_model` | Exact provider-owned model id; clients cannot override it. |
| `capability_profile` | Reviewed semantic capability set used during admission. |
| `support_status` | `stable`, `technical_preview`, or `blocked`. |
| `enabled` | Defaults to `true`; a disabled alias is not resolvable. |
| `deprecated` | Defaults to `false`; marks an alias without silently remapping it. |

Unknown fields, duplicate YAML/JSON keys, duplicate profile ids, and duplicate
aliases are rejected. Profile files are bounded to 1 MiB. Production
destinations require public HTTPS. Private, link-local, metadata, and loopback
addresses are rejected unless the profile is the explicit HTTP loopback
development exception. Redirects and request-supplied destination overrides
are not routing mechanisms.

Version 1 remains accepted unchanged and requires a non-empty `models` list for
every profile. It does not accept `model_inventory`. Version 2 makes provider
discovery explicit: `model_inventory: dynamic` removes the need to enumerate
every credential-visible GigaChat model, while any configured `models` entries
remain exact aliases rather than an inventory filter. Static external-provider
profiles continue to require at least one alias.

## Alias and revision behavior

Alias lookup is exact. Case changes, surrounding whitespace, missing aliases,
and disabled aliases return `unknown_model_alias`; they never select a similar
model or a different provider. A deprecated alias still resolves only to its
declared upstream model until it is disabled or removed on restart.

The gateway canonicalizes the secret-free document and assigns
`sha256:<lowercase-hex>` revisions to the full config and each profile. Model
discovery and execution evidence bind decisions to those revisions. Credential
values are not part of a revision and are never returned by model or capability
manifests.

The support decision for each client-protocol/provider combination is described
in [Bridge compatibility, loss, and errors](bridge-compatibility.md).
Startup preflight, supervisor lifecycle, migration, and rollback are described
in [0.3 migration and supervisor integration](migration-0-3.md).
