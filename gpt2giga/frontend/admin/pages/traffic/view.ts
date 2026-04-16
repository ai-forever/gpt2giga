import { pathForPage, subpagesFor } from "../../routes.js";
import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import {
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderFilterSelectOptions,
  renderFormSection,
  renderGuideLinks,
  renderStaticSelectOptions,
  renderStatLines,
  renderSubpageNav,
  renderWorkflowCard,
} from "../../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber, formatTimestamp } from "../../utils.js";
import type { TrafficPageData } from "./api.js";
import {
  buildLogsUrlForRequest,
  buildTrafficScopeSummary,
  buildTrafficSelectionSummary,
  buildTrafficUrl,
  renderErrorRows,
  renderRequestRows,
  renderTrafficSelectionActions,
  renderUsageKeyRows,
  renderUsageProviderRows,
} from "./serializers.js";
import type { TrafficFilters, TrafficPage } from "./state.js";

const PREVIEW_LIMIT = 4;

export interface TrafficPageElements {
  actionNode: HTMLElement;
  detailDisclosure: HTMLDetailsElement;
  detailSummaryNode: HTMLElement;
  detailNode: HTMLPreElement;
  filtersForm: HTMLFormElement;
  resetButton: HTMLButtonElement;
  summaryNode: HTMLElement;
}

export function renderTrafficHeroActions(page: TrafficPage, filters: TrafficFilters): string {
  const logsHref = buildLogsUrlForRequest(filters.requestId, filters);
  const logsLabel = filters.requestId ? "Open pinned logs" : "Open logs with current filters";

  if (page === "traffic") {
    return `
      <button class="button button--secondary" id="reset-traffic-filters" type="button">Reset filters</button>
      <a class="button" href="${escapeHtml(logsHref)}">
        ${escapeHtml(logsLabel)}
      </a>
    `;
  }

  return `
    <button class="button button--secondary" id="reset-traffic-filters" type="button">Reset filters</button>
    <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic"))}">
      Open traffic summary
    </a>
    <a class="button" href="${escapeHtml(page === "traffic-usage" ? buildTrafficUrl(filters, "traffic-requests") : logsHref)}">
      ${escapeHtml(page === "traffic-usage" ? "Open requests" : logsLabel)}
    </a>
  `;
}

export function renderTrafficPage(
  page: TrafficPage,
  data: TrafficPageData,
  filters: TrafficFilters,
): string {
  const requestPinned = Boolean(filters.requestId);
  const scopeSummary = buildTrafficScopeSummary(
    filters,
    data.requestEvents,
    data.errorEvents,
    data.providerEntries,
    data.providerSummary,
  );

  return `
    ${kpi(requestPinned ? "Pinned requests" : "Requests", formatNumber(scopeSummary.requestCount))}
    ${kpi(requestPinned ? "Pinned errors" : "Errors", formatNumber(scopeSummary.errorCount))}
    ${kpi(requestPinned ? "Pinned tokens" : "Tokens", formatNumber(scopeSummary.totalTokens))}
    ${kpi(requestPinned ? "Pinned providers" : "Providers", formatNumber(scopeSummary.providerCount))}
    ${card(
      "Traffic navigation",
      renderTrafficNavigation(page, filters),
      "panel panel--span-12",
    )}
    ${renderTrafficSurface(page, data, filters, requestPinned)}
  `;
}

function renderTrafficSurface(
  page: TrafficPage,
  data: TrafficPageData,
  filters: TrafficFilters,
  requestPinned: boolean,
): string {
  if (page === "traffic-requests") {
    return renderTrafficRequestsPage(data, filters, requestPinned);
  }
  if (page === "traffic-errors") {
    return renderTrafficErrorsPage(data, filters, requestPinned);
  }
  if (page === "traffic-usage") {
    return renderTrafficUsagePage(data, filters, requestPinned);
  }
  return renderTrafficOverviewPage(data, filters, requestPinned);
}

