# gpt2giga: general overview and refactoring notes

Date: 2026-04-14

Status note as of 2026-04-16:

- This document is the baseline overview that informed the Codex refactor plan.
- Several high-risk items mentioned below are already addressed:
  - shipped admin assets now have a single source of truth in `packages/gpt2giga-ui/src/gpt2giga_ui/static/`;
  - `api/admin/runtime.py` and `api/admin/settings.py` are thin HTTP layers over `app/admin_runtime.py` and `app/admin_settings.py`;
  - the four heaviest admin pages were split into page-slice modules;
  - native Responses v2 helpers now live under `gpt2giga/providers/gigachat/responses/`, with top-level `responses_*` modules kept only as compatibility wrappers.
- Use this overview together with `docs/architecture.md` and `docs/codex-gpt-5.4-progress.md`, not as the single source of current structure.

## Executive summary

`gpt2giga` is already more than a thin protocol adapter. In practice it is an integration gateway with four distinct responsibilities:

1. Protocol translation: OpenAI, Anthropic, Gemini, LiteLLM-compatible surfaces.
2. Provider adaptation: request/response mapping into GigaChat v1/v2.
3. Runtime platform: config loading, control plane, telemetry, runtime stores, governance, auth.
4. Operator product: a fairly large admin console with setup, settings, logs, traffic, playground, keys, files, batches, and system views.

The project is useful and already reasonably structured, but it has crossed the threshold where "modular files" no longer automatically mean "simple system". The main simplification opportunity is not cosmetic cleanup. It is reducing the number of concepts a contributor must keep in their head at once.

## What the repository looks like

- Backend shape is sane at a high level: `api -> features -> providers/gigachat -> SDK`.
- The project surface is broad:
  - `149` Python files under `gpt2giga/`
  - `54` test files
  - `19` admin TypeScript source files
  - about `23.8k` Python LOC in `gpt2giga/`
  - about `9.3k` admin TS LOC in `gpt2giga/frontend/admin/`
  - compiled admin JS is shipped from `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`
- The repo contains strong supporting assets: examples, docs, integration guides, Docker/Traefik, CI, PR template, tests by layer.

## What is good already

### 1. The backend architecture has a real shape

There is a visible layering model and it is not fake:

- transport and compatibility routes in `gpt2giga/api/`
- use-case orchestration in `gpt2giga/features/`
- provider-specific transformation logic in `gpt2giga/providers/gigachat/`
- runtime wiring in `gpt2giga/app/`

This is much better than a route-centric FastAPI codebase where everything lives in handlers.

### 2. The feature split is meaningful

The split into chat, responses, files, batches, embeddings, models is coherent. It matches real product surfaces and makes the repo navigable.

### 3. The project has operator thinking

The runtime/config/control-plane/admin effort is substantial. This is not just a demo proxy. It is clearly evolving toward an operable gateway.

### 4. The test and docs posture is above average

The repo has unit/integration/smoke structure, runnable examples, and integration docs for real tools. That is a good base for safe refactoring.

## Where complexity is accumulating

## 1. Admin/control-plane is becoming a second product inside the repo

This is the strongest architectural signal.

Files and modules like:

- `gpt2giga/app/admin_runtime.py`
- `gpt2giga/app/admin_settings.py`
- `gpt2giga/app/telemetry.py`
- `gpt2giga/app/runtime_backends.py`

show that the repository is not only a proxy anymore. It is also building an operator platform. That is valid, but it means simplification should treat admin/control-plane as a first-class subsystem, not as "just some endpoints".

My read: the core proxy path is still understandable; the operational layer is where most "too much is piled on" pressure now lives.

## 2. The GigaChat provider layer is conceptually correct, but cognitively dense

The provider directory is split into many focused modules, which is good, but there are now too many similarly named stages:

- `request_mapper.py`
- `request_mapping_base.py`
- `chat_request_mapper.py`
- `responses/`
- `response_mapper.py`
- `response_mapping_common.py`
- compatibility `responses_*` wrappers

This suggests local modularity but global complexity. A new contributor likely understands each file only after first understanding the whole pipeline. That is a sign the abstraction graph needs pruning or stronger grouping.

