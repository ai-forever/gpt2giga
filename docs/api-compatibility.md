# API compatibility

`gpt2giga` is a compatibility proxy, not a full clone of OpenAI, Anthropic, or
Gemini. It focuses on the API subset commonly needed by SDKs, editors, and
agent tools when the backend is GigaChat or a reviewed OpenAI-compatible Chat
Completions server.

## What does not work directly with GigaChat

Below are the practical incompatibilities that the proxy covers.

| Client expectation | Why it breaks without the proxy | What `gpt2giga` does |
|---|---|---|
| OpenAI Chat Completions JSON | GigaChat has different formats for messages, tools, attachments, and responses. | Converts requests and responses, including streaming chunks. |
| OpenAI Responses API | GigaChat has no equivalent `/responses` route and schema for output items. | Accepts `/responses`, maps input/instructions/tools, and normalizes output items where possible. |
| Anthropic Messages API | Anthropic content blocks, tool use, `system`, `max_tokens`, and stream events do not match GigaChat. | Converts Anthropic payloads into GigaChat-compatible chat requests and maps the responses back. |
| Gemini GenerateContent API | Gemini `contents`/`parts`, candidates, function declarations, token counting, and SSE chunks differ from OpenAI/Anthropic and GigaChat. | Accepts Gemini-like requests at the root, under `/v1`, `/v2`, and `/v1beta`, translates them into normalized chat/embeddings requests, and maps the responses back into the Gemini shape. |
| SDK `extra_headers`, `extra_query`, `extra_body` | SDKs may send transport fields or optional model fields that GigaChat does not accept. | Filters dangerous headers, passes only allowed metadata, forwards GigaChat-specific `extra_body`, and ignores known unsupported optional fields. |
| Streaming SSE | OpenAI, Anthropic, and Gemini SDKs expect their own event names and delta shapes. | Generates OpenAI-, Anthropic-, and Gemini-compatible SSE from GigaChat streaming responses. |
| Tools and structured output | Function/tool schemas and JSON-schema controls differ between providers and backend modes. | Maps local tools/functions and forwards structured-output schemas through native GigaChat `response_format`. |
| Authorization | OpenAI/Anthropic clients work with API keys, while GigaChat requires a different credentials/scope mechanism. | Separates proxy API-key authentication from upstream GigaChat authorization and, if needed, supports per-request pass-through. |
| Model discovery | GigaChat model responses do not match the OpenAI/Anthropic/Gemini/LiteLLM shape. | Repackages the model list and description for the target client. |
| OpenAI/Anthropic/Gemini batch routes | The installed GigaChat SDK/backend has no full create/list/retrieve/cancel flow for batch APIs. | Keeps the Files/Batches routers disabled until they can work end-to-end. |

## Mounted routes

Public API routes are available at the root and under versioned prefixes.
For built-in GigaChat models, `/v1` forces the GigaChat v1 contract, `/v2`
forces v2, and root routes use `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`. A model that
resolves to an explicit provider-profile alias uses that profile instead; the
versioned public prefix does not redirect it to GigaChat.

Examples:

- `/chat/completions`, `/v1/chat/completions`, and `/v2/chat/completions`
- `/responses`, `/v1/responses`, and `/v2/responses`
- `/messages`, `/v1/messages`, and `/v2/messages`
- `/models/{model}:generateContent`, `/v1/models/{model}:generateContent`, `/v2/models/{model}:generateContent`, and `/v1beta/models/{model}:generateContent`

## OpenAI-compatible routes

| Route / group | Status | Comment |
|---|---|---|
| `GET /models` | Supported | Dynamic GigaChat inventory or static provider-profile aliases in OpenAI form. |
| `GET /models/{model}` | Supported | One dynamic model or exact static alias in OpenAI form. |
| `POST /chat/completions` | Supported | Non-streaming and streaming chat, tools/function calling, structured output, attachments where supported. |
| `POST /responses` | Stable native / normalized preview | Native GigaChat execution preserves the compatibility surface, including hosted tools and attachment handoff. Route-selected normalized execution is technical preview and rejects semantics that its selected route/model/API mode cannot preserve. |
| `POST /embeddings` | Supported | Uses the model from the request or the proxy default for embeddings, depending on the configuration. |
| `GET /model/info` | Supported | LiteLLM-compatible model info endpoint. |
| `POST /files`, `GET /files*` | Disabled | Router code exists but is not mounted: files without batches give an incomplete OpenAI batch flow. |
| `POST /batches`, `GET /batches*` | Disabled | Disabled until batch create/list/retrieve/cancel appears in the GigaChat SDK/backend. |
| Stored chat-completion routes | Not implemented | Stored completions are out of scope for now. |
| Legacy `POST /completions` | Not implemented | Legacy text completions are out of scope for now. |
| Images, audio, moderations, uploads | Not implemented | The proxy does not implement these OpenAI route families. |
| Fine-tuning, assistants, threads, runs, vector stores | Not implemented | Out of scope for now. |
| Realtime/WebSocket API | Not implemented | Out of scope for now. |

