# ADR: Scoped network access

Status: accepted for GigaLoom roadmap slice G4-02 on 2026-07-27.

## Context

The authority schema already distinguishes a network endpoint from filesystem,
process, GitHub, browser, MCP, integration, and child-agent authority. The
Approval Center can show a network target, but the prior interactive profile
still treated `network.connect` as ambiently allowed and no Harness-owned
transport contract defended the connection after approval.

Current Codex guidance keeps command network access off by default, separates
the sandbox boundary from approval policy, and applies allowlist-first
destination rules when network isolation is enabled. It also calls out
non-public address classification and transport-layer address pinning as
separate DNS-rebinding controls. GigaLoom adopts those boundaries without
copying a blanket internet toggle.

## Decision

`gpt2giga_harness.runtime.network_access` owns schema version 1 for
Harness-enforced outbound HTTPS. Authorization requires both:

1. an explicitly enabled sandbox network boundary; and
2. an unrevoked, unexpired, Harness-enforced `AuthorityGrant`.

The grant is bound to an exact host, port, protocol, safe-or-write method
class, redirect policy, content-free purpose, and preview digest. Request body
content is never retained: non-empty bodies are represented by byte count and
SHA-256. The requested response ceiling is also part of the preview.

The interactive permission profile now resolves `network.connect` to `ask`.
Intent, an interactive session, or provider selection cannot enable network
access by itself.

## SSRF and DNS rebinding boundary

Before a transport opens a socket, it supplies every resolved address to
`authorize_scoped_network_access`. Empty resolution, invalid addresses, and any
loopback, private, link-local, unspecified, multicast, reserved, or otherwise
non-public result fail closed. An IP-literal target must resolve to exactly that
literal.

Authorization returns a short-lived `NetworkAccessTicket` with the public
address set pinned. The transport must validate the connected peer against that
set before sending a request. A different peer fails closed. This makes DNS
classification and transport pinning explicit rather than claiming that one
pre-connect lookup eliminates rebinding.

Redirects are denied by default. A grant may admit `same_origin`, but every hop
must repeat scope, preview, expiry, allowlist, DNS, and peer validation.
Cross-origin redirects, changed method or purpose, and automatic retries require
fresh authority.

## Reviewed domain proxy policy

An optional `ReviewedDomainProxyPolicy` adds a second, auditable allowlist:

- the listener is an exact loopback IP;
- each exact, `*.example.com`, or `**.example.com` rule has explicit purposes,
  reviewer identity, and expiry;
- a global `*` rule is invalid;
- absence of a matching rule denies access;
- request and response body ceilings are bounded by hard schema limits;
- the normalized policy has a stable SHA-256 included in authorization
  receipts.

The policy class is the enforcement contract for a reviewed proxy transport; it
does not open a listener or send traffic. No existing provider, MCP, catalog, or
integration transport is activated automatically by this slice.

## Audit and privacy

Receipts expose the grant, scope, preview, policy, purpose, expiry, address
count, and hashes. They do not expose URL paths or queries, request bodies,
headers, credentials, or resolved addresses. Peer evidence records only the
peer-address hash.

## Consequences

G4-02 provides the reusable fail-closed seam for later Harness-owned network
consumers while preserving delegated provider sandboxes as a distinct
enforcement boundary. A consumer is not protected merely because it creates an
approval request; it must resolve through this contract and enforce the
returned ticket at connection and bounded-read time.

This slice performs no live DNS lookup, socket connection, proxy startup,
provider traffic, credential configuration, GitHub mutation, or deployment.

## References

- [Codex agent approvals and network security](https://learn.chatgpt.com/docs/agent-approvals-security)
- [Authority and approval schema](./authority-approval-schema-adr.md)