function renderTrafficNavigation(page: TrafficPage, filters: TrafficFilters): string {
  return renderSubpageNav({
    currentPage: page,
    title: "Traffic pages",
    intro:
      page === "traffic"
        ? "Keep the hub summary-first. Open requests, errors, or usage only when one lane becomes the real task."
        : page === "traffic-requests"
          ? "This page stays request-first. Keep request review here, then escalate into Logs only when raw line context is actually needed."
          : page === "traffic-errors"
            ? "This page stays failure-first. Review error patterns here before jumping into raw logs."
            : "This page stays usage-first. Keep provider and key rollups together without the request and error tables competing for space.",
    items: subpagesFor(page),
    hrefForPage: (target) => buildTrafficUrl(filters, target as TrafficPage),
  });
}

function renderTrafficOverviewPage(
  data: TrafficPageData,
  filters: TrafficFilters,
  requestPinned: boolean,
): string {
  return `
    ${card(
      requestPinned ? "Pinned traffic workflow" : "Summary-first observe workflow",
      renderTrafficWorkflowGuide(filters, requestPinned),
      "panel panel--span-12",
    )}
    ${card(
      "Traffic filters",
      renderTrafficFilters(data, filters, "overview"),
      "panel panel--span-12 panel--measure",
    )}
    ${card(
      "Requests lane",
      renderTrafficPreviewLane({
        title: "Recent request sample",
        intro:
          "Keep the overview broad. Open the requests page when request review becomes the primary operator task.",
        rows: renderRequestPreviewRows(data.requestEvents, filters),
        stats: [
          { label: "Rows in scope", value: formatNumber(data.requestEvents.length) },
          { label: "Pinned request", value: filters.requestId || "none" },
        ],
        primaryHref: buildTrafficUrl(filters, "traffic-requests"),
        primaryLabel: "Open requests",
        secondaryHref: buildLogsUrlForRequest(filters.requestId, filters),
        secondaryLabel: "Open logs",
      }),
      "panel panel--span-4",
    )}
    ${card(
      "Errors lane",
      renderTrafficPreviewLane({
        title: "Recent error sample",
        intro:
          "Use the focused errors page when failure triage needs more than a short summary sample.",
        rows: renderErrorPreviewRows(data.errorEvents, filters),
        stats: [
          { label: "Rows in scope", value: formatNumber(data.errorEvents.length) },
          {
            label: "Error types",
            value: formatNumber(
              new Set(
                data.errorEvents
                  .map((item) => String(item.error_type ?? "").trim())
                  .filter(Boolean),
              ).size,
            ),
          },
        ],
        primaryHref: buildTrafficUrl(filters, "traffic-errors"),
        primaryLabel: "Open errors",
        secondaryHref: buildTrafficUrl(filters, "traffic-requests"),
        secondaryLabel: "Open requests",
      }),
      "panel panel--span-4",
    )}
    ${card(
      "Usage lane",
      renderTrafficPreviewLane({
        title: "Aggregate usage sample",
        intro:
          "Stay on the hub until one provider or key grouping stands out. Use the focused usage page only when grouped rollups become the main question.",
        rows: renderUsagePreviewRows(data.providerEntries),
        stats: [
          {
            label: "Provider rows",
            value: formatNumber(data.providerEntries.length),
          },
          { label: "Key rows", value: formatNumber(data.keyEntries.length) },
        ],
        primaryHref: buildTrafficUrl(filters, "traffic-usage"),
        primaryLabel: "Open usage",
        secondaryHref: buildTrafficUrl(filters, "traffic-requests"),
        secondaryLabel: "Open requests",
      }),
      "panel panel--span-4",
    )}
    ${card(
      "Current scope and handoff",
      renderTrafficInspector({
        filters,
        summaryIntro:
          requestPinned
            ? "The overview is already pinned to one request id. Keep the hub for high-level context, then open a focused child page only when that lane becomes the real task."
            : "Use this summary to confirm the current filter posture. The raw payload snapshot stays secondary until a focused child page or Logs is actually needed.",
        statItems: [
          { label: "Request rows", value: formatNumber(data.requestEvents.length) },
          { label: "Error rows", value: formatNumber(data.errorEvents.length) },
          { label: "Usage providers", value: formatNumber(data.providerEntries.length) },
          { label: "Usage keys", value: formatNumber(data.keyEntries.length) },
        ],
        emptySelectionMessage:
          "No request, error, or usage row is selected on the summary page.",
        rawPayload: {
          active_filters: filters,
          usage_summary: data.providerSummary,
        },
      }),
      "panel panel--span-12",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
          {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Follow the summary-first request workflow and know when to stay broad versus when to pin one request.",
          },
          {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Open this once the traffic surface already narrowed the issue to one request or one failure pattern.",
          },
          {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the escalation map when the current traffic lane still does not clearly point at the next surface.",
          },
        ],
        "Keep the hub lightweight. The longer guides only matter after one traffic lane already exposed the next diagnostic question.",
      ),
      "panel panel--span-12",
    )}
  `;
}