## Anthropic-compatible routes

| Route / group | Status | Comment |
|---|---|---|
| `GET /models` | Supported | Returned in the Anthropic shape when the request contains Anthropic SDK headers. |
| `GET /models/{model_id}` | Supported | Returned in the Anthropic shape when the request contains Anthropic SDK headers. |
| `POST /messages` | Supported | Messages API, streaming, local tools, GigaChat v2 mapping for compatible Anthropic provider tools, and native structured output. With `GPT2GIGA_NORMALIZATION_MODE=on`, the accepted v1 subset uses the normalized request/response/SSE core. |
| `POST /messages/count_tokens` | Provider-dependent | GigaChat can count message, system, tool, and structured-output text. A Chat Completions-only external alias rejects the operation because it has no exact token-count API. |
| `POST /messages/batches`, `GET /messages/batches*` | Disabled | Router code exists but is not mounted until batch methods appear in the GigaChat SDK/backend. |
| Files API beta | Not implemented | Out of scope for now. |
| Skills API beta | Not implemented | Out of scope for now. |
| Agents, Sessions, Environments, Admin beta APIs | Not implemented | Out of scope for now. |

## Gemini-compatible routes

Gemini operation routes are mounted at the root, under `/v1`, `/v2`, and `/v1beta`,
like the other public APIs. For clients that add the Gemini API version to an
already versioned base URL, `/v1/v1beta` and `/v2/v1beta` are also available.
`/v1` and `/v1/v1beta` force the GigaChat v1 backend contract, `/v2` and
`/v2/v1beta` force the GigaChat v2 backend contract. The root Gemini paths
`/...` and `/v1beta/...` without an outer `/v1` or `/v2` use
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

Those Gemini version-prefix rules apply to built-in GigaChat models. An exact
external provider-profile alias remains on its selected provider for every
compatible public path.

Gemini model discovery in the pure Gemini form is always available under
`/v1beta`, `/v1/v1beta`, and `/v2/v1beta`.
On the shared `/models`, `/v1/models`, and `/v2/models`, the proxy keeps the
OpenAI form by default, but returns the Gemini form for Google/Gemini clients,
for example with the `X-Goog-Api-Client` or `X-Goog-Api-Key` headers, or with the
`?key=...` query parameter.

OpenAI-shaped model objects include the gpt2giga extension
`metadata.type="chat"|"embedder"`. The gateway preserves an upstream type when
available and otherwise infers embedding models from their model id. Consumers
can use this metadata to keep embedding-only models out of chat model selectors
without changing the standard OpenAI model fields.

If proxy API-key authentication is enabled, Gemini-compatible clients can pass
the key via `x-goog-api-key` or `?key=...`, in addition to the common
`Authorization: Bearer ...`, `x-api-key`, and `?x-api-key=...`. For new setups,
header-based authentication is preferable: query keys more often end up in access
logs.

`supportedGenerationMethods` is built conservatively: known GigaChat/chat-like
models advertise `generateContent`, `streamGenerateContent`, and `countTokens`;
embedding-like models advertise only `embedContent` and `batchEmbedContents`;
unknown/custom model ids advertise only `countTokens`, unless the backend metadata
provides more precise information. A static Chat Completions alias advertises
generation and streaming, but not `countTokens`.

