import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import {
  card,
  kpi,
  renderDefinitionList,
  renderFilterSelectOptions,
  renderGuideLinks,
  renderStaticSelectOptions,
} from "../../templates.js";
import { asArray, asRecord, escapeHtml } from "../../utils.js";
import type { LogsPageData } from "./api.js";
import {
  buildStreamDiagnostics,
  buildTailContextRows,
  buildTrafficUrlForRequest,
  countMatchingLines,
  formatRenderedLogOutput,
  indexEventsByRequestId,
  renderErrorRows,
  renderLogSelectionActions,
  renderRequestRows,
  renderStreamPill,
  renderTailContextTable,
  summarizeActiveFilters,
} from "./serializers.js";
import type { LogsFilters } from "./state.js";
import { createLogsStreamState, DEFAULT_LIMIT, DEFAULT_LINES } from "./state.js";
import { normalizeLogText } from "./serializers.js";

export interface LogsPageElements {
  actionsNode: HTMLElement;
  autoScrollToggle: HTMLInputElement;
  clearButton: HTMLButtonElement;
  detailDisclosure: HTMLDetailsElement;
  detailSummaryNode: HTMLElement;
  detailNode: HTMLPreElement;
  filtersForm: HTMLFormElement;
  logOutput: HTMLPreElement;
  matchCount: HTMLElement;
  refreshButton: HTMLButtonElement;
  resetFiltersButton: HTMLButtonElement;
  streamButton: HTMLButtonElement;
  streamDiagnostics: HTMLElement;
  streamDiagnosticsDisclosure: HTMLDetailsElement;
  streamNote: HTMLElement;
  streamStatus: HTMLElement;
  summaryNode: HTMLElement;
  tailContextNode: HTMLElement;
}

export function renderLogsHeroActions(filters: LogsFilters): string {
  const trafficHref = buildTrafficUrlForRequest(filters.requestId, filters);
  return `
    <button class="button button--secondary" id="reset-log-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-logs" type="button">Refresh tail</button>
    <button class="button" id="toggle-stream" type="button">Start live stream</button>
    <a class="button button--secondary" href="${escapeHtml(trafficHref)}">${escapeHtml(
      filters.requestId ? "Open pinned traffic" : "Open traffic summary",
    )}</a>
  `;
}

export function renderLogsPage(data: LogsPageData, filters: LogsFilters): string {
  const rawLogLines = normalizeLogText(data.tailText);
  const requestLookup = indexEventsByRequestId(data.requestEvents);
  const errorLookup = indexEventsByRequestId(data.errorEvents);
  const streamState = createLogsStreamState();

  return `
    ${kpi("Tail lines", filters.lines || DEFAULT_LINES)}
    ${kpi("Matching lines", countMatchingLines(rawLogLines, filters))}
    ${kpi("Recent errors", data.errorEvents.length)}
    ${kpi("Recent requests", data.requestEvents.length)}
    ${card(
      filters.requestId ? "Diagnose workflow" : "Deep-dive diagnose workflow",
      renderLogsWorkflowGuide(filters),
      "panel panel--span-12",
    )}
    ${card(
      "Log filters",
      `
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
                ${renderFilterSelectOptions(
                  filters.provider,
                  [
                    ...asArray<unknown>(asRecord(data.recentRequestsPayload.available_filters).provider),
                    ...asArray<unknown>(asRecord(data.recentErrorsPayload.available_filters).provider),
                  ],
                )}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderFilterSelectOptions(
                  filters.method,
                  [
                    ...asArray<unknown>(asRecord(data.recentRequestsPayload.available_filters).method),
                    ...asArray<unknown>(asRecord(data.recentErrorsPayload.available_filters).method),
                  ],
                )}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderFilterSelectOptions(
                  filters.statusCode,
                  [
                    ...asArray<unknown>(asRecord(data.recentRequestsPayload.available_filters).status_code),
                    ...asArray<unknown>(asRecord(data.recentErrorsPayload.available_filters).status_code),
                  ],
                )}
              </select>
            </label>
            <label class="field">
              <span>Error type</span>
              <select name="error_type">
                ${renderFilterSelectOptions(
                  filters.errorType,
                  asArray<unknown>(asRecord(data.recentErrorsPayload.available_filters).error_type),
                )}
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
            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(filters.requestId, filters))}">
              ${escapeHtml(filters.requestId ? "Open pinned traffic" : "Open traffic summary")}
            </a>
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
            <details class="details-disclosure" id="logs-stream-diagnostics-disclosure">
              <summary>Session diagnostics</summary>
              <p class="field-note">
                Expand this only when the live SSE lifecycle needs troubleshooting or when a hanging reader is suspected.
              </p>
              <div id="logs-stream-diagnostics">
                ${renderDefinitionList(buildStreamDiagnostics(streamState, rawLogLines.length))}
              </div>
            </details>
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
            <div class="workflow-card">
              <div class="workflow-card__header">
                <span class="eyebrow">${escapeHtml(filters.requestId ? "Pinned context" : "Start here")}</span>
                <h4>${escapeHtml(
                  filters.requestId ? "Pinned request evidence is ready" : "Narrow the deep dive before reading raw logs",
                )}</h4>
                <p>${escapeHtml(
                  filters.requestId
                    ? "This page is already scoped to one request id. Inspect the structured request or error context first, then keep the rendered tail and live stream secondary."
                    : "Use Traffic or a tail-derived request id to narrow one request first. Keep the raw tail and live stream secondary until one failure or text pattern actually needs line-by-line evidence.",
                )}</p>
              </div>
            </div>
            <div id="logs-selection-summary">
              ${renderDefinitionList(
                [
                  { label: "Selection", value: "No context selected" },
                  { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
                  {
                    label: "Request scope",
                    value: filters.requestId || "Recent log window",
                    note: filters.requestId
                      ? "The rendered tail, tail-derived request links, and event panels are pinned to one request id."
                      : "Select a tail-derived request link or a recent request/error row to inspect context.",
                  },
                ],
                "No event selected yet.",
              )}
            </div>
            <div class="toolbar" id="logs-selection-actions">
              ${renderLogSelectionActions(null, filters)}
            </div>
            <details class="details-disclosure" id="logs-detail-disclosure">
              <summary id="logs-detail-summary">Raw context snapshot</summary>
              <pre class="code-block" id="logs-detail">${escapeHtml(
                JSON.stringify(
                  {
                    filters,
                    requests_loaded: data.requestEvents.length,
                    errors_loaded: data.errorEvents.length,
                  },
                  null,
                  2,
                ),
              )}</pre>
            </details>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Tail-derived request context",
      `
        <div id="logs-tail-context">
          ${renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup), filters)}
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
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
        ],
        filters.requestId
          ? "Logs is already pinned to one request. These links explain how to keep the deep dive scoped and when to return to broader operator surfaces."
          : "Logs is the deep-dive surface. Use the guide links when you need a fuller troubleshooting flow instead of continuing ad hoc from the raw tail alone.",
      ),
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
                <p class="muted">Client-side filtering is applied after fetching the selected tail window. Use the tail-derived context panel to jump from matching lines into structured request data, then return to Traffic with the same request scope when you need the aggregate view again.</p>
              </div>
              <div class="surface__meta">
                <span class="pill" id="logs-match-count">${escapeHtml(
                  `${countMatchingLines(rawLogLines, filters)} matches`,
                )}</span>
              </div>
            </div>
            <pre class="code-block code-block--tall" id="log-output">${escapeHtml(
              formatRenderedLogOutput(rawLogLines, filters),
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card("Recent errors", renderErrorRows(data.errorEvents, filters), "panel panel--span-6")}
    ${card("Recent requests", renderRequestRows(data.requestEvents, filters), "panel panel--span-6")}
  `;
}

