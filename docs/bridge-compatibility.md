# Bridge compatibility, loss, and errors

The 0.3 bridge does not claim that every client protocol is equivalent to every
upstream provider. It publishes a versioned, machine-readable decision for each
route and rejects meaning that cannot be preserved before provider I/O.

The matrix schema is `gpt2giga.bridge-loss-matrix.v1`. It contains exactly 16
cells: four public protocols multiplied by four upstream provider kinds.

| Dimension | Values |
|---|---|
| Public protocol | `openai_responses`, `openai_chat_completions`, `anthropic_messages`, `gemini_generate_content` |
| Upstream provider | `gigachat`, `openai_compatible`, `anthropic`, `gemini` |

An adapter existing in the package is not, by itself, proof that a cell is
executable. Use the matrix revision exposed by the running gateway.

The route matrix describes normalized bridge maturity. Native GigaChat
Responses is the stable compatibility owner and bypasses the normalized matrix.
The normalized OpenAI Responses to GigaChat cell remains `technical_preview`:
hosted-tool coverage is admitted per model and API mode, while attachments and
other native-only semantics are not yet normalized end to end.

Responses, Anthropic Messages, and Gemini GenerateContent can also select an
exact `openai_compatible` profile alias. Those three cells are
`technical_preview` and use one startup-owned Chat Completions adapter. The
direct OpenAI Chat Completions cell remains blocked until its public route is
integrated with this registry. A v3 profile must declare the model's verified
normalized features and limits. Unsupported semantics and exact token-count
requests are rejected before that adapter performs I/O.

## Cell support statuses

Every cell has exactly one status. `unknown`, a missing cell, and an implicit
default make the manifest invalid.

| Status | Meaning |
|---|---|
| `stable` | The declared subset is covered by pinned client/provider version windows, hermetic conformance, and release E2E evidence. It is not a claim of complete vendor API parity. |
| `technical_preview` | The declared subset is tested, but at least one documented semantic loss or elevated upstream-drift risk remains. Callers must inspect the semantic rows. |
| `blocked` | No reviewed safe route exists. Admission rejects the route before credentials, provider-client construction, or network dispatch. |

Each cell also carries bounded reason ids, evidence ids, client and provider
version windows, and a complete semantic table. The table covers roles,
multimodal input, tool definitions/call ids/choice/results, parallel calls,
JSON Schema output, stream lifecycle, input/output/cache/reasoning usage, stop
reasons, safety/refusal, reasoning controls, previous-response state,
files/images, hosted/provider-native tools, cancellation, timeout, malformed
streams, and disconnect.

## Semantic dispositions

Each semantic row has one disposition:

- `exact`: the selected route preserves the declared meaning;
- `conditional`: it is admitted only when the exact named capability predicate
  is present in the resolved capability profile;
- `unsupported`: the request is rejected before dispatch when it requires this
  semantic.

`technical_preview` does not turn `unsupported` rows into best-effort behavior.
Likewise, an `exact` row does not upgrade the whole cell to `stable`. The cell,
semantic row, pinned version windows, and evidence ids must be evaluated
together.

The secret-free canonical matrix has a `sha256:<lowercase-hex>` revision. A
successful admission record uses schema `gpt2giga.bridge-admission.v1` and binds
the public protocol and alias, exact provider/profile, config revision,
capability profile revision, matrix revision, requested semantic paths, and
evidence ids. It contains no prompt, credential, or response content.

## Admission happens before I/O

For each bridge request the gateway performs this order:

1. resolve the exact public alias from the immutable
   [provider registry](provider-profiles.md);
2. select the exact public-protocol/upstream-provider cell;
3. reject a `blocked` cell;
4. derive the requested semantic rows from the normalized request;
5. require each row to be `exact` or satisfy its named capability predicate;
6. record a content-free, revision-bound admission decision;
7. dispatch exactly the selected provider adapter.

The gateway does not downgrade a semantic, choose a similar alias, or retry a
different provider/model/account. A request-supplied provider, destination,
upstream model, credential, TLS control, or arbitrary authorization header is
not a routing override.

An OpenAI-shaped semantic rejection is stable and points to the public field:

```json
{
  "error": {
    "code": "unsupported_semantic",
    "message": "The selected bridge route cannot preserve this semantic.",
    "param": "web_search_options",
    "type": "invalid_request_error"
  }
}
```

Anthropic- and Gemini-shaped public routes keep their native error envelopes
where required, while preserving the bounded machine code where representable.
No error may echo credentials, authorization headers, prompt content, or an
unredacted upstream body.

## Stable bridge error codes

| Code | Meaning |
|---|---|
| `invalid_request` | The public request is malformed within the admitted syntax. |
| `unknown_model_alias` | The exact public alias is missing, disabled, or otherwise unavailable. |
| `unsupported_semantic` | The selected cell or semantic row cannot preserve the request. |
| `credential_unavailable` | The selected profile's startup credential reference cannot be resolved. |
| `destination_mismatch` | The attempted transport destination differs from the reviewed profile. |
| `provider_timeout` | The exact provider operation exceeded its bound. |
| `provider_protocol_error` | The exact upstream returned a malformed response or stream. |
| `provider_failure` | The selected provider returned another mapped failure. |
| `client_disconnected` | The client disconnected before completion and the exact upstream work was cancelled. |

Startup/profile validation additionally uses `invalid_profile_schema`,
`duplicate_profile_id`, `duplicate_model_alias`, `invalid_destination`, and
`invalid_policy_reference`. Machine endpoint failures use the versioned
`gpt2giga.error.v1` envelope with bounded, content-free `details` reason ids.

## Route and effective-capability machine contracts

`GET /bridge/capabilities` returns
`gpt2giga.route-support-matrix.v1`. The document binds the current
`config_revision` and `matrix_revision` and contains all 16 cells in stable
lexical order. It is content-free and does not contact providers. Incomplete,
revision-mismatched, `unknown`, duplicate, or secret-bearing projections are
rejected rather than published.

With `model`, `protocol`, and optional `api_mode` query parameters, the same
endpoint returns `gpt2giga.effective-capabilities.v1` for that exact model and
route. The effective projection is tri-state and carries inventory and
capability revisions.

Use this endpoint for route planning and diagnostics; do not infer support from
HTTP route presence, an installed SDK, or a provider adapter class. Protocol
surface details remain in [API compatibility](api-compatibility.md), and the
normative matrix decision is recorded in the
[bridge status/loss ADR](architecture/bridge-compatibility-matrix.md).
