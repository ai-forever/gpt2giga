# ADR: protocol/provider support status and loss matrix

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owners: bridge-matrix and integration lanes
- Matrix schema: `gpt2giga.bridge-loss-matrix.v1`
- Manifest schema: `gpt2giga.bridge-capabilities.v1`

## Context

The existing normalized v1 matrix describes whether a normalized feature has
an exact, conditional, or unsupported projection into three downstream wire
protocols. The release additionally needs a public-protocol by upstream-provider
matrix. This route matrix is a coarse maturity view; it is not model inventory
or the effective capability answer for a selected model.

## Decision

### Matrix identity

The matrix contains exactly these public protocols:

- `openai_responses`
- `openai_chat_completions`
- `anthropic_messages`
- `gemini_generate_content`

and these upstream provider kinds:

- `gigachat`
- `openai_compatible`
- `anthropic`
- `gemini`

Each of the 16 cells has one status:

- `stable`: version-windowed corpus and hermetic release E2E prove the declared
  subset;
- `technical_preview`: the subset is tested but has documented semantic loss or
  increased upstream drift risk;
- `blocked`: no safe supported path exists and admission must reject before I/O.

`unknown` is invalid for route maturity cells because every route must be
classified before release. This does not remove `unknown` from model-level
capabilities: lack of model evidence must remain an explicit tri-state result.
Omitted cells, implicit defaults, and marketing claims of general equivalence
are invalid.

### Cell and semantic rows

Each cell records `status`, `reasons`, `evidence_ids`, supported client/provider
version windows, and a complete semantic table. Required rows cover roles,
multimodal inputs, tools and call ids, tool results, parallel calls, JSON Schema,
stream lifecycle, usage/cache/reasoning tokens, stop/refusal/safety, reasoning,
previous-response state, files/images, hosted tools, cancellation, timeout,
malformed stream, and disconnect.

Every coarse row uses `exact`, `conditional`, or `unsupported`, matching the
existing normalized semantic vocabulary. A `conditional` row delegates to the
effective capability resolver for the selected model and API mode. The resolver
combines public-protocol support, provider-adapter support, model evidence, API
mode, and route policy. Each effective decision is `supported`, `unsupported`,
or `unknown` and retains reason, source, evidence, and revision identifiers.

### Revision

The secret-free matrix is canonicalized using the same JSON rules as provider
profiles. `matrix_revision` is `sha256:<lowercase-hex>`. Evidence timestamps,
free-form prose ordering, and runtime health do not affect the digest; semantic
status, reasons, version windows, and evidence ids do.

### Admission order

Admission is deterministic and finishes before credential or network work:

1. resolve the immutable provider route;
2. resolve the selected model from the shared catalog;
3. select the exact protocol/provider cell and reject a `blocked` route;
4. resolve effective model/API-mode capabilities;
5. derive requested semantic rows without discarding recognized intent;
6. apply the explicit policy for `unknown` and reject unsupported semantics;
7. emit a content-free admission record bound to config/profile/inventory/matrix
   revisions;
8. dispatch the exact provider adapter.

There is no downgrade from exact to lossy behavior and no provider/model
fallback. Rejection uses `unsupported_semantic` with the public field path and a
bounded reason id. The human explanation comes from the manifest, not from raw
provider output.

### Machine projection

`GET /bridge/capabilities` without a model query returns the complete 16-cell
route manifest in stable lexical order. A model/protocol/API-mode query returns
the effective tri-state projection with inventory and capability revisions. No
projection contains prompts, response bodies, credentials, destinations with
embedded userinfo, or raw provider data.

## Migration and rollback

- Existing `PROTOCOL_LOSS_MATRIX_V1` remains an internal input until the new
  schema replaces its public machine projection.
- Cells without evidence start as `blocked`, not preview.
- Rolling back to 0.2.x removes the new endpoint/admission layer; matrix files
  remain inert evidence and do not alter user state.
