import type { AdminApp } from "../app.js";
import {
  card,
  kpi,
  renderDefinitionList,
  renderStatLines,
  renderTable,
} from "../templates.js";
import {
  asArray,
  asRecord,
  escapeHtml,
  formatDurationMs,
  formatNumber,
  formatTimestamp,
} from "../utils.js";

interface TrafficFilters {
  limit: string;
  requestId: string;
  provider: string;
  endpoint: string;
  method: string;
  statusCode: string;
  model: string;
  errorType: string;
  source: string;
  apiKeyName: string;
}

interface DefinitionItem {
  label: string;
  value: string;
  note?: string;
}

interface TrafficSelection {
  requestId: string | null;
  counterpartKind: "request" | "error" | null;
  counterpartIndex: number | null;
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
  const requestLookup = indexEventsByRequestId(requestEvents);
  const errorLookup = indexEventsByRequestId(errorEvents);
  const requestPinned = Boolean(filters.requestId);
  const scopeSummary = buildTrafficScopeSummary(filters, requestEvents, errorEvents, providerEntries, providerSummary);

  app.setHeroActions(`
    <button class="button button--secondary" id="reset-traffic-filters" type="button">Reset filters</button>
    <a class="button" href="${escapeHtml(filters.requestId ? buildLogsUrlForRequest(filters.requestId) : "/admin/logs")}">
      ${escapeHtml(filters.requestId ? "Open pinned logs" : "Open logs")}
    </a>
  `);

