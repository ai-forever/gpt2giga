# Client parameter compatibility

This document is a public reference for the parameter compatibility of the OpenAI,
Anthropic, and Gemini-like client SDKs in gpt2giga. It reflects the current
structure of the source code:

- OpenAI routers: `gpt2giga/routers/openai/`
- Anthropic routers: `gpt2giga/routers/anthropic/`
- Gemini routers: `gpt2giga/routers/gemini/`
- shared request policies: `gpt2giga/common/client_params.py`
- OpenAI request classification: `gpt2giga/protocol/request/params.py`
- Anthropic request classification: `gpt2giga/protocol/anthropic/params.py`
- Gemini adapter: `gpt2giga/protocols/gemini/`

Other client families are not covered by this compatibility check.

To inspect how one concrete request will be classified without calling GigaChat,
use [Compatibility Doctor](diagnostics.md). It returns the same public status
language for fields, tools, backend mode, model selection, and redaction.

## Compatibility statuses

| Status | Meaning |
|---|---|
| `supported` | The parameter affects the request or response and is covered by tests. |
| `accepted_ignored` | The parameter is accepted for SDK compatibility but is not sent upstream. |
| `accepted_diagnostic_only` | The parameter is retained only for diagnostics, observability summaries, or future UI explanation. |
| `approximated` | The parameter or operation is implemented through a documented approximation rather than exact provider semantics. |
| `rejected` | The request has an unexecutable shape, for example a missing required `input` or an `extra_body` that is not an object. Optional client feature flags do not use this status. |
| `not_applicable` | The option relates to client-side transport configuration, not to a server-side request body parameter. |

## SDK transport options

`base_url`, `api_key`, `timeout`, retry settings, a custom
`http_client`, proxy configuration, and low-level transport settings are
client-side SDK options. gpt2giga does not assign them server-side semantics.

Credentials and transport headers are not forwarded to GigaChat as arbitrary
upstream metadata. This applies to `Authorization`, `x-api-key`, cookies,
`host`, content and transfer headers, `x-stainless-*`, `openai-*`, and
`anthropic-*`. To intentionally pass GigaChat authorization, use the separate
`GPT2GIGA_PASS_TOKEN=True` mode.

## `extra_headers` and `extra_query`

`extra_headers` from an SDK arrives at the server as regular HTTP headers.
gpt2giga moves safe headers into the request-scoped contextvars of the GigaChat
SDK:

- `x-request-id`
- `x-session-id`
- `x-service-id`
- `x-operation-id`
- `x-client-id`
- `x-trace-id`
- `x-agent-id`

Other safe custom headers are passed through `custom_headers_cvar`. The
diagnostic `x-correlation-id` and `traceparent` can also be passed as custom
headers. `Authorization`, `x-api-key`, transport headers, and the SDK-internal
`x-stainless-*`, `openai-*`, `anthropic-*` headers remain blocked.

The SDK URL contextvars, for example `chat_url_cvar` and
`chat_completions_url_cvar`, are not populated from `extra_headers`.

`extra_query` does not forward arbitrary query parameters upstream by default:
the list of allowed upstream query parameters is empty.

## `extra_body`

The OpenAI and Anthropic SDKs usually merge `extra_body` with the outgoing JSON
body as top-level fields. HTTP clients that work directly can also send a literal
`extra_body` object. gpt2giga handles both forms.

For OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages, the
`extra_body` object is moved into GigaChat `additional_fields` in full. SDK-style
unknown top-level fields that appear after the client expands `extra_body` are
handled the same way.

Known unsupported optional client parameters are accepted and ignored if sent as
top-level fields: for example `logprobs`, `audio`, `container`, or
`mcp_servers`. `previous_response_id` is supported for OpenAI Responses in
GigaChat v2 mode and is mapped to `storage.thread_id`; in Responses v1 mode it is
accepted and ignored.
If the same key is explicitly placed inside a literal `extra_body`, gpt2giga
passes it to `additional_fields`, and the GigaChat upstream determines the final
support.

OpenAI Embeddings accepts and ignores `extra_body`, unknown top-level fields, and
`dimensions`; at the moment there are no GigaChat-specific allowed fields for
embeddings.

## OpenAI body parameters