## 3. Runtime wiring is centralized but still broad

`gpt2giga/app/factory.py` is reasonable, but the app startup model still spans many concerns:

- middleware order
- provider route inclusion
- auth policy
- admin mounting
- metrics
- root redirect behavior
- config/bootstrap checks

`gpt2giga/app/wiring.py` is cleaner, but it still constructs many services/providers inline. It works, yet it is close to "composition root as a god factory".

## 4. Frontend is modular by file, but not simple in interaction model

The admin frontend was the clearest simplification candidate.

At the time of this baseline review, the biggest hotspots were giant page renderers such as:

- `render-files-batches.ts`
- `render-playground.ts`
- `render-logs.ts`
- `render-traffic.ts`
- `render-setup.ts`
- `render-settings.ts`

Those pages have since been split into slice-local modules, but the core observation still matters: the UI complexity was caused by mixed responsibilities, not by the lack of a framework.

Operationally it is a vanilla TypeScript SPA built around:

- string templates
- `innerHTML`
- page-local DOM queries
- page-local event listener registration
- manual state sync

This is workable for a small console, but the current console is no longer small.

The main frontend issue is not "plain TS instead of framework". Plain TS is fine. The issue is that each page is now doing rendering, state, effects, DOM wiring, validation, network orchestration, and UX flow in the same module.

## 5. Setup and settings look partially duplicated

The historical diff between `render-setup.ts` and `render-settings.ts` showed strong overlap in:

- application form rendering
- GigaChat form rendering
- security form rendering
- persistence/runtime status messaging
- save/test flow mechanics

That overlap is now reduced via shared control-plane form bindings, but the underlying design lesson remains valid.

## 6. Source and compiled admin assets live side by side

Historically the repository kept:

- source in `gpt2giga/frontend/admin/`
- compiled output in a shipped tree alongside it

That issue is now resolved by shipping compiled assets from `packages/gpt2giga-ui/src/gpt2giga_ui/static/`, but it is still a useful reminder of why the packaging flow had to be clarified first.

## 7. Documentation is mostly good, but navigation is drifting

Concrete example: `README.md` links to `ARCHITECTURE_v2.md`, but that file is not present in the repo. This is a small but useful signal that the conceptual model is changing faster than the docs map.

## Frontend-specific assessment

## Internationalization should be planned now, not later

I agree that the admin frontend should support at least two languages: Russian and English.

Right now the console is text-heavy and almost all strings are embedded directly in page renderers and templates. That means adding i18n later will be more expensive if the current structure is preserved.

This is another reason to simplify the frontend first:

- today many labels/messages are hardcoded inside large page modules
- setup/settings/playground/logs pages contain a lot of operator-facing copy
- mixed concerns already make pages large; adding a second language on top of that in the current form will worsen it

My recommendation is to treat i18n as part of the frontend refactor, not as a separate late-stage polish task.

## How I would implement bilingual support

I would keep it simple and avoid bringing a frontend framework just for localization.

Good fit for the current stack:

- a small `i18n.ts` module
- dictionaries like `en.ts` and `ru.ts`
- stable translation keys instead of inline strings
- one language resolver:
  - saved browser preference
  - optional query param for testing
  - fallback to browser locale
  - final fallback to English
- formatting helpers for:
  - static labels
  - button text
  - warnings/errors
  - empty states
  - page titles/subtitles

The main rule should be: no new user-facing strings directly inside page modules.

## What the live MCP browser pass confirmed

I opened the local admin console through MCP on a running app and checked `overview`, `settings`, `playground`, `logs`, `traffic`, and `files-batches`.

The live UI confirms the same structural issue visible in code:

- `playground` renders many stacked panels and controls on one screen.
- `logs` combines filters, stream controls, context inspector, request context, rendered tail, recent errors, and recent requests in one page.
- `traffic` combines filters, requests table, selected payload, recent errors, usage summary, usage by key, and usage by provider in one page.
- `files-batches` combines inventory filters, upload flow, batch creation flow, inspector, files table, and batches table in one page.

So the frontend problem is not only code size. The information architecture is also dense. The pages are trying to be control room dashboards and task workbenches at the same time.

