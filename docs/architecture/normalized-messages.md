# Normalized messages architecture

The normalized layer is an internal contract between the public API formats and
the upstream providers. It is not a new public API. Clients keep sending OpenAI
Chat Completions, OpenAI Responses, Anthropic Messages, or Gemini GenerateContent,
and the gateway brings the compatible parts of the payload to canonical models
from `gpt2giga/protocols/normalized/`. Gemini GenerateContent already uses a
dedicated Gemini-to-normalized adapter in the main execution path.

## Current status

- `GPT2GIGA_NORMALIZATION_MODE=off`: OpenAI Chat Completions and Anthropic
  Messages go through legacy transforms.
- `GPT2GIGA_NORMALIZATION_MODE=shadow`: OpenAI Chat builds a normalized request
  alongside the legacy path and stores a safe diagnostic shape hash without prompt content.
- `GPT2GIGA_NORMALIZATION_MODE=on`: OpenAI Chat Completions, the accepted
  Anthropic Messages v1 subset, and Gemini `countTokens` are executed through
  their protocol adapters, normalized models, and `GigaChatProviderAdapter`; a
  legacy fallback is available before the response starts via
  `GPT2GIGA_LEGACY_CHAT_FALLBACK=True`.
- OpenAI Responses is still executed through legacy route transforms.
- Gemini GenerateContent and streamGenerateContent are executed through
  `GeminiProtocolAdapter`, normalized models, and `GigaChatProviderAdapter`
  independently of the OpenAI Chat normalization flags. Their admitted request,
  response, SSE, function-calling, usage, safety/error, model-list, and typed
  image contracts are frozen by Gemini golden fixtures.
- Debug endpoints can translate between the `openai`, `anthropic`, `normalized`, and
  `gigachat` formats for protected admin workflows.
- G7-01 provides a normalized OpenAI Chat Completions upstream adapter for
  explicitly admitted OpenAI-compatible/vLLM profiles. It is an internal
  execution component, not a new public route switch. G7-02 adds the direct
  Anthropic request/response/SSE and count-token projection. G7-03 makes the
  admitted Gemini subset bridge-compatible: fully modeled fields no longer
  masquerade as unmodeled extensions, images use typed references, and
  `countTokens` uses `NormalizedTokenCountRequest`. Public upstream selection
  remains gated by G7-04.

## Core models

The normalized request envelope:

- `NormalizedChatRequest`: versioned request class, `protocol`, `operation`,
  `model`, `stream`, `messages`, `tools`, `tool_choice`,
  `parallel_tool_calls`, `response_format`, `generation_config`,
  `cancellation`, `user`, `metadata`.
- `NormalizedMessage`: `role`, `content`, `name`, `tool_call_id`,
  `tool_calls`.
- `NormalizedContentPart`: a generic content part plus a typed
  `NormalizedImageReference` for admitted `url` and `data_url` images.
- `NormalizedTool`: a flattened tool/function contract with `name`,
  `description`, `parameters`.
- `NormalizedGenerationConfig`: common generation knobs:
  `temperature`, `top_p`, `max_tokens`, penalties, `stop`, `seed`.
- `NormalizedTokenCountRequest`, `NormalizedTokenCountResponse`, and
  `NormalizedTokenLimits`: explicit token-count and context-limit contracts.

Normalized output:

- `NormalizedResponse`: a provider-independent non-streaming response:
  `choices`, `usage`, `error`, `metadata`, `provider_metadata`.
- `NormalizedChoice`: `message` or `delta`, legacy `finish_reason`, normalized
  v1 `stop_reason`, and `index`.
- `NormalizedUsage`: `input_tokens`, `output_tokens`, `total_tokens`.
- `NormalizedStreamEvent`: canonical stream events:
  `message_start`, `content_delta`, `reasoning_delta`, `tool_call_start`,
  `tool_call_delta`, `usage`, `message_end`, `cancelled`, `error`,
  `heartbeat`.

All normalized models inherit two extension buckets:

- `raw_extensions`: fields of the original public protocol that the gateway must
  keep but not promote into the canonical model.
- `provider_metadata`: provider-specific data, for example GigaChat
  `additional_fields` or safe metadata from the upstream response.

## OpenAI-compatible protocol bridge v1

G7-00 froze translation feasibility. G7-01 adds the first upstream runtime
without changing the matrix. The machine-readable source is
`PROTOCOL_LOSS_MATRIX_V1` in `gpt2giga.protocols.normalized`; its serialized
status is now `implementation_status="openai_compatible_upstream_adapter"`.

