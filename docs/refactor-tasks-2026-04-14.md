# Refactor task list

Date: 2026-04-14

## Phase 0: quick wins

- [x] Remove stale documentation links and align repo navigation.
  - `README.md` references `ARCHITECTURE_v2.md`, but the file is absent.
  - Re-check references to operator/config docs and actual file names.
- [x] Add one current architecture note for contributors.
  - Cover request flow, provider mapping flow, runtime/control-plane flow, and admin UI structure.
- [x] Document admin frontend build workflow.
  - Explain that `gpt2giga/frontend/admin/` is source and `gpt2giga/static/admin/` is generated output.
- [x] Decide whether compiled admin assets must stay committed.
  - If yes, document when and how to rebuild them.
  - If no, update packaging/release flow before removing them from git.

## Phase 1: frontend simplification

- [ ] Split each large admin page into a directory-based slice.
  - Target first: `render-files-batches.ts`, `render-playground.ts`, `render-logs.ts`, `render-traffic.ts`.
  - Suggested shape per page:
    - `index.ts`
    - `api.ts`
    - `state.ts`
    - `render.ts`
    - `bindings.ts`
    - `serializers.ts`
- [ ] Extract shared page-controller utilities.
  - Common patterns now repeated:
    - loading state
    - cancellation/cleanup
    - query-string sync
    - form submit busy-state
    - inline status updates
    - event listener registration/unregistration
- [ ] Merge duplicated setup/settings form sections into reusable modules.
  - Shared candidates:
    - application section
    - GigaChat section
    - security section
    - control-plane status block
    - persist/test/save result messaging
- [ ] Reduce direct `innerHTML` usage on interactive pages.
  - Keep template strings for static fragments if desired.
  - Move highly interactive areas to targeted DOM updates with typed bindings.
- [ ] Introduce a page-local state model instead of scattered mutable locals.
  - Especially for:
    - logs stream page
    - playground run state
    - files/batches filters + selection state
    - traffic filters + pagination state
- [ ] Add minimal frontend verification.
  - At least one build check in CI already exists implicitly via TypeScript compile.
  - Add simple smoke coverage for core admin routes or rendering helpers.

## Phase 1.5: frontend i18n (RU/EN)

- [ ] Add a minimal i18n layer for the admin console.
  - Keep it framework-free.
  - Add `ru` and `en` dictionaries.
  - Add a tiny translation helper with stable keys.
- [ ] Decide the default language policy.
  - Suggested order:
    - explicit saved user choice
    - optional query param for testing/demo
    - browser locale
    - fallback to English
- [ ] Add a language switcher to the admin shell.
  - Put it in the left rail or top hero area.
  - Persist preference in browser storage.
- [ ] Replace hardcoded user-facing strings in shared modules first.
  - `templates.ts`
  - `app.ts`
  - common alerts/banners/empty states
- [ ] Replace hardcoded page strings in large admin pages.
  - Prioritize:
    - `render-setup.ts`
    - `render-settings.ts`
    - `render-playground.ts`
    - `render-logs.ts`
    - `render-traffic.ts`
    - `render-files-batches.ts`
- [ ] Standardize translation keys before large-scale replacement.
  - Group by page and shared UI area.
  - Avoid ad hoc free-form key naming.
- [ ] Localize page metadata too.
  - nav labels
  - page eyebrow/title/subtitle
  - CTA labels
  - filter labels
  - validation messages
  - warnings and empty states
- [ ] Add a rule for future frontend work.
  - No new operator-facing string should be introduced without a translation key.

## Phase 2: admin backend simplification

- [ ] Extract admin runtime payload builders from `gpt2giga/api/admin/runtime.py`.
  - Move route-independent shaping into dedicated modules/services.
- [ ] Extract control-plane mutation logic from `gpt2giga/api/admin/settings.py`.
  - Goal: route handlers become thin orchestration endpoints.
- [ ] Introduce explicit admin domain modules.
  - Suggested areas:
    - runtime_snapshot
    - capability_matrix
    - usage_reporting
    - control_plane_updates
    - key_management
- [ ] Unify repeated filtering/sorting/payload patterns in admin endpoints.
  - Request/error feeds
  - usage by key/provider
  - routes/capabilities/runtime summaries
- [ ] Add focused tests around extracted admin services before moving more code.

## Phase 3: provider-layer simplification

- [ ] Write a single request/response flow map for `providers/gigachat/`.
  - Explain v1 vs v2 path clearly.
  - Explain chat vs responses path clearly.
- [ ] Review naming across request/response mapper modules.
  - Reduce "near-duplicate names with different scope" where possible.
- [ ] Group Responses v2 helpers more coherently.
  - Current helper spread is wide enough to be hard to scan quickly.
- [ ] Identify dead compatibility shims and transitional code.
  - Remove only after verifying test coverage.
- [ ] Consider subpackages for response-v2 internals if naming cleanup is not enough.

## Phase 4: runtime and composition cleanup

- [ ] Slim down the composition root in `gpt2giga/app/factory.py`.
  - Keep middleware/routers there.
  - Move policy-building and route-registration details out where helpful.
- [ ] Slim down `gpt2giga/app/wiring.py`.
  - Extract provider/service assembly helpers so the wiring file reads as configuration, not construction detail.
- [ ] Revisit boundaries between:
  - config
  - control plane
  - runtime state
  - observability state
- [ ] Reduce implicit `app.state` knowledge required outside app/runtime modules.

## Suggested implementation order

- [x] Step 1: docs cleanup plus one current architecture document.
- [ ] Step 2: setup/settings frontend deduplication.
- [ ] Step 3: split `render-playground.ts` and `render-logs.ts`.
- [ ] Step 4: split `render-files-batches.ts` and `render-traffic.ts`.
- [ ] Step 5: extract admin backend services from `runtime.py` and `settings.py`.
- [ ] Step 6: provider-layer naming cleanup and pipeline docs.

## Concrete first PRs I would open

- [x] `docs:` fix stale architecture references and add current architecture note.
- [ ] `refactor:` extract shared admin settings/setup sections.
- [ ] `refactor:` split admin playground page into view/state/api modules.
- [ ] `refactor:` split admin logs page into stream/controller/render modules.
- [ ] `refactor:` extract admin runtime payload builders from route module.

## Success criteria

- [ ] New contributors can understand the admin frontend without reading 1k+ line files.
- [ ] Admin route files mostly delegate instead of building large payloads inline.
- [ ] Provider mapping flow can be explained in one short document.
- [ ] Docs reflect the real repo layout.
- [ ] Refactors preserve compatibility and keep existing tests green.
