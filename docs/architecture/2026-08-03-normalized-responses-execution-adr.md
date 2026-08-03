# ADR: normalized OpenAI Responses execution

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owners: Responses protocol and integration lanes
- Contract revision: `gpt2giga.responses-execution.v1`

## Context

Codex custom model providers use the OpenAI Responses wire API. Current Codex
configuration exposes a provider `base_url`, an environment-backed key, optional
reviewed headers, and `wire_api = "responses"`; Responses is the only supported
custom-provider wire value. The current gateway mounts `/responses`, but its v1
and v2 branches call GigaChat compatibility transforms directly. Normalized
Responses models are currently used for diagnostics and observability, not as
the execution authority.

The 0.3 bridge cannot claim Codex compatibility while retaining two execution
owners or silently dropping client semantics. The admitted subset is pinned by
the versioned corpus under `tests/corpora/bridge/`, not by an open-ended claim of
Responses API equivalence.

## Decision

### One execution owner

Every admitted `/responses` request follows this sequence:

```text
Responses request decoder
-> NormalizedChatRequest / normalized state contract
-> capability and loss admission
-> exact provider profile and public alias resolution
-> upstream provider adapter
-> NormalizedResponse / NormalizedStreamEvent
-> Responses response or SSE projection
```

The route may not call the legacy GigaChat transformer or a second provider
after normalized admission. No fallback is allowed after provider dispatch or
after any response bytes are exposed.

### Compatibility mode

Normalized Responses is the 0.3 default. The old direct GigaChat path may be
selected only with `GPT2GIGA_LEGACY_RESPONSES=true`, only when no bridge config
file is supplied, and only for the synthesized legacy GigaChat profile. Using
that flag with `--config` or `GPT2GIGA_CONFIG` is an `invalid_profile` startup
error. The flag is deprecated in 0.3 and is not a provider fallback.

### Request admission

Every top-level field and every nested input/tool/content item is classified as
one of:

- normalized and executed;
- accepted but ignored with an exact corpus evidence id and a capability
  manifest reason;
- rejected before credential resolution, network-ticket creation, or provider
  client use.

Unknown fields are rejected. Request fields may never become provider metadata
or upstream extension fields merely because a Pydantic model accepts extras.
`base_url`, provider selectors, credentials, TLS controls, arbitrary headers,
and upstream model ids are always rejected with `unsupported_semantic`.

The stable Codex target covers text input, instructions, function declarations,
function-call outputs, representable JSON Schema output, usage, stop reasons,
HTTP SSE, and cooperative disconnect. `previous_response_id`, reasoning
controls/summaries, images, files, hosted tools, computer use, web search, and
other stateful or multimodal semantics are admitted only when the selected
profile/matrix revision explicitly proves them. Otherwise they fail closed.

### Response and stream lifecycle

Non-stream output has one Responses object with an honest `status`, output
items, usage facts that were actually observed, and the requested public alias.
Missing token categories remain absent or null; totals are never fabricated.

HTTP streaming uses typed SSE and preserves the following partial order:

1. exactly one `response.created`;
2. item/content start events before their deltas;
3. function argument deltas before the corresponding done event;
4. usage only when known;
5. exactly one terminal `response.completed`, `response.failed`, or
   `response.incomplete` event.

An `error` event terminates the stream. Duplicate terminals, data after a
terminal, malformed upstream events, and unfinished streams become stable
provider-protocol failures. Client disconnect cancels the exact upstream
operation and releases the model limit and client; it does not retry or switch
route.

### Stable errors

Responses request errors retain the OpenAI envelope and these machine codes:

| Code | Meaning |
|---|---|
| `invalid_request` | The request is malformed within the admitted syntax. |
| `unknown_model_alias` | The public alias does not exist. |
| `unsupported_semantic` | The selected cell cannot preserve requested meaning. |
| `credential_unavailable` | The admitted profile credential cannot be resolved. |
| `destination_mismatch` | The transport destination differs from its profile. |
| `provider_timeout` | The exact provider operation exceeded its bound. |
| `provider_protocol_error` | The upstream response/stream is malformed. |
| `provider_failure` | The exact upstream provider returned a mapped failure. |
| `client_disconnected` | The client disconnected before completion. |

The `param` field points to the rejected public field when available. Error
messages contain no request content, credential value, or unredacted upstream
body.

## Migration and rollback

- Existing routes and `/v1` aliases remain mounted.
- Users can temporarily select the explicitly named legacy mode without
  changing stored data.
- Rollback to 0.2.x removes normalized Responses execution and leaves profile
  files inert; no persistent response state is rewritten.
- Removing the legacy flag restores normalized execution. It never remaps a
  public alias or selects a different provider.

## References

- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Responses streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses)
