# How to add a provider or protocol

This document describes a practical checklist for extending gpt2giga with a new
upstream provider or a new public protocol. Before changing the API surface,
first decide what exactly is being added:

- a new public protocol: clients send Gemini-compatible payloads, and the
  upstream stays GigaChat;
- a new upstream provider: normalized requests are executed not only through
  GigaChat;
- both layers at once.

Terms:

- a protocol adapter translates an external wire format into normalized models and back;
- a provider adapter executes a normalized request on a specific upstream;
- a router mounts the HTTP surface and handles authorization, request context, streaming, and
  the response media type;
- observability, traffic logs, and metrics receive safe normalized or
  request-context fields.

## 1. Fix the scope

For a new protocol:

- define routes, headers, authorization expectations, and the `/v1` alias policy;
- describe the minimal supported operations: chat/messages, embeddings,
  a responses-like endpoint, count tokens, models;
- decide which optional fields are accepted and ignored for SDK
  compatibility.

For a new upstream provider:

- define authorization settings and secret handling;
- describe sync/non-streaming and streaming SDK calls;
- define model resolution, the per-model concurrency label, and timeout/retry
  semantics;
- decide which provider-specific fields can be stored in `provider_metadata`.

## 2. Add configuration

Update:

- `gpt2giga/models/config.py`: settings, validators, default values.
- `.env.example`: new env vars and safe defaults.
- `docs/configuration.md`: user-facing description.
- `tests/test_config/test_config.py`: defaults, env parsing, invalid values.

Secrets must stay in the env/secrets manager. Do not add provider secrets
to CLI examples, traffic logs, metrics labels, or debug output.

## 3. Add a protocol adapter

The files for a new public protocol usually live in
`gpt2giga/protocols/<protocol>/`.

A minimal set:

- `adapter.py` with an implementation of `ProtocolAdapter` from `gpt2giga/core/interfaces.py`;
- a request mapper to `NormalizedChatRequest` or another normalized model;
- a response mapper from `NormalizedResponse` to the public response shape;
- a streaming mapper from `NormalizedStreamEvent` to the public SSE/event format;
- a parameter sanitizer/classifier if the SDK sends many optional fields.

Mapping rules:

- put canonical fields into normalized fields;
- put unknown or accepted-but-not-executed public fields into
  `raw_extensions`, if they need to be kept;
- put provider-specific passthrough into `provider_metadata`;
- do not mix authorization/transport headers with the model payload;
- bring tool schemas and tool calls to `NormalizedTool` and
  `NormalizedToolCall`;
- bring usage to `input_tokens`, `output_tokens`, `total_tokens`;
- bring finish reasons to a common set such as `stop`, `length`,
  `tool_calls`, where possible.

For the already mounted Gemini protocol, this is done with a dedicated
Gemini-to-normalized mapper, not a new branch inside the OpenAI adapter.
Gemini-specific safety settings, candidates, content parts, tool declarations, and
stream events must be either promoted to canonical fields or explicitly stored in
extensions. For future protocols, keep the same principle of isolating the wire format
from the OpenAI adapter.

## 4. Add a provider adapter

The files for a new upstream provider live in `gpt2giga/providers/<provider>/`.

Usually needed:

- `adapter.py`: an implementation for non-streaming and streaming calls;
- `auth.py`: credentials/access-token helpers;
- `client.py`: an SDK/client factory;
- `streaming.py`: upstream chunks into `NormalizedStreamEvent`;
- `types.py`: local Protocol/types if the SDK types are inconvenient for tests.

The provider adapter must:

- accept a `NormalizedChatRequest`;
- call the upstream async-first;
- update the `RequestContext` effective model through `update_request_context`;
- use `ModelConcurrencyLimiter` with a bounded provider label;
- return a `NormalizedResponse` for non-streaming;
- return a `NormalizedStreamEvent` for streaming;
- normalize provider errors into `NormalizedError`;
- store only safe provider metadata;
- not write raw credentials, API keys, cookies, and authorization headers.

If the upstream provider can natively accept a normalized-like payload, there is no
need to reconstruct the OpenAI shape. For GigaChat the current adapter still
reuses an OpenAI-like payload and the legacy `RequestTransformer`; this is a
transitional detail, not a requirement for new providers.

## 5. Mount routes

Update the necessary layers:

