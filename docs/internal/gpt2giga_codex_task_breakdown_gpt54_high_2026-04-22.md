# gpt2giga — Codex task breakdown for GPT-5.4-high

Date: 2026-04-22
Audience: coding model working directly in the repository
Primary release target: **1.0.0**
Secondary target only if product owner explicitly decides otherwise: keep the release on the `1.0.0rc*` line a bit longer. Do **not** silently reframe the work as `0.2.0`.

## Why this file exists

The original Codex handoff describes the stabilization direction.
This file slices that direction into **PR-sized tasks** that can be executed independently by a coding model.

Default rule: **one task = one PR**.
Only bundle tasks when they are clearly the same subsystem and share the same acceptance tests.

## Progress

- [x] RLS-001 — done
- [x] RLS-002 — done
- [x] RLS-003 — done
- [x] RLS-004 — done
- [x] RLS-005 — done
- [x] RLS-006 — done
- [x] RLS-007 — done
- [x] RLS-008 — done
- [x] RLS-009 — done
- [x] RLS-010 — done
- [x] RLS-011 — done
- [x] RLS-012 — done
- [x] RLS-013 — done

---

## Operating assumptions for the coding model

- Treat the current local repository as the source of truth.
- Preserve architecture boundaries.
- Favor narrow diffs.
- Add or update tests with every behavior change.
- Keep comments/docstrings honest to the code.
- If TypeScript sources change, keep committed admin assets in sync.
- Do not introduce a frontend framework.
- Do not flatten provider/app/features/api layering.

Preferred source-of-truth order:

1. code
2. CI workflows
3. `README.md`
4. `docs/architecture.md`
5. `docs/design-notes.md`
6. `docs/operator-guide.md`
7. tests

---

## Task board

## P0 — release blockers

### RLS-001 — resolve the request body size enforcement honesty gap

**Why this matters**

`gpt2giga/api/middleware/request_validation.py` documents behavior for chunked or missing-`Content-Length` requests more strongly than the code currently guarantees.
For a 1.0 release, the implementation and documentation must match.

**Likely files**

- `gpt2giga/api/middleware/request_validation.py`
- `gpt2giga/app/factory.py`
- `tests/integration/app/` (new regression tests are acceptable)
- `tests/unit/` if helper extraction is introduced

**Scope**

Do one of these two outcomes:

1. preferred: implement real size enforcement for requests without `Content-Length`
2. fallback: narrow the docstring and any public docs immediately so behavior is explicit and honest

**Acceptance criteria**

- requests with oversized `Content-Length` still return `413`
- requests without `Content-Length` are either enforced correctly or explicitly documented as not enforced at middleware level
- tests cover both paths
- error shape remains consistent with existing `request_entity_too_large`

**Out of scope**

- broad request streaming redesign
- unrelated middleware cleanup

**Suggested verification**

- targeted pytest for request validation behavior
- a focused integration app test using `TestClient`

---

### RLS-002 — add a shared client-IP resolution policy with explicit proxy trust

**Why this matters**

Client IP is currently derived from `X-Forwarded-For` in multiple places with implicit trust.
That is too ambiguous for a major release.

**Likely files**

- `gpt2giga/api/admin/access.py`
- `gpt2giga/api/middleware/observability.py`
- `gpt2giga/app/_admin_settings/shared.py`
- `gpt2giga/core/config/` (new settings or grouped security settings if needed)
- `README.md` and/or `docs/configuration.md`
- `tests/unit/api/test_admin_access.py`
- `tests/integration/app/test_system_router_extra.py`

**Scope**

Introduce one shared helper or policy layer for resolving the client IP.
The default must be safe.
A direct client request must not be able to spoof admin allowlist behavior unless trusted proxy handling is explicitly enabled.

**Acceptance criteria**

- one canonical helper or policy for client IP resolution
- admin access and observability use the same semantics
- untrusted `X-Forwarded-For` does not bypass IP allowlist checks
- trusted-proxy mode is documented and tested