| Endpoint | Supported |
|---|---|
| Chat Completions | `model`, `messages`, `stream`, `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`, function `tools`, `functions`, `function_call`, supported `tool_choice`, built-in tools in GigaChat v2 mode (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`), `response_format`, `reasoning`, `reasoning_effort`, `extra_body` passthrough |
| Responses | `model`, `input`, `instructions`, `stream`, `temperature`, `top_p`, `max_output_tokens`, function `tools`, built-in tools in GigaChat v2 mode (`web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate`; normalized output items and stream progress events are currently built for `web_search*` and `image_generation` / `image_generate`), supported `tool_choice`, `text.format`, `response_format`, `reasoning`, `reasoning_effort`, `extra_body` passthrough |
| Embeddings | `input`, `model`, `dimensions`, `encoding_format`, `user`, `extra_headers`, `extra_query` |
| Models | `GET /models`, `GET /models/{model}` |

Structured output is supported through `json_schema`. Schema-less JSON mode
(`response_format.type=json_object` in OpenAI or Gemini
`responseMimeType=application/json` without `responseJsonSchema` / `responseSchema`)
is rejected, because the GigaChat upstream does not support a separate JSON mode.

With `GPT2GIGA_DISABLE_REASONING=True`, the proxy accepts `reasoning` and
`reasoning_effort` but does not pass them to the upstream payload sent to GigaChat.

With `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True`, the proxy accepts provider
built-in tools for compatibility but does not map or send them to GigaChat as
executable tools. User function tools continue to work.

OpenAI metadata fields such as `user`, `metadata`, `service_tier`,
`safety_identifier`, `seed`, `prompt_cache_key`, and `prompt_cache_retention` are
accepted and ignored where they are classified.

Unsupported optional OpenAI parameters are accepted and ignored. Examples:
`logprobs`, `top_logprobs`, `logit_bias`, audio output, `prediction`,
`web_search_options`, built-in tools outside GigaChat v2 mode, `n > 1`,
`parallel_tool_calls=true`, stored completions requests, `conversation`, and
`previous_response_id` in Responses v1 mode. `/chat/completions` v1
remains a supported compatibility route, but new tool/built-in-tool
capabilities evolve for GigaChat `v2/chat/completions`.

## Anthropic body parameters

| Endpoint | Supported |
|---|---|
| Messages | `model`, `messages`, `system`, `max_tokens`, `stream`, `temperature`, `top_p`, `stop_sequences`, local function `tools`, Anthropic provider tools in GigaChat v2 mode (`web_search*`, `web_fetch*` as `url_content_extraction`, `code_execution*` as `code_interpreter`), `tool_choice` values `auto`/`none`/forced `tool`, `thinking`, `output_config.format`, `output_format`, `extra_body` passthrough |
| Count Tokens | `model`, `messages`, `system`, `tools`, structured-output schema text, compatible message content validation |
| Models | `GET /models`, `GET /models/{model_id}`, when the request contains Anthropic SDK headers, for example `anthropic-version` |

Anthropic `metadata`, `service_tier`, `top_k`, beta headers, and `betas`
are accepted and ignored where they are classified.

Unsupported optional Anthropic parameters or features are accepted and
ignored. Examples: `container`, `context_management`, `mcp_servers`,
unsupported provider tools (`advisor`, `tool_search`, `mcp_toolset`, `memory`,
`bash`, `text_editor`, `computer`), computer use, document/file content
blocks, container uploads, search result blocks, citations, and
`thinking`/`redacted_thinking` input blocks.

The Anthropic Message Batches code exists, but the public router is not mounted
until batch operation support appears in the GigaChat SDK or backend.

## Gemini body parameters

Gemini-like operation routes are available at the root, under `/v1`, `/v2`, and `/v1beta`,
for example `/v1/models/{model}:generateContent`. The Gemini SDK/CLI paths
`/v1/v1beta/...` and `/v2/v1beta/...` are also supported when the client itself
adds `/v1beta` to a versioned base URL. `/v1` and `/v1/v1beta` force the
GigaChat v1 backend contract, `/v2` and `/v2/v1beta` force the GigaChat v2 backend
contract. Root paths without `/v1` or `/v2`, including `/v1beta/...`, select the
backend by `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

| Endpoint | Supported |
|---|---|
| Generate Content | `contents`, `systemInstruction`, `generationConfig.temperature`, `generationConfig.topP`, `generationConfig.maxOutputTokens`, `generationConfig.stopSequences`, `generationConfig.seed`, `generationConfig.presencePenalty`, `generationConfig.frequencyPenalty`, function `tools.functionDeclarations`, Gemini provider tools in GigaChat v2 mode (`googleSearch` / `googleSearchRetrieval` as `web_search`, `urlContext` as `url_content_extraction`, `codeExecution` as `code_interpreter`), basic `toolConfig.functionCallingConfig`, text/image/file parts |
| Stream Generate Content | The same fields as Generate Content; the response is returned as Gemini `GenerateContentResponse` SSE chunks. |
| Count Tokens | Text parts of `contents`, `systemInstruction`, and function declaration names/descriptions. |
| Embeddings | `content.parts[].text`, `requests[].content.parts[].text` for batch embeddings, `outputDimensionality` accepted as compatibility metadata. |
| Models | `GET /v1beta/models`, `GET /v1/v1beta/models`, `GET /v2/v1beta/models` and `{model}` variants; the shared `/models`, `/v1/models`, `/v2/models` return the Gemini form for Google/Gemini requests, for example with `X-Goog-Api-Client` |

Gemini `safetySettings`, `cachedContent`, `serviceTier`, `store`, and
unsupported `generationConfig` subfields are accepted and kept in normalized extensions
for diagnostics, but are not passed to GigaChat as executable parameters and are
not applied by the proxy. Non-function provider tools that do not match the
GigaChat SDK built-in tools (`fileSearch`, `googleMaps`, `computerUse`,
MCP, RAG/retrieval/Vertex tools) are also kept for diagnostics only.
The full list of canonical built-in tools and provider aliases is described in
[Built-in tools](builtin-tools.md).

The Gemini Files and Batches code exists, but the public router is not mounted
until file/batch execution is verified end-to-end.

## Route scope

The mounted OpenAI, Anthropic, LiteLLM, and Gemini operation routes are available
at the root, under `/v1`, and under `/v2` via the application router.
Gemini-compatible routes are also available under `/v1beta`, `/v1/v1beta`, and
`/v2/v1beta`.
`/v1` always selects the GigaChat v1 backend contract, `/v2` always selects the
GigaChat v2 backend contract, and the root without a versioned prefix follows
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.
The prepared but disabled OpenAI Files/Batches, Anthropic Message
Batches, and Gemini Files/Batches routes are intentionally excluded from the OpenAPI schema by default.
