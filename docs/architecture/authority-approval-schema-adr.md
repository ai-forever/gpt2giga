# ADR: Authority and approval schema

Status: accepted for GigaLoom roadmap slice G4-00 on 2026-07-27.

## Context

The Harness already has approval requests, grants, permission profiles, a
side-effect-free permission simulator, and hash-bound audit evidence. Their
current action taxonomy is an enforcement projection, not a complete authority
contract: a filesystem path is not a network endpoint, a GitHub repository is
not local Git, and changing an approval reviewer must not change the sandbox.

G4 needs one versioned source before adding approval UX, network grants, GitHub
grants, or first-run diagnostics.

## Decision

Schema version 1 is owned by `gpt2giga_harness.runtime.authority`. It models
eight target types separately:

- workspace-rooted filesystem paths;
- explicit subprocess executable plus content-addressed argv and cwd;
- network host, port, protocol, and redirect policy;
- exact GitHub `owner/repository`;
- exact browser origin;
- managed MCP server and optional tool;
- integration definition plus immutable revision;
- child agent plus its parent-ceiling digest.

Every scope contains a concrete target and a non-empty set of operation
classes. Its semantic payload is content-addressed. Approval previews are bound
by SHA-256, so secrets, file content, command arguments, and other raw inputs do
not need to enter grants or receipts.

`operation`, `session`, and `persisted_policy` are distinct lifetimes.
Persisted policy grants always expire. Every grant exposes its policy source,
reviewer kind and identity, enforcement boundary, preview digest, creation and
expiry, revocation, and optional parent grant.

The user-facing presets compile to explicit per-scope rules:

| Preset | Schema-v1 result |
| --- | --- |
| `always_ask` | Every concrete scope resolves to `ask`. |
| `ask_on_writes` | Only the frozen read-only operation set may resolve to `allow`; every other operation resolves to `ask`. |
| `allow_reviewed` | Only an exact scope and preview-digest pair in the reviewed set resolves to `allow`; all others resolve to `ask`. |

Human review and auto review are reviewer identities. They do not alter the
`enforced_by_harness`, `delegated_to_cli_sandbox`, or
`advisory_or_unobservable` boundary.

Child authority is valid only when the child target is identical to a target in
the parent ceiling and the child operations are a subset. G4-00 deliberately
chooses this strict rule; future code may add a separately reviewed narrower
target relation, but must never infer one from strings.

A revoked or expired grant, stale preview digest, changed target, redirect, or
retry requires revalidation. No prior approval may be rebound to the changed
operation.

## Compatibility

`gpt2giga_harness.runtime.policy.PermissionAction` remains the current
enforcement and persistence projection. G4-01 may map version-1 authority
scopes into those actions while it builds the approval UX and permission
simulator. Existing approval rows and grants are not migrated by G4-00.

Unknown schema versions, resource targets, presets, lifetimes, operations, and
invalid digests fail closed. The source-derived manifest is the documentation
and UI vocabulary authority.

## Consequences

G4-00 does not grant filesystem, process, network, GitHub, browser, MCP,
integration, or child-agent authority. It does not change sandbox settings,
persist new policy, revoke existing grants, access credentials, or perform live
mutations. G4-01 and later slices must consume this schema instead of creating
local target or lifetime vocabularies.