**Out of scope**

- full reverse-proxy product redesign
- adding unrelated auth features

**Suggested verification**

- unit tests for trusted and untrusted forwarded headers
- integration tests proving spoof prevention

---

### RLS-003 — apply the shared IP policy everywhere it matters

**Why this matters**

Even after introducing a shared helper, the repository still needs consistent adoption across admin, observability, and settings/runtime reporting paths.

**Likely files**

- `gpt2giga/api/admin/access.py`
- `gpt2giga/api/middleware/observability.py`
- `gpt2giga/app/_admin_settings/shared.py`
- any thin compatibility wrappers that still compute the IP separately

**Scope**

Replace duplicated IP extraction logic with the shared helper introduced by `RLS-002`.
Do not leave parallel implementations behind unless a compatibility shim is clearly intentional and documented.

**Acceptance criteria**

- duplicate logic is removed or turned into a thin wrapper around the shared helper
- admin allowlist, observability, and settings/runtime surfaces behave consistently
- tests still pass after the consolidation

**Dependency**

- `RLS-002`

---

### RLS-004 — sync release metadata and version surface

**Why this matters**

Release-facing metadata needs to stay coherent across package manifests and changelogs.
This task existed because the repository briefly presented itself as `1.0.0rc3`, while the top changelog entries still lagged behind.

**Likely files**

- `pyproject.toml`
- `packages/gpt2giga-ui/pyproject.toml`
- `CHANGELOG.md`
- `CHANGELOG_en.md`
- release notes drafts under `.github/` if needed

**Scope**

Align the package versions and the top changelog/release note entries with the chosen release target.
If the project is staying on the RC line briefly, keep that line coherent.
If the project cuts `1.0.0`, make all release-facing metadata reflect it.

**Acceptance criteria**

- package versions and changelog headers match
- English and Russian changelogs agree on the top version
- no stale `rc2` references remain where `rc3` or final `1.0.0` should be shown

**Status**

Completed in the current repository state: `pyproject.toml`, `packages/gpt2giga-ui/pyproject.toml`, `CHANGELOG.md`, and `CHANGELOG_en.md` are aligned on `1.0.0rc3`.

**Out of scope**

- marketing rewrite of the README

---

### RLS-005 — remove or relocate internal/stale AI planning docs from the public docs surface

**Why this matters**

The user-facing `docs/` tree currently includes internal AI handoff/planning files, some of which are stale.
That makes the docs surface less trustworthy.

**Likely files**

- `docs/README.md`
- `docs/CODEX_GPT5_4_HIGH_HANDOFF.md`
- `docs/gpt2giga_codex_gpt54_high.md`
- `docs/gpt2giga_review_and_codex_brief.md`
- `docs/gpt2giga_task_progress.md`
- `docs/gpt2giga_task_slices.md`
- any doc index or docs-links asset references that surface these files

**Scope**

Choose one clean outcome:

1. move internal planning/handoff material out of the public docs tree, or
2. clearly isolate it under an `internal/` or similarly non-canonical location and remove it from user-facing indexes

**Acceptance criteria**

- the public docs index is clearly canonical
- stale internal docs are not presented as normal operator documentation
- any user-facing docs links stop pointing at internal planning notes unless explicitly marked internal

**Status**

Completed in the tracked repository state: the task breakdown now lives under `docs/internal/`, and `docs/README.md` explicitly defines the canonical user-facing docs surface separately from internal working notes.

**Out of scope**

- deleting useful architectural docs

---

### RLS-006 — add a real `0.1.x -> 1.0.0` upgrade guide

**Why this matters**

The repository has expanded from a proxy into a larger operator platform.
A major release needs a migration story.

**Likely files**

- `docs/README.md`
- new file such as `docs/upgrade-0.x-to-1.0.md`
- `README.md` if a link should be surfaced there
- `docs/operator-guide.md` if rollout steps belong there

**Scope**

Write an upgrade guide that explains:

