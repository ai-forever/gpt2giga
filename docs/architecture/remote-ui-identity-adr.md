# ADR: Remote UI identity boundary

Status: accepted for GigaLoom roadmap slice G3-04 on 2026-07-26.

Implementation status: not implemented. Remote UI binding remains fail-closed
until G3-05 satisfies this contract.

## Context

GigaLoom can read workspaces and start processes with the authority of its
operating-system account. The local UI therefore uses an OS-local, one-time
claim and server-side browser sessions. That local bootstrap proves proximity
to one OS account; it is not a remote user identity, tenant boundary, role
assignment, or auditable organization principal.

The former remote opt-in exchanged one shared environment bearer for one
process-local cookie. Even with TLS, Host checks, CSRF protection, and secure
cookies, that design could not distinguish operators, revoke one user, bind an
audit event to an identity, or safely recover a multi-user deployment.

Remote multi-user access is useful for a shared control plane, but accepting it
also makes identity-provider availability, session persistence, proxy trust,
role mapping, key rotation, logout, and incident recovery part of GigaLoom's
security boundary.

## Decision

Remote multi-user UI remains in the current roadmap scope, subject to a
separate G3-05 implementation and deployment gate. The supported identity
boundary is one deployment-owned, statically configured OpenID Connect issuer
per GigaLoom deployment.

GigaLoom will act as a confidential Backend for Frontend (BFF):

- use OpenID Connect Authorization Code flow with PKCE `S256`;
- keep client credentials, authorization codes, ID tokens, access tokens, and
  refresh tokens out of browser JavaScript and browser storage;
- expose only an opaque, host-only, `Secure`, `HttpOnly`, `SameSite=Strict`
  session cookie;
- retain authenticated sessions and revocation state server-side;
- send browser API requests only to the same GigaLoom origin;
- use the exact configured issuer, client identifier, external HTTPS origin,
  and registered callback URI.

The deployment profile admits only issuer metadata and algorithms that G3-05
explicitly reviews. There is no user-selected issuer, dynamic client
registration, implicit flow, password flow, local password database, social
login aggregation, or bearer-token paste form.

### Identity and roles

The stable remote actor is the exact `(iss, sub)` pair from a validated ID
token. Email address, display name, domain, and other mutable claims never
become identity keys.

G3-05 will implement two roles:

- `viewer`: authenticated read access to bounded product state, with no
  mutation, execution, approval, secret resolution, or integration change;
- `operator`: the same visibility plus access to mutation entry points, still
  bounded by the independent action-authority and approval system.

An unmapped subject or group is denied. Role mapping is deployment-owned,
default-deny configuration over exact signed claims; GigaLoom must not infer a
role from an email suffix. A role change rotates or revokes existing sessions.
Neither role changes the filesystem/process ceiling of the service account, so
deployments needing tenant isolation require separate GigaLoom instances and
OS isolation.

Audit receipts use a stable, non-display actor identifier derived from the
validated issuer and subject, the admitted role, session identifier, and
authentication time. Optional display claims may be shown ephemerally but are
not trusted for authorization.

### Login and session contract

Each login transaction has one-use, expiring `state`, `nonce`, and PKCE
verifier values bound to the initiating browser. The callback validates issuer,
signature, algorithm, audience, authorized party where applicable, expiry,
issued-at time, nonce, and the exact redirect URI before creating a session.
Unknown algorithms, metadata drift, key-fetch failure, replay, and clock values
outside a bounded skew fail closed.

Remote sessions have an absolute lifetime and a shorter idle lifetime. They
rotate at login, privilege change, and recovery. OAuth material is never
returned by UI APIs, stored in project state, or emitted to logs, diagnostics,
screenshots, traces, or audit receipts.

Every state-changing request requires the custom CSRF header and exact
same-origin validation in addition to the session cookie. `SameSite` alone is
not the complete CSRF defense.

### Logout, revocation, and recovery

Local logout revokes the GigaLoom server-side session before any provider
redirect. RP-initiated logout may then be used when the configured issuer
advertises and passes the reviewed capability contract.

G3-05 must support deployment-wide and actor/session-specific revocation. A
validated OpenID Connect back-channel logout token may revoke sessions by
issuer plus `sid` or `sub`; replayed, unsigned, mistyped, or incorrectly
audienced logout tokens fail closed. A provider without the admitted logout
capability receives only the bounded GigaLoom session lifetime and is reported
as degraded, not silently treated as fully revocable.

