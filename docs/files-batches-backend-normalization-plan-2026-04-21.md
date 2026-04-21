# Files and Batches Backend Normalization Plan

Date: 2026-04-21

## Goal

Move `Files and Batches` away from OpenAI-only frontend assumptions and introduce a backend normalization layer for files and batch jobs, similar in spirit to `NormalizedChatRequest`.

The target outcome is:

- admin UI consumes one normalized backend contract;
- backend aggregates OpenAI, Anthropic, and Gemini artifacts;
- provider-specific response quirks stay behind adapters;
- frontend stops knowing provider wire formats.

## Current Problem

Today the admin page is coupled to OpenAI-shaped payloads:

- files are loaded from `/v1/files`;
- batches are loaded from `/v1/batches`;
- UI expects fields like `input_file_id`, `output_file_id`, `endpoint`, `status`;
- Anthropic and Gemini use different list/retrieve/create/result schemas;
- Anthropic batch APIs do not expose the same file linkage fields the frontend expects.

Because of that, adding format selection in the frontend becomes fragile unless the backend first exposes one canonical artifact model.

## Proposed Architecture

### 1. Add canonical normalized artifact contracts

Create a dedicated normalized contract module, parallel to request normalization:

- `gpt2giga/core/contracts/normalized_artifacts.py`

Suggested models:

- `NormalizedArtifactFormat`
  - `openai`
  - `anthropic`
  - `gemini`
- `NormalizedFileRef`
  - canonical file reference used by batches and output previews
- `NormalizedFileRecord`
  - canonical file metadata for admin inventory
- `NormalizedBatchRequestCounts`
  - unified request counters
- `NormalizedBatchRecord`
  - canonical batch metadata for admin inventory and inspector
- `NormalizedArtifactsInventory`
  - normalized response for the admin Files and Batches page

Required normalized file fields:

- `id`
- `api_format`
- `filename`
- `purpose`
- `bytes`
- `status`
- `created_at`
- `content_kind`
- `download_path`
- `content_path`
- `delete_path`
- `raw`

Required normalized batch fields:

- `id`
- `api_format`
- `endpoint`
- `status`
- `created_at`
- `input_file_id`
- `output_file_id`
- `output_kind`
  - `file`
  - `results`
- `output_path`
- `request_counts`
- `model`
- `display_name`
- `raw`

Notes:

- keep `raw`/`extra` payloads so the admin inspector can still show provider-native metadata;
- keep canonical field names close to existing frontend expectations to reduce UI churn;
- avoid putting this into the existing request-normalization file directly, because artifact contracts are a separate domain.

### 2. Add provider-specific normalizers

Create a provider normalization layer that maps provider-native file/batch records into canonical contracts:

- `gpt2giga/features/files_batches/contracts.py`
- `gpt2giga/features/files_batches/service.py`
- `gpt2giga/features/files_batches/normalizers.py`

Normalizer entrypoints:

- `normalize_openai_file(...)`
- `normalize_openai_batch(...)`
- `normalize_anthropic_batch(...)`
- `normalize_gemini_file(...)`
- `normalize_gemini_batch(...)`

Normalization rules:

- OpenAI:
  - mostly pass-through into canonical fields
  - preserve existing file and batch linkage
- Anthropic:
  - use internal batch store metadata, not only public Anthropic response shape
  - recover `input_file_id`, `output_file_id`, and internal endpoint from batch metadata
  - normalize `processing_status` into canonical `status`
  - expose result retrieval via canonical `output_path`
- Gemini:
  - normalize file resource `name=files/...` into canonical `id`
  - normalize operation `name=batches/...` into canonical `id`
  - map `metadata.state` into canonical `status`
  - extract input and output file references from `inputConfig` and `output.responsesFile`

### 3. Add admin inventory and inspector endpoints

Extend admin runtime API with admin-only normalized endpoints:

- `GET /admin/api/files-batches/inventory`
- `GET /admin/api/files-batches/files/{file_id}`
- `GET /admin/api/files-batches/batches/{batch_id}`

Optional but useful follow-up:

- `GET /admin/api/files-batches/content`
  - unified content fetch endpoint for file or batch-result preview

Why admin endpoints instead of reusing public provider routes directly:

- admin UI needs one stable schema;
- admin UI needs store-enriched linkage fields that some public APIs do not expose;
- it prevents leaking frontend normalization logic across several TS files;
- it keeps provider compatibility surfaces thin and focused.

### 4. Build a backend service that aggregates mixed inventory

`FilesBatchesService` should:

- list OpenAI files via existing files feature/service;
- list OpenAI batches via existing batches feature/service;
- list Anthropic batches via existing batches feature/service using stored metadata;
- list Gemini files via existing files feature/service plus Gemini file metadata normalization;
- list Gemini batches via existing batches feature/service filtered by `api_format`;
- merge and sort everything into one canonical inventory object;
- support optional filter arguments:
  - `api_format`
  - `kind`
  - `query`
  - `status`
  - `endpoint`
  - `purpose`

Recommended response shape:

```json
{
  "files": [],
  "batches": [],
  "counts": {
    "files": 0,
    "batches": 0,
    "output_ready": 0,
    "needs_attention": 0
  }
}
```

## Implementation Plan

### Phase 1. Canonical contracts

1. Add `normalized_artifacts.py` with Pydantic models.
2. Export new models from `gpt2giga/core/contracts/__init__.py`.
3. Keep fields minimal but stable; do not encode frontend-only wording in the contracts.

### Phase 2. Service and normalizers

1. Introduce `gpt2giga/features/files_batches/`.
2. Implement normalizers for OpenAI, Anthropic, and Gemini.
3. Reuse `get_batch_store_from_state(...)` and `get_file_store_from_state(...)` so Anthropic and Gemini normalization can recover local linkage metadata.
4. Centralize status mapping here, not in the frontend.

