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
matrix. Every cell must state what is safe to execute; absence or `unknown` is
not a releaseable state.

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

`unknown`, omitted cells, implicit defaults, and marketing claims of general
equivalence are invalid.

### Cell and semantic rows

Each cell records `status`, `reasons`, `evidence_ids`, supported client/provider
version windows, and a complete semantic table. Required rows cover roles,
multimodal inputs, tools and call ids, tool results, parallel calls, JSON Schema,
stream lifecycle, usage/cache/reasoning tokens, stop/refusal/safety, reasoning,
previous-response state, files/images, hosted tools, cancellation, timeout,
malformed stream, and disconnect.

Every row uses `exact`, `conditional`, or `unsupported`, matching the existing
normalized semantic vocabulary. A `conditional` row names the exact capability
profile predicate. A `blocked` cell may still describe why individual rows are
unrepresentable, but it cannot be dispatched.

### Revision

The secret-free matrix is canonicalized using the same JSON rules as provider
profiles. `matrix_revision` is `sha256:<lowercase-hex>`. Evidence timestamps,
free-form prose ordering, and runtime health do not affect the digest; semantic
status, reasons, version windows, and evidence ids do.

### Admission order

Admission is deterministic and finishes before credential or network work:

1. resolve the public alias;
2. select the exact protocol/provider cell;
3. reject a `blocked` cell;
4. derive requested semantic rows from the normalized request;
5. require every row to be exact or satisfy its named capability predicate;
6. emit a content-free admission record bound to config/profile/matrix
   revisions;
7. dispatch the exact provider adapter.

There is no downgrade from exact to lossy behavior and no provider/model
fallback. Rejection uses `unsupported_semantic` with the public field path and a
bounded reason id. The human explanation comes from the manifest, not from raw
provider output.

### Machine projection

`GET /bridge/capabilities` returns the complete 16-cell manifest in stable
lexical order. It contains no prompts, response bodies, credentials,
destinations with embedded userinfo, or live provider data. The endpoint never
contacts an upstream service.

## Migration and rollback

- Existing `PROTOCOL_LOSS_MATRIX_V1` remains an internal input until the new
  schema replaces its public machine projection.
- Cells without evidence start as `blocked`, not preview.
- Rolling back to 0.2.x removes the new endpoint/admission layer; matrix files
  remain inert evidence and do not alter user state.