Bootstrap recovery is OS-local and cannot mint a remote browser session. It may
validate identity configuration, rotate GigaLoom session keys, and revoke all
remote sessions. If the issuer or trusted proxy is unavailable, remote login
is unavailable; the local bootstrap is never reused as a remote break-glass
credential.

### Proxy and origin policy

The public origin is one exact HTTPS scheme, host, and port. Direct HTTP remote
service is unsupported. Forwarded host, scheme, and client-address fields are
ignored unless the immediate peer matches an explicit trusted-proxy
configuration. Conflicting or multi-hop values outside that configuration are
rejected.

Allowed Hosts, callback URLs, post-logout redirects, and CORS are exact
allowlists. Wildcards and request-derived redirect targets are prohibited. TLS
termination, HSTS, request-size limits, rate limits, and trusted-proxy
configuration remain deployment responsibilities and must be checked by the
first-run doctor before remote mode can start.

## Threat model

| Threat | Required control |
| --- | --- |
| Shared bootstrap disclosure or replay | Remove it as a remote authenticator; reject non-loopback startup until G3-05 is configured. |
| Authorization-code interception or injection | Exact redirect URI, one-use transaction state, Authorization Code flow, PKCE `S256`, and nonce validation. |
| Issuer mix-up or token substitution | One exact issuer; validate `iss`, signature, algorithm, `aud`, `azp`, nonce, and key provenance. |
| CSRF or login CSRF | Browser-bound one-use login state, PKCE/nonce, exact Origin, strict cookie, and custom header on mutations. |
| Session fixation or cookie theft | Rotate opaque server-side sessions; host-only `Secure`, `HttpOnly`, strict cookie; bounded idle and absolute expiry. |
| Proxy-header spoofing or Host confusion | Trust forwarded fields only from explicit proxy peers; exact public origin and Host allowlist. |
| Role escalation through mutable claims | Default-deny exact mapping from validated claims; no email-domain inference; revoke on mapping change. |
| Stale access after logout or incident | Local, actor, and global revocation; admitted back-channel logout; bounded session lifetime. |
| XSS or compromised frontend asset | No OAuth tokens in the browser, no runtime third-party assets, CSP, output encoding, and server-side authorization on every request. |
| One user reaching another tenant's OS resources | Explicitly out of scope for one instance; use separate service accounts and deployments. |
| Identity-provider outage or lost configuration | Fail closed; OS-local configuration doctor and session-key/revocation recovery only. |

## Operational decision

The cost is acceptable only for this bounded single-issuer BFF profile. It
reuses GigaLoom's server-side request boundary while keeping provider tokens
away from the browser. It still requires durable session/revocation storage,
reviewed OIDC validation, rotation, proxy policy, role enforcement, audit
identity, hermetic fixtures, and deployment documentation.

Those costs are not accepted for multiple issuers, tenant isolation inside one
OS process, identity-provider hosting, SCIM, dynamic registration, local
password recovery, or live provider onboarding. Those remain out of scope.

## Transition and gates

Until G3-05 is implemented, GigaLoom accepts loopback UI binding only.
`--allow-remote`, the legacy bootstrap-token environment input, and remote Host
allowlists do not authorize a listener. A non-loopback host fails before the
FastAPI application or worker pool starts and reports that the OIDC contract is
not implemented.

G3-05 is authorized to implement this one profile using hermetic issuer
fixtures. It is not authorized to register a live client, configure secrets,
create users or groups, expose a callback publicly, deploy a reverse proxy, or
start a remote listener against a real identity provider. Each remains an
explicit external gate.

## Primary standards

- [OAuth 2.0 Security Best Current Practice (RFC 9700)](https://www.rfc-editor.org/rfc/rfc9700.html)
- [OAuth 2.0 for Browser-Based Applications (RFC 10017)](https://www.rfc-editor.org/rfc/rfc10017.html)
- [Proof Key for Code Exchange (RFC 7636)](https://www.rfc-editor.org/rfc/rfc7636.html)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [OpenID Connect Back-Channel Logout 1.0](https://openid.net/specs/openid-connect-backchannel-1_0-final.html)
- [OpenID Connect RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0-final.html)

## Consequences

The shared remote bearer exchange is no longer an available product mode.
Existing remote experiments must return to loopback until G3-05 and a separate
deployment authorization are complete. Local first-run, logout, rotation, and
recovery are unchanged.

This ADR authorizes only G3-05. It does not grant a remote identity, role,
action authority, network access, GitHub access, deployment, or live OIDC
configuration.
