# ADR: normalized OpenAI Responses execution

- Date: 2026-08-03
- Status: accepted for gpt2giga 0.3
- Decision owners: Responses protocol and integration lanes
- Contract revision: `gpt2giga.responses-execution.v2`

## Context

Codex custom model providers use the OpenAI Responses wire API. Current Codex
configuration exposes a provider `base_url`, an environment-backed key, optional
reviewed headers, and `wire_api = "responses"`; Responses is the only supported
custom-provider wire value. The gateway already has a GigaChat-native Responses
path that preserves hosted tools, attachments, conversation state, v1/v2
execution, non-streaming, SSE, and provider-specific response adaptation. The
first 0.3 implementation made a smaller normalized subset the default and
renamed that native owner `legacy`. It therefore rejected supported GigaChat
semantics before resolving the route, model, or API mode.

The 0.3 bridge cannot claim Codex compatibility while retaining two execution
owners or silently dropping client semantics. The admitted subset is pinned by
the versioned corpus under `tests/corpora/bridge/`, not by an open-ended claim of
Responses API equivalence.

## Decision

### One selected execution owner

Every `/responses` request follows this sequence before provider I/O:

```text
decode known public fields without discarding recognized intent
-> resolve the immutable provider route
-> resolve the effective model
-> resolve protocol/provider/model/API-mode/route capabilities
-> admit or reject requested semantics
-> select exactly one executor
```

The selected executor is `native_gigachat` for a GigaChat route and
`normalized_bridge` for a real cross-provider route. Selection is recorded in
the request context. After dispatch, the route may not call another executor,
provider, account, or model. No fallback is allowed after provider dispatch or
after any response bytes are exposed.

### Compatibility ownership

Native GigaChat Responses remains the compatibility owner and the default when
no explicit cross-provider configuration is supplied. An explicit GigaChat
bridge route also selects the native owner until normalized parity is proven
and separately promoted. Ordinary GigaChat use requires no compatibility flag.

The normalized bridge is route-selected for cross-provider execution. It is
not the global minimum denominator for every route. The
`GPT2GIGA_LEGACY_RESPONSES` workaround is not part of the corrected 0.3 public
contract and must be removed before release approval.

### Request admission

The decoder preserves every recognized top-level field and nested
input/tool/content item long enough for route/model admission. Each semantic is
then classified as one of:

- normalized and executed;
- accepted but ignored with an exact corpus evidence id and a capability
  manifest reason;
- rejected before credential resolution, network-ticket creation, or provider
  client use, with the exact semantic and reason id.

Unknown fields are rejected. Request fields may never become provider metadata
or upstream extension fields merely because a Pydantic model accepts extras.
`base_url`, provider selectors, credentials, TLS controls, arbitrary headers,
and upstream model ids are always rejected with `unsupported_semantic`.

Hosted tools, attachments, reasoning, previous-response state, conversation
state, images, and files are not globally unsupported. They are admitted when
the selected route, model, and API mode prove support. `unknown` capability
evidence follows the explicit route policy and is never silently converted to
supported or unsupported.

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
- Existing GigaChat-only deployments require no flag or configuration change.
- Explicit bridge profiles retain their exact immutable aliases and provider
  routes.
- Rollback to 0.2.x removes normalized Responses execution and leaves profile
  files inert; no persistent response state is rewritten.
- Executor selection never remaps a public alias or silently selects a
  different provider or model.

## References

- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Responses streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses)