  app.setContent(`
    ${kpi(requestPinned ? "Pinned requests" : "Requests", formatNumber(scopeSummary.requestCount))}
    ${kpi(requestPinned ? "Pinned errors" : "Errors", formatNumber(scopeSummary.errorCount))}
    ${kpi(requestPinned ? "Pinned tokens" : "Tokens", formatNumber(scopeSummary.totalTokens))}
    ${kpi(requestPinned ? "Providers in scope" : "Providers", formatNumber(scopeSummary.providerCount))}
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
          <div class="dual-grid">
            <label class="field">
              <span>Request id</span>
              <input
                name="request_id"
                value="${escapeHtml(filters.requestId)}"
                placeholder="Pin one request across recent traffic surfaces"
              />
            </label>
            <div class="surface">
              <div class="stack">
                <h4>Request pinning</h4>
                <p class="muted">
                  Request id filters lock the recent request/error tables and payload inspector to one
                  audit event. Usage rollups stay aggregate, but every request/error row can jump straight
                  back into the matching Logs view with the same request id.
                </p>
              </div>
            </div>
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
          { label: "Actions" },
        ],
        requestEvents.map((event, index) => [
          `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
          `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
          renderStatusSummary(event),
          `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
          `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
          renderEventRowActions(index, "request", String(event.request_id ?? ""), buildLogsUrlForRequest),
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
          <div id="traffic-selection-summary">
            ${renderDefinitionList(buildTrafficSelectionSummary(filters), "Select a request, error, or usage row.")}
          </div>
          <div class="toolbar" id="traffic-selection-actions">
            ${renderTrafficSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null }, filters)}
          </div>
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
          { label: "Actions" },
        ],
        errorEvents.map((event, index) => [
          `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(String(event.request_id ?? "no request id"))}</span>`,
          `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
          `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
          `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">${escapeHtml(String(event.client_ip ?? "client hidden"))}</span>`,
          `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
          renderEventRowActions(index, "error", String(event.request_id ?? ""), buildLogsUrlForRequest),
        ]),
        "No recent errors matched the selected filters.",
      ),
      "panel panel--span-8",
    )}
    ${card(
      "Usage summary",
      `
        ${requestPinned ? '<div class="banner banner--warn">Usage rollups below still follow provider/model/key filters, but request-id pinning only scopes recent request and error feeds.</div>' : ""}
        ${renderStatLines(
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
        )}
      `,
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
  const summaryNode = app.pageContent.querySelector<HTMLElement>("#traffic-selection-summary");
  const actionNode = app.pageContent.querySelector<HTMLElement>("#traffic-selection-actions");
  if (!detailNode || !filtersForm || !summaryNode || !actionNode) {
    return;
  }

  const inspectPayloads: Record<string, Record<string, unknown>[]> = {
    request: requestEvents,
    error: errorEvents,
    key: keyEntries,
    provider: providerEntries,
  };

  const setSelectionSummary = (items: DefinitionItem[]): void => {
    summaryNode.innerHTML = renderDefinitionList(items, "Select a request, error, or usage row.");
  };

  const setSelectionActions = (selection: TrafficSelection): void => {
    actionNode.innerHTML = renderTrafficSelectionActions(selection, filters);
  };

  const selectTrafficEvent = (kind: "request" | "error", item: TrafficEvent): void => {
    const requestId = normalizeOptionalText(item.request_id);
    const counterpartKind = kind === "request" ? "error" : "request";
    const counterpartRows = counterpartKind === "error" ? errorEvents : requestEvents;
    const counterpartIndex = requestId
      ? counterpartRows.findIndex((candidate) => normalizeOptionalText(candidate.request_id) === requestId)
      : -1;
    const counterpart =
      requestId && kind === "request"
        ? (errorLookup.get(requestId) ?? null)
        : requestId
          ? (requestLookup.get(requestId) ?? null)
          : null;

    setSelectionSummary(buildTrafficEventSelectionSummary(kind, item, counterpart));
    setSelectionActions({
      requestId: requestId || null,
      counterpartKind: counterpartIndex >= 0 ? counterpartKind : null,
      counterpartIndex: counterpartIndex >= 0 ? counterpartIndex : null,
    });
    detailNode.textContent = JSON.stringify(
      {
        selected_event: item,
        counterpart_event: counterpart,
        active_filters: filters,
      },
      null,
      2,
    );
  };

  const selectUsageRow = (kind: "key" | "provider", item: UsageEntry): void => {
    setSelectionSummary(buildUsageSelectionSummary(kind, item, filters));
    setSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null });
    detailNode.textContent = JSON.stringify(
      {
        selected_usage_entry: item,
        usage_summary: providerSummary,
        active_filters: filters,
      },
      null,
      2,
    );
  };

  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      limit: HTMLSelectElement;
      request_id: HTMLInputElement;
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
      requestId: fields.request_id.value.trim(),
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

  actionNode.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>("[data-traffic-action]");
    if (!button) {
      return;
    }
    const action = button.dataset.trafficAction;
    if (action === "scope-request") {
      const requestId = button.dataset.requestId?.trim();
      if (!requestId) {
        return;
      }
      window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId }));
      void app.render("traffic");
      return;
    }
    if (action === "clear-request-scope") {
      window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId: "" }));
      void app.render("traffic");
      return;
    }
    if (action === "inspect-counterpart") {
      const kind = button.dataset.counterpartKind;
      const indexValue = button.dataset.counterpartIndex;
      if ((kind !== "request" && kind !== "error") || indexValue === undefined) {
        return;
      }
      const item = inspectPayloads[kind]?.[Number(indexValue)];
      if (!item) {
        return;
      }
      selectTrafficEvent(kind, item);
    }
  });

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

      if (kind === "request" || kind === "error") {
        selectTrafficEvent(kind, item);
        return;
      }

      if (kind === "key" || kind === "provider") {
        selectUsageRow(kind, item);
      }
    });
  });

  seedTrafficSelection(filters, requestLookup, errorLookup, selectTrafficEvent);
}

function buildTrafficScopeSummary(
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

function buildTrafficSelectionSummary(filters: TrafficFilters): DefinitionItem[] {
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

function buildTrafficEventSelectionSummary(
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

function buildUsageSelectionSummary(
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

function renderTrafficSelectionActions(
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

function buildLogsUrlForRequest(requestId: string): string {
  const params = new URLSearchParams();
  if (requestId.trim()) {
    params.set("request_id", requestId.trim());
  }
  const query = params.toString();
  return query ? `/admin/logs?${query}` : "/admin/logs";
}

function summarizeTrafficFilters(filters: TrafficFilters): string {
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

function readTrafficFilters(): TrafficFilters {
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

function buildEventQuery(filters: TrafficFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setIfPresent(params, "request_id", filters.requestId);
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
  setIfPresent(params, "request_id", filters.requestId);
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

function summarizeTokenUsage(usage: Record<string, unknown>): string {
  if (Object.keys(usage).length === 0) {
    return "No token usage recorded";
  }
  return `${formatNumber(usage.total_tokens ?? 0)} total tokens`;
}

function summarizeRouteStatus(event: TrafficEvent): string {
  return `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")} · status ${formatNumber(event.status_code ?? 0)}`;
}

function normalizeOptionalText(value: unknown): string {
  return String(value ?? "").trim();
}

function indexEventsByRequestId(events: TrafficEvent[]): Map<string, TrafficEvent> {
  const index = new Map<string, TrafficEvent>();
  events.forEach((event) => {
    const requestId = normalizeOptionalText(event.request_id);
    if (requestId && !index.has(requestId)) {
      index.set(requestId, event);
    }
  });
  return index;
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

function seedTrafficSelection(
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