- what changed conceptually
- what is compatible
- what is not
- what operators should verify after upgrade
- how UI packaging works now if relevant
- what environment/config migration risks exist

**Acceptance criteria**

- guide is linked from a canonical docs entry point
- guide is specific, not generic prose
- operators can follow it without reading internal design notes

**Status**

Completed in the tracked repository state: `docs/upgrade-0.x-to-1.0.md` provides an operator-oriented migration path, and the guide is linked from `docs/README.md`, `README.md`, and `docs/operator-guide.md`.

---

### RLS-007 — document the stable/partial/experimental support boundary

**Why this matters**

A 1.0 release does not require every route to be fully implemented.
It does require clear promises about what is stable versus partial or experimental.

**Likely files**

- `README.md`
- `docs/api-compatibility.md`
- `docs/operator-guide.md`
- admin docs links or operator copy if it references feature maturity

**Scope**

Turn the current compatibility story into an explicit support boundary.
Use labels such as stable, partial, beta, experimental, or unsupported where needed.
Be honest about `501`/partial routes and provider-specific limitations.

**Acceptance criteria**

- a reader can tell what 1.0 commits to
- provider/endpoint maturity is clearly labeled
- docs do not oversell incomplete surfaces

**Status**

Completed in the tracked repository state: `README.md`, `docs/api-compatibility.md`, and `docs/operator-guide.md` now define an explicit `Stable`/`Partial`/`Unsupported` support boundary for the 1.0 release line.

---

### RLS-008 — expand backend regression coverage for settings diff/apply/rollback and secret masking

**Why this matters**

The setup/settings flow is a trust-critical part of the product.
It deserves stronger regression protection before the major release.

**Likely files**

- `tests/integration/app/test_admin_console_settings.py`
- `gpt2giga/app/_admin_settings/`
- `gpt2giga/app/_admin_runtime/`

**Scope**

Add focused tests around:

- revision history behavior
- rollback behavior
- apply-after-rollback correctness
- secret masking in payloads and previews
- security-related settings serialization

**Acceptance criteria**

- tests are behavior-oriented, not snapshot noise
- critical settings flows are covered by regression tests
- secret fields do not leak in admin previews or responses

**Status**

Completed in the current repository state: admin settings coverage now includes
rollback followed by partial re-apply, masked secret previews in revision
snapshots and rollback payloads, and focused unit coverage for safe
security/GigaChat settings serialization.

---

### RLS-009 — expand provider golden tests for high-risk compatibility edges

**Why this matters**

The public value of `gpt2giga` is compatibility.
The expensive regressions are usually in edge-case mapping and streaming semantics.

**Likely files**

- `tests/unit/providers/`
- `tests/integration/` if route-level coverage is needed
- provider mapping modules under `gpt2giga/providers/`
- feature services under `gpt2giga/features/`

**Scope**

Add or strengthen golden behavior tests for:

- streaming
- tool calls / tool results
- multimodal content blocks
- structured outputs where relevant
- error mapping
- path normalization edge cases

**Acceptance criteria**

- tests are stable and focused
- fixtures are readable
- at least the highest-risk provider compatibility edges are guarded

**Status**

Completed in the current repository state: provider regression coverage now
locks down v2-to-legacy chat tool-call normalization, Gemini response-builder
structured-output and provider-error coercion, and Anthropic response ordering
plus non-object tool-argument normalization.

---

## P1 — stabilization refactors with bounded scope

### RLS-010 — extract pure helpers from `features/files_batches/service.py`

**Why this matters**

`gpt2giga/features/files_batches/service.py` is a hotspot at roughly 900 lines and contains a lot of behavior-heavy branching.
It is a likely regression source.

**Likely files**

- `gpt2giga/features/files_batches/service.py`
- new helper modules under `gpt2giga/features/files_batches/`
- `tests/unit/features/files_batches/`

**Scope**

Perform a narrow extraction refactor.
Prefer pulling out pure normalization, validation, or payload-construction helpers first.
Keep the public service entrypoints unchanged.

