# Client Parameter Compatibility

This document is the public compatibility reference for OpenAI and Anthropic
client SDK parameters in gpt2giga. It reflects the current source layout:

- OpenAI routers: `gpt2giga/routers/openai/`
- Anthropic routers: `gpt2giga/routers/anthropic/`
- Shared request policies: `gpt2giga/common/client_params.py`
- OpenAI request classification: `gpt2giga/protocol/request/params.py`
- Anthropic request classification: `gpt2giga/protocol/anthropic/params.py`

No other client families are covered by this compatibility pass.

## Compatibility Statuses

| Status | Meaning |
|---|---|
| `supported` | The parameter affects the request/response and is tested. |
| `accepted_ignored` | The parameter is accepted for SDK compatibility but is not sent upstream. |
| `rejected` | The parameter cannot be emulated correctly and returns a compatible `400` error. |
| `not_applicable` | The option is client-side transport configuration, not a server body parameter. |

## SDK Transport Options

`base_url`, `api_key`, `timeout`, retry settings, custom `http_client`, proxy
configuration, and low-level transport settings are client-side SDK options.
gpt2giga does not assign server-side semantics to them.

Credentials and transport headers are never forwarded to GigaChat as arbitrary
upstream metadata. This includes `Authorization`, `x-api-key`, cookies,
`host`, content/transfer headers, `x-stainless-*`, `openai-*`, and
`anthropic-*`.

## `extra_headers` and `extra_query`

Only these diagnostic headers are allowed to reach the upstream GigaChat HTTP
request:

- `x-request-id`
- `x-correlation-id`
- `x-trace-id`
- `traceparent`

The upstream query allowlist is empty by default. SDK `extra_query` values and
ordinary unknown query parameters are accepted by the proxy where the route
allows them, but arbitrary keys are not forwarded to GigaChat.

## `extra_body`

OpenAI SDK and Anthropic SDK normally merge `extra_body` into the outgoing JSON
body as top-level fields. Raw HTTP clients may also send a literal
`extra_body` object. gpt2giga handles both forms.

The allowlisted GigaChat-specific fields are:

- `flags`
- `function_ranker`
- `profanity_check`
- `repetition_penalty`
- `storage`
- `update_interval`

For OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages these
fields are moved into GigaChat `additional_fields`. Unknown `extra_body` fields
are rejected with `400`.

OpenAI Embeddings rejects `extra_body`; no embeddings-specific GigaChat fields
are currently allowlisted.

## OpenAI Body Parameters

| Endpoint | Supported |
|---|---|
| Chat Completions | `model`, `messages`, `stream`, `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`, function `tools`, `functions`, `function_call`, supported `tool_choice`, `response_format`, `reasoning`, `reasoning_effort`, allowlisted `extra_body` |
| Responses | `model`, `input`, `instructions`, `stream`, `temperature`, `top_p`, `max_output_tokens`, function `tools`, supported `tool_choice`, `text.format`, `response_format`, `reasoning`, `reasoning_effort`, allowlisted `extra_body` |
| Embeddings | `input`, `model`, `dimensions`, `encoding_format`, `user`, `extra_headers`, `extra_query` |
| Models | `GET /models`, `GET /models/{model}` |

OpenAI metadata fields such as `user`, `metadata`, `service_tier`,
`safety_identifier`, `seed`, `prompt_cache_key`, and
`prompt_cache_retention` are accepted and ignored where classified.

Unsupported OpenAI parameters return `400` when present with meaningful values.
Examples include `logprobs`, `top_logprobs`, `logit_bias`, audio output,
`prediction`, `web_search_options`, built-in tools, `n > 1`,
`parallel_tool_calls=true`, stored completion requests, and stateful Responses
features such as `previous_response_id` and `conversation`.

## Anthropic Body Parameters

| Endpoint | Supported |
|---|---|
| Messages | `model`, `messages`, `system`, `max_tokens`, `stream`, `temperature`, `top_p`, `stop_sequences`, local function `tools`, `tool_choice` values `auto`/`none`/forced `tool`, `thinking`, `output_config.format`, `output_format`, allowlisted `extra_body` |
| Count Tokens | `model`, `messages`, `system`, `tools`, structured-output schema text, compatible message content validation |
| Models | `GET /models`, `GET /models/{model_id}` when the request carries Anthropic SDK headers such as `anthropic-version` |

Anthropic `metadata`, `service_tier`, `top_k`, beta headers, and `betas` are
accepted and ignored where classified.

Unsupported Anthropic parameters or features return `400`. Examples include
`container`, `context_management`, `mcp_servers`, server-side tools, web search,
code execution, computer use, document/file content blocks, container uploads,
search result blocks, citations, and input `thinking`/`redacted_thinking`
blocks.

Anthropic Message Batches code exists but the public router is not mounted
until GigaChat SDK/backend batch support is available.

## Route Scope

Mounted routes are available both at root and under `/v1` through the app
router. Prepared but disabled OpenAI Files/Batches and Anthropic Message Batches
routes are intentionally omitted from the default OpenAPI schema.