| Route / group | Status | Comment |
|---|---|---|
| `GET /v1beta/models`, `/v1/v1beta/models`, `/v2/v1beta/models` | Supported | List of GigaChat models in the Gemini `models/*` form. |
| `GET /v1beta/models/{model}`, `/v1/v1beta/models/{model}`, `/v2/v1beta/models/{model}` | Supported | A single model in the Gemini `Model` form. |
| `POST /models/{model}:generateContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Supported | Maps the admitted `contents`/`parts`, `systemInstruction`, `generationConfig`, function declarations/results, typed inline images, and JSON Schema output into a bridge-admissible normalized chat request. Unmodeled safety, cache, file, and tool semantics remain explicit and fail OpenAI-compatible bridge admission before I/O. |
| `POST /models/{model}:streamGenerateContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Supported | Returns `text/event-stream` with Gemini `GenerateContentResponse` chunks. |
| `POST /models/{model}:countTokens`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Provider-dependent | GigaChat counts `systemInstruction`, `contents`, and function declarations. A Chat Completions-only external alias rejects the operation. |
| `POST /models/{model}:embedContent`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Supported | Returns Gemini `embedding.values` using the GigaChat embeddings backend. |
| `POST /models/{model}:batchEmbedContents`, `/v1/...`, `/v2/...`, `/v1beta/...`, `/v1/v1beta/...`, `/v2/v1beta/...` | Supported | Returns Gemini `embeddings[]` using the GigaChat embeddings backend. |
| `POST /v1beta/files`, `GET /v1beta/files*` | Disabled | Router code is prepared but not mounted by default. |
| `POST /v1beta/models/{model}:batchGenerateContent`, `GET /v1beta/batches*` | Disabled | Router code is prepared but not mounted until end-to-end batch execution. |

### Gemini function calling

`toolConfig.functionCallingConfig` is mapped to the nearest supported semantics
of the normalized/OpenAI-like layer:

- `mode=AUTO` keeps function calling optional. If `allowedFunctionNames` is set,
  the upstream receives only those declared functions.
- `mode=NONE` disables function calling.
- `mode=ANY` is supported only when, after applying `allowedFunctionNames`,
  exactly one function remains; it is mapped to a forced function call.
- `mode=ANY` without `allowedFunctionNames` is also supported if exactly one
  function is declared.
- `mode=ANY` with several possible functions returns `400`, because the
  GigaChat backend path currently cannot honestly express "must call one of
  several functions."
- `allowedFunctionNames` is validated against the declared
  `functionDeclarations`; references to undeclared functions return `400`.

### Gemini embeddings

`embedContent` and `batchEmbedContents` support only text
`content.parts[].text`. Empty `requests`, malformed batch entries, and
non-text parts return `400` before the GigaChat embeddings backend is called.

`outputDimensionality` is accepted as compatibility metadata for the normalized
request/observability, but is not passed upstream as an executable setting:
the current GigaChat embeddings backend path does not provide controlled
dimension reduction through this parameter.

### Gemini release scope and validation

This is a Gemini-compatible API surface, not full Gemini API parity. Before a
release, check exactly the declared scope:

- supported routes: `generateContent`, `streamGenerateContent`, `countTokens`,
  `embedContent`, `batchEmbedContents`, model discovery;
- supported prefixes: root, `/v1`, `/v2`, `/v1beta`, `/v1/v1beta`,
  `/v2/v1beta`;
- disabled routes: the Gemini Files API and `batchGenerateContent` routers exist
  in the code but are not publicly mounted until end-to-end upstream execution;
- partially supported fields: `safetySettings` and `cachedContent` are accepted
  for compatibility/diagnostics but not enforced; `candidateCount`, `topK`, and
  `responseModalities` are accepted/observed but ignored by GigaChat execution;
- structured output: `generationConfig.responseMimeType=text/plain` is treated as
  the default text mode, `application/json` is mapped to the JSON response
  format, and other MIME types and `responseSchema` without `application/json`
  return `400`;
- unsupported features: Gemini tools outside the GigaChat SDK built-in mapping
  (`fileSearch`, `googleMaps`, `computerUse`, MCP, RAG/retrieval/Vertex tools),
  full multimodal/file-backed Gemini flows, non-text embeddings content;
- approximations: `countTokens` counts the extracted text through GigaChat token
  counting, ignores non-text/file/cachedContent parts, and is not an exact
  Gemini tokenizer.

Copyable release checklist for the PR description:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/test_protocol/test_gemini_adapter.py tests/test_router/test_gemini_router.py tests/integration/gemini/test_gemini_app_wiring.py

