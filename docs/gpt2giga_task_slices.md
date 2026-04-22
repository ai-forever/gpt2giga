# gpt2giga Task Slices

Source documents:
- `docs/CODEX_GPT5_4_HIGH_HANDOFF.md`
- `docs/gpt2giga_codex_gpt54_high.md`
- `docs/gpt2giga_review_and_codex_brief.md`

This file is the consolidated execution backlog extracted from those three briefs.

## Fixed Workflow Rules

1. Each completed slice must be committed as a separate commit.
2. Do not leave a finished slice only in the working tree.
3. After each completed slice, update `docs/gpt2giga_task_progress.md`.
4. Each progress entry must include at least:
   - date
   - slice id
   - status
   - commit hash
   - brief summary
   - checks/tests run
5. Prefer small, test-backed slices over large cross-cutting rewrites.
6. If a slice touches frontend TS sources, regenerate compiled admin assets before closing it.

## Priority Order

## P0

### S1. CI guard for stale admin assets
Scope:
- add a CI step after `npm run build:admin`
- fail if generated files under `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` changed
- align docs/workflow if contributor expectations changed

Acceptance:
- a PR with changed TS source and stale compiled output fails CI
- a PR with regenerated assets passes

### S2. Frontend hotspot split: `files-batches`
Scope:
- split `gpt2giga/frontend/admin/pages/files-batches/bindings.ts`
- extract sub-feature modules for inventory, filters, inspector, upload/composer, preview/validation where justified
- preserve existing UX and routes

Acceptance:
- smaller modules with clearer boundaries
- no behavior drift
- tests added for extracted pure helpers

### S3. Frontend hotspot split: settings/setup
Scope:
- reduce size of `render-settings.ts`, `control-plane-sections.ts`, `render-setup.ts`
- move toward page-folder structure such as `api`, `state`, `serializers`, `view`, `bindings`
- keep frameworkless TypeScript approach

Acceptance:
- no giant 700-900+ line hubs without strong reason
- pure helpers covered by tests
- compiled assets regenerated

### S4. Frontend helper test baseline
Scope:
- add TypeScript unit tests for pure logic first
- cover route state / URL helpers
- cover traffic serializers and filters
- cover files-batches serializers and summaries
- cover settings diff/render helpers

Acceptance:
- frontend logic has a minimal regression net beyond `tsc`
- tests are runnable in CI

### S5. Backend refactor: batch validation
Scope:
- split `gpt2giga/features/batches/validation.py`
- separate parsing/JSONL diagnostics, format detection, structural checks, provider validators, report builders
- keep behavior stable

Acceptance:
- smaller composable validators/builders
- easier provider-rule extension
- targeted tests around current behavior

### S6. Backend refactor: responses input normalizer
Scope:
- split `gpt2giga/providers/gigachat/responses/input_normalizer.py`
- extract multimodal content normalization, tool/function-call normalization, history repair, message building
- preserve current public behavior/import surface

Acceptance:
- lower cognitive complexity
- targeted tests before/after extraction

### S7. Runtime typing hardening
Scope:
- reduce `Any` on runtime boundaries
- start with `gpt2giga/app/dependencies.py` and closely related contracts
- use `Protocol`, `TypedDict`, `dataclass`, or explicit DTOs where they improve safety

Acceptance:
- fewer weakly typed runtime contracts
- no public behavior change

### S8. Backend refactor: `ProxySettings`
Scope:
- split grouped concerns inside `gpt2giga/core/config/settings.py`
- isolate internal helper models by domain where possible
- preserve env compatibility and current access patterns

Acceptance:
- smaller and easier-to-reason-about settings structure
- tests for existing env aliases/grouped accessors

### S9. Backend refactor: admin settings/runtime services
Scope:
- reduce responsibility density in `gpt2giga/app/admin_settings.py` and `gpt2giga/app/admin_runtime.py`
- extract read-model builders, mutations, snapshots, usage/reporting helpers
- keep HTTP contract stable

Acceptance:
- smaller service modules
- targeted tests around compatibility-sensitive behavior

### S10. Architecture guardrail expansion
Scope:
- add dependency-direction tests
- protect rules such as:
  - routers stay thin
  - routers do not call provider transport details directly
  - provider modules do not depend on transport formatting helpers they should not know about
  - admin routes delegate to app/services
  - frontend pages use shared URL/state helpers

Acceptance:
- new tests fail on obvious layering regressions

## P1

### S11. Admin access helper cleanup
Scope:
- replace or wrap misleading helpers such as `verify_logs_ip_allowlist()` where responsibility is broader than logs
- improve naming without breaking compatibility needlessly

Acceptance:
- names reflect actual responsibility
- compatibility preserved where required

### S12. Typed DTOs for admin/settings payloads
Scope:
- replace the most important `dict[str, Any]` payloads on admin/settings surfaces
- add typed request/update models where it reduces refactor risk

Acceptance:
- fewer generic payloads at critical boundaries

### S13. Provider adapter deduplication
Scope:
- find normalization/mapping duplication across provider adapters
- extract shared internal contracts only where it reduces maintenance cost

Acceptance:
- less repeated logic without flattening provider-specific behavior

### S14. Frontend/browser smoke coverage
Scope:
- add 1-2 critical admin smoke scenarios first
- likely paths: `/admin`, `/admin/playground`, `/admin/files-batches`, `/admin/settings`

Acceptance:
- at least minimal browser-level regression signal for critical flows

### S15. Perf and large-data checks
Scope:
- add targeted perf or regression checks for streaming, batch validation, and admin inventory endpoints on larger datasets

Acceptance:
- basic signal for obvious slowdowns/regressions

## P2

### S16. Compatibility facade lifecycle policy
Scope:
- document which wrappers/facades are permanent public contracts
- document which ones are migration-only and removable later

Acceptance:
- less ambiguity around cleanup decisions

### S17. ADR/design note expansion
Scope:
- document disputed choices more explicitly:
  - frameworkless admin UI
  - committed compiled assets
  - feature vs provider boundary

Acceptance:
- contributors understand why these tradeoffs exist

### S18. Frontend packaging ergonomics
Scope:
- improve contributor workflow around source/build/output sync
- consider safer release packaging flow if/when pipeline changes

Acceptance:
- less manual drift risk and clearer workflow

### S19. Vendored wheel strategy review
Scope:
- revisit lifecycle/provenance policy for the vendored `gigachat` wheel
- decide whether current approach stays or gets a more explicit policy

Acceptance:
- strategy is explicit, not accidental

## Suggested Execution Sequence

1. `S1` CI guard for stale admin assets
2. `S4` frontend helper test baseline
3. `S2` frontend `files-batches` split
4. `S3` frontend settings/setup split
5. `S5` batch validation refactor
6. `S6` responses input normalizer refactor
7. `S7` runtime typing hardening
8. `S8` `ProxySettings` refactor
9. `S9` admin settings/runtime split
10. `S10` architecture guardrail expansion

## Slice Closure Checklist

Before marking a slice done:
- relevant tests added or updated
- targeted checks passed
- full checks run if scope justifies it
- compiled admin assets regenerated if TS changed
- progress recorded in `docs/gpt2giga_task_progress.md`
- separate commit created for the slice
