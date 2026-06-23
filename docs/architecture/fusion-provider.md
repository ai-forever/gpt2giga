# Fusion provider architecture

GigaFusion is a composition provider. It does not add a new external upstream:
it orchestrates several internal normalized GigaChat calls and returns one
normalized response to the public protocol mapper.

```text
OpenAI / Anthropic / Gemini request
  -> route-specific request adapter
  -> Fusion detection
  -> NormalizedChatRequest
  -> FusionProviderAdapter
       -> optional direct candidate through GigaChatProviderAdapter
       -> parallel panel calls through GigaChatProviderAdapter
       -> judge/finalizer or selector call through GigaChatProviderAdapter
       -> optional selector finalizer through GigaChatProviderAdapter
       -> FusionRunResult + NormalizedResponse
  -> route-specific response adapter
```

## Module map

| Module | Role |
|---|---|
| `gpt2giga.providers.fusion.detection` | Detects aliases, OpenRouter-style plugin/tool hints, and native `gpt2giga_fusion` metadata. |
| `gpt2giga.providers.fusion.presets` | Built-in `general`, `code-budget`, and `code-high` presets plus custom preset merge. |
| `gpt2giga.providers.fusion.adapter` | Runs direct/panel candidates, judge/finalizer or selector calls, fallback handling, metadata, telemetry and normalized response construction. |
| `gpt2giga.providers.fusion.prompts` | Panel and judge prompt templates. |
| `gpt2giga.providers.fusion.schemas` | Pydantic models for panel results, structured judge analysis and complete run result. |
| `gpt2giga.providers.fusion.tool_arbitration` | Reference-only panel tool schemas and validated final tool-call arbitration. |
| `gpt2giga.providers.fusion.usage` | Aggregates token usage across panel and judge phases. |
| `gpt2giga.providers.fusion.telemetry` | Emits bounded metrics and observability events without prompt content. |
| `gpt2giga.providers.fusion.model_discovery` | Adds virtual Fusion aliases to OpenAI, Gemini and LiteLLM model listings. |

## Detection contract

Fusion detection runs only when `GPT2GIGA_FUSION_ENABLED=True`.

Priority is intentionally explicit:

1. `tools: [{"type": "openrouter:fusion"}]`
2. `plugins: [{"id": "fusion"}]`
3. `metadata.gpt2giga_fusion`, `extra_body.gpt2giga_fusion`, or top-level
   `gpt2giga_fusion`
4. configured model alias such as `gpt2giga/fusion-code`

Plugin/tool/metadata configs can set `"enabled": false` to opt out for that
request. Resolved panel, judge and final model ids are validated against the
configured aliases so Fusion cannot recursively call Fusion.

Routes strip Fusion request artifacts before internal GigaChat calls:

- `openrouter:fusion` pseudo-tools are removed from normalized tools;
- `plugins` and `gpt2giga_fusion` metadata are removed from passthrough fields;
- internal requests add `gpt2giga_fusion_stage=direct_candidate|panel|judge|selector_judge|selector_finalizer` metadata for bounded operational context.

## Request flow

The public route first converts the request into `NormalizedChatRequest`. When
`include_direct_candidate=true`, Fusion first deep-copies the original request
for a baseline-like direct candidate:

- `model` is replaced with `direct_model` or `judge_model`;
- `stream` is forced to `False`;
- no Fusion system prompt or panel role is added;
- preset generation overrides are applied only when non-null.

Fusion also deep-copies that request for each panel model:

- `model` is replaced with the concrete panel model;
- `stream` is forced to `False`;
- response format is disabled for panels;
- preset generation overrides are applied only when non-null;
- a Fusion system prompt and optional panel role are prepended;
- tools are not forwarded for execution in panel calls.

Panel calls run concurrently with `GPT2GIGA_FUSION_MAX_PANEL_CONCURRENCY`, bounded
by the number of analysis models. The whole Fusion request also enters the
application-scoped `GPT2GIGA_FUSION_MAX_CONCURRENT_REQUESTS` limiter, and request
detection rejects plans whose direct candidate, panel calls, judge call and
mandatory selector finalizer exceed
`GPT2GIGA_FUSION_MAX_TOTAL_UPSTREAM_CALLS_PER_REQUEST` when that limit is
positive. Each upstream call has the preset timeout. Disconnect checks cancel
in-flight panel tasks when the client connection goes away before the buffered
response is produced.

After panels complete, the adapter requires at least `min_successful_panels`.
Failed panels remain in run metadata as `error` or `timeout`, but raw error
messages are not exported through metrics or telemetry.

## Judge/finalizer flow