function renderLogsWorkflowGuide(filters: LogsFilters): string {
  const trafficHref = buildTrafficUrlForRequest(filters.requestId, filters);
  const scoped = Boolean(filters.requestId);
  return `
    <div class="workflow-grid">
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Diagnose</span>
          <h4>${escapeHtml(scoped ? "Keep the deep dive scoped" : "Use Logs only after Traffic narrowed the question")}</h4>
          <p>${escapeHtml(
            scoped
              ? "Logs is already scoped to one request id. Follow the rendered tail, structured request and error context, and live stream from here when you need raw evidence for one request."
              : "Logs is the diagnose surface. Start from Traffic summaries when possible, then land here only after one request, failure, or text pattern is worth tracing line by line.",
          )}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button button--secondary" href="/admin/logs">${escapeHtml(
            scoped ? "Reset log scope" : "Reset to default tail",
          )}</a>
        </div>
      </article>
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Observe</span>
          <h4>${escapeHtml(scoped ? "Return to the matching traffic summary" : "Return to the broad traffic summary")}</h4>
          <p>${escapeHtml(
            scoped
              ? "When the root cause is clear, jump back to Traffic to compare the same request context against recent request and error summaries."
              : "Return to Traffic whenever you need to re-check recent request volume, error mix, or usage rollups around the same provider and status filters.",
          )}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button" href="${escapeHtml(trafficHref)}">${escapeHtml(
            scoped ? "Open pinned traffic" : "Open traffic summary",
          )}</a>
        </div>
      </article>
    </div>
  `;
}

export function resolveLogsElements(pageContent: HTMLElement): LogsPageElements | null {
  const refreshButton = document.getElementById("refresh-logs") as HTMLButtonElement | null;
  const resetFiltersButton = document.getElementById("reset-log-filters") as HTMLButtonElement | null;
  const streamButton = document.getElementById("toggle-stream") as HTMLButtonElement | null;
  const clearButton = pageContent.querySelector<HTMLButtonElement>("#clear-log-output");
  const filtersForm = pageContent.querySelector<HTMLFormElement>("#logs-filters-form");
  const logOutput = pageContent.querySelector<HTMLPreElement>("#log-output");
  const matchCount = pageContent.querySelector<HTMLElement>("#logs-match-count");
  const streamStatus = pageContent.querySelector<HTMLElement>("#logs-stream-status");
  const streamNote = pageContent.querySelector<HTMLElement>("#logs-stream-note");
  const streamDiagnostics = pageContent.querySelector<HTMLElement>("#logs-stream-diagnostics");
  const streamDiagnosticsDisclosure = pageContent.querySelector<HTMLDetailsElement>(
    "#logs-stream-diagnostics-disclosure",
  );
  const autoScrollToggle = pageContent.querySelector<HTMLInputElement>("#logs-auto-scroll");
  const detailDisclosure = pageContent.querySelector<HTMLDetailsElement>("#logs-detail-disclosure");
  const detailSummaryNode = pageContent.querySelector<HTMLElement>("#logs-detail-summary");
  const detailNode = pageContent.querySelector<HTMLPreElement>("#logs-detail");
  const summaryNode = pageContent.querySelector<HTMLElement>("#logs-selection-summary");
  const actionsNode = pageContent.querySelector<HTMLElement>("#logs-selection-actions");
  const tailContextNode = pageContent.querySelector<HTMLElement>("#logs-tail-context");

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
    !streamDiagnostics ||
    !streamDiagnosticsDisclosure ||
    !autoScrollToggle ||
    !detailDisclosure ||
    !detailSummaryNode ||
    !detailNode ||
    !summaryNode ||
    !actionsNode ||
    !tailContextNode
  ) {
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