### Phase 3. Admin runtime API

1. Add new admin runtime routes in `gpt2giga/api/admin/runtime.py` or a dedicated `gpt2giga/api/admin/files_batches.py`.
2. Register them via `gpt2giga/api/admin/__init__.py`.
3. Keep the endpoints admin-only and IP-allowlist protected like the rest of `/admin/api/*`.

Preferred split:

- `gpt2giga/api/admin/files_batches.py`
  - keeps runtime router from growing into a dump file
  - makes ownership obvious

### Phase 4. Frontend migration

After backend normalization lands, switch admin TS to:

- load inventory from `/admin/api/files-batches/inventory`;
- inspect files/batches from normalized admin endpoints;
- use `api_format` to render format badges and route actions;
- keep upload/create actions provider-specific, but drive them from normalized records instead of hardcoded OpenAI assumptions.

Frontend should no longer:

- parse Gemini operation names itself;
- infer Anthropic result paths;
- rely on provider-specific shape differences.

#### Status update

- done: admin `Files & Batches` page now loads mixed inventory from `/admin/api/files-batches/inventory`
- done: file and batch inspector refresh now uses `/admin/api/files-batches/files/{file_id}` and `/admin/api/files-batches/batches/{batch_id}`
- done: frontend preview/download flows consume canonical `content_path` / `download_path`
- done: delete action now respects canonical `delete_path` and stays disabled for formats without delete support
- done: UI renders `api_format` directly from normalized records instead of inferring provider shape
- done: shipped admin assets under `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` were rebuilt in sync with source TS
- done: admin batch composer now creates OpenAI, Anthropic, and Gemini jobs through one normalized backend endpoint
- done: backend batch creation lives in `FilesBatchesService` and reuses provider adapters instead of pushing wire-format branching back into the frontend
- done: admin API exposes `POST /admin/api/files-batches/batches` and returns normalized batch records immediately after create
- done: frontend batch composer is format-aware, including Gemini model/display-name inputs and provider-specific input-shape guidance
- done: unit and integration coverage now exercises normalized admin batch creation for OpenAI, Anthropic, and Gemini

#### Commit slice

The current commit should include:

- `docs/files-batches-backend-normalization-plan-2026-04-21.md`
- `gpt2giga/api/admin/files_batches.py`
- `gpt2giga/features/files_batches/service.py`
- `gpt2giga/frontend/admin/pages/files-batches/api.ts`
- `gpt2giga/frontend/admin/pages/files-batches/bindings.ts`
- `gpt2giga/frontend/admin/pages/files-batches/view.ts`
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/pages/files-batches/api.js`
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/pages/files-batches/bindings.js`
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/pages/files-batches/view.js`
- `tests/unit/features/files_batches/test_service.py`
- `tests/integration/app/test_admin_files_batches_api.py`

Explicitly keep out of this commit:

- unrelated review/progress docs
- unrelated repo-level draft docs
- unrelated examples and deployment files

### Phase 5. Batch creation follow-up

Once normalized inventory exists, add backend-backed creation helpers for format-aware batch creation:

- OpenAI: create from staged file id
- Anthropic: load staged file content, convert JSONL rows into `requests`, create message batch
- Gemini: create from Gemini file id or inline normalized requests

This can remain a second slice after inventory normalization if we want to reduce initial risk.

## Testing Plan

### Unit tests

Add tests for each normalizer:

- OpenAI file normalization
- OpenAI batch normalization
- Anthropic batch normalization with store-enriched metadata
- Gemini file normalization
- Gemini batch normalization
- status mapping edge cases
- missing linkage metadata fallbacks

Suggested locations:

- `tests/unit/features/files_batches/test_normalizers.py`
- `tests/unit/features/files_batches/test_service.py`

### Integration tests

Add admin API coverage:

- mixed inventory returns OpenAI + Anthropic + Gemini artifacts
- filtering by `api_format` works
- Anthropic batch response contains recovered input/output linkage in canonical form
- Gemini batch output path is normalized correctly

Suggested location:

- `tests/integration/admin/test_files_batches_api.py`

### Frontend regression checks

When frontend migration starts, add checks that admin assets still load and `Files and Batches` renders from normalized admin payloads.

## Risks and Decisions

### Decision: admin-only normalization first

Do not reshape public provider compatibility routes just to satisfy admin UI needs.

Reason:

- public compatibility routes should stay wire-compatible;
- admin UI needs richer linkage than public routes guarantee;
- admin-only normalized endpoints are the cleaner boundary.

### Risk: duplicated normalization logic

If file and batch normalization lives partly in routers and partly in the new feature service, drift will appear.

Mitigation:

- keep normalization in one feature package;
- routers should only call the service and return canonical payloads.

### Risk: unclear status mapping across providers

Anthropic and Gemini use different lifecycle vocabularies.

Mitigation:

- define one explicit canonical status mapping table in the normalizer layer;
- test it directly.

## Definition of Done

This slice is done when:

1. backend exposes a normalized admin inventory for files and batches;
2. normalized records include `api_format` and stable file/batch linkage fields;
3. Anthropic and Gemini artifacts can be listed and inspected without frontend provider-specific parsing;
4. tests cover normalization and admin API responses;
5. frontend can be migrated to one admin payload without relying on `/v1/batches` as the source of truth.

## Recommended Execution Order

1. Add normalized artifact contracts.
2. Add `features/files_batches` service and provider normalizers.
3. Add admin API endpoints.
4. Cover with unit and integration tests.
5. Migrate frontend to normalized admin endpoints.
6. Add format-aware create/upload helpers as a follow-up slice if needed.
