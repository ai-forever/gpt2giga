import { renderTable } from "../../templates.js";
import {
  asRecord,
  escapeHtml,
  formatDurationMs,
  formatNumber,
  formatTimestamp,
  setQueryParamIfPresent,
} from "../../utils.js";
import type {
  DefinitionItem,
  TrafficDetailKind,
  TrafficEvent,
  TrafficFilters,
  TrafficSelection,
  UsageEntry,
} from "./state.js";
import { DEFAULT_LIMIT } from "./state.js";

export function readTrafficFilters(): TrafficFilters {
  const params = new URLSearchParams(window.location.search);
  return {
    limit: params.get("limit") || DEFAULT_LIMIT,
    requestId: params.get("request_id") || "",
    provider: params.get("provider") || "",
    endpoint: params.get("endpoint") || "",
    method: params.get("method") || "",
    statusCode: params.get("status_code") || "",
    model: params.get("model") || "",
    errorType: params.get("error_type") || "",
    source: params.get("source") || "",
    apiKeyName: params.get("api_key_name") || "",
  };
}

export function buildEventQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setQueryParamIfPresent(params, "request_id", filters.requestId);
  setQueryParamIfPresent(params, "provider", filters.provider);
  setQueryParamIfPresent(params, "endpoint", filters.endpoint);
  setQueryParamIfPresent(params, "method", filters.method);
  setQueryParamIfPresent(params, "status_code", filters.statusCode);
  setQueryParamIfPresent(params, "model", filters.model);
  setQueryParamIfPresent(params, "error_type", filters.errorType);
  return params.toString();
}

export function buildUsageKeysQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setQueryParamIfPresent(params, "provider", filters.provider);
  setQueryParamIfPresent(params, "model", filters.model);
  setQueryParamIfPresent(params, "source", filters.source);
  return params.toString();
}

export function buildUsageProvidersQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setQueryParamIfPresent(params, "provider", filters.provider);
  setQueryParamIfPresent(params, "model", filters.model);
  setQueryParamIfPresent(params, "api_key_name", filters.apiKeyName);
  return params.toString();
}

export function buildTrafficUrl(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  setQueryParamIfPresent(params, "limit", filters.limit, DEFAULT_LIMIT);
  setQueryParamIfPresent(params, "request_id", filters.requestId);
  setQueryParamIfPresent(params, "provider", filters.provider);
  setQueryParamIfPresent(params, "endpoint", filters.endpoint);
  setQueryParamIfPresent(params, "method", filters.method);
  setQueryParamIfPresent(params, "status_code", filters.statusCode);
  setQueryParamIfPresent(params, "model", filters.model);
  setQueryParamIfPresent(params, "error_type", filters.errorType);
  setQueryParamIfPresent(params, "source", filters.source);
  setQueryParamIfPresent(params, "api_key_name", filters.apiKeyName);
  const query = params.toString();
  return query ? `/admin/traffic?${query}` : "/admin/traffic";
}

export function buildLogsUrlForRequest(requestId: string): string {
  const params = new URLSearchParams();
  if (requestId.trim()) {
    params.set("request_id", requestId.trim());
  }
  const query = params.toString();
  return query ? `/admin/logs?${query}` : "/admin/logs";
}

export function buildTrafficScopeSummary(
  filters: TrafficFilters,
  requestEvents: TrafficEvent[],
  errorEvents: TrafficEvent[],
  providerEntries: UsageEntry[],
  providerSummary: Record<string, unknown>,
): {
  requestCount: number;
  errorCount: number;
  totalTokens: number;
  providerCount: number;
} {
  if (!filters.requestId) {
    return {
      requestCount: Number(providerSummary.request_count ?? 0),
      errorCount: Number(providerSummary.error_count ?? 0),
      totalTokens: Number(providerSummary.total_tokens ?? 0),
      providerCount: providerEntries.length,
    };
  }

  const providers = new Set(
    [...requestEvents, ...errorEvents]
      .map((item) => String(item.provider ?? "").trim())
      .filter(Boolean),
  );
  const totalTokens = requestEvents.reduce((sum, item) => {
    const usage = asRecord(item.token_usage);
    return sum + Number(usage.total_tokens ?? 0);
  }, 0);

  return {
    requestCount: requestEvents.length,
    errorCount: errorEvents.length,
    totalTokens,
    providerCount: providers.size,
  };
}

