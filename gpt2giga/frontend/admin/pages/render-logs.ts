import type { AdminApp } from "../app.js";
import {
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderTable,
} from "../templates.js";
import {
  asArray,
  asRecord,
  escapeHtml,
  formatDurationMs,
  formatNumber,
  formatTimestamp,
  toErrorMessage,
} from "../utils.js";

interface LogsFilters {
  lines: string;
  query: string;
  provider: string;
  method: string;
  statusCode: string;
  errorType: string;
  limit: string;
}

type LogEvent = Record<string, unknown>;

const DEFAULT_LINES = "150";
const DEFAULT_LIMIT = "8";
const MAX_LOG_LINES = 4000;

export async function renderLogs(app: AdminApp, token: number): Promise<void> {
  const filters = readLogsFilters();
  const [tail, recentRequests, recentErrors] = await Promise.all([
    app.api.text(`/admin/api/logs?lines=${encodeURIComponent(filters.lines || DEFAULT_LINES)}`),
    app.api.json<Record<string, unknown>>(`/admin/api/requests/recent?${buildLogsEventQuery(filters)}`),
    app.api.json<Record<string, unknown>>(`/admin/api/errors/recent?${buildLogsEventQuery(filters)}`),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const requestEvents = asArray<LogEvent>(recentRequests.events);
  const errorEvents = asArray<LogEvent>(recentErrors.events);
  let rawLogLines = normalizeLogText(tail);
  let streamController: AbortController | null = null;
  let streaming = false;
  let autoScroll = true;

  app.setHeroActions(`
    <button class="button button--secondary" id="reset-log-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-logs" type="button">Refresh tail</button>
    <button class="button" id="toggle-stream" type="button">Start live stream</button>
  `);
  app.setContent(`
    ${kpi("Tail lines", filters.lines || DEFAULT_LINES)}
    ${kpi("Matching lines", countMatchingLines(rawLogLines, filters.query))}
    ${kpi("Recent errors", formatNumber(errorEvents.length))}
    ${kpi("Recent requests", formatNumber(requestEvents.length))}
    ${card(
      "Log filters",
      `
        <form id="logs-filters-form" class="stack">
          <div class="dual-grid">
            <label class="field">
              <span>Tail lines</span>
              <select name="lines">
                ${["100", "150", "250", "500", "1000"]
                  .map((value) => renderOption(value, filters.lines || DEFAULT_LINES))
                  .join("")}
              </select>
            </label>
            <label class="field">
              <span>Text match</span>
              <input name="query" value="${escapeHtml(filters.query)}" placeholder="Filter the rendered tail client-side" />
            </label>
          </div>
          <div class="quad-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderSelectOptions(
                  filters.provider,
                  uniqueOptions([
                    ...asArray<unknown>(asRecord(recentRequests.available_filters).provider),
                    ...asArray<unknown>(asRecord(recentErrors.available_filters).provider),
                  ]),
                )}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderSelectOptions(
                  filters.method,
                  uniqueOptions([
                    ...asArray<unknown>(asRecord(recentRequests.available_filters).method),
                    ...asArray<unknown>(asRecord(recentErrors.available_filters).method),
                  ]),
                )}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderSelectOptions(
                  filters.statusCode,
                  uniqueOptions([
                    ...asArray<unknown>(asRecord(recentRequests.available_filters).status_code),
                    ...asArray<unknown>(asRecord(recentErrors.available_filters).status_code),
                  ]),
                )}
              </select>
            </label>
            <label class="field">
              <span>Error type</span>
              <select name="error_type">
                ${renderSelectOptions(
                  filters.errorType,
                  asArray<unknown>(asRecord(recentErrors.available_filters).error_type),
                )}
              </select>
            </label>
          </div>
          <div class="toolbar">
            <label class="field">
              <span>Recent event limit</span>
              <select name="limit">
                ${["5", "8", "12", "20"].map((value) => renderOption(value, filters.limit || DEFAULT_LIMIT)).join("")}
              </select>
            </label>
            <span class="muted">Filters scope the request/error context panels and the tail viewer in one place.</span>
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Apply filters</button>
            <a class="button button--secondary" href="/admin/traffic">Open traffic</a>
          </div>
        </form>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Stream controls",
      `
        <div class="surface">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Live tail status</h4>
                <p class="muted">Streaming now parses SSE events and appends only log lines, not the raw protocol envelope.</p>
              </div>
              <div class="surface__meta" id="logs-stream-status">${pill("idle")}</div>
            </div>
            <div class="toolbar">
              <label class="checkbox-field">
                <input id="logs-auto-scroll" type="checkbox" checked />
                <span>Auto-scroll while streaming</span>
              </label>
              <button class="button button--secondary" id="clear-log-output" type="button">Clear buffer</button>
              <span class="muted" id="logs-stream-note">Tail buffer loaded from the file on disk.</span>
            </div>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Context inspector",
      `
        <div class="surface">
          <div class="stack">
            <div id="logs-selection-summary">
              ${renderDefinitionList(
                [
                  { label: "Selection", value: "No event selected" },
                  { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
                ],
                "No event selected yet.",
              )}
            </div>
            <pre class="code-block" id="logs-detail">${escapeHtml(
              JSON.stringify(
                {
                  filters,
                  requests_loaded: requestEvents.length,
                  errors_loaded: errorEvents.length,
                },
                null,
                2,
              ),
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Rendered log tail",
      `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Rendered output</h4>
                <p class="muted">Client-side text filtering is applied after fetching the selected tail window.</p>
              </div>
              <div class="surface__meta">
                <span class="pill" id="logs-match-count">${escapeHtml(
                  `${countMatchingLines(rawLogLines, filters.query)} matches`,
                )}</span>
              </div>
            </div>
            <pre class="code-block code-block--tall" id="log-output">${escapeHtml(
              formatRenderedLogOutput(rawLogLines, filters.query),
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-8",
    )}
    ${card(
      "Recent errors",
      renderTable(
        [
          { label: "When" },
          { label: "Failure" },
          { label: "Route" },
          { label: "Inspect" },
        ],
        errorEvents.map((event, index) => [
          `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(
            String(event.request_id ?? "no request id"),
          )}</span>`,
          `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(
            formatNumber(event.status_code ?? 0),
          )}</span>`,
          `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(
            `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`,
          )}</span>`,
          `<button class="button button--secondary" data-log-detail="${index}" data-log-kind="error" type="button">Inspect</button>`,
        ]),
        "No recent errors matched the current filters.",
      ),
      "panel panel--span-6",
    )}
    ${card(
      "Recent requests",
      renderTable(
        [
          { label: "When" },
          { label: "Latency" },
          { label: "Route" },
          { label: "Inspect" },
        ],
        requestEvents.map((event, index) => [
          `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(
            String(event.request_id ?? "no request id"),
          )}</span>`,
          `<strong>${escapeHtml(formatDurationMs(event.stream_duration_ms ?? event.duration_ms))}</strong><br /><span class="muted">status ${escapeHtml(
            formatNumber(event.status_code ?? 0),
          )}</span>`,
          `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(
            `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`,
          )}</span>`,
          `<button class="button button--secondary" data-log-detail="${index}" data-log-kind="request" type="button">Inspect</button>`,
        ]),
        "No recent requests matched the current filters.",
      ),
      "panel panel--span-6",
    )}
  `);

  const refreshButton = document.getElementById("refresh-logs");
  const resetFiltersButton = document.getElementById("reset-log-filters");
  const streamButton = document.getElementById("toggle-stream");
  const clearButton = app.pageContent.querySelector<HTMLButtonElement>("#clear-log-output");
  const filtersForm = app.pageContent.querySelector<HTMLFormElement>("#logs-filters-form");
  const logOutput = app.pageContent.querySelector<HTMLPreElement>("#log-output");
  const matchCount = app.pageContent.querySelector<HTMLElement>("#logs-match-count");
  const streamStatus = app.pageContent.querySelector<HTMLElement>("#logs-stream-status");
  const streamNote = app.pageContent.querySelector<HTMLElement>("#logs-stream-note");
  const autoScrollToggle = app.pageContent.querySelector<HTMLInputElement>("#logs-auto-scroll");
  const detailNode = app.pageContent.querySelector<HTMLPreElement>("#logs-detail");
  const summaryNode = app.pageContent.querySelector<HTMLElement>("#logs-selection-summary");
  if (
    !refreshButton ||
    !resetFiltersButton ||
    !streamButton ||
    !clearButton ||
    !filtersForm ||
    !logOutput ||
    !matchCount ||
    !streamStatus ||
    !streamNote ||
    !autoScrollToggle ||
    !detailNode ||
    !summaryNode
  ) {
    return;
  }

  const setRenderedLogs = (): void => {
    const rendered = formatRenderedLogOutput(rawLogLines, filters.query);
    const matchingLines = countMatchingLines(rawLogLines, filters.query);
    logOutput.textContent = rendered;
    matchCount.textContent = `${matchingLines} matches`;
    if (autoScroll) {
      logOutput.scrollTop = logOutput.scrollHeight;
    }
  };

  const setStreamVisuals = (
    label: string,
    tone: "default" | "good" | "warn" = "default",
    note = "Tail buffer loaded from the file on disk.",
  ): void => {
    streamStatus.innerHTML = pill(label, tone);
    streamNote.textContent = note;
    streamButton.textContent = streaming ? "Stop live stream" : "Start live stream";
  };

  const stopStream = (): void => {
    streamController?.abort();
    streamController = null;
    streaming = false;
    setStreamVisuals("idle");
  };

  app.registerCleanup(() => {
    stopStream();
  });

  const refreshLogs = async (): Promise<void> => {
    const nextTail = await app.api.text(
      `/admin/api/logs?lines=${encodeURIComponent(filters.lines || DEFAULT_LINES)}`,
    );
    rawLogLines = normalizeLogText(nextTail);
    setRenderedLogs();
    if (!streaming) {
      setStreamVisuals("idle", "default", "Tail refreshed from the file on disk.");
    }
  };

  const appendLogLine = (line: string): void => {
    if (!line.trim()) {
      return;
    }
    rawLogLines = [...rawLogLines, line].slice(-MAX_LOG_LINES);
    setRenderedLogs();
  };

  const startStream = async (): Promise<void> => {
    if (streaming) {
      return;
    }
    streaming = true;
    streamController = new AbortController();
    setStreamVisuals("connecting", "warn", "Opening the live SSE stream for new log lines.");

    try {
      const response = await app.api.raw("/admin/api/logs/stream", {
        signal: streamController.signal,
      });
      if (!response.body) {
        throw new Error("Log stream body is unavailable.");
      }

      setStreamVisuals("streaming", "good", "New log lines are appended as they arrive.");
      await readSseStream(response.body, (event) => {
        if (event.type === "error") {
          setStreamVisuals("stream error", "warn", event.data || "Log stream reported an error.");
          app.pushAlert(event.data || "Log stream reported an error.", "warn");
          return;
        }
        if (event.type === "message" && event.data) {
          appendLogLine(event.data);
        }
      });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setStreamVisuals("stream error", "warn", toErrorMessage(error));
        app.pushAlert(toErrorMessage(error), "danger");
      }
    } finally {
      streaming = false;
      streamController = null;
      if (app.isCurrentRender(token)) {
        setStreamVisuals("idle", "default", "Live stream stopped. The current tail remains available.");
      }
    }
  };

  refreshButton.addEventListener("click", () => {
    void refreshLogs();
  });
  resetFiltersButton.addEventListener("click", () => {
    window.history.replaceState({}, "", "/admin/logs");
    void app.render("logs");
  });
  streamButton.addEventListener("click", () => {
    if (streaming) {
      stopStream();
      return;
    }
    void startStream();
  });
  clearButton.addEventListener("click", () => {
    rawLogLines = [];
    setRenderedLogs();
    setStreamVisuals(
      streaming ? "streaming" : "idle",
      streaming ? "good" : "default",
      streaming ? "Stream is still connected. Buffer cleared locally." : "Tail buffer cleared locally.",
    );
  });
  autoScrollToggle.addEventListener("change", () => {
    autoScroll = autoScrollToggle.checked;
  });
  filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      lines: HTMLSelectElement;
      query: HTMLInputElement;
      provider: HTMLSelectElement;
      method: HTMLSelectElement;
      status_code: HTMLSelectElement;
      error_type: HTMLSelectElement;
      limit: HTMLSelectElement;
    };

    const nextFilters: LogsFilters = {
      lines: fields.lines.value || DEFAULT_LINES,
      query: fields.query.value.trim(),
      provider: fields.provider.value,
      method: fields.method.value,
      statusCode: fields.status_code.value,
      errorType: fields.error_type.value,
      limit: fields.limit.value || DEFAULT_LIMIT,
    };
    window.history.replaceState({}, "", buildLogsUrl(nextFilters));
    void app.render("logs");
  });

  const inspectPayloads: Record<"request" | "error", LogEvent[]> = {
    request: requestEvents,
    error: errorEvents,
  };

  app.pageContent.querySelectorAll<HTMLElement>("[data-log-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.logKind;
      const indexValue = button.dataset.logDetail;
      if ((kind !== "request" && kind !== "error") || indexValue === undefined) {
        return;
      }
      const item = inspectPayloads[kind][Number(indexValue)];
      if (!item) {
        return;
      }

      summaryNode.innerHTML = renderDefinitionList(
        [
          { label: "Selection", value: kind === "error" ? "Recent error" : "Recent request" },
          { label: "Request id", value: String(item.request_id ?? "n/a") },
          { label: "Provider", value: String(item.provider ?? "unknown") },
          {
            label: "Route",
            value: `${String(item.method ?? "GET")} ${String(item.endpoint ?? item.path ?? "n/a")}`,
          },
          { label: "Status", value: formatNumber(item.status_code ?? 0) },
          {
            label: "Timing",
            value: formatDurationMs(item.stream_duration_ms ?? item.duration_ms),
            note: kind === "error" ? String(item.error_type ?? "request failed") : String(item.model ?? "no model"),
          },
        ],
        "No event selected yet.",
      );
      detailNode.textContent = JSON.stringify(item, null, 2);
    });
  });

  setRenderedLogs();
  setStreamVisuals("idle");
}

