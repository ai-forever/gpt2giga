import type { AdminApp } from "../app";
import {
  card,
  kpi,
  renderEmptyState,
  renderJson,
  renderStatLines,
  renderTable,
} from "../templates";
import {
  asArray,
  asRecord,
  escapeHtml,
  formatDurationMs,
  formatNumber,
  formatTimestamp,
} from "../utils";

interface TrafficFilters {
  limit: string;
  provider: string;
  endpoint: string;
  method: string;
  statusCode: string;
  model: string;
  errorType: string;
  source: string;
  apiKeyName: string;
}

type TrafficEvent = Record<string, unknown>;
type UsageEntry = Record<string, unknown>;

const DEFAULT_LIMIT = "25";

export async function renderTraffic(app: AdminApp, token: number): Promise<void> {
  const filters = readTrafficFilters();
  const [requests, errors, usageKeys, usageProviders] = await Promise.all([
    app.api.json<Record<string, unknown>>(`/admin/api/requests/recent?${buildEventQuery(filters)}`),
    app.api.json<Record<string, unknown>>(`/admin/api/errors/recent?${buildEventQuery(filters)}`),
    app.api.json<Record<string, unknown>>(`/admin/api/usage/keys?${buildUsageKeysQuery(filters)}`),
    app.api.json<Record<string, unknown>>(
      `/admin/api/usage/providers?${buildUsageProvidersQuery(filters)}`,
    ),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const requestEvents = asArray<TrafficEvent>(requests.events);
  const errorEvents = asArray<TrafficEvent>(errors.events);
  const keyEntries = asArray<UsageEntry>(usageKeys.entries);
  const providerEntries = asArray<UsageEntry>(usageProviders.entries);
  const providerSummary = asRecord(usageProviders.summary);

  app.setHeroActions(`
    <button class="button button--secondary" id="reset-traffic-filters" type="button">Reset filters</button>
    <a class="button" href="/admin/logs">Open logs</a>
  `);

  app.setContent(`
    ${kpi("Requests", formatNumber(providerSummary.request_count ?? 0))}
    ${kpi("Errors", formatNumber(providerSummary.error_count ?? 0))}
    ${kpi("Tokens", formatNumber(providerSummary.total_tokens ?? 0))}
    ${kpi("Providers", formatNumber(providerEntries.length))}
    ${card(
      "Traffic filters",
      `
        <form id="traffic-filters-form" class="stack">
          <div class="triple-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderSelectOptions(
                  filters.provider,
                  uniqueOptions([
                    ...asArray<unknown>(asRecord(requests.available_filters).provider),
                    ...asArray<unknown>(asRecord(errors.available_filters).provider),
                    ...asArray<unknown>(asRecord(usageKeys.available_filters).provider),
                    ...asArray<unknown>(asRecord(usageProviders.available_filters).provider),
                  ]),
                )}
              </select>
            </label>
            <label class="field">
              <span>Model</span>
              <select name="model">
                ${renderSelectOptions(
                  filters.model,
                  uniqueOptions([
                    ...asArray<unknown>(asRecord(requests.available_filters).model),
                    ...asArray<unknown>(asRecord(errors.available_filters).model),
                    ...asArray<unknown>(asRecord(usageKeys.available_filters).model),
                    ...asArray<unknown>(asRecord(usageProviders.available_filters).model),
                  ]),
                )}
              </select>
            </label>
            <label class="field">
              <span>Limit</span>
              <select name="limit">
                ${["10", "25", "50", "100"].map((value) => renderOption(value, filters.limit, value)).join("")}
              </select>
            </label>
          </div>
          <div class="triple-grid">
            <label class="field">
              <span>Endpoint</span>
              <select name="endpoint">
                ${renderSelectOptions(filters.endpoint, asArray<unknown>(asRecord(requests.available_filters).endpoint))}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderSelectOptions(filters.method, asArray<unknown>(asRecord(requests.available_filters).method))}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderSelectOptions(
                  filters.statusCode,
                  uniqueOptions([
                    ...asArray<unknown>(asRecord(requests.available_filters).status_code),
                    ...asArray<unknown>(asRecord(errors.available_filters).status_code),
                  ]),
                )}
              </select>
            </label>
          </div>
          <div class="triple-grid">
            <label class="field">
              <span>Error type</span>
              <select name="error_type">
                ${renderSelectOptions(filters.errorType, asArray<unknown>(asRecord(errors.available_filters).error_type))}
              </select>
            </label>
            <label class="field">
              <span>Key source</span>
              <select name="source">
                ${renderSelectOptions(filters.source, asArray<unknown>(asRecord(usageKeys.available_filters).source))}
              </select>
            </label>
            <label class="field">
              <span>API key name</span>
              <select name="api_key_name">
                ${renderSelectOptions(
                  filters.apiKeyName,
                  asArray<unknown>(asRecord(usageProviders.available_filters).api_key_name),
                )}
              </select>
            </label>
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Apply filters</button>
            <span class="muted">Filters apply across recent events and usage summaries using the same admin APIs.</span>
          </div>
        </form>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Recent requests",
      renderTable(
        [
          { label: "When" },
          { label: "Route" },
          { label: "Status" },
          { label: "Latency" },
          { label: "Model / Key" },
          { label: "Inspect" },
        ],
        requestEvents.map((event, index) => [
          `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
          `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
          renderStatusSummary(event),
          `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
          `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
          `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="request" type="button">View</button>`,
        ]),
        "No recent requests matched the selected filters.",
      ),
      "panel panel--span-8",
    )}
    ${card(
      "Selected payload",
      `
        <div class="stack">
          ${renderStatLines(
            [
              { label: "Request events", value: formatNumber(requestEvents.length) },
              { label: "Error events", value: formatNumber(errorEvents.length) },
              { label: "Usage key rows", value: formatNumber(keyEntries.length) },
              { label: "Usage provider rows", value: formatNumber(providerEntries.length) },
            ],
            "No traffic rows are loaded yet.",
          )}
          <pre class="code-block code-block--tall" id="traffic-detail">${escapeHtml(
            JSON.stringify(
              {
                active_filters: filters,
                usage_summary: providerSummary,
              },
              null,
              2,
            ),
          )}</pre>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Recent errors",
      renderTable(
        [
          { label: "When" },
          { label: "Route" },
          { label: "Failure" },
          { label: "Latency" },
          { label: "Context" },
          { label: "Inspect" },
        ],
        errorEvents.map((event, index) => [
          `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
          `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
          `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
          `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">${escapeHtml(String(event.client_ip ?? "client hidden"))}</span>`,
          `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
          `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="error" type="button">View</button>`,
        ]),
        "No recent errors matched the selected filters.",
      ),
      "panel panel--span-8",
    )}
    ${card(
      "Usage summary",
      renderStatLines(
        [
          {
            label: "Successful requests",
            value: formatNumber(providerSummary.success_count ?? 0),
            tone: "good",
          },
          {
            label: "Errored requests",
            value: formatNumber(providerSummary.error_count ?? 0),
            tone: Number(providerSummary.error_count ?? 0) > 0 ? "warn" : "default",
          },
          { label: "Prompt tokens", value: formatNumber(providerSummary.prompt_tokens ?? 0) },
          {
            label: "Completion tokens",
            value: formatNumber(providerSummary.completion_tokens ?? 0),
          },
        ],
        "Usage totals are empty.",
      ),
      "panel panel--span-4",
    )}
    ${card(
      "Usage by key",
      renderTable(
        [
          { label: "Key" },
          { label: "Traffic" },
          { label: "Tokens" },
          { label: "Breakdown" },
          { label: "Inspect" },
        ],
        keyEntries.map((entry, index) => [
          `<strong>${escapeHtml(String(entry.name ?? "unnamed"))}</strong><br /><span class="muted">${escapeHtml(String(entry.source ?? "unknown"))}</span>`,
          `${escapeHtml(formatNumber(entry.request_count ?? 0))} req<br /><span class="muted">${escapeHtml(formatNumber(entry.error_count ?? 0))} errors</span>`,
          `${escapeHtml(formatNumber(entry.total_tokens ?? 0))}<br /><span class="muted">${escapeHtml(formatNumber(entry.prompt_tokens ?? 0))} prompt / ${escapeHtml(formatNumber(entry.completion_tokens ?? 0))} completion</span>`,
          `<span class="muted">${escapeHtml(joinObjectKeys(entry.providers))}</span><br /><span class="muted">${escapeHtml(joinObjectKeys(entry.models))}</span>`,
          `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="key" type="button">View</button>`,
        ]),
        "No API-key usage matched the selected filters.",
      ),
      "panel panel--span-6",
    )}
    ${card(
      "Usage by provider",
      renderTable(
        [
          { label: "Provider" },
          { label: "Traffic" },
          { label: "Tokens" },
          { label: "Breakdown" },
          { label: "Inspect" },
        ],
        providerEntries.map((entry, index) => [
          `<strong>${escapeHtml(String(entry.provider ?? "unknown"))}</strong><br /><span class="muted">${escapeHtml(formatTimestamp(entry.last_seen_at))}</span>`,
          `${escapeHtml(formatNumber(entry.request_count ?? 0))} req<br /><span class="muted">${escapeHtml(formatNumber(entry.error_count ?? 0))} errors</span>`,
          `${escapeHtml(formatNumber(entry.total_tokens ?? 0))}<br /><span class="muted">${escapeHtml(formatNumber(entry.prompt_tokens ?? 0))} prompt / ${escapeHtml(formatNumber(entry.completion_tokens ?? 0))} completion</span>`,
          `<span class="muted">${escapeHtml(joinObjectKeys(entry.api_keys))}</span><br /><span class="muted">${escapeHtml(joinObjectKeys(entry.models))}</span>`,
          `<button class="button button--secondary" data-traffic-detail="${index}" data-traffic-kind="provider" type="button">View</button>`,
        ]),
        "No provider usage matched the selected filters.",
      ),
      "panel panel--span-6",
    )}
  `);

  const detailNode = app.pageContent.querySelector<HTMLPreElement>("#traffic-detail");
  const filtersForm = app.pageContent.querySelector<HTMLFormElement>("#traffic-filters-form");
  if (!detailNode || !filtersForm) {
    return;
  }

  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      limit: HTMLSelectElement;
      provider: HTMLSelectElement;
      endpoint: HTMLSelectElement;
      method: HTMLSelectElement;
      status_code: HTMLSelectElement;
      model: HTMLSelectElement;
      error_type: HTMLSelectElement;
      source: HTMLSelectElement;
      api_key_name: HTMLSelectElement;
    };

    const nextFilters: TrafficFilters = {
      limit: fields.limit.value || DEFAULT_LIMIT,
      provider: fields.provider.value,
      endpoint: fields.endpoint.value,
      method: fields.method.value,
      statusCode: fields.status_code.value,
      model: fields.model.value,
      errorType: fields.error_type.value,
      source: fields.source.value,
      apiKeyName: fields.api_key_name.value,
    };
    window.history.replaceState({}, "", buildTrafficUrl(nextFilters));
    void app.render("traffic");
  });

  document.getElementById("reset-traffic-filters")?.addEventListener("click", () => {
    window.history.replaceState({}, "", "/admin/traffic");
    void app.render("traffic");
  });

  const inspectPayloads: Record<string, Record<string, unknown>[]> = {
    request: requestEvents,
    error: errorEvents,
    key: keyEntries,
    provider: providerEntries,
  };

  app.pageContent.querySelectorAll<HTMLElement>("[data-traffic-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.trafficKind;
      const indexValue = button.dataset.trafficDetail;
      if (!kind || indexValue === undefined) {
        return;
      }
      const rows = inspectPayloads[kind];
      const item = rows?.[Number(indexValue)];
      if (!item) {
        return;
      }
      detailNode.textContent = JSON.stringify(item, null, 2);
    });
  });
}