# Optional, requires live GigaChat credentials.
GPT2GIGA_RUN_LIVE_TESTS=1 uv run pytest tests/live/test_real_gigachat_integration.py -k gemini

# Optional release smoke for google-genai + Gemini CLI, auth on/off, and base URL matrix.
GPT2GIGA_RUN_GEMINI_SMOKE=1 GPT2GIGA_LIVE_ENV_FILE=.env.live uv run pytest tests/live/test_gemini_client_smoke.py
```

## Compatibility policy

`gpt2giga` intentionally accepts many optional SDK fields that GigaChat cannot execute. This keeps clients from failing before the useful part of the request reaches the model.

Typical fields that are accepted and ignored:

- OpenAI metadata and fine-tuning parameters: `user`, `metadata`, `service_tier`, `seed`, `prompt_cache_key`, `logprobs`, `top_logprobs`, `logit_bias`, `prediction`, `web_search_options`, `n > 1`, `parallel_tool_calls=true`;
- Optional Anthropic fields: `metadata`, `service_tier`, `top_k`, `container`, `context_management`, `mcp_servers`, unsupported provider tools, citations, unsupported document/file content blocks. Compatible provider tools (`web_search*`, `web_fetch*`, `code_execution*`) are mapped to GigaChat v2 built-in tools.
- Optional Gemini fields: `safetySettings`, `cachedContent`, `serviceTier`, ignored `generationConfig` controls such as `candidateCount`/`topK`/`responseModalities`, and unsupported non-function tools are accepted and kept for diagnostics, but not applied by GigaChat. Compatible Gemini provider tools are mapped to GigaChat v2 built-in tools: `googleSearch` / `googleSearchRetrieval` -> `web_search`, `urlContext` -> `url_content_extraction`, `codeExecution` -> `code_interpreter`; the full mapping is described in [Built-in tools](builtin-tools.md). Unsupported `responseMimeType` values and `responseSchema` without `application/json` are rejected.

If a field is intentionally ignored, it is not sent upstream as an executable GigaChat feature. A literal `extra_body` object can be passed to GigaChat `additional_fields`; in that case the GigaChat API determines support.

In observability, ignored request extensions are published in the redacted
`llm.request.extensions` attribute, and ignored Gemini generation controls remain
in `llm.invocation_parameters`.

A reference for each parameter: [Client parameter compatibility](./client-parameter-compatibility.md).

The 0.3 multi-provider route statuses, semantic dispositions, machine
capability contract, and stable bridge errors are documented in
[Bridge compatibility, loss, and errors](bridge-compatibility.md).

The internal normalized layer that separates public protocol formats from
provider execution is described in
[Normalized messages architecture](./architecture/normalized-messages.md).

The normalized bridge includes:

- a versioned semantic-loss matrix for OpenAI-compatible, Anthropic, and Gemini
  routes, with unsupported requests rejected before provider I/O;
- an OpenAI-compatible/vLLM Chat Completions adapter with exact profile/model
  binding, request-specific network authorization, `SecretRef`, strict model
  discovery, and bounded streaming;
- direct Anthropic request, response, SSE, tool, usage, error, and token-count
  projection through the normalized core;
- the admitted Gemini request, response, SSE, function, safety, usage, model,
  and token-count contracts, including typed inline-image references;
- hermetic coverage for text, streaming, partial usage, function tools,
  cancellation, malformed streams, timeouts, and provider errors across the
  three public protocol families.

This does not add a public switch for arbitrary upstream addresses. Version 0.3
profiles define routes, credential values remain in the environment, and the
trusted application owner supplies network/TLS policy references. See
[Provider profiles and model aliases](provider-profiles.md).

## Backend modes

By default, the GigaChat root compatibility methods are used:

```dotenv
GPT2GIGA_GIGACHAT_API_MODE=v1
```

Set `GPT2GIGA_GIGACHAT_API_MODE=v2` so that root routes without `/v1` or
`/v2` use the newer GigaChat `v2/chat/completions` surface for chat-like
requests. For an explicit choice at the client level, use a `base_url` with
`/v1` or `/v2`: `/v1` always goes to the GigaChat v1 contract, `/v2` always
goes to the GigaChat v2 contract.

`/chat/completions` remains a compatibility route and follows the env. The new
built-in-tool capabilities evolve mostly around GigaChat v2 mode, so clients that
need them can point to `http://localhost:8090/v2`.
