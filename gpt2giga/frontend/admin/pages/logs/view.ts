import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import {
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderFilterSelectOptions,
  renderFormSection,
  renderGuideLinks,
  renderPageFrame,
  renderPageSection,
  renderStatLines,
  renderStaticSelectOptions,
} from "../../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber } from "../../utils.js";
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
  const requestPinned = Boolean(filters.requestId);
  const matchingLines = countMatchingLines(rawLogLines, filters);

  return renderPageFrame({
    toolbar: renderLogsToolbar(filters, matchingLines, data.errorEvents.length, data.requestEvents.length),
    stats: [
      kpi("Tail lines", filters.lines || DEFAULT_LINES),
      kpi("Matching lines", matchingLines),
      kpi("Recent errors", data.errorEvents.length),
      kpi("Recent requests", data.requestEvents.length),
    ],
    sections: [
      renderPageSection({
        eyebrow: "Operational Surface",
        title: requestPinned ? "Pinned log workspace" : "Log tail workspace",
        description:
          requestPinned
            ? "Keep one request pinned across rendered tail, extracted ids, and recent structured rows."
            : "Filter the tail, extract one useful request id, and then pin or escalate into Traffic.",
        actions: `
          <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(filters.requestId, filters))}">${escapeHtml(
            requestPinned ? "Open pinned traffic" : "Open traffic summary",
          )}</a>
          <a class="button button--secondary" href="/admin/logs">${escapeHtml(
            requestPinned ? "Reset request pin" : "Reset scope",
          )}</a>
        `,
        bodyClassName: "page-grid",
        body: `
          ${card(
            "Scope controls",
            renderLogsFiltersForm(data, filters),
            "panel panel--span-4 panel--aside",
          )}
          ${card(
            requestPinned ? "Pinned rendered tail" : "Rendered tail",
            `
              <div class="surface surface--dark">
                <div class="stack">
                  <div class="surface__header">
                    <div class="stack">
                      <h4>${escapeHtml(requestPinned ? "Pinned request output" : "Rendered output")}</h4>
                      <p class="muted">${escapeHtml(
                        requestPinned
                          ? "The current request pin filters the rendered tail and keeps the same scope ready for Traffic."
                          : "Use the rendered tail first. Pin a request only after one line or row is clearly relevant.",
                      )}</p>
                    </div>
                    <div class="surface__meta">
                      <span class="pill" id="logs-match-count">${escapeHtml(`${matchingLines} matches`)}</span>
                    </div>
                  </div>
                  <pre class="code-block code-block--tall" id="log-output">${escapeHtml(
                    formatRenderedLogOutput(rawLogLines, filters),
                  )}</pre>
                </div>
              </div>
            `,
            "panel panel--span-8",
          )}
          ${card(
            requestPinned ? "Pinned request context" : "Tail request context",
            `
              <div class="stack">
                <p class="muted">
                  ${escapeHtml(
                    requestPinned
                      ? "Use extracted request ids to confirm the pinned investigation still matches the tail."
                      : "Extract request ids only when they help reopen the same scope in Traffic.",
                  )}
                </p>
                <div id="logs-tail-context">
                  ${renderTailContextTable(buildTailContextRows(rawLogLines, filters, requestLookup, errorLookup), filters)}
                </div>
              </div>
            `,
            "panel panel--span-8",
          )}
          ${card(
            "Selection and live stream",
            `
              <div class="stack">
                ${renderLogsInspector(data, filters, rawLogLines)}
                ${renderLogsStreamPanel(streamState, rawLogLines.length)}
              </div>
            `,
            "panel panel--span-4 panel--aside",
          )}
        `,
      }),
      renderPageSection({
        eyebrow: "Recent Inventory",
        title: requestPinned ? "Pinned request and failure rows" : "Recent request and failure rows",
        description:
          requestPinned
            ? "Use structured rows to validate the same request pin before raw diagnostics."
            : "Compare the current tail scope against recent structured rows before moving back to Traffic.",
        actions: `
          <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(filters.requestId, filters))}">${escapeHtml(
            requestPinned ? "Open pinned traffic" : "Open traffic summary",
          )}</a>
        `,
        bodyClassName: "page-grid",
        body: `
          ${card(
            "Recent requests",
            `
              <div class="stack">
                ${renderRequestRows(data.requestEvents, filters)}
                <p class="field-note">Inspect a row to review one request or reopen Traffic with the same scope.</p>
              </div>
            `,
            "panel panel--span-6",
          )}
          ${card(
            "Recent errors",
            `
              <div class="stack">
                ${renderErrorRows(data.errorEvents, filters)}
                <p class="field-note">Failures stay beside request rows so the same scope can be compared before escalation.</p>
              </div>
            `,
            "panel panel--span-6",
          )}
          ${card(
            "Operator handoff",
            renderGuideLinks(
              [
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
              ],
              {
                compact: true,
                collapsibleSummary: "Operator guides",
                intro: filters.requestId
                  ? "Open only if the pinned request still needs a cross-page handoff."
                  : "Open only if this scope still needs another surface.",
              },
            ),
            "panel panel--span-12",
          )}
        `,
      }),
    ],
  });
}