function renderTrafficRequestsPage(
  data: TrafficPageData,
  filters: TrafficFilters,
  requestPinned: boolean,
): string {
  return `
    ${card(
      "Request filters",
      renderTrafficFilters(data, filters, "requests"),
      "panel panel--span-12 panel--measure",
    )}
    ${card(
      "Recent requests",
      renderRequestRows(data.requestEvents, filters),
      "panel panel--span-8",
    )}
    ${card(
      "Request inspector and handoff",
      renderTrafficInspector({
        filters,
        summaryIntro:
          requestPinned
            ? "The request feed is already pinned. Compare the selected request against the matching recent error and escalate into Logs only if raw line-by-line evidence is still required."
            : "Select one request row to inspect payload, pin it, and reopen Logs with the same request id and compatible filters already applied.",
        statItems: [
          { label: "Request rows", value: formatNumber(data.requestEvents.length) },
          { label: "Error companions", value: formatNumber(data.errorEvents.length) },
          {
            label: "Providers in scope",
            value: formatNumber(
              new Set(
                data.requestEvents
                  .map((item) => String(item.provider ?? "").trim())
                  .filter(Boolean),
              ).size,
            ),
          },
          { label: "Pinned request", value: filters.requestId || "none" },
        ],
        rawPayload: {
          active_filters: filters,
          usage_summary: data.providerSummary,
        },
      }),
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Companion failure lane",
      `
        <div class="stack">
          <p class="muted">
            Keep this page request-first. Use the focused errors page only when recent failures, not successful request flow, become the main diagnostic question.
          </p>
          ${renderErrorPreviewRows(data.errorEvents, filters)}
          <div class="toolbar">
            <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Open errors</a>
            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic"))}">Open traffic summary</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
          {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Use the request-first checklist when the main question is which request deserves pinning.",
          },
          {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Escalate here only after one request row already proved that raw logs are the next step.",
          },
        ],
        "This focused page is for request review and handoff. The longer guides stay secondary until one request already stands out.",
      ),
      "panel panel--span-12",
    )}
  `;
}

function renderTrafficErrorsPage(
  data: TrafficPageData,
  filters: TrafficFilters,
  requestPinned: boolean,
): string {
  return `
    ${card(
      "Error filters",
      renderTrafficFilters(data, filters, "errors"),
      "panel panel--span-12 panel--measure",
    )}
    ${card(
      "Recent errors",
      renderErrorRows(data.errorEvents, filters),
      "panel panel--span-8",
    )}
    ${card(
      "Error inspector and handoff",
      renderTrafficInspector({
        filters,
        summaryIntro:
          requestPinned
            ? "The failure feed is already pinned to one request id. Inspect the selected failure here first, then open Logs only if the remaining question is line-level evidence."
            : "Select one error row to inspect payload, compare the matching request when available, and pin the request only if the failure now needs a request-scoped follow-up.",
        statItems: [
          { label: "Error rows", value: formatNumber(data.errorEvents.length) },
          {
            label: "Request companions",
            value: formatNumber(data.requestEvents.length),
          },
          {
            label: "Error types",
            value: formatNumber(
              new Set(
                data.errorEvents
                  .map((item) => String(item.error_type ?? "").trim())
                  .filter(Boolean),
              ).size,
            ),
          },
          { label: "Pinned request", value: filters.requestId || "none" },
        ],
        rawPayload: {
          active_filters: filters,
          usage_summary: data.providerSummary,
        },
      }),
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Companion request lane",
      `
        <div class="stack">
          <p class="muted">
            Keep this page failure-first. Move back to the requests page when recent healthy and unhealthy requests need to be compared in one place.
          </p>
          ${renderRequestPreviewRows(data.requestEvents, filters)}
          <div class="toolbar">
            <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-requests"))}">Open requests</a>
            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic"))}">Open traffic summary</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
          {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Use the error-first path when the main question is which failure pattern deserves request pinning.",
          },
          {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Open this when the error row is already isolated and only raw log evidence is missing.",
          },
        ],
        "This focused page is for failure triage. The longer playbooks stay secondary until one error pattern is clearly isolated.",
      ),
      "panel panel--span-12",
    )}
  `;
}

function renderTrafficUsagePage(
  data: TrafficPageData,
  filters: TrafficFilters,
  requestPinned: boolean,
): string {
  return `
    ${card(
      "Usage filters",
      renderTrafficFilters(data, filters, "usage"),
      "panel panel--span-12 panel--measure",
    )}
    ${card(
      "Usage by provider",
      `
        <div class="stack">
          <p class="muted">
            Keep grouped provider totals primary here. Use key-level breakdown only after provider totals already show where the traffic spike or cost concentration lives.
          </p>
          ${renderUsageProviderRows(data.providerEntries)}
        </div>
      `,
      "panel panel--span-8",
    )}
    ${card(
      "Usage inspector and handoff",
      renderTrafficInspector({
        filters,
        summaryIntro:
          requestPinned
            ? "Request pinning still affects only recent request and error feeds. Keep this page usage-first and treat the pinned request as a secondary breadcrumb back into the request lane."
            : "Select one provider or key row to inspect aggregate payload. Move back to requests only when grouped usage already exposed the provider or key that needs request-level evidence.",
        statItems: [
          {
            label: "Provider rows",
            value: formatNumber(data.providerEntries.length),
          },
          { label: "Key rows", value: formatNumber(data.keyEntries.length) },
          {
            label: "Successful requests",
            value: formatNumber(data.providerSummary.success_count ?? 0),
          },
          {
            label: "Errored requests",
            value: formatNumber(data.providerSummary.error_count ?? 0),
          },
        ],
        rawPayload: {
          active_filters: filters,
          usage_summary: data.providerSummary,
        },
        emptySelectionMessage:
          "Select one provider or API-key row to inspect aggregate usage payload.",
      }),
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Usage by key",
      `
        ${requestPinned ? '<div class="banner banner--warn">Request pinning narrows recent request and error feeds only. Usage rows stay aggregate and continue following provider, model, key, and source filters.</div>' : ""}
        ${renderUsageKeyRows(data.keyEntries)}
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Return to request evidence only when needed",
      `
        <div class="step-grid">
          ${renderWorkflowCard({
            workflow: "observe",
            title: "Move into request review after one provider stands out",
            note: "Use the requests page when grouped usage already exposed the provider, key, or model that now needs request-level evidence.",
            pills: [pill("Requests"), pill("Pinned request"), pill("Logs")],
            actions: [
              {
                label: "Open requests",
                href: buildTrafficUrl(filters, "traffic-requests"),
                primary: true,
              },
              { label: "Open traffic summary", href: buildTrafficUrl(filters, "traffic") },
            ],
          })}
          ${renderWorkflowCard({
            workflow: "diagnose",
            title: "Escalate into logs only after request scope exists",
            note: "Logs are still downstream from usage. Keep the grouped rollups primary until one request or failure lane is actually identified.",
            pills: [pill("Usage first"), pill("Logs later"), pill("Request scoped")],
            actions: [
              {
                label: "Open errors",
                href: buildTrafficUrl(filters, "traffic-errors"),
                primary: true,
              },
              { label: "Open logs", href: buildLogsUrlForRequest(filters.requestId, filters) },
            ],
          })}
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
          {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Use the grouped-usage path when the first question is where the traffic went before picking one request.",
          },
          {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Open the escalation map once grouped usage already pointed at the next request or provider surface.",
          },
        ],
        "This focused page is for grouped usage review. The guides matter only after one provider or key grouping already became the real issue.",
      ),
      "panel panel--span-12",
    )}
  `;
}

function renderTrafficFilters(
  data: TrafficPageData,
  filters: TrafficFilters,
  variant: "overview" | "requests" | "errors" | "usage",
): string {
  const requestFilterOptions = asRecord(data.requestsPayload.available_filters);
  const errorFilterOptions = asRecord(data.errorsPayload.available_filters);
  const usageKeyFilterOptions = asRecord(data.usageKeysPayload.available_filters);
  const usageProviderFilterOptions = asRecord(data.usageProvidersPayload.available_filters);

  const providerOptions = [
    ...asArray<unknown>(requestFilterOptions.provider),
    ...asArray<unknown>(errorFilterOptions.provider),
    ...asArray<unknown>(usageKeyFilterOptions.provider),
    ...asArray<unknown>(usageProviderFilterOptions.provider),
  ];
  const modelOptions = [
    ...asArray<unknown>(requestFilterOptions.model),
    ...asArray<unknown>(errorFilterOptions.model),
    ...asArray<unknown>(usageKeyFilterOptions.model),
    ...asArray<unknown>(usageProviderFilterOptions.model),
  ];

  const intro =
    variant === "overview"
      ? "Keep the hub filters broad. The focused child pages exist so request, error, and usage drill-down do not have to share the same screen."
      : variant === "requests"
        ? "Keep this form request-centric: route, model, and request id narrowing belong here; grouped usage drill-down does not."
        : variant === "errors"
          ? "Keep this form failure-centric: error type, route, and request id narrowing belong here before any raw-log escalation."
          : "Keep this form usage-centric: provider, model, key source, and key name narrowing belong here before dropping back into request evidence.";

  const primarySection =
    variant === "usage"
      ? `
          <div class="triple-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderFilterSelectOptions(filters.provider, providerOptions)}
              </select>
            </label>
            <label class="field">
              <span>Model</span>
              <select name="model">
                ${renderFilterSelectOptions(filters.model, modelOptions)}
              </select>
            </label>
            <label class="field">
              <span>Limit</span>
              <select name="limit">
                ${renderStaticSelectOptions(filters.limit, ["10", "25", "50", "100"])}
              </select>
            </label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Key source</span>
              <select name="source">
                ${renderFilterSelectOptions(
                  filters.source,
                  asArray<unknown>(usageKeyFilterOptions.source),
                )}
              </select>
            </label>
            <label class="field">
              <span>API key name</span>
              <select name="api_key_name">
                ${renderFilterSelectOptions(
                  filters.apiKeyName,
                  asArray<unknown>(usageProviderFilterOptions.api_key_name),
                )}
              </select>
            </label>
          </div>
        `
      : `
          <div class="triple-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderFilterSelectOptions(filters.provider, providerOptions)}
              </select>
            </label>
            <label class="field">
              <span>Model</span>
              <select name="model">
                ${renderFilterSelectOptions(filters.model, modelOptions)}
              </select>
            </label>
            <label class="field">
              <span>Limit</span>
              <select name="limit">
                ${renderStaticSelectOptions(filters.limit, ["10", "25", "50", "100"])}
              </select>
            </label>
          </div>
          <div class="triple-grid">
            <label class="field">
              <span>Endpoint</span>
              <select name="endpoint">
                ${renderFilterSelectOptions(
                  filters.endpoint,
                  asArray<unknown>(requestFilterOptions.endpoint),
                )}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderFilterSelectOptions(
                  filters.method,
                  asArray<unknown>(requestFilterOptions.method),
                )}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderFilterSelectOptions(
                  filters.statusCode,
                  [
                    ...asArray<unknown>(requestFilterOptions.status_code),
                    ...asArray<unknown>(errorFilterOptions.status_code),
                  ],
                )}
              </select>
            </label>
          </div>
          ${
            variant === "requests"
              ? ""
              : `
                <div class="dual-grid">
                  <label class="field">
                    <span>Error type</span>
                    <select name="error_type">
                      ${renderFilterSelectOptions(
                        filters.errorType,
                        asArray<unknown>(errorFilterOptions.error_type),
                      )}
                    </select>
                  </label>
                  <div class="surface">
                    <p class="muted">
                      ${escapeHtml(
                        variant === "overview"
                          ? "The hub keeps error-type filtering available, but open the focused errors page once failure analysis stops being summary-first."
                          : "Keep error-type narrowing here, then move into Logs only after one failure row already proved that raw evidence is the next step.",
                      )}
                    </p>
                  </div>
                </div>
              `
          }
        `;

  return `
    <form id="traffic-filters-form" class="form-shell form-shell--compact">
      <div class="form-shell__intro">
        <p class="muted">${escapeHtml(intro)}</p>
      </div>
      ${renderFormSection({
        title:
          variant === "overview"
            ? "Shared traffic scope"
            : variant === "requests"
              ? "Request traffic scope"
              : variant === "errors"
                ? "Error traffic scope"
                : "Usage traffic scope",
        intro:
          variant === "overview"
            ? "These filters stay shared across the traffic family so child pages can open with the same current scope."
            : variant === "usage"
              ? "Usage filters stay aggregate even when recent request and error feeds are pinned to one request id elsewhere."
              : "Request pinning follows the current filters so Logs can reopen with the same compatible scope.",
        body: primarySection,
      })}
      ${renderFormSection({
        title: "Request pinning",
        intro:
          variant === "usage"
            ? "Request id remains secondary here. It affects request and error lanes more than grouped usage, but keeping it visible preserves handoff consistency."
            : "Use request pinning when the next step is correlating recent rows with the same request id across traffic and Logs.",
        body: `
          <div class="dual-grid">
            <label class="field">
              <span>Request id</span>
              <input
                name="request_id"
                value="${escapeHtml(filters.requestId)}"
                placeholder="Pin one request across traffic and logs"
              />
            </label>
            <div class="surface">
              <p class="muted">
                ${escapeHtml(
                  variant === "usage"
                    ? "Grouped usage rows stay aggregate even when a request id is pinned. Use the focused requests or errors page for request-level inspection."
                    : "Pinned request ids keep request and error review coherent and make the Logs handoff predictable without starting in raw output.",
                )}
              </p>
            </div>
          </div>
        `,
      })}
      <div class="toolbar">
        <button class="button" type="submit">Apply filters</button>
        <span class="muted">The same scope carries across the traffic family and into Logs handoff links.</span>
      </div>
    </form>
  `;
}

function renderTrafficInspector(options: {
  emptySelectionMessage?: string;
  filters: TrafficFilters;
  rawPayload: Record<string, unknown>;
  statItems: { label: string; value: string }[];
  summaryIntro: string;
}): string {
  return `
    <div class="stack">
      <p class="muted">${escapeHtml(options.summaryIntro)}</p>
      ${renderStatLines(options.statItems, "No traffic rows are loaded yet.")}
      <div id="traffic-selection-summary">
        ${renderDefinitionList(
          buildTrafficSelectionSummary(options.filters),
          options.emptySelectionMessage ?? "Select a request, error, or usage row.",
        )}
      </div>
      <div class="toolbar" id="traffic-selection-actions">
        ${renderTrafficSelectionActions(
          { requestId: null, counterpartKind: null, counterpartIndex: null },
          options.filters,
        )}
      </div>
      <details class="details-disclosure" id="traffic-detail-disclosure">
        <summary id="traffic-detail-summary">Raw payload snapshot</summary>
        <pre class="code-block code-block--tall" id="traffic-detail">${escapeHtml(
          JSON.stringify(options.rawPayload, null, 2),
        )}</pre>
      </details>
    </div>
  `;
}

function renderTrafficWorkflowGuide(filters: TrafficFilters, requestPinned: boolean): string {
  const logsHref = buildLogsUrlForRequest(filters.requestId, filters);
  return `
    <div class="step-grid">
      ${renderWorkflowCard({
        workflow: "observe",
        title: requestPinned
          ? "Stay scoped to one request"
          : "Stay broad until one lane stands out",
        note: requestPinned
          ? "Traffic is already pinned to one request id. Use the focused request or error page only when one lane becomes the main task."
          : "Keep the overview broad first: requests, errors, and usage stay visible together so you can choose the right focused page before escalating.",
        pills: [
          pill("Overview"),
          pill(requestPinned ? "Pinned request" : "Summary first"),
          pill("Focused lanes"),
        ],
        actions: [
          {
            label: "Open requests",
            href: buildTrafficUrl(filters, "traffic-requests"),
            primary: true,
          },
          { label: "Open errors", href: buildTrafficUrl(filters, "traffic-errors") },
        ],
      })}
      ${renderWorkflowCard({
        workflow: "diagnose",
        title: requestPinned
          ? "Escalate only when raw context is needed"
          : "Open Logs only after one request exists",
        note: requestPinned
          ? "Use Logs when the pinned request now needs raw line evidence, live tail correlation, or downstream trace context."
          : "Logs stay downstream from traffic. Pick the lane first, then pin one request before escalating to raw output.",
        pills: [pill("Logs"), pill("Request scoped"), pill("Raw evidence")],
        actions: [
          {
            label: requestPinned ? "Open pinned logs" : "Open logs with current filters",
            href: logsHref,
            primary: true,
          },
          { label: "Open usage", href: buildTrafficUrl(filters, "traffic-usage") },
        ],
      })}
    </div>
  `;
}

function renderTrafficPreviewLane(options: {
  intro: string;
  primaryHref: string;
  primaryLabel: string;
  rows: string;
  secondaryHref: string;
  secondaryLabel: string;
  stats: { label: string; value: string }[];
  title: string;
}): string {
  return `
    <div class="stack">
      <p class="muted">${escapeHtml(options.intro)}</p>
      ${renderStatLines(options.stats)}
      ${renderFormSection({
        title: options.title,
        body: options.rows,
      })}
      <div class="toolbar">
        <a class="button" href="${escapeHtml(options.primaryHref)}">${escapeHtml(options.primaryLabel)}</a>
        <a class="button button--secondary" href="${escapeHtml(options.secondaryHref)}">${escapeHtml(options.secondaryLabel)}</a>
      </div>
    </div>
  `;
}

function renderRequestPreviewRows(events: Record<string, unknown>[], filters: TrafficFilters): string {
  if (!events.length) {
    return '<p class="muted">No recent requests matched the current traffic scope.</p>';
  }

  return events
    .slice(0, PREVIEW_LIMIT)
    .map((event) => {
      const requestId = String(event.request_id ?? "").trim();
      const route = `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`;
      const logsHref = requestId ? buildLogsUrlForRequest(requestId, filters) : pathForPage("logs");

      return `
        <article class="surface">
          <div class="stack">
            <div class="stat-line">
              <span class="muted">${escapeHtml(formatTimestamp(event.created_at))}</span>
              ${pill(String(event.status_code ?? "n/a"), Number(event.status_code ?? 0) >= 400 ? "warn" : "good")}
            </div>
            <div class="stack">
              <strong>${escapeHtml(String(event.provider ?? "unknown"))}</strong>
              <p class="muted">${escapeHtml(route)}</p>
              <p class="muted">${escapeHtml(requestId || "no request id")}</p>
            </div>
            <div class="toolbar">
              <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl({ ...filters, requestId }, "traffic-requests"))}">Focus request</a>
              <a class="button button--secondary" href="${escapeHtml(logsHref)}">Open logs</a>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderErrorPreviewRows(events: Record<string, unknown>[], filters: TrafficFilters): string {
  if (!events.length) {
    return '<p class="muted">No recent errors matched the current traffic scope.</p>';
  }

  return events
    .slice(0, PREVIEW_LIMIT)
    .map((event) => {
      const requestId = String(event.request_id ?? "").trim();
      const route = `${String(event.method ?? "GET")} ${String(event.endpoint ?? event.path ?? "n/a")}`;
      const logsHref = requestId ? buildLogsUrlForRequest(requestId, filters) : pathForPage("logs");

      return `
        <article class="surface">
          <div class="stack">
            <div class="stat-line">
              <span class="muted">${escapeHtml(formatTimestamp(event.created_at))}</span>
              ${pill(String(event.error_type ?? "HTTP error"), "warn")}
            </div>
            <div class="stack">
              <strong>${escapeHtml(route)}</strong>
              <p class="muted">${escapeHtml(String(event.provider ?? "unknown"))}</p>
              <p class="muted">${escapeHtml(requestId || "no request id")}</p>
            </div>
            <div class="toolbar">
              <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl({ ...filters, requestId }, "traffic-errors"))}">Focus error</a>
              <a class="button button--secondary" href="${escapeHtml(logsHref)}">Open logs</a>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderUsagePreviewRows(entries: Record<string, unknown>[]): string {
  if (!entries.length) {
    return '<p class="muted">No provider usage rows matched the current traffic scope.</p>';
  }

  return entries
    .slice(0, PREVIEW_LIMIT)
    .map((entry) => {
      const apiKeys = Object.keys(asRecord(entry.api_keys));
      const models = Object.keys(asRecord(entry.models));
      return `
        <article class="surface">
          <div class="stack">
            <div class="stat-line">
              <span class="muted">${escapeHtml(String(entry.provider ?? "unknown"))}</span>
              ${pill(formatNumber(entry.total_tokens ?? 0))}
            </div>
            <p class="muted">
              ${escapeHtml(
                `${formatNumber(entry.request_count ?? 0)} requests · ${formatNumber(entry.error_count ?? 0)} errors`,
              )}
            </p>
            <p class="muted">
              ${escapeHtml(
                `${apiKeys.length} keys · ${models.length} models`,
              )}
            </p>
          </div>
        </article>
      `;
    })
    .join("");
}

export function resolveTrafficElements(pageContent: HTMLElement): TrafficPageElements | null {
  const detailDisclosure = pageContent.querySelector<HTMLDetailsElement>("#traffic-detail-disclosure");
  const detailSummaryNode = pageContent.querySelector<HTMLElement>("#traffic-detail-summary");
  const detailNode = pageContent.querySelector<HTMLPreElement>("#traffic-detail");
  const filtersForm = pageContent.querySelector<HTMLFormElement>("#traffic-filters-form");
  const summaryNode = pageContent.querySelector<HTMLElement>("#traffic-selection-summary");
  const actionNode = pageContent.querySelector<HTMLElement>("#traffic-selection-actions");
  const resetButton = document.getElementById("reset-traffic-filters") as HTMLButtonElement | null;

  if (
    !detailDisclosure ||
    !detailSummaryNode ||
    !detailNode ||
    !filtersForm ||
    !summaryNode ||
    !actionNode ||
    !resetButton
  ) {
    return null;
  }

  return {
    actionNode,
    detailDisclosure,
    detailSummaryNode,
    detailNode,
    filtersForm,
    resetButton,
    summaryNode,
  };
}
