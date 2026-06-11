# Logging и observability

Документ определяет термины logging, которые используются в modular roadmap.
Они намеренно разделены, потому что у них разные требования к security, storage
и operations.

## Runtime Logs

Runtime logs — это process logs, которые пишет запущенный service gpt2giga.
Сейчас их обрабатывает существующий Loguru-based logger; они пишутся в stdout
и настроенный log file.

Runtime logs используются для:

- статуса startup и shutdown;
- operational warnings и errors;
- request-scoped diagnostics с внутренним request id;
- development-only debug payload logging, если это разрешено configuration.

Runtime logs не должны содержать raw API keys, credentials, cookies, tokens или
другие secrets. Sensitive field redaction остаётся включённой по умолчанию.

## Traffic Logs

Traffic logs — это structured records для LLM request/response traffic. Они
отделены от runtime logs и предназначены для controlled storage sinks: JSONL,
Postgres или OpenSearch.

Traffic logs могут содержать:

- request id, trace id, protocol, route, method и timing metadata;
- hashed client или API-key identifiers;
- requested и effective model names;
- status и token usage;
- prompts и responses, если это явно разрешено opt-in settings.

Content capture должен оставаться выключенным по умолчанию. Redaction должна
оставаться включённой по умолчанию. Raw authorization headers, `x-api-key`,
cookies, credentials и local certificate material никогда не должны сохраняться.

## Observability

Observability включает traces, spans и metrics, которые отправляются через
OpenTelemetry/OpenInference-compatible integrations. Arize Phoenix — optional
destination, а не замена runtime logs или traffic logs.

Observability events должны использовать request context fields для correlation:

- `request_id`;
- `trace_id`;
- optional `span_id`;
- metadata protocol и route;
- metadata model, если доступна.

Prompt и response capture для observability должны быть opt-in и следовать тем
же redaction rules, что и traffic logs.

LLM-specific observability строится вокруг normalized request/response models,
где это возможно: Chat Completions использует `NormalizedChatRequest` и
`NormalizedResponse`, Responses и Anthropic helpers приводят public payloads к
chat-like normalized representation для spans, а streaming milestones могут
строиться из `NormalizedStreamEvent`. Это позволяет добавлять новый
protocol/provider без копирования всей OpenInference/Phoenix mapping logic.
Подробности: [Normalized messages architecture](./normalized-messages.md).

## Metrics

Metrics — это aggregate counters и histograms для operational health. Они
выключены по умолчанию и могут публиковаться через Prometheus-compatible
endpoint `/metrics` при `GPT2GIGA_METRICS_ENABLED=True`.

Metrics должны описывать aggregate behavior, например:

- request counts по protocol, route, status и model;
- latency histograms;
- upstream error counts;
- stream disconnect counts;
- сбои traffic-log и observability sinks.

Metrics не должны включать prompt или response content. Labels должны избегать
high-cardinality raw identifiers; по возможности используйте bounded значения
protocol, route, status и model.

Metrics endpoint следует той же API-key policy, что и public API routes. В
`PROD` он требует `GPT2GIGA_API_KEY`; в `DEV` он открыт только при выключенной
global API-key auth. Он экспортирует baseline service series для request counts,
request/upstream latency, upstream errors, token totals, stream disconnects и
traffic-log queue drops.
