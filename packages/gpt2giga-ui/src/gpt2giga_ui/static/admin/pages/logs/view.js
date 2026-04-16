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
    ${card(filters.requestId ? "Diagnose workflow" : "Deep-dive diagnose workflow", renderLogsWorkflowGuide(filters), "panel panel--span-12 panel--measure")}
    ${card("Log scope", renderLogsFiltersForm(data, filters), "panel panel--span-8 panel--measure")}
    ${card("Current posture and handoff", renderLogsInspector(data, filters, rawLogLines), "panel panel--span-4 panel--aside")}
    ${card("Rendered log tail", `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Rendered output</h4>
                <p class="muted">Keep the tail readable first. Use the request scope and tail-derived context table to correlate one request before expanding live stream troubleshooting or raw snapshots.</p>
              </div>
              <div class="surface__meta">
                <span class="pill" id="logs-match-count">${escapeHtml(`${countMatchingLines(rawLogLines, filters)} matches`)}</span>
              </div>
            </div>
            <pre class="code-block code-block--tall" id="log-output">${escapeHtml(formatRenderedLogOutput(rawLogLines, filters))}</pre>
          </div>
        </div>
      `, "panel panel--span-8")}
    ${card("Live tail controls", renderLogsStreamPanel(streamState, rawLogLines.length), "panel panel--span-4 panel--aside")}
    ${card("Tail-derived request context", `
        <div class="stack">
          <p class="muted">
            Extract request ids from the rendered tail only after the current scope is narrow enough to be useful. This keeps the handoff back to Traffic predictable instead of starting from raw lines alone.
          </p>
          <div id="logs-tail-context">
            ${renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup), filters)}
          </div>
        </div>
      `, "panel panel--span-8")}
    ${card("Guide and troubleshooting", renderGuideLinks([
        {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Use the longer playbook for request-pinned tail inspection, live streaming, and the moment when raw logs become necessary.",
        },
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Step back to the summary-first request flow when you need to re-check recent request volume, error mix, or a broader provider window.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the page-to-page escalation map when the problem no longer belongs only to Logs and needs a clearer next handoff.",
        },
    ], filters.requestId
        ? "Logs is already pinned to one request. Use these guides only when the current posture and handoff actions still leave the next step unclear."
        : "Logs stays request-scoped. Use the guides when the current posture and tail context are still not enough to choose the next handoff."), "panel panel--span-4 panel--aside")}
    ${card("Recent errors", renderErrorRows(data.errorEvents, filters), "panel panel--span-6")}
    ${card("Recent requests", renderRequestRows(data.requestEvents, filters), "panel panel--span-6")}
  `;
}
function renderLogsFiltersForm(data, filters) {
    return `
    <form id="logs-filters-form" class="form-shell form-shell--compact">
      <div class="form-shell__intro">
        <p class="muted">
          Keep Logs narrower than the broad traffic workflow. Start by shaping one tail window, then pin one request only when the next step really needs raw evidence.
        </p>
      </div>
      ${renderFormSection({
        title: "Tail window",
        intro: "These controls shape the rendered tail first. Text matching stays client-side so you can re-scope quickly without another page transition.",
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
        intro: "Pin one request id only when structured request and error context should stay aligned with the same log window and Traffic handoff.",
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
                Request pinning narrows the recent request and error context, tail-derived request links, and the rendered tail without forcing you into raw output too early.
              </p>
            </div>
          </div>
        `,
    })}
      ${renderFormSection({
        title: "Event scope",
        intro: "These filters stay aligned with the recent request and error feeds so the current scope can move between Traffic and Logs without rework.",
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
            <span class="muted">The same scope drives recent request and error panels, tail-derived links, and the Traffic handoff.</span>
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
      <p class="muted">
        Keep the selected scope readable before expanding any raw snapshot. The page should answer what is pinned, what evidence is loaded, and where the next handoff goes.
      </p>
      ${renderFormSection({
        title: "Current posture",
        intro: "Read the current log scope first. Tail evidence and live stream internals stay secondary until this summary still leaves ambiguity.",
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
        intro: "Inspect the selected event or tail-derived request here first, then hand off to Traffic only when the aggregated view needs to come back into focus.",
        body: `
          <div id="logs-selection-summary">
            ${renderDefinitionList([
            { label: "Selection", value: "No context selected" },
            { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
            {
                label: "Request scope",
                value: filters.requestId || "Recent log window",
                note: filters.requestId
                    ? "The rendered tail, tail-derived request links, and event panels are pinned to one request id."
                    : "Select a tail-derived request line or a recent request or error row to inspect context.",
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
          Expand this only when the posture summary and handoff actions still are not enough.
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
            <p class="muted">Use streaming only after the current scope is already clear. Restart and diagnostics stay secondary to the rendered tail and request handoff.</p>
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
            Expand this only when the SSE lifecycle itself needs troubleshooting or when a hanging reader is suspected.
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
          <h4>${escapeHtml(scoped ? "Keep the deep dive scoped" : "Use Logs only after Traffic narrowed the question")}</h4>
          <p>${escapeHtml(scoped
        ? "Logs is already scoped to one request id. Read the posture summary, use the selected request and error context, and open the rendered tail only as the evidence surface for that same request."
        : "Logs is the deep-dive surface. Start from Traffic summaries when possible, then land here only after one request, failure, or text pattern is worth tracing line by line.")}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button button--secondary" href="/admin/logs">${escapeHtml(scoped ? "Reset log scope" : "Reset to default tail")}</a>
        </div>
      </article>
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Observe</span>
          <h4>${escapeHtml(scoped ? "Return to the matching traffic summary" : "Return to the broad traffic summary")}</h4>
          <p>${escapeHtml(scoped
        ? "When the root cause is clear, jump back to Traffic to compare the same request context against recent request and error summaries without rebuilding the scope."
        : "Return to Traffic whenever you need to re-check recent request volume, error mix, or usage rollups around the same provider and status filters.")}</p>
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
