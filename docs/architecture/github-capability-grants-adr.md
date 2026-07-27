# ADR: GitHub capability grants

Status: accepted for GigaLoom roadmap slice G4-03 on 2026-07-27.

## Context

GigaLoom already has two deliberately different GitHub-related paths:

- `GitHubEnvironmentService` performs bounded, read-only repository
  orientation through reviewed `gh` commands;
- `GovernedEnvironmentPullRequestService` creates one exact pull request only
  after an approval bound to immutable local and hosted state.

Neither path makes local `git` equivalent to hosted GitHub authority. A local
commit or branch operation has different credentials, targets, enforcement,
and side effects from an authenticated GitHub API or CLI request.

GitHub CLI also separates the active account and host from each API request.
Its `gh api` command can change the HTTP method implicitly when fields are
provided, so GigaLoom must bind the operation class and reviewed payload rather
than trusting a command label. GitHub REST permissions are endpoint-specific
and may require more than one repository permission.

## Decision

`gpt2giga_harness.runtime.github_access` owns schema version 1 for the semantic
GitHub authority boundary. It classifies:

- `local_git` as separate, non-GitHub authority;
- `github_api` and `github_cli` as hosted GitHub authority;
- read-only orientation independently from issue, comment, pull-request, and
  release writes.

Every request binds one canonical `owner/repository`, one operation class, one
API or CLI surface, and one opaque credential binding. The credential binding
contains only its owner class, host, principal hash, permission-set hash, and
expiry when the credential owner discloses it. Tokens, account labels, and
credential storage paths never enter requests, approvals, or receipts.

This contract does not configure, refresh, switch, print, or otherwise resolve
GitHub credentials. In particular, GigaLoom never invokes token-revealing
`gh auth` options.

## Read-only orientation

`orientation.read` does not accept or consume mutation authority. This keeps
repository identity, pull-request state, issue/check counts, and recent Actions
orientation available without granting a hosted write.

Orientation still requires separately admitted network/CLI execution at the
actual transport boundary. The G4-03 contract is semantic authorization only;
it does not contact GitHub or weaken G4-02 network controls.

## Hosted writes

Issue, comment, pull-request, and release writes require:

1. an exact Harness-enforced `AuthorityGrant`;
2. operation lifetime rather than a session or persisted write grant;
3. an unrevoked grant with explicit expiry;
4. the same repository, operation class, credential binding, content-free
   resource identity, payload byte count, and payload SHA-256 as the reviewed
   preview;
5. a preview window of at most five minutes;
6. another validation immediately before dispatch.

Automatic retry is not covered by the prior grant. A retry, changed target,
changed payload, changed credential identity or permission set, expired
preview, or expired/revoked grant requires a fresh preview and decision.

Existing pull-request creation remains owned by its immutable-state service.
G4-03 provides the common semantic seam; it does not silently re-authorize or
execute that older flow.

## Audit and privacy

Receipts expose repository, operation class, API/CLI surface, credential
source class, hashes, byte counts, policy source, reviewer class, expiry, and
outcome. Resource and reviewer identities are hashed.

Receipts omit credential material, raw principals, write bodies, and direct
personal, contact, or payment data. Consumers must apply the same rule before
passing a preview to the shared Approval Center.

## Consequences

GigaLoom can reason about GitHub orientation and mutation without a blanket
“GitHub enabled” switch. A mutation consumer is not protected merely because
it uses `gh` or creates an approval request: it must enforce the exact ticket
at dispatch and retain the separate network boundary.

This slice performs no live GitHub read or write, login, credential setup,
push, issue/comment/PR mutation, release publication, or network request.

## References

- [GitHub CLI `gh auth status`](https://cli.github.com/manual/gh_auth_status)
- [GitHub CLI `gh api`](https://cli.github.com/manual/gh_api)
- [GitHub REST API permission troubleshooting](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api)
- [Authority and approval schema](./authority-approval-schema-adr.md)
- [Scoped network access](./scoped-network-access-adr.md)
