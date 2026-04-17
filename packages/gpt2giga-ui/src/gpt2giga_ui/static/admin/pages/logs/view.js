import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import { card, kpi, renderDefinitionList, renderFilterSelectOptions, renderFormSection, renderGuideLinks, renderStatLines, renderStaticSelectOptions, } from "../../templates.js";
import { asArray, asRecord, escapeHtml } from "../../utils.js";
import { buildStreamDiagnostics, buildTailContextRows, buildTrafficUrlForRequest, countMatchingLines, formatRenderedLogOutput, indexEventsByRequestId, renderErrorRows, renderLogSelectionActions, renderRequestRows, renderStreamPill, renderTailContextTable, summarizeActiveFilters, } from "./serializers.js";
import { createLogsStreamState, DEFAULT_LIMIT, DEFAULT_LINES } from "./state.js";
import { normalizeLogText } from "./serializers.js";
export function renderLogsHeroActions(filters) {
    const trafficHref = buildTrafficUrlForRequest(filters.requestId, filters);
    return `
    <button class="button button--secondary" id="reset-log-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-logs" type="button">Refresh tail</button>
    <button class="button" id="toggle-stream" type="button">Start live stream</button>
    <a class="button button--secondary" href="${escapeHtml(trafficHref)}">${escapeHtml(filters.requestId ? "Open pinned traffic" : "Open traffic summary")}</a>
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
    ${card("Workflow", renderLogsWorkflowGuide(filters), "panel panel--span-12 panel--measure")}
    ${card("Scope", renderLogsFiltersForm(data, filters), "panel panel--span-8 panel--measure")}
    ${card("Posture", renderLogsInspector(data, filters, rawLogLines), "panel panel--span-4 panel--aside")}
    ${card("Rendered log tail", `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Rendered output</h4>
                <p class="muted">Read the rendered tail first. Use one request scope before opening stream diagnostics or raw snapshots.</p>
              </div>
              <div class="surface__meta">
                <span class="pill" id="logs-match-count">${escapeHtml(`${countMatchingLines(rawLogLines, filters)} matches`)}</span>
              </div>
            </div>
            <pre class="code-block code-block--tall" id="log-output">${escapeHtml(formatRenderedLogOutput(rawLogLines, filters))}</pre>
          </div>
        </div>
      `, "panel panel--span-8")}
    ${card("Live stream", renderLogsStreamPanel(streamState, rawLogLines.length), "panel panel--span-4 panel--aside")}
    ${card("Tail context", `
        <div class="stack">
          <p class="muted">
            Extract request ids only after the current scope is narrow enough to be useful.
          </p>
          <div id="logs-tail-context">
            ${renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup), filters)}
          </div>
        </div>
      `, "panel panel--span-8")}
    ${card("Guides", renderGuideLinks([
        {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Request-pinned tail inspection and live streaming.",
        },
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Step back when you need the broader request summary.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Cross-page escalation map.",
        },
    ], {
        compact: true,
        collapsibleSummary: "Operator guides",
        intro: filters.requestId ? "Open only if the pinned request still needs a handoff." : "Open only if the current scope still needs a handoff.",
    }), "panel panel--span-4 panel--aside")}
    ${card("Recent errors", renderErrorRows(data.errorEvents, filters), "panel panel--span-6")}
    ${card("Recent requests", renderRequestRows(data.requestEvents, filters), "panel panel--span-6")}
  `;
}
function renderLogsFiltersForm(data, filters) {
    return `
    <form id="logs-filters-form" class="form-shell form-shell--compact">
      <div class="form-shell__intro">
        <p class="muted">
          Keep Logs narrower than Traffic. Shape the tail window first, then pin one request only when needed.
        </p>
      </div>
      ${renderFormSection({
        title: "Tail window",
        intro: "Shape the rendered tail first.",
        body: `
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
        `,
    })}
      ${renderFormSection({
        title: "Request pinning",
        intro: "Pin one request only when the same scope should stay aligned across logs and traffic.",
        body: `
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
              <p class="muted">
                Pinning narrows the rendered tail, recent events, and handoff links together.
              </p>
            </div>
          </div>
        `,
    })}
      ${renderFormSection({
        title: "Event scope",
        intro: "Keep the current scope aligned with recent request and error feeds.",
        body: `
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
            <span class="muted">The same scope drives recent panels, tail links, and Traffic handoff.</span>
          </div>
        `,
    })}
      <div class="form-actions">
        <button class="button" type="submit">Apply filters</button>
        <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(filters.requestId, filters))}">
          ${escapeHtml(filters.requestId ? "Open pinned traffic" : "Open traffic summary")}
        </a>
      </div>
    </form>
  `;
}
function renderLogsInspector(data, filters, rawLogLines) {
    return `
    <div class="stack">
      ${renderFormSection({
        title: "Current posture",
        intro: "Read the current log scope first.",
        body: renderStatLines([
            { label: "Tail lines loaded", value: String(rawLogLines.length) },
            { label: "Matching lines", value: countMatchingLines(rawLogLines, filters) },
            { label: "Request rows", value: String(data.requestEvents.length) },
            { label: "Error rows", value: String(data.errorEvents.length) },
            { label: "Pinned request", value: filters.requestId || "none" },
        ], "No log posture is available."),
    })}
      ${renderFormSection({
        title: "Selection and handoff",
        intro: "Inspect the selected event or tail-derived request here first.",
        body: `
          <div id="logs-selection-summary">
            ${renderDefinitionList([
            { label: "Selection", value: "No context selected" },
            { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
            {
                label: "Request scope",
                value: filters.requestId || "Recent log window",
                note: filters.requestId
                    ? "Tail, tail links, and recent panels are pinned to one request."
                    : "Select a tail-derived request line or recent event row.",
            },
        ], "No event selected yet.")}
          </div>
          <div class="toolbar" id="logs-selection-actions">
            ${renderLogSelectionActions(null, filters)}
          </div>
        `,
    })}
      <details class="details-disclosure" id="logs-detail-disclosure">
        <summary id="logs-detail-summary">Current scope snapshot</summary>
        <p class="field-note">
          Expand only if the posture summary still is not enough.
        </p>
        <pre class="code-block" id="logs-detail">${escapeHtml(JSON.stringify({
        filters,
        requests_loaded: data.requestEvents.length,
        errors_loaded: data.errorEvents.length,
    }, null, 2))}</pre>
      </details>
    </div>
  `;
}
function renderLogsStreamPanel(streamState, rawLineCount) {
    return `
    <div class="surface">
      <div class="stack">
        <div class="surface__header">
          <div class="stack">
            <h4>Live tail status</h4>
            <p class="muted">Use streaming only after the current scope is clear.</p>
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
        <details class="details-disclosure" id="logs-stream-diagnostics-disclosure">
          <summary>Live stream diagnostics</summary>
          <p class="field-note">
            Expand only when the SSE lifecycle itself needs troubleshooting.
          </p>
          <div id="logs-stream-diagnostics">
            ${renderDefinitionList(buildStreamDiagnostics(streamState, rawLineCount))}
          </div>
        </details>
      </div>
    </div>
  `;
}
function renderLogsWorkflowGuide(filters) {
    const trafficHref = buildTrafficUrlForRequest(filters.requestId, filters);
    const scoped = Boolean(filters.requestId);
    return `
    <div class="workflow-grid">
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Diagnose</span>
          <h4>${escapeHtml(scoped ? "Keep the deep dive scoped" : "Open Logs after Traffic narrows the question")}</h4>
          <p>${escapeHtml(scoped
        ? "Logs is already pinned to one request. Keep the same request across posture, tail, and recent-event context."
        : "Start from Traffic summaries when possible, then land here only after one request, failure, or text pattern is worth tracing line by line.")}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button button--secondary" href="/admin/logs">${escapeHtml(scoped ? "Reset log scope" : "Reset to default tail")}</a>
        </div>
      </article>
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Observe</span>
          <h4>${escapeHtml(scoped ? "Return to matching traffic" : "Return to traffic summary")}</h4>
          <p>${escapeHtml(scoped
        ? "Jump back to Traffic to compare the same request against recent request and error summaries."
        : "Return to Traffic when you need the broader request, error, or usage summary.")}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button" href="${escapeHtml(trafficHref)}">${escapeHtml(scoped ? "Open pinned traffic" : "Open traffic summary")}</a>
        </div>
      </article>
    </div>
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
    const streamDiagnosticsDisclosure = pageContent.querySelector("#logs-stream-diagnostics-disclosure");
    const autoScrollToggle = pageContent.querySelector("#logs-auto-scroll");
    const detailDisclosure = pageContent.querySelector("#logs-detail-disclosure");
    const detailSummaryNode = pageContent.querySelector("#logs-detail-summary");
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
        !streamDiagnosticsDisclosure ||
        !autoScrollToggle ||
        !detailDisclosure ||
        !detailSummaryNode ||
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
        detailDisclosure,
        detailSummaryNode,
        detailNode,
        filtersForm,
        logOutput,
        matchCount,
        refreshButton,
        resetFiltersButton,
        streamButton,
        streamDiagnostics,
        streamDiagnosticsDisclosure,
        streamNote,
        streamStatus,
        summaryNode,
        tailContextNode,
    };
}