**Acceptance criteria**

- smaller helpers with direct tests
- no public behavior regression

**Status**

Completed in the current repository state: creation-specific pure helpers now
live in `features/files_batches/creation.py`, the service delegates provider
metadata/fallback-model preparation there, and the extracted helper module has
direct unit coverage.
- main service becomes easier to scan

**Out of scope**

- redesigning the files/batches feature architecture

---

### RLS-011 — thin down `api/admin/files_batches.py` without changing route behavior

**Why this matters**

The admin files/batches router is large enough that even simple behavior changes become expensive to reason about.

**Likely files**

- `gpt2giga/api/admin/files_batches.py`
- new route-helper modules if needed
- `tests/integration/app/test_admin_files_batches_api.py`

**Scope**

Extract request parsing, response shaping, or shared error/detail shaping into small helpers.
Leave route names, payload shapes, and route registration behavior intact.

**Acceptance criteria**

- router is thinner
- extracted logic has tests where practical
- route contracts remain stable

**Status**

Completed in the current repository state: route-scoped parsing, preview
response shaping, staged/inline batch-input resolution, and batch-output
loading helpers now live in `api/admin/files_batches_helpers.py`. The router
delegates through the shared helper context, direct helper coverage lives in
`tests/unit/api/test_admin_files_batches_helpers.py`, and the existing admin
files/batches integration suite stays green.

---

### RLS-012 — split `frontend/admin/pages/files-batches/serializers.ts` into focused helpers

**Why this matters**

The current serializer module is very large and likely mixes unrelated concerns.
It is a prime target for low-risk extraction.

**Likely files**

- `gpt2giga/frontend/admin/pages/files-batches/serializers.ts`
- new serializer helper modules under the same page folder
- staged assets under `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/pages/files-batches/`
- frontend tests if present or helpful

**Scope**

Extract pure mapping/serialization helpers.
Keep the current public imports stable if the page still imports from `serializers.ts`.
A thin facade re-export is acceptable.

**Acceptance criteria**

- serialization helpers are separated by concern
- asset build output is refreshed and committed
- no UI behavior regressions

**Status**

Completed in the current repository state: the files/batches serializer surface is
now split into focused `serializers-filters.ts`, `serializers-inventory.ts`, and
`serializers-preview.ts` helper modules, while `serializers.ts` remains a thin
facade that preserves existing imports. Frontend coverage now exercises the
extracted inventory and preview helpers directly, and the committed admin assets
have been rebuilt in sync.

---

### RLS-013 — continue splitting files-batches bindings with focus on inventory and batch composer

**Why this matters**

The bindings already show page-folder discipline, but the `inventory` and `batch-composer` modules are still hotspot-sized.

**Likely files**

- `gpt2giga/frontend/admin/pages/files-batches/bindings/inventory.ts`
- `gpt2giga/frontend/admin/pages/files-batches/bindings/batch-composer.ts`
- sibling helper modules under the same folder
- staged assets package copy

**Scope**

Extract focused helpers for form-state derivation, event binding, filter interpretation, or DOM update logic.
Avoid changing DOM ids and HTTP payload contracts.

**Acceptance criteria**

- bindings modules shrink meaningfully
- extracted helpers are named by responsibility
- admin assets stay in sync

**Status**

Completed in the current repository state: files/batches binding orchestration is
now split further through `bindings/inventory-selection.ts` and
`bindings/batch-composer-state.ts`, with `inventory.ts` and
`batch-composer.ts` delegating selection-surface and composer-state derivation
instead of inlining that logic. Frontend coverage now directly exercises the
new helper modules, and the committed admin assets have been rebuilt in sync.

---

### RLS-014 — split `frontend/admin/pages/traffic/view.ts` into render helpers

**Why this matters**

Traffic inspection is an operator-critical surface, and the view module is large.
The safest improvement is render-helper extraction.

**Likely files**