The accepted request subset has exactly four roles (`system`, `user`,
`assistant`, `tool`), ordered text and typed image-reference parts, function
tools/calls/results, admitted tool choice, optional parallel-call control,
JSON Schema output, streaming with terminal events, normalized stop/usage/model
and request/error classes, cooperative cancellation, declared context/token
limits, and explicit token counting. Files, audio, arbitrary content parts,
provider metadata, and unmodeled extension semantics are outside v1.

`E` means the normalized meaning has an exact downstream representation. `C`
means a reviewed adapter/model profile must opt into the feature. `U` means the
meaning cannot be preserved in v1 and admission fails.

| Normalized v1 feature | OpenAI downstream | Anthropic downstream | Gemini downstream |
| --- | --- | --- | --- |
| Roles | E | E | E |
| Ordered content parts | E | E | E |
| Text | E | E | E |
| Image references | C | C | C |
| Generation controls | C | C | C |
| Function tools/calls | E | E | E |
| Tool choice | E | E | C |
| Explicit parallel-tool toggle | E | E | U |
| Tool results | E | E | E |
| JSON Schema output | C | C | C |
| Streaming deltas | E | E | E |
| Streaming terminal events | E | E | E |
| Stop reason | E | E | E |
| Usage | E | E | E |
| Model identity | E | E | E |
| Request/error classes | E | E | E |
| Cancellation | E | E | E |
| Context/token limits | C | C | C |
| Count tokens | U | E | E |

`admit_protocol_bridge_request()` is the mandatory pre-I/O guard. It derives
the request's semantic requirements, requires each one in the reviewed
OpenAI-compatible upstream profile, requires explicit opt-in for every `C`
cell, enforces declared token limits, and rejects every `U` cell or unmodeled
extension. `UnsupportedSemanticLossError` is raised before an adapter may open
a network connection.