Small live observation: the only browser console error I saw from the app itself was a missing `/favicon.ico` with `404`. That is minor.

## What I think the frontend is trying to be

The admin console is trying to serve three roles at once:

1. Bootstrap wizard
2. Runtime observability dashboard
3. Operator workbench for keys/settings/playground/files/batches

That explains why it feels overloaded. These are related roles, but they produce different UX patterns.

## Why it currently feels "too much piled on"

- Too many high-responsibility pages.
- Too much page-local business logic.
- String-template rendering scales poorly once pages become interactive tools.
- Validation, API calls, and UI status rules are spread across pages.
- There is no obvious shared state model beyond the `AdminApp` shell.
- No visible frontend-specific tests, linting, or component boundaries.

## What I would not do

- I would not jump to React/Vue just because the console is large.
- I would not do a full rewrite of the admin UI.
- I would not mix styling redesign with structural refactor in one pass.

The better move is to keep the current stack, but impose stronger internal structure.

## Backend-specific assessment

## What feels solid

- Compatibility surfaces are explicit.
- Feature services are a good seam for testing.
- Provider mapping is intentionally isolated.
- Runtime dependency containers are a good direction.

## What feels heavy

- Admin runtime/settings endpoints own too much payload-building and policy logic.
- Some "assembler" files are becoming aggregation points for unrelated decisions.
- The provider mapping graph is hard to explain quickly.
- There is overlap between "config/control plane/runtime state" concepts that should be easier to distinguish from each other.

## Simplification principles I would use here

## 1. Reduce concept count before reducing line count

The repo does not mainly need shorter files. It needs fewer mental models:

- one clear request-mapping pipeline
- one clear control-plane mutation pipeline
- one clear admin page composition model

## 2. Move policy/building logic out of route/page files

Routes and page entrypoints should mostly:

- parse input
- call service/controller
- render/return result

This is especially relevant for:

- `gpt2giga/api/admin/runtime.py` and `gpt2giga/app/admin_runtime.py`
- `gpt2giga/api/admin/settings.py` and `gpt2giga/app/admin_settings.py`
- large admin page renderers

## 3. Prefer vertical slices inside admin

Instead of "all templates here, all forms there, giant page there", I would favor slice-local structure for big areas such as:

- settings
- traffic
- logs
- playground
- files-batches

Each slice should own:

- API access helpers
- state model
- DOM bindings
- render helpers
- serialization/validation

## 4. Separate stable backend core from fast-changing operator features

The proxy compatibility core should stay boring and legible. Admin/control-plane can evolve faster, but it should not make the whole repository feel dense.

## Refactoring candidates with the best payoff

### Highest payoff

- Break admin frontend pages into per-page submodules.
- Extract admin backend payload builders and control-plane mutation services from route files.
- Consolidate duplicated setup/settings frontend logic.
- Document the provider mapping pipeline as one diagram plus one "how a request flows" doc.

### Medium payoff

- Normalize naming in the GigaChat mapping layer.
- Group related response-v2 helpers under narrower subpackages or clearer prefixes.
- Introduce shared admin page controller utilities instead of repeated event lifecycle code.
- Reduce `app.state` surface further behind dedicated accessors.

### Lower payoff but still useful

- Tighten docs navigation and remove stale references.
- Make compiled frontend output handling more explicit in docs and contributor workflow.
- Add small frontend smoke tests for the admin console.

## Recommended direction

If the goal is "simplify and refactor without destabilizing the repo", I would do it in this order:

1. Fix docs drift and write one current architecture note.
2. Refactor admin frontend structure without changing UX much.
3. Extract admin backend service/payload logic from route modules.
4. Clean up provider mapping naming and request/response pipeline documentation.
5. Only then consider deeper runtime/control-plane consolidation.

## Final opinion

The repository is healthy enough to refactor, but it is now large enough that opportunistic cleanup will not be enough.

My main conclusion is:

- backend core is mostly structurally sound
- admin/control-plane is the main complexity magnet
- frontend is the most obvious place to simplify quickly
- the repo needs stronger subsystem boundaries more than it needs a framework rewrite

I would treat the next phase as "make the operator platform legible", not just "clean some code".
