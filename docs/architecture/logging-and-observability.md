# Logging and observability

This document defines the logging terms used in the modular roadmap.
They are intentionally separated because they have different requirements for
security, storage, and operations.

## Runtime logs

Runtime logs are the process logs written by the running gpt2giga service.
They are currently handled by the existing Loguru-based logger; they are written to
stdout and the configured log file.

Runtime logs are used for:

- startup and shutdown status;
- operational warnings and errors;
- request-scoped diagnostics with an internal request id;
- development-only debug payload logging, if allowed by the configuration.

Runtime logs must not contain raw API keys, credentials, cookies, tokens, or
other secrets. Sensitive field redaction stays enabled by default.

## Traffic logs

Traffic logs are structured records of LLM request/response traffic. They are
separated from runtime logs and intended for controlled storage sinks: JSONL,
Postgres, or OpenSearch.

Traffic logs may contain:

- request id, trace id, protocol, route, method, and timing metadata;
- hashed client or API-key identifiers;
- requested and effective model names;
- status and token usage;
- prompts and responses, if explicitly allowed by opt-in settings.

Content capture must stay disabled by default. Redaction must stay enabled by
default. Raw authorization headers, `x-api-key`, cookies, credentials, and local
certificate material must never be stored.

## Observability

Observability includes traces, spans, and metrics sent through
OpenTelemetry/OpenInference-compatible integrations. Arize Phoenix is an optional
destination, not a replacement for runtime logs or traffic logs.

Observability events must use request context fields for correlation:

- `request_id`;
- `trace_id`;
- optional `span_id`;
- protocol and route metadata;
- model metadata, if available.

Prompt and response capture for observability must be opt-in and follow the same
redaction rules as traffic logs.

LLM-specific observability is built around the normalized request/response models
where possible: Chat Completions uses `NormalizedChatRequest` and
`NormalizedResponse`, Responses and Anthropic helpers bring public payloads to a
chat-like normalized representation for spans, and streaming milestones can be
built from `NormalizedStreamEvent`. This makes it possible to add a new
protocol/provider without copying all the OpenInference/Phoenix mapping logic.
Details: [Normalized messages architecture](./normalized-messages.md).

## Metrics

Metrics are aggregate counters and histograms for operational health. They are
disabled by default and can be published through the Prometheus-compatible
endpoint `/metrics` with `GPT2GIGA_METRICS_ENABLED=True`.

Metrics must describe aggregate behavior, for example:

- request counts by protocol, route, status, and model;
- latency histograms;
- upstream error counts;
- stream disconnect counts;
- traffic-log and observability sink failures.

Metrics must not include prompt or response content. Labels must avoid
high-cardinality raw identifiers; where possible, use bounded values of
protocol, route, status, and model.

The metrics endpoint follows the same API-key policy as the public API routes. In
`PROD` it requires `GPT2GIGA_API_KEY`; in `DEV` it is open only with the global
API-key authentication disabled. It exports the baseline service series for request counts,
request/upstream latency, upstream errors, token totals, stream disconnects, and
traffic-log queue drops.