The matrix was revalidated against the current
[OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[Anthropic Messages SDK contract](https://github.com/anthropics/anthropic-sdk-python/tree/main/src/anthropic/types),
and [Gemini GenerateContent documentation](https://ai.google.dev/gemini-api/docs/text-generation).

### OpenAI-compatible upstream execution

`OpenAICompatibleProviderAdapter` executes only the frozen normalized v1 Chat
Completions subset. Before any request it binds the exact profile revision and
route model, runs `admit_protocol_bridge_request()`, serializes the reviewed
body, and obtains a request-specific network authorization. The transport
revalidates the serialized body, connected peer, and bounded response size.
Redirects and automatic retries are disabled.

Harness owns the provider profile, model route, `SecretRef`, TLS/proxy policy
references, and scoped network ticket. A credential is resolved and revealed
only to the exact `provider-execution:openai-compatible` boundary; profiles,
logs, persisted settings, network intents, and receipts retain only the
reference identity. vLLM has a versioned
`gigaloom.vllm-openai-compatible.v1` profile, while other compatible servers
must provide an explicitly reviewed profile and normalized capability/limit
contract.

The adapter supports strict model discovery, non-streaming and streaming text,
function tools and tool deltas, usage and stop normalization, bounded SSE, and
content-free transport failures. Provider-returned error facts are preserved
when present; missing usage, model metadata, or capabilities are not invented.
The hermetic fake-server suite is the default validation. A live remote vLLM
smoke is explicit opt-in:

```bash
GPT2GIGA_RUN_VLLM_SMOKE=1 \
GPT2GIGA_VLLM_BASE_URL=https://vllm.example/v1 \
GPT2GIGA_VLLM_MODEL=model-id \
uv run pytest -n 0 tests/live/test_vllm_openai_compatible_smoke.py
```

Set `GPT2GIGA_VLLM_API_KEY` only when the reviewed server requires it. The live
smoke requires a remote HTTPS endpoint and a scoped Harness network grant.

### Protocol bridge closure

The G7-04 hermetic closure suite composes the same reviewed
`OpenAICompatibleProviderAdapter` with the OpenAI, Anthropic, and Gemini
downstream adapters. Text, streaming, partial usage, and function-tool
workloads reach an identical OpenAI Chat Completions upstream payload and are
then projected back into each requested wire shape. OpenAI image inputs are
promoted to the same typed `NormalizedImageReference` contract already used by
Anthropic and Gemini.

The streaming parser rejects data after a terminal choice, usage before a
terminal choice, data after the usage summary, malformed JSON, and incomplete
streams with stable non-retryable protocol errors. Cooperative disconnects,
timeouts, and provider HTTP failures retain distinct normalized cancellation,
retryability, error class, code, and parameter facts. Partial usage stays
partial; missing token counts are not invented.

This closes the internal normalized v1 composition contract. It does not add a
gateway environment switch that accepts an arbitrary upstream URL or secret.
OpenAI-compatible profiles, credentials, TLS/proxy policy, and network grants
remain owned by the reviewed Harness execution boundary. Batches, files,
embeddings, prompt caching, computer use, audio, and unsupported multimodal
forms remain outside bridge v1.

## OpenAI Chat flow

OpenAI Chat Completions in normalized mode goes like this:

1. `gpt2giga/routers/openai/chat_completions.py` reads the payload and request
   context.
2. `OpenAIProtocolAdapter` from `gpt2giga/protocols/openai/adapter.py` builds
   a `NormalizedChatRequest`.
3. `GigaChatProviderAdapter` from `gpt2giga/providers/gigachat/adapter.py`
   executes the normalized request through the current GigaChat SDK path.
4. The provider adapter returns a `NormalizedResponse` or a
   `NormalizedStreamEvent`.
5. OpenAI response adapters map the result back into an OpenAI Chat
   Completions payload or SSE chunks.
6. Observability receives the normalized request/response and builds safe
   OpenInference-style span attributes.

Inside `GigaChatProviderAdapter`, the normalized request is currently
reconstructed into an OpenAI-like payload, after which the existing
`RequestTransformer` for the GigaChat v1/v2 SDK is used. This is a transitional
layer: the normalized contract is already separated from the router, but part of
the GigaChat-specific preparation still reuses the legacy code.

## Differences from OpenAI Chat Completions

OpenAI Chat Completions is the public wire format. Normalized messages are the
internal gateway contract.

Main differences:

- OpenAI stores tool schemas as `{"type": "function", "function": {...}}`;
  the normalized layer stores `NormalizedTool` with flat `name`, `description`,
  `parameters`.
- OpenAI `tool_calls` contains nested `function.arguments`; the normalized layer stores
  `NormalizedToolCall.name` and `arguments` directly, while the nested provider fields
  remain in `raw_extensions`.
- OpenAI content parts use concrete fields such as `text`, `image_url`,
  `file`; the normalized content part has a generic `data` and optional metadata.
- OpenAI top-level parameters are mixed in one object; the normalized layer groups
  generation knobs in `generation_config`, structured output in
  `response_format`, and unknown/compatibility fields in `raw_extensions`.
- OpenAI usage is called `prompt_tokens` and `completion_tokens`; the normalized layer
  uses provider-neutral `input_tokens` and `output_tokens`.
- The OpenAI response `id`/`object`/`created`/`system_fingerprint` are formed only on
  the way out of the normalized response adapter.

## Differences from OpenAI Responses

The OpenAI Responses API has a different public contract: `input`, `instructions`,
`output` items, `previous_response_id`, stateful response ids, built-in tool
progress events, and `text.format`.

The normalized layer currently describes Responses as a chat-like exchange only for
observability:

- `responses_request_to_normalized()` builds a `NormalizedChatRequest` with
  `operation="responses"`.
- `input` and `instructions` are turned into normalized messages.
- `max_output_tokens` is mapped to `generation_config.max_tokens`.
- `text.format` is mapped to `NormalizedResponseFormat`.
- Responses output items are collapsed into an assistant message and tool calls for
  LLM spans.

Execution of `/responses` stays in the legacy route path:
`gpt2giga/routers/openai/responses.py` uses the existing GigaChat v1/v2
request transformers and response processor. So the normalized Responses helper
is currently needed for consistent observability, not for the main execution path.

## Differences from Gemini GenerateContent

Gemini GenerateContent is a separate public protocol with `contents`, `parts`,
`systemInstruction`, `generationConfig`, `tools.functionDeclarations`,
`toolConfig.functionCallingConfig`, candidates, and its own SSE response shape.

The normalized layer differs as follows:

- `contents[].parts` are turned into normalized messages/content parts.
- `systemInstruction` becomes a normalized system message.
- `generationConfig.temperature`, `topP`, `maxOutputTokens`, penalties, `seed`, and
  `stopSequences` are mapped to `NormalizedGenerationConfig`.
- `functionDeclarations` are turned into `NormalizedTool`; supported provider
  tools are kept as GigaChat-compatible built-in tool metadata, while
  unsupported tools remain in `raw_extensions` for diagnostics.
- `toolConfig.functionCallingConfig` applies to function declarations and does not
  force the built-in provider tools.
- Gemini candidates, finish reasons, and usage metadata are formed on the way out of
  the normalized response/stream adapters.
- Accepted inline images use typed `NormalizedImageReference` values. Fully
  modeled function-call config, function responses, and JSON Schema output do
  not remain in `raw_extensions`; safety settings, cached content, unsupported
  tools, files, and other unmodeled semantics do, so OpenAI-compatible bridge
  admission rejects them before provider I/O.
- With normalization mode `on`, `countTokens` uses the same normalized
  token-count request/response contract as the admitted bridge.

The Gemini Files/Batches router modules are prepared but not mounted in the public
API surface; they are not part of the current normalized execution path.

## Differences from the GigaChat format

GigaChat is the upstream provider format that the gateway calls through the SDK. Its
v1/v2 contracts, SDK models, function-call state ids, attachments, and
`additional_fields` differ from the public OpenAI/Anthropic shapes.

The normalized layer differs as follows:

- it does not depend on `gigachat.models.Messages` or the v2 `ChatMessage`;
- it stores provider-neutral roles/messages/tools/usage/errors;
- it does not expose GigaChat authorization, SDK contextvars, and transport details;
- it keeps GigaChat-specific passthrough in `provider_metadata["gigachat"]`;
- it filters response headers before moving them into metadata and does not store
  `authorization`, `x-api-key`, `cookie`;
- it normalizes the GigaChat `function_call` into `NormalizedToolCall` and the finish reason
  `function_call` into `tool_calls`.

The provider adapter is responsible for the reverse side: it takes the normalized request,
prepares the GigaChat payload, calls the upstream, and returns the normalized
response/events.

## Differences from Anthropic Messages

Anthropic Messages is a separate public protocol with a top-level `system`,
content blocks, `max_tokens`, `stop_sequences`, `tool_use`, `tool_result`,
`thinking`, and its own streaming event names.

The normalized layer differs as follows:

- `system` becomes a regular normalized `system` message.
- Anthropic text/image blocks are translated into a normalized `content` string or
  content parts.
- `tool_use` becomes assistant `tool_calls`.
- `tool_result` becomes a normalized message with `role="tool"` and
  `tool_call_id`.
- `max_tokens` is stored in `generation_config.max_tokens`, and `stop_sequences`
  in `generation_config.stop`.
- `thinking`/reasoning content is not a separate canonical field and
  is kept as a controlled extension, for example `reasoning_content`.
- Anthropic `usage.input_tokens` and `usage.output_tokens` already match the
  normalized naming, and `total_tokens` is computed when both values are present.

With `GPT2GIGA_NORMALIZATION_MODE=on`, `AnthropicProtocolAdapter` builds the
normalized request directly, `GigaChatProviderAdapter` executes it, and the
Anthropic response/SSE projector restores the client wire contract. The same
path represents `count_tokens` with `NormalizedTokenCountRequest` and
`NormalizedTokenCountResponse`. Legacy execution remains the default and the
pre-response fallback for semantics outside the accepted v1 subset. Prompt
caching, computer use, files, and other unmodeled Anthropic features are not
claimed by the normalized path.

## Observability

LLM observability is intentionally built on top of normalized shapes:

- Chat Completions spans get request/response attributes from
  `NormalizedChatRequest` and `NormalizedResponse`.
- Responses and Anthropic helpers bring their public payloads to a normalized
  chat-like representation before building span attributes.
- The Gemini GenerateContent route already produces observability from the
  normalized request/response and uses the root span `Gemini-Content`.
- Streaming milestones are built from `NormalizedStreamEvent` when the route already
  uses the normalized stream path.
- Content capture stays disabled by default; messages, tool args, and
  responses require a separate opt-in and go through redaction.

This makes it possible to add new protocols/providers without copying all the
OpenInference/Phoenix attribute logic for each wire format.

## Debugging

For a local check, enable protected debug translation:

```dotenv
GPT2GIGA_DEBUG_TRANSLATE_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Useful endpoints:

- `POST /_debug/translate/openai-to-normalized`
- `POST /_debug/translate/anthropic-to-normalized`
- `POST /_debug/translate/normalized-to-gigachat`
- `POST /_debug/translate/gigachat-to-openai`
- `POST /_debug/translate` for a generic `from`/`to` envelope

Shadow diagnostics do not write prompt or response content. They store the route,
status, warnings/errors, and the shape hash of the normalized payload.