- `gpt2giga/frontend/admin/pages/traffic/view.ts`
- new helper modules under the traffic page folder
- staged admin assets

**Scope**

Extract pure render/build helpers for repeated cards, metadata blocks, empty states, or status formatting.
Do not redesign the page.

**Acceptance criteria**

- main view file is thinner and easier to review
- render logic gets more localized tests where reasonable
- no copy or DOM regressions

---

### RLS-015 — split `frontend/admin/forms.ts` into smaller parsing/normalization helpers

**Why this matters**

`forms.ts` appears to serve as shared UI plumbing and is large enough to become a hidden coupling point.

**Likely files**

- `gpt2giga/frontend/admin/forms.ts`
- new helper modules under `gpt2giga/frontend/admin/`
- staged assets copy

**Scope**

Extract pure helpers for CSV parsing, coercion, field reading, or shared normalization.
Keep external call sites stable wherever possible.

**Acceptance criteria**

- reduced file size and better responsibility separation
- no regression in existing pages using shared forms helpers
- assets rebuilt and committed

---

### RLS-016 — make `app/factory.py` and `app/wiring.py` slightly easier to reason about

**Why this matters**

These files are not the biggest in the repository, but they are central.
Even small clarity improvements pay off.

**Likely files**

- `gpt2giga/app/factory.py`
- `gpt2giga/app/wiring.py`
- tests around app creation or runtime wiring if available

**Scope**

Extract narrowly scoped helper functions where setup intent becomes clearer:

- middleware mounting
- router registration
- service assembly
- provider feature wiring

Keep startup behavior identical.

**Acceptance criteria**

- fewer long imperative blocks
- no startup behavior regression
- app construction remains easy to trace

---

## P2 — release polish and guardrails

### RLS-017 — add a release gate checklist for the 1.0 line

**Why this matters**

The repository now has enough moving parts that a human-readable release gate is worth having.

**Likely files**

- new doc such as `docs/release-checklist.md`
- `.github/PULL_REQUEST_TEMPLATE.md` if a lightweight reminder belongs there
- release workflow notes if appropriate

**Scope**

Create a checklist covering:

- version sync
- changelog sync
- upgrade guide link
- docs index sanity
- backend tests
- admin UI tests/build
- asset sync verification
- docker smoke if part of the normal release flow

**Acceptance criteria**

- checklist is short, real, and usable
- it matches the repository’s actual release mechanics

---

### RLS-018 — audit admin docs links and operator copy after docs cleanup

**Why this matters**

The repository ships operator-facing admin assets and helper links.
After docs cleanup, those links should point at canonical docs.

**Likely files**

- `gpt2giga/frontend/admin/**/docs-links*`
- staged admin assets
- `docs/README.md`

**Scope**

Update any admin docs links, “operator guides” references, or help-copy surfaces so they point to stable documentation rather than internal planning notes.

**Acceptance criteria**

- admin links only surface canonical docs
- copy still matches the shipped features
- assets are synced

---

## Recommended execution order

1. `RLS-001`
2. `RLS-002`
3. `RLS-003`
4. `RLS-004`
5. `RLS-005`
6. `RLS-006`
7. `RLS-007`
8. `RLS-008`
9. `RLS-009`
10. `RLS-018`
11. `RLS-010`
12. `RLS-011`
13. `RLS-012`
14. `RLS-013`
15. `RLS-014`
16. `RLS-015`
17. `RLS-016`
18. `RLS-017`

---

## Definition of done for any task

A task is not done unless:

- architecture boundaries remain intact
- tests cover the changed behavior
- docs/comments match the real implementation
- admin assets are synced if TS changed
- no release/config drift was introduced accidentally

---

## Recommended release-positioning decision

Unless the product owner explicitly expects another round of near-term contract churn, treat this repository as a **1.0 release candidate line**.
The right move is to finish the stabilization work above and release `1.0.0`, not to relabel the effort as `0.2.0`.

The practical fallback is **another RC**, not a return to a smaller-looking minor version.