function readLogsFilters(): LogsFilters {
  const params = new URLSearchParams(window.location.search);
  return {
    lines: params.get("lines") || DEFAULT_LINES,
    query: params.get("query") || "",
    provider: params.get("provider") || "",
    method: params.get("method") || "",
    statusCode: params.get("status_code") || "",
    errorType: params.get("error_type") || "",
    limit: params.get("limit") || DEFAULT_LIMIT,
  };
}

function buildLogsEventQuery(filters: LogsFilters): string {
  const params = new URLSearchParams();
  params.set("limit", filters.limit || DEFAULT_LIMIT);
  setIfPresent(params, "provider", filters.provider);
  setIfPresent(params, "method", filters.method);
  setIfPresent(params, "status_code", filters.statusCode);
  setIfPresent(params, "error_type", filters.errorType);
  return params.toString();
}

function buildLogsUrl(filters: LogsFilters): string {
  const params = new URLSearchParams();
  setIfPresent(params, "lines", filters.lines, DEFAULT_LINES);
  setIfPresent(params, "query", filters.query);
  setIfPresent(params, "provider", filters.provider);
  setIfPresent(params, "method", filters.method);
  setIfPresent(params, "status_code", filters.statusCode);
  setIfPresent(params, "error_type", filters.errorType);
  setIfPresent(params, "limit", filters.limit, DEFAULT_LIMIT);
  const query = params.toString();
  return query ? `/admin/logs?${query}` : "/admin/logs";
}