export function buildTrafficSelectionSummary(filters: TrafficFilters): DefinitionItem[] {
  return [
    { label: "Selection", value: "No row selected" },
    { label: "Filters", value: summarizeTrafficFilters(filters) || "No active filters" },
    {
      label: "Request scope",
      value: filters.requestId || "Recent request window",
      note: filters.requestId
        ? "Pinned traffic tables are scoped to one request id."
        : "Select a request or error row to pin its traffic context and jump back into Logs.",
    },
    {
      label: "Usage rollups",
      value: filters.requestId ? "Provider/model/key filtered only" : "Aligned with the current filters",
      note: "Usage tables stay aggregate even when recent request/error feeds are pinned to one request id.",
    },
  ];
}

export function buildTrafficEventSelectionSummary(
  kind: "request" | "error",
  item: TrafficEvent,
  counterpart: TrafficEvent | null,
): DefinitionItem[] {
  const requestId = normalizeOptionalText(item.request_id);
  const usage = asRecord(item.token_usage);

  return [
    { label: "Selection", value: kind === "error" ? "Recent error event" : "Recent request event" },
    {
      label: "Request id",
      value: requestId || "n/a",
      note: requestId
        ? "This id can reopen Logs with the same request context already applied."
        : "No request id was recorded, so the Logs handoff is unavailable for this row.",
    },
    {
      label: "Route",
      value: `${String(item.method ?? "GET")} ${String(item.endpoint ?? item.path ?? "n/a")}`,
    },
    {
      label: "Provider",
      value: String(item.provider ?? "unknown"),
      note: String(item.model ?? item.api_key_name ?? item.api_key_source ?? "no model or key recorded"),
    },
    {
      label: "Status",
      value: formatNumber(item.status_code ?? 0),
      note: kind === "error" ? String(item.error_type ?? "request failed") : summarizeTokenUsage(usage),
    },
    {
      label: "Timing",
      value: formatDurationMs(item.stream_duration_ms ?? item.duration_ms),
      note: String(item.client_ip ?? "client hidden"),
    },
    {
      label: kind === "error" ? "Matching recent request" : "Matching recent error",
      value: counterpart ? "Loaded in the current window" : requestId ? "Not in the current window" : "Unavailable",
      note: counterpart ? summarizeRouteStatus(counterpart) : undefined,
    },
  ];
}

export function buildUsageSelectionSummary(
  kind: "key" | "provider",
  item: UsageEntry,
  filters: TrafficFilters,
): DefinitionItem[] {
  return [
    {
      label: "Selection",
      value: kind === "key" ? "Usage by key" : "Usage by provider",
    },
    {
      label: kind === "key" ? "Key" : "Provider",
      value: String(item.name ?? item.provider ?? "unknown"),
    },
    {
      label: "Requests",
      value: formatNumber(item.request_count ?? 0),
      note: `${formatNumber(item.error_count ?? 0)} errors`,
    },
    { label: "Tokens", value: formatNumber(item.total_tokens ?? 0) },
    {
      label: "Breakdown",
      value: kind === "key" ? joinObjectKeys(item.providers) : joinObjectKeys(item.api_keys),
      note: joinObjectKeys(item.models),
    },
    {
      label: "Request pin impact",
      value: filters.requestId ? "Aggregate tables stay unpinned" : "Following the current filters",
      note: filters.requestId
        ? "The recent request/error feeds are pinned, but usage rows stay grouped by provider/model/key."
        : "Pin a request from the request/error tables to hand off one request into Logs.",
    },
  ];
}

