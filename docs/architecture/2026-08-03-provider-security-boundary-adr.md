# ADR: provider credential, destination, TLS, and no-fallback boundary

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owners: provider-profiles, provider adapters, and integration lanes
- Boundary revision: `gpt2giga.provider-security.v1`

## Context

A universal bridge expands the set of destinations and credentials available to
the process. Without one startup-owned boundary, a compatibility field, header,
redirect, DNS result, or retry could become an unintended provider switch or
SSRF path. Existing GigaChat compatibility options and the internal
OpenAI-compatible network authorization provide useful mechanisms, but 0.3
needs one rule for every provider kind.

## Decision

### Authority and request boundary

Only the immutable provider profile selects provider kind, scheme, host, port,
base path, TLS policy, credential reference, and upstream model. Public request
bodies and headers may not override them. In particular, fields named
`base_url`, `url`, `provider`, `api_key`, `token`, `authorization`, TLS controls,
proxy controls, arbitrary headers, or upstream model ids are rejected before
I/O instead of being copied into provider extensions.

Client protocol headers are consumed only for the public wire/auth contract.
Adapters generate provider-required version/content headers and an explicit
allowlist of bounded trace ids. Profile schema v1 has no generic arbitrary
header map.

### Destination and DNS

- Production profiles require `https`.
- Plain `http` is permitted only for an explicitly marked loopback development
  profile and can never resolve outside loopback.
- Userinfo, fragments, ambiguous ports, unsupported schemes, and non-canonical
  hosts are invalid.
- Private, link-local, multicast, unspecified, loopback, and cloud metadata
  addresses are rejected unless the exact loopback development rule applies.
- Resolution produces a request-scoped network authorization bound to scheme,
  canonical host, port, resolved address set, method, body digest/size, purpose,
  response-size ceiling, and expiry.
- The connected peer is checked against the authorization. Provider SDKs that
  cannot expose this boundary are not publicly configurable until they use the
  shared controlled transport.
- HTTP redirects are disabled. A redirect response is a
  `destination_mismatch`; it is never followed automatically.

### TLS and credentials

TLS verification is on. A profile may reference a reviewed TLS policy by id;
requests may not disable verification or supply certificates. Hostname and
certificate validation must apply to the exact profile host.

Profiles store only an environment/SecretRef name. Enabled profiles resolve the
credential during preflight/startup; missing values fail startup with
`credential_unavailable`. Values are revealed only to the exact adapter client
construction/request boundary and are excluded from repr, errors, logs, traces,
metrics, inspect output, manifests, fixtures, and persistence. The bridge does
not accept per-request provider credentials. Legacy pass-token behavior remains
outside bridge-profile mode.

### Retry, cancellation, and fallback

Automatic provider, profile, alias, model, account, or credential fallback is
forbidden. A bounded retry may repeat the same idempotent operation against the
same exact profile/model only when its reviewed retry policy permits it and
before the first response event is exposed. Streaming interruption, client
disconnect, cancellation, destination mismatch, protocol error, and semantic
rejection are not cross-route retry signals.

All acquired model limits, network authorizations, response bodies, iterators,
and owned clients are closed on success, failure, timeout, or cancellation.

### Redacted evidence

Execution evidence may contain profile id, public alias, provider kind, upstream
model id, config/profile/matrix revisions, bounded error code, timings, byte
counts, and network-attempt count. It may not contain credential values,
credential hashes, raw auth headers, prompt/response/tool content by default,
or unrestricted provider error bodies.

## Migration and rollback

- Existing GigaChat environment settings feed only the synthesized legacy
  profile when no bridge config is present.
- Request-carried transport/provider fields that were previously ignored or
  forwarded now fail closed in bridge mode; this is an intentional security
  tightening documented by stable error codes.
- Removing the bridge config restores the legacy compatibility boundary on
  restart. Downgrading to 0.2.x leaves profile files and policy references inert.