- `gpt2giga/routers/<protocol>/`: concrete HTTP handlers.
- `gpt2giga/api/<protocol>/routes.py`: route aggregation.
- `gpt2giga/app/factory.py`: mounting, auth dependencies, debug/admin flags.
- `gpt2giga/openapi_specs/`: OpenAPI extras for new endpoints.
- `gpt2giga/app_state.py` and lifecycle setup, if a new client is needed.

The route handler must:

- read the body through shared helpers;
- create or use a request context;
- apply the proxy/admin authorization policy;
- call the protocol adapter and the provider adapter;
- wrap the streaming body iterator so that metrics, traffic logs, and
  observability see the final lifecycle;
- keep conversation stitching only where the semantics match.

## 6. Add observability

A new provider/protocol must be visible in Phoenix/OpenTelemetry, metrics, and
traffic logs without enabling prompt capture.

Update LLM observability:

- use `build_llm_chat_completion_attributes()` for chat-like flows,
  if the request/response is already normalized;
- add a separate helper in `gpt2giga/sinks/observability/<protocol>.py`,
  if the public protocol has a special output/event format;
- set a span name if a new root span is needed, for example `Gemini-Content`;
- set `gpt2giga.api_format` to a bounded value: `chat_completions`,
  `responses`, `messages`, `generate_content`, `embeddings`, or a new explicit
  format;
- map stream milestones to span events through `NormalizedStreamEvent`, where
  possible;
- keep tool visibility: counts/names by default, args/schema only
  with `GPT2GIGA_OBSERVABILITY_CAPTURE_CONTENT=True` and
  `GPT2GIGA_OBSERVABILITY_CAPTURE_TOOL_ARGS=True`;
- do not add prompts, responses, tool args, or the raw provider payload to
  attributes without opt-in and redaction.

Update request lifecycle observability:

- `RequestContext.protocol`, route, requested/effective model, and provider
  must be filled before emission;
- LLM routes must set `context.llm_observability_emitted=True` so as
  not to duplicate the successful lifecycle span;
- errors must reach `error_type`, `error_message`, the OpenTelemetry status,
  and the normalized error fields.

Update metrics:

- provider/protocol labels must be bounded;
- do not add request id, trace id, user id, API key hash, or raw model
  variants with high cardinality;
- check request counts, latency, upstream latency, upstream errors, token
  totals, stream disconnects, and dropped queue events.

Update traffic logs:

- request/response content capture stays opt-in;
- new payload fields must go through redaction;
- if the storage schema requires new indexed fields, add a migration and
  an OpenSearch template update;
- admin log filters must use bounded fields.

## 7. Add debug translation

For a new protocol/provider, extend the protected debug API:

- `SUPPORTED_TRANSLATE_FORMATS` in `gpt2giga/api/admin/routes.py`;
- a `<protocol>-to-normalized` endpoint, if a short path is needed;
- generic `/_debug/translate` pair handling;
- fixtures in `tests/fixtures/debug_translate/`;
- tests for unsupported pairs and safe errors.

Debug translation must not require real upstream credentials, except for
directions where you need to actually prepare a provider SDK payload. Raw secrets must
not end up in the response.

## 8. Add tests

A minimal set:

- adapter unit tests: request, response, tools, multimodal content, errors;
- streaming mapper tests: start/delta/tool/usage/end/error events;
- router tests: non-streaming, streaming, auth, invalid params, fallback;
- observability tests: spans, attributes, capture flags, redaction, tool events;
- metrics/traffic-log tests, if labels or emitted fields change;
- OpenAPI tests;
- golden fixtures for the public response/SSE format;
- SDK compatibility smoke tests, if a client package is available.

For the Gemini protocol, separately check candidate mapping, finish reasons,
safety-related fields, tool declarations/function calls, multimodal parts, and
stream event order.

## 9. Update docs

Update:

- `docs/api-compatibility.md`: route status and limitations.
- `docs/client-parameter-compatibility.md`: accepted/supported/ignored fields.
- `docs/configuration.md`: env vars and modes.
- `docs/operations.md`: metrics, traffic logs, observability, debug endpoints.
- `docs/deployment.md`: compose/env changes, if external services appear.
- `docs/architecture/normalized-messages.md`: if the normalized
  contract or execution status changes.
- the README documentation table, if a new user-facing document appears.

The documentation must clearly separate "implemented now" and "prepared for the
next step." This is especially important for partially prepared API families,
for example Files/Batches, so as not to promise a public route until it is mounted and
covered by tests.

## 10. Check quality

Before the PR:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

If dependencies changed, update `uv.lock`. If the deploy/env contracts changed,
check `.env.example`, the Compose files, and the docs together.