function normalizeLogText(text: string): string[] {
  return text
    .split(/\r?\n/u)
    .map((line) => line.trimEnd())
    .filter((line) => line.length > 0)
    .slice(-MAX_LOG_LINES);
}

function formatRenderedLogOutput(lines: string[], query: string): string {
  const filtered = filterLogLines(lines, query);
  return filtered.length ? filtered.join("\n") : "No log lines matched the current filters.";
}

function filterLogLines(lines: string[], query: string): string[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return lines;
  }
  return lines.filter((line) => line.toLowerCase().includes(normalizedQuery));
}

function countMatchingLines(lines: string[], query: string): string {
  return formatNumber(filterLogLines(lines, query).length);
}

function summarizeActiveFilters(filters: LogsFilters): string {
  const active = [
    filters.provider ? `provider=${filters.provider}` : "",
    filters.method ? `method=${filters.method}` : "",
    filters.statusCode ? `status=${filters.statusCode}` : "",
    filters.errorType ? `error=${filters.errorType}` : "",
    filters.query ? `text=${filters.query}` : "",
  ].filter(Boolean);
  return active.join(" · ");
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

async function readSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: { type: string; data: string }) => void,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      flushSseBuffer(buffer, onEvent);
      return;
    }

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/u);
    buffer = frames.pop() ?? "";
    frames.forEach((frame) => flushSseBuffer(frame, onEvent));
  }
}

function flushSseBuffer(
  rawFrame: string,
  onEvent: (event: { type: string; data: string }) => void,
): void {
  const frame = rawFrame.trim();
  if (!frame) {
    return;
  }

  let eventType = "message";
  const dataLines: string[] = [];
  frame.split(/\r?\n/u).forEach((line) => {
    if (!line || line.startsWith(":")) {
      return;
    }
    if (line.startsWith("event:")) {
      eventType = line.slice("event:".length).trim() || "message";
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  });

  if (dataLines.length === 0 && eventType === "message") {
    return;
  }
  onEvent({ type: eventType, data: dataLines.join("\n") });
}
