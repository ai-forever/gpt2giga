import { card, kpi, renderDefinitionList, renderFilterSelectOptions, renderStaticSelectOptions, } from "../../templates.js";
import { asArray, asRecord, escapeHtml } from "../../utils.js";
import { buildStreamDiagnostics, buildTailContextRows, buildTrafficUrlForRequest, countMatchingLines, formatRenderedLogOutput, indexEventsByRequestId, renderErrorRows, renderLogSelectionActions, renderRequestRows, renderStreamPill, renderTailContextTable, summarizeActiveFilters, } from "./serializers.js";
import { createLogsStreamState, DEFAULT_LIMIT, DEFAULT_LINES } from "./state.js";
import { normalizeLogText } from "./serializers.js";
export function renderLogsHeroActions() {
    return `
    <button class="button button--secondary" id="reset-log-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-logs" type="button">Refresh tail</button>
    <button class="button" id="toggle-stream" type="button">Start live stream</button>
  `;
}
export function renderLogsPage(data, filters) {
    const rawLogLines = normalizeLogText(data.tailText);
    const requestLookup = indexEventsByRequestId(data.requestEvents);
    const errorLookup = indexEventsByRequestId(data.errorEvents);
    const streamState = createLogsStreamState();
    return `
    ${kpi("Tail lines", filters.lines || DEFAULT_LINES)}
    ${kpi("Matching lines", countMatchingLines(rawLogLines, filters))}
    ${kpi("Recent errors", data.errorEvents.length)}
    ${kpi("Recent requests", data.requestEvents.length)}
    ${card("Log filters", `
        <form id="logs-filters-form" class="stack">
          <div class="dual-grid">
            <label class="field">
              <span>Tail lines</span>
              <select name="lines">
                ${renderStaticSelectOptions(filters.lines || DEFAULT_LINES, ["100", "150", "250", "500", "1000"])}
              </select>
            </label>
            <label class="field">
              <span>Text match</span>
              <input name="query" value="${escapeHtml(filters.query)}" placeholder="Filter the rendered tail client-side" />
            </label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Request id</span>
              <input
                name="request_id"
                value="${escapeHtml(filters.requestId)}"
                placeholder="Pin one request across logs and traffic"
              />
            </label>
            <div class="surface">
              <div class="stack">
                <h4>Request scope</h4>
                <p class="muted">
                  Request pinning narrows the recent request/error context panels, tail-derived request
                  context, and the rendered tail by one request id so Traffic handoff stays one click away.
                </p>
              </div>
            </div>
          </div>
          <div class="quad-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderFilterSelectOptions(filters.provider, [
        ...asArray(asRecord(data.recentRequestsPayload.available_filters).provider),
        ...asArray(asRecord(data.recentErrorsPayload.available_filters).provider),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderFilterSelectOptions(filters.method, [
        ...asArray(asRecord(data.recentRequestsPayload.available_filters).method),
        ...asArray(asRecord(data.recentErrorsPayload.available_filters).method),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderFilterSelectOptions(filters.statusCode, [
        ...asArray(asRecord(data.recentRequestsPayload.available_filters).status_code),
        ...asArray(asRecord(data.recentErrorsPayload.available_filters).status_code),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Error type</span>
              <select name="error_type">
                ${renderFilterSelectOptions(filters.errorType, asArray(asRecord(data.recentErrorsPayload.available_filters).error_type))}
              </select>
            </label>
          </div>
          <div class="toolbar">
            <label class="field">
              <span>Recent event limit</span>
              <select name="limit">
                ${renderStaticSelectOptions(filters.limit || DEFAULT_LIMIT, ["5", "8", "12", "20"])}
              </select>
            </label>
            <span class="muted">Filters scope the request/error context panels, tail-derived request links, and the tail viewer in one place.</span>
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Apply filters</button>
            <a class="button button--secondary" href="${escapeHtml(filters.requestId ? buildTrafficUrlForRequest(filters.requestId) : "/admin/traffic")}">
              ${escapeHtml(filters.requestId ? "Open pinned traffic" : "Open traffic")}
            </a>
          </div>
        </form>
      `, "panel panel--span-12")}
    ${card("Stream controls", `
        <div class="surface">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Live tail status</h4>
                <p class="muted">SSE lifecycle is tracked explicitly so stop/reload flows do not leave a hanging stream reader behind.</p>
              </div>
              <div class="surface__meta" id="logs-stream-status">${renderStreamPill("idle")}</div>
            </div>
            <div class="toolbar">
              <label class="checkbox-field">
                <input id="logs-auto-scroll" type="checkbox" checked />
                <span>Auto-scroll while streaming</span>
              </label>
              <button class="button button--secondary" id="clear-log-output" type="button">Clear buffer</button>
              <span class="muted" id="logs-stream-note">Tail buffer loaded from the file on disk.</span>
            </div>
            <div id="logs-stream-diagnostics">
              ${renderDefinitionList(buildStreamDiagnostics(streamState, rawLogLines.length))}
            </div>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Context inspector", `
        <div class="surface">
          <div class="stack">
            <div id="logs-selection-summary">
              ${renderDefinitionList([
        { label: "Selection", value: "No context selected" },
        { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
        {
            label: "Request scope",
            value: filters.requestId || "Recent log window",
            note: filters.requestId
                ? "The rendered tail, tail-derived request links, and event panels are pinned to one request id."
                : "Select a tail-derived request link or a recent request/error row to inspect context.",
        },
    ], "No event selected yet.")}
            </div>
            <div class="toolbar" id="logs-selection-actions">
              ${renderLogSelectionActions(null, filters)}
            </div>
            <pre class="code-block" id="logs-detail">${escapeHtml(JSON.stringify({
        filters,
        requests_loaded: data.requestEvents.length,
        errors_loaded: data.errorEvents.length,
    }, null, 2))}</pre>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Tail-derived request context", `
        <div id="logs-tail-context">
          ${renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup))}
        </div>
      `, "panel panel--span-4")}
    ${card("Rendered log tail", `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Rendered output</h4>
                <p class="muted">Client-side filtering is applied after fetching the selected tail window. Use the tail-derived context panel to jump from matching lines into structured request data.</p>
              </div>
              <div class="surface__meta">
                <span class="pill" id="logs-match-count">${escapeHtml(`${countMatchingLines(rawLogLines, filters)} matches`)}</span>
              </div>
            </div>
            <pre class="code-block code-block--tall" id="log-output">${escapeHtml(formatRenderedLogOutput(rawLogLines, filters))}</pre>
          </div>
        </div>
      `, "panel panel--span-12")}
    ${card("Recent errors", renderErrorRows(data.errorEvents), "panel panel--span-6")}
    ${card("Recent requests", renderRequestRows(data.requestEvents), "panel panel--span-6")}
  `;
}
export function resolveLogsElements(pageContent) {
    const refreshButton = document.getElementById("refresh-logs");
    const resetFiltersButton = document.getElementById("reset-log-filters");
    const streamButton = document.getElementById("toggle-stream");
    const clearButton = pageContent.querySelector("#clear-log-output");
    const filtersForm = pageContent.querySelector("#logs-filters-form");
    const logOutput = pageContent.querySelector("#log-output");
    const matchCount = pageContent.querySelector("#logs-match-count");
    const streamStatus = pageContent.querySelector("#logs-stream-status");
    const streamNote = pageContent.querySelector("#logs-stream-note");
    const streamDiagnostics = pageContent.querySelector("#logs-stream-diagnostics");
    const autoScrollToggle = pageContent.querySelector("#logs-auto-scroll");
    const detailNode = pageContent.querySelector("#logs-detail");
    const summaryNode = pageContent.querySelector("#logs-selection-summary");
    const actionsNode = pageContent.querySelector("#logs-selection-actions");
    const tailContextNode = pageContent.querySelector("#logs-tail-context");
    if (!refreshButton ||
        !resetFiltersButton ||
        !streamButton ||
        !clearButton ||
        !filtersForm ||
        !logOutput ||
        !matchCount ||
        !streamStatus ||
        !streamNote ||
        !streamDiagnostics ||
        !autoScrollToggle ||
        !detailNode ||
        !summaryNode ||
        !actionsNode ||
        !tailContextNode) {
        return null;
    }
    return {
        actionsNode,
        autoScrollToggle,
        clearButton,
        detailNode,
        filtersForm,
        logOutput,
        matchCount,
        refreshButton,
        resetFiltersButton,
        streamButton,
        streamDiagnostics,
        streamNote,
        streamStatus,
        summaryNode,
        tailContextNode,
    };
}