export function renderTrafficSelectionActions(
  selection: TrafficSelection,
  filters: TrafficFilters,
): string {
  const actions: string[] = [];

  if (selection.requestId) {
    actions.push(
      `<a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(selection.requestId))}">Open logs for request</a>`,
    );
    if (filters.requestId !== selection.requestId) {
      actions.push(
        `<button class="button" data-traffic-action="scope-request" data-request-id="${escapeHtml(selection.requestId)}" type="button">Pin this request</button>`,
      );
    }
  }

  if (selection.counterpartKind && selection.counterpartIndex !== null) {
    actions.push(
      `<button class="button button--secondary" data-traffic-action="inspect-counterpart" data-counterpart-kind="${escapeHtml(selection.counterpartKind)}" data-counterpart-index="${escapeHtml(String(selection.counterpartIndex))}" type="button">Inspect matching ${escapeHtml(selection.counterpartKind)}</button>`,
    );
  }

  if (filters.requestId) {
    actions.push(
      '<button class="button button--secondary" data-traffic-action="clear-request-scope" type="button">Clear request pin</button>',
    );
  }

  return actions.length
    ? actions.join("")
    : '<span class="muted">Select a request or error row to inspect payload and reopen the matching Logs context.</span>';
}

export function summarizeTrafficFilters(filters: TrafficFilters): string {
  return [
    filters.requestId ? `request=${filters.requestId}` : "",
    filters.provider ? `provider=${filters.provider}` : "",
    filters.endpoint ? `endpoint=${filters.endpoint}` : "",
    filters.method ? `method=${filters.method}` : "",
    filters.statusCode ? `status=${filters.statusCode}` : "",
    filters.model ? `model=${filters.model}` : "",
    filters.errorType ? `error=${filters.errorType}` : "",
    filters.source ? `source=${filters.source}` : "",
    filters.apiKeyName ? `key=${filters.apiKeyName}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function renderStatusSummary(event: TrafficEvent): string {
  const statusCode = Number(event.status_code ?? 0);
  const tone = statusCode >= 400 || event.error_type ? "warn" : "good";
  const lines = [
    `${formatNumber(event.status_code ?? 0)} ${event.error_type ? `· ${String(event.error_type)}` : ""}`.trim(),
  ];
  const usage = asRecord(event.token_usage);
  if (Object.keys(usage).length > 0) {
    lines.push(`${formatNumber(usage.total_tokens ?? 0)} tokens`);
  }
  return `
    <strong>${escapeHtml(lines[0])}</strong><br />
    <span class="muted">${escapeHtml(lines[1] ?? (tone === "good" ? "successful response" : "request failed"))}</span>
  `;
}

export function joinObjectKeys(value: unknown): string {
  const keys = Object.keys(asRecord(value));
  return keys.length ? keys.join(", ") : "no breakdown";
}

export function summarizeTokenUsage(usage: Record<string, unknown>): string {
  if (Object.keys(usage).length === 0) {
    return "No token usage recorded";
  }
  return `${formatNumber(usage.total_tokens ?? 0)} total tokens`;
}

export function summarizeRouteStatus(event: TrafficEvent): string {
  return `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")} · status ${formatNumber(event.status_code ?? 0)}`;
}

export function normalizeOptionalText(value: unknown): string {
  return String(value ?? "").trim();
}

export function indexEventsByRequestId(events: TrafficEvent[]): Map<string, TrafficEvent> {
  const index = new Map<string, TrafficEvent>();
  events.forEach((event) => {
    const requestId = normalizeOptionalText(event.request_id);
    if (requestId && !index.has(requestId)) {
      index.set(requestId, event);
    }
  });
  return index;
}

export function renderRequestRows(events: TrafficEvent[]): string {
  return renderTable(
    [
      { label: "When" },
      { label: "Route" },
      { label: "Status" },
      { label: "Latency" },
      { label: "Model / Key" },
      { label: "Actions" },
    ],
    events.map((event, index) => [
      `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
      `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
      renderStatusSummary(event),
      `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
      `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
      renderEventRowActions(index, "request", String(event.request_id ?? ""), buildLogsUrlForRequest),
    ]),
    "No recent requests matched the selected filters.",
  );
}

export function renderErrorRows(events: TrafficEvent[]): string {
  return renderTable(
    [
      { label: "When" },
      { label: "Route" },
      { label: "Failure" },
      { label: "Latency" },
      { label: "Context" },
      { label: "Actions" },
    ],
    events.map((event, index) => [
      `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
      `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
      `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
      `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">${escapeHtml(String(event.client_ip ?? "client hidden"))}</span>`,
      `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
      renderEventRowActions(index, "error", String(event.request_id ?? ""), buildLogsUrlForRequest),
    ]),
    "No recent errors matched the selected filters.",
  );
}

export function renderUsageKeyRows(entries: UsageEntry[]): string {
  return renderTable(
    [
      { label: "Key" },
      { label: "Traffic" },
      { label: "Tokens" },
      { label: "Breakdown" },
      { label: "Inspect" },
    ],
    entries.map((entry, index) => [
      `<strong>${escapeHtml(String(entry.name ?? "unnamed"))}</strong><br /><span class="muted">${escapeHtml(String(entry.source ?? "unknown"))}</span>`,
      `${escapeHtml(formatNumber(entry.request_count ?? 0))} req<br /><span class="muted">${escapeHtml(formatNumber(entry.error_count ?? 0))} errors</span>`,
      `${escapeHtml(formatNumber(entry.total_tokens ?? 0))}<br /><span class="muted">${escapeHtml(formatNumber(entry.prompt_tokens ?? 0))} prompt / ${escapeHtml(formatNumber(entry.completion_tokens ?? 0))} completion</span>`,
      `<span class="muted">${escapeHtml(joinObjectKeys(entry.providers))}</span><br /><span class="muted">${escapeHtml(joinObjectKeys(entry.models))}</span>`,
      `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="key" type="button">View</button>`,
    ]),
    "No API-key usage matched the selected filters.",
  );
}

export function renderUsageProviderRows(entries: UsageEntry[]): string {
  return renderTable(
    [
      { label: "Provider" },
      { label: "Traffic" },
      { label: "Tokens" },
      { label: "Breakdown" },
      { label: "Inspect" },
    ],
    entries.map((entry, index) => [
      `<strong>${escapeHtml(String(entry.provider ?? "unknown"))}</strong><br /><span class="muted">${escapeHtml(formatTimestamp(entry.last_seen_at))}</span>`,
      `${escapeHtml(formatNumber(entry.request_count ?? 0))} req<br /><span class="muted">${escapeHtml(formatNumber(entry.error_count ?? 0))} errors</span>`,
      `${escapeHtml(formatNumber(entry.total_tokens ?? 0))}<br /><span class="muted">${escapeHtml(formatNumber(entry.prompt_tokens ?? 0))} prompt / ${escapeHtml(formatNumber(entry.completion_tokens ?? 0))} completion</span>`,
      `<span class="muted">${escapeHtml(joinObjectKeys(entry.api_keys))}</span><br /><span class="muted">${escapeHtml(joinObjectKeys(entry.models))}</span>`,
      `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="provider" type="button">View</button>`,
    ]),
    "No provider usage matched the selected filters.",
  );
}

export function seedTrafficSelection(
  filters: TrafficFilters,
  requestLookup: Map<string, TrafficEvent>,
  errorLookup: Map<string, TrafficEvent>,
  selectTrafficEvent: (kind: "request" | "error", item: TrafficEvent) => void,
): void {
  if (!filters.requestId) {
    return;
  }

  const requestEvent = requestLookup.get(filters.requestId);
  if (requestEvent) {
    selectTrafficEvent("request", requestEvent);
    return;
  }

  const errorEvent = errorLookup.get(filters.requestId);
  if (errorEvent) {
    selectTrafficEvent("error", errorEvent);
  }
}

function renderEventRowActions(
  index: number,
  kind: "request" | "error",
  requestId: string,
  buildContextUrl: (requestId: string) => string,
): string {
  const actions = [
    `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="${kind}" type="button">View</button>`,
  ];
  if (requestId.trim()) {
    actions.push(`<a class="button" href="${escapeHtml(buildContextUrl(requestId))}">Open logs</a>`);
  }
  return `<div class="toolbar">${actions.join("")}</div>`;
}