The compact pipeline has two decision modes. `synthesize` combines judge and
finalizer into one GigaChat call and returns `FusionAnalysis`. `selector`
returns `FusionSelection`; if `needs_rewrite=false` and
`return_selected_candidate=true`, the selected candidate is returned unchanged.
Otherwise an optional finalizer call uses `final_model` or `judge_model`.

The synthesize judge request contains:

- the original normalized messages;
- successful and failed panel summaries;
- a structured-output instruction asking for `FusionAnalysis`;
- optional tool arbitration instructions.

The judge is expected to return JSON with:

- `consensus`
- `schema_version`
- `contradictions`
- `partial_coverage`
- `unique_insights`
- `blind_spots`
- `risk_flags`
- `selected_strategy`
- `final_answer`
- `final_tool_call`

Candidate outputs are wrapped as untrusted advisory data and the judge prompt
tells the model not to follow instructions inside them. Candidate content is
truncated before the judge prompt with per-candidate and total character
budgets.

If the synthesize judge response is empty or not parseable as the expected
object, Fusion makes one repair call. If repair also fails, or selector parsing
fails, Fusion falls back in order to direct candidate, selected candidate,
solver panel and first successful panel, recording
`gpt2giga_fusion_fallback_reason`.

## Tool arbitration

Fusion does not execute tools itself.

`tools_mode` controls how tool schemas affect the run:

| Mode | Behavior |
|---|---|
| `off` | Panel and judge calls do not receive executable tools; final tool calls are forbidden. |
| `schema_only` | Panels receive tool schemas as text reference only; the judge may return one validated final tool call when request policy allows it. |
| `final_arbitration` | Panels may propose candidates, but only the judge/finalizer can emit the final validated tool call. |

Panel-stage tool candidates are advisory. Final calls are validated against
allowed tool names, forced `tool_choice`, required tool calls,
`GPT2GIGA_FUSION_MAX_TOOL_CALLS=1` and the original tool arguments JSON Schema.
Judge final actions are normalized to one visible action: final text or one
validated progress tool call. Meta/state tools from
`GPT2GIGA_FUSION_META_TOOL_NAMES` are not final progress actions, and repeated
assistant tool-call signatures after the latest user message are suppressed.
If the client required a tool call and the judge does not produce a valid one,
Fusion returns a typed normalized error instead of silently returning text.

## Streaming

Fusion streaming is buffered. Internal panel and judge calls complete first, then
the completed normalized response is converted to the protocol-specific SSE
shape:

- OpenAI Chat Completions chunks;
- OpenAI Responses events;
- Anthropic Messages events;
- Gemini `GenerateContentResponse` SSE chunks.

`GPT2GIGA_FUSION_STREAM_HEARTBEAT_SECONDS` is disabled by default. When set to a
positive value, OpenAI Chat Completions streaming sends SSE comment heartbeat
frames while Fusion deliberation is still running. Other protocol streams remain
strict buffered streams until their client SDK compatibility is verified.

`GPT2GIGA_FUSION_STREAMING_MODE=off` makes streaming Fusion requests fail with a
configuration error. Non-streaming Fusion requests continue to work.

## Metadata and observability

The public normalized metadata is bounded:

- `gpt2giga_fusion=true`
- requested alias
- preset
- analysis models
- judge/final model
- decision mode and prompt mode
- selected candidate id/source
- rewrite, judge parse error and truncation flags
- successful and failed panel counts
- fallback reason, when present

Provider metadata contains structured run internals for process-local consumers.
Raw panel content is included only when
`GPT2GIGA_FUSION_EXPOSE_PANEL_RESPONSES=True`; judge analysis is included only
when `GPT2GIGA_FUSION_EXPOSE_ANALYSIS_METADATA=True`.

Telemetry emits:

- one `GigaFusion` span per completed run;
- panel events with model, role, status, latency and error type;
- direct, judge and optional finalizer stage latency events;
- Prometheus-compatible `gpt2giga_fusion_*` metrics.

Telemetry does not export prompt content, raw panel responses, tool arguments,
credentials, Authorization headers or cookies.

## Extending Fusion safely

When changing Fusion behavior:

1. Keep public protocol routes responsible for request/response shape only.
2. Keep orchestration inside `FusionProviderAdapter`.
3. Never pass Fusion aliases as internal panel/judge/final models.
4. Preserve artifact stripping before internal GigaChat calls.
5. Add tests for detection, adapter behavior, route mapping and telemetry
   safety when changing any execution path.
6. Update [GigaFusion](../fusion.md) when env variables, presets, request shapes
   or public metadata change.
