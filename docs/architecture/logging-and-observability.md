# Logging and Observability

This document defines the logging terms used by the modular roadmap. The terms
are intentionally separate because they have different security, storage, and
operational requirements.

## Runtime Logs

Runtime logs are process logs emitted by the running gpt2giga service. Today
they are handled by the existing Loguru-based logger and are written to stdout
and the configured log file.

Runtime logs are used for:

- startup and shutdown status;
- operational warnings and errors;
- request-scoped diagnostics with the internal request id;
- development-only debug payload logging when allowed by configuration.

Runtime logs must not contain raw API keys, credentials, cookies, tokens, or
other secrets. Sensitive field redaction stays enabled by default.

## Traffic Logs

Traffic logs are future structured records of LLM request/response traffic. They
are separate from runtime logs and are intended for controlled storage sinks such
as JSONL, Postgres, or OpenSearch.

Traffic logs may contain:

- request id, trace id, protocol, route, method, and timing metadata;
- hashed client or API-key identifiers;
- requested and effective model names;
- status and token usage;
- optionally captured prompts and responses when explicit opt-in settings allow it.

Content capture must remain disabled by default. Redaction must remain enabled by
default. Raw authorization headers, `x-api-key`, cookies, credentials, and local
certificate material must never be stored.

## Observability

Observability covers traces, spans, and metrics emitted through future
OpenTelemetry/OpenInference integrations. Arize Phoenix is a planned destination,
not a replacement for runtime logs or traffic logs.

Observability events should use request context fields for correlation:

- `request_id`;
- `trace_id`;
- optional `span_id`;
- protocol and route metadata;
- model metadata when available.

Prompt and response capture for observability must be opt-in and must follow the
same redaction rules as traffic logs.

## Metrics

Metrics are aggregate counters and histograms for operational health. They are
disabled by default and can be exposed through the Prometheus-compatible
`/metrics` endpoint with `GPT2GIGA_METRICS_ENABLED=True`.

Metrics should describe aggregate behavior such as:

- request counts by protocol, route, status, and model;
- latency histograms;
- upstream error counts;
- stream disconnect counts;
- traffic-log and observability sink failures.

Metrics must not include prompt or response content. Labels should avoid high
cardinality raw identifiers; use bounded protocol, route, status, and model
values where possible.

The metrics endpoint follows the same API-key policy as public API routes. In
`PROD` it requires `GPT2GIGA_API_KEY`; in `DEV` it is open only when global
API-key auth is disabled. It exports baseline service series for request counts,
request/upstream latency, upstream errors, token totals, stream disconnects, and
traffic-log queue drops.