function renderLogsToolbar(
  filters: LogsFilters,
  matchingLines: string,
  errorCount: number,
  requestCount: number,
): string {
  const activeFilters = summarizeActiveFilters(filters);
  const requestPinned = Boolean(filters.requestId);

  return `
    <div class="toolbar">
      <span class="muted">${escapeHtml(
        requestPinned
          ? "One request is pinned across rendered tail, extracted context, and recent rows."
          : "Keep the tail narrow, then pin one request only when the investigation needs durable scope.",
      )}</span>
    </div>
    <div class="pill-row">
      ${pill(requestPinned ? `Pinned ${filters.requestId}` : `Tail ${filters.lines || DEFAULT_LINES} lines`, requestPinned ? "good" : "default")}
      ${pill(`Matches ${matchingLines}`)}
      ${pill(`Requests ${formatNumber(requestCount)}`)}
      ${pill(`Errors ${formatNumber(errorCount)}`, errorCount ? "warn" : "default")}
      ${activeFilters ? pill(`Scope ${activeFilters}`) : pill("No event filters")}
    </div>
  `;
}

function renderLogsFiltersForm(data: LogsPageData, filters: LogsFilters): string {
  return `
    <form id="logs-filters-form" class="form-shell form-shell--compact">
      <div class="form-shell__intro">
        <p class="muted">
          Tail window, request pin, and recent event scope stay linked.
        </p>
      </div>
      ${renderFormSection({
        title: "Tail window",
        intro: "Set the rendered window before inspecting requests.",
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
        intro: "Pin one request only when Logs and Traffic should stay aligned.",
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
                The request pin drives rendered tail filtering, recent rows, and Traffic handoff together.
              </p>
            </div>
          </div>
        `,
      })}
      ${renderFormSection({
        title: "Event scope",
        intro: "Keep recent request and error rows on the same scope.",
        body: `
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
            <span class="muted">The same scope powers recent rows and Traffic handoff.</span>
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

function renderLogsInspector(data: LogsPageData, filters: LogsFilters, rawLogLines: string[]): string {
  return `
    <div class="stack">
      ${renderFormSection({
        title: "Current posture",
        intro: "Read this scope before opening raw payloads or restarting the live stream.",
        body: renderStatLines(
          [
            { label: "Tail lines loaded", value: String(rawLogLines.length) },
            { label: "Matching lines", value: countMatchingLines(rawLogLines, filters) },
            { label: "Request rows", value: String(data.requestEvents.length) },
            { label: "Error rows", value: String(data.errorEvents.length) },
            { label: "Pinned request", value: filters.requestId || "none" },
          ],
          "No log posture is available.",
        ),
      })}
      ${renderFormSection({
        title: "Selection and handoff",
        intro: "Inspect one selected request or failure, then decide whether to pin or hand off.",
        body: `
          <div id="logs-selection-summary">
            ${renderDefinitionList(
              [
                { label: "Selection", value: "No context selected" },
                { label: "Filters", value: summarizeActiveFilters(filters) || "No event filters" },
                {
                  label: "Request scope",
                  value: filters.requestId || "Recent log window",
                  note: filters.requestId
                    ? "Tail and recent panels stay pinned to one request."
                    : "Pick a tail-derived request line or recent row.",
                },
              ],
              "No event selected yet.",
            )}
          </div>
          <div class="toolbar" id="logs-selection-actions">
            ${renderLogSelectionActions(null, filters)}
          </div>
        `,
      })}
      <details class="details-disclosure" id="logs-detail-disclosure">
        <summary id="logs-detail-summary">Current scope snapshot</summary>
        <p class="field-note">
          Open only if the posture summary is not enough.
        </p>
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
  `;
}

function renderLogsStreamPanel(streamState: ReturnType<typeof createLogsStreamState>, rawLineCount: number): string {
  return `
    <div class="surface">
      <div class="stack">
        <div class="surface__header">
          <div class="stack">
            <h4>Live tail status</h4>
            <p class="muted">Open SSE only after the working scope is narrow enough to be useful.</p>
          </div>
          <div class="surface__meta" id="logs-stream-status">${renderStreamPill("idle")}</div>
        </div>
        <div class="toolbar">
          <label class="checkbox-field">
            <input id="logs-auto-scroll" type="checkbox" checked />
            <span>Auto-scroll while streaming</span>
          </label>
          <button class="button button--secondary" id="clear-log-output" type="button">Clear buffer</button>
          <span class="muted" id="logs-stream-note">Tail buffer loaded from disk.</span>
        </div>
        <details class="details-disclosure" id="logs-stream-diagnostics-disclosure">
          <summary>Live stream diagnostics</summary>
          <p class="field-note">
            Open only when the SSE lifecycle needs debugging.
          </p>
          <div id="logs-stream-diagnostics">
            ${renderDefinitionList(buildStreamDiagnostics(streamState, rawLineCount))}
          </div>
        </details>
      </div>
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