function readTrafficFilters(): TrafficFilters {
  const params = new URLSearchParams(window.location.search);
  return {
    limit: params.get("limit") || DEFAULT_LIMIT,
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

function buildEventQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setIfPresent(params, "provider", filters.provider);
  setIfPresent(params, "endpoint", filters.endpoint);
  setIfPresent(params, "method", filters.method);
  setIfPresent(params, "status_code", filters.statusCode);
  setIfPresent(params, "model", filters.model);
  setIfPresent(params, "error_type", filters.errorType);
  return params.toString();
}

function buildUsageKeysQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setIfPresent(params, "provider", filters.provider);
  setIfPresent(params, "model", filters.model);
  setIfPresent(params, "source", filters.source);
  return params.toString();
}

function buildUsageProvidersQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setIfPresent(params, "provider", filters.provider);
  setIfPresent(params, "model", filters.model);
  setIfPresent(params, "api_key_name", filters.apiKeyName);
  return params.toString();
}

function buildTrafficUrl(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  setIfPresent(params, "limit", filters.limit, DEFAULT_LIMIT);
  setIfPresent(params, "provider", filters.provider);
  setIfPresent(params, "endpoint", filters.endpoint);
  setIfPresent(params, "method", filters.method);
  setIfPresent(params, "status_code", filters.statusCode);
  setIfPresent(params, "model", filters.model);
  setIfPresent(params, "error_type", filters.errorType);
  setIfPresent(params, "source", filters.source);
  setIfPresent(params, "api_key_name", filters.apiKeyName);
  const query = params.toString();
  return query ? `/admin/traffic?${query}` : "/admin/traffic";
}

function setIfPresent(
  params: URLSearchParams,
  key: string,
  value: string,
  skipValue = "",
): void {
  if (value && value !== skipValue) {
    params.set(key, value);
  }
}

function renderSelectOptions(selected: string, values: unknown[]): string {
  return [renderOption("", selected, "All"), ...uniqueOptions(values).map((value) => renderOption(value, selected))].join("");
}

function renderOption(value: unknown, selected: string, label?: string): string {
  const normalizedValue = String(value ?? "");
  return `<option value="${escapeHtml(normalizedValue)}" ${selected === normalizedValue ? "selected" : ""}>${escapeHtml(label ?? normalizedValue)}</option>`;
}

function uniqueOptions(values: unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => String(value ?? "").trim())
        .filter(Boolean),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

function renderStatusSummary(event: TrafficEvent): string {
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

function joinObjectKeys(value: unknown): string {
  const keys = Object.keys(asRecord(value));
  return keys.length ? keys.join(", ") : "no breakdown";
}
