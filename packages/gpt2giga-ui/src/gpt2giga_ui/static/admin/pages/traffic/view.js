import { pathForPage, subpagesFor } from "../../routes.js";
import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import { card, kpi, pill, renderDefinitionList, renderFilterSelectOptions, renderFormSection, renderGuideLinks, renderPageFrame, renderPageSection, renderStaticSelectOptions, renderStatLines, renderSubpageNav, } from "../../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber, formatTimestamp } from "../../utils.js";
import { buildLogsUrlForRequest, buildTrafficScopeSummary, buildTrafficSelectionSummary, buildTrafficUrl, renderErrorRows, renderRequestRows, renderTrafficSelectionActions, renderUsageKeyRows, renderUsageProviderRows, summarizeTrafficFilters, } from "./serializers.js";
const PREVIEW_LIMIT = 4;
export function renderTrafficHeroActions(page, filters) {
    const logsHref = buildLogsUrlForRequest(filters.requestId, filters);
    const logsLabel = filters.requestId ? "Open pinned logs" : "Open logs with current filters";
    if (page === "traffic") {
        return `
      <button class="button button--secondary" id="reset-traffic-filters" type="button">Reset filters</button>
      <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-requests"))}">Open requests</a>
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Open errors</a>
      <a class="button button--secondary" href="${escapeHtml(logsHref)}">${escapeHtml(logsLabel)}</a>
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
export function renderTrafficPage(page, data, filters) {
    const requestPinned = Boolean(filters.requestId);
    const scopeSummary = buildTrafficScopeSummary(filters, data.requestEvents, data.errorEvents, data.providerEntries, data.providerSummary);
    return renderPageFrame({
        toolbar: renderTrafficToolbar(page, filters, scopeSummary, requestPinned),
        stats: [
            kpi(requestPinned ? "Pinned requests" : "Requests", formatNumber(scopeSummary.requestCount)),
            kpi(requestPinned ? "Pinned errors" : "Errors", formatNumber(scopeSummary.errorCount)),
            kpi(requestPinned ? "Pinned tokens" : "Tokens", formatNumber(scopeSummary.totalTokens)),
            kpi(requestPinned ? "Pinned providers" : "Providers", formatNumber(scopeSummary.providerCount)),
        ],
        sections: [
            renderPageSection({
                eyebrow: page === "traffic" ? "Operational Surface" : "Operational Lane",
                title: resolveTrafficTitle(page),
                description: page === "traffic"
                    ? "Start with filters and recent requests, then drill into errors or usage only when the scope is clear."
                    : page === "traffic-usage"
                        ? "Grouped usage stays aggregate while provider and key tables stay visible."
                        : "Keep filters, the primary table, and the inspector on one surface.",
                actions: renderTrafficSectionActions(page, filters),
                bodyClassName: "page-grid",
                body: renderTrafficSurface(page, data, filters, requestPinned),
            }),
        ],
    });
}
function renderTrafficToolbar(page, filters, scopeSummary, requestPinned) {
    return `
    ${renderSubpageNav({
        currentPage: page,
        title: "Traffic",
        intro: requestPinned
            ? "One request is pinned across requests, errors, and logs."
            : "Switch lanes without losing scope.",
        items: subpagesFor(page),
        hrefForPage: (target) => buildTrafficUrl(filters, target),
    })}
    <div class="pill-row">
      ${pill(requestPinned ? `Pinned ${filters.requestId}` : "Recent traffic window", requestPinned ? "good" : "default")}
      ${pill(`Requests ${formatNumber(scopeSummary.requestCount)}`)}
      ${pill(`Errors ${formatNumber(scopeSummary.errorCount)}`, scopeSummary.errorCount ? "warn" : "default")}
      ${pill(`Tokens ${formatNumber(scopeSummary.totalTokens)}`)}
      ${pill(`Providers ${formatNumber(scopeSummary.providerCount)}`)}
    </div>
  `;
}
function resolveTrafficTitle(page) {
    if (page === "traffic-requests") {
        return "Request inventory";
    }
    if (page === "traffic-errors") {
        return "Error inventory";
    }
    if (page === "traffic-usage") {
        return "Usage inventory";
    }
    return "Traffic inventory";
}
function renderTrafficSectionActions(page, filters) {
    if (page === "traffic") {
        return `
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Error lane</a>
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-usage"))}">Usage lane</a>
      <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(filters.requestId, filters))}">Logs</a>
    `;
    }
    if (page === "traffic-usage") {
        return `
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-requests"))}">Requests</a>
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Errors</a>
      <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(filters.requestId, filters))}">Logs</a>
    `;
    }
    return `
    <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic"))}">Summary</a>
    <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-usage"))}">Usage</a>
    <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(filters.requestId, filters))}">Logs</a>
  `;
}
function renderTrafficSurface(page, data, filters, requestPinned) {
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
function renderTrafficOverviewPage(data, filters, requestPinned) {
    return `
    ${card("Traffic filters", renderTrafficFilters(data, filters, "overview"), "panel panel--span-12 panel--measure")}
    ${card(requestPinned ? "Pinned request inventory" : "Recent requests", `
        <div class="stack">
          ${renderRequestRows(data.requestEvents, filters)}
          <p class="field-note">Requests stay primary here. Pin one request or reopen Logs with the same scope.</p>
        </div>
      `, "panel panel--span-8 panel--measure")}
    ${card("Scope and next move", renderTrafficOverviewAside(data, filters, requestPinned), "panel panel--span-4 panel--aside")}
    ${card("Error lane", renderTrafficPreviewLane({
        title: "Recent failure sample",
        rows: renderErrorPreviewRows(data.errorEvents, filters),
        stats: [
            { label: "Rows in scope", value: formatNumber(data.errorEvents.length) },
            {
                label: "Error types",
                value: formatNumber(new Set(data.errorEvents
                    .map((item) => String(item.error_type ?? "").trim())
                    .filter(Boolean)).size),
            },
        ],
        primaryHref: buildTrafficUrl(filters, "traffic-errors"),
        primaryLabel: "Open errors",
        secondaryHref: buildLogsUrlForRequest(filters.requestId, filters),
        secondaryLabel: "Open logs",
    }), "panel panel--span-8")}
    ${card("Usage lane", renderTrafficPreviewLane({
        title: "Aggregate usage sample",
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
    }), "panel panel--span-4 panel--aside")}
    ${card("Selection inspector", renderTrafficInspector({
        filters,
        summaryIntro: requestPinned
            ? "Pinned request context is active. Inspect it here before switching lanes."
            : "Inspect one row here, then move into a dedicated lane only when needed.",
        statItems: [
            { label: "Request rows", value: formatNumber(data.requestEvents.length) },
            { label: "Error rows", value: formatNumber(data.errorEvents.length) },
            { label: "Usage providers", value: formatNumber(data.providerEntries.length) },
            { label: "Usage keys", value: formatNumber(data.keyEntries.length) },
        ],
        emptySelectionMessage: "No request, error, or usage row is selected on the summary page.",
        rawPayload: {
            active_filters: filters,
            usage_summary: data.providerSummary,
        },
    }), "panel panel--span-8 panel--aside")}
    ${card("Guides", renderGuideLinks([
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Follow the summary-first flow and know when to pin one request.",
        },
        {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Open this once traffic already narrowed the issue.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use when the current lane still does not point clearly at the next surface.",
        },
    ], {
        collapsibleSummary: "Operator guides",
        compact: true,
    }), "panel panel--span-4 panel--aside")}
  `;
}
function renderTrafficRequestsPage(data, filters, requestPinned) {
    return `
    ${card("Request filters", renderTrafficFilters(data, filters, "requests"), "panel panel--span-12 panel--measure")}
    ${card("Recent requests", renderRequestRows(data.requestEvents, filters), "panel panel--span-8")}
    ${card("Request inspector", renderTrafficInspector({
        filters,
        summaryIntro: requestPinned
            ? "Already pinned. Compare the selected request with recent failures, then open Logs only if raw evidence is still needed."
            : "Select one request, inspect it, then reopen Logs with the same request id if needed.",
        statItems: [
            { label: "Request rows", value: formatNumber(data.requestEvents.length) },
            { label: "Error companions", value: formatNumber(data.errorEvents.length) },
            {
                label: "Providers in scope",
                value: formatNumber(new Set(data.requestEvents
                    .map((item) => String(item.provider ?? "").trim())
                    .filter(Boolean)).size),
            },
            { label: "Pinned request", value: filters.requestId || "none" },
        ],
        rawPayload: {
            active_filters: filters,
            usage_summary: data.providerSummary,
        },
    }), "panel panel--span-4 panel--aside")}
    ${card("Companion failure lane", `
        <div class="stack">
          <p class="muted">Keep requests primary here. Open Errors only when failures become the main task.</p>
          ${renderErrorPreviewRows(data.errorEvents, filters)}
          <div class="toolbar">
            <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Open errors</a>
            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic"))}">Open traffic summary</a>
          </div>
        </div>
      `, "panel panel--span-8")}
    ${card("Guides", renderGuideLinks([
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Use the request-first checklist when the main question is which request deserves pinning.",
        },
        {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Escalate only after one request row proves raw logs are next.",
        },
    ], {
        collapsibleSummary: "Operator guides",
        compact: true,
    }), "panel panel--span-4 panel--aside")}
  `;
}
function renderTrafficErrorsPage(data, filters, requestPinned) {
    return `
    ${card("Error filters", renderTrafficFilters(data, filters, "errors"), "panel panel--span-12 panel--measure")}
    ${card("Recent errors", renderErrorRows(data.errorEvents, filters), "panel panel--span-8")}
    ${card("Error inspector", renderTrafficInspector({
        filters,
        summaryIntro: requestPinned
            ? "Already pinned. Inspect the failure here first, then open Logs only if line-level evidence is still missing."
            : "Select one error, compare the matching request when needed, then pin only if the follow-up becomes request-scoped.",
        statItems: [
            { label: "Error rows", value: formatNumber(data.errorEvents.length) },
            {
                label: "Request companions",
                value: formatNumber(data.requestEvents.length),
            },
            {
                label: "Error types",
                value: formatNumber(new Set(data.errorEvents
                    .map((item) => String(item.error_type ?? "").trim())
                    .filter(Boolean)).size),
            },
            { label: "Pinned request", value: filters.requestId || "none" },
        ],
        rawPayload: {
            active_filters: filters,
            usage_summary: data.providerSummary,
        },
    }), "panel panel--span-4 panel--aside")}
    ${card("Companion request lane", `
        <div class="stack">
          <p class="muted">Keep failures primary here. Return to Requests when request flow becomes the comparison point.</p>
          ${renderRequestPreviewRows(data.requestEvents, filters)}
          <div class="toolbar">
            <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-requests"))}">Open requests</a>
            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic"))}">Open traffic summary</a>
          </div>
        </div>
      `, "panel panel--span-8")}
    ${card("Guides", renderGuideLinks([
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Use the error-first path when the main question is which failure pattern deserves request pinning.",
        },
        {
            label: "Logs deep-dive guide",
            href: OPERATOR_GUIDE_LINKS.logs,
            note: "Open this when the error row is isolated and only raw log evidence is missing.",
        },
    ], {
        collapsibleSummary: "Operator guides",
        compact: true,
    }), "panel panel--span-4 panel--aside")}
  `;
}
function renderTrafficUsagePage(data, filters, requestPinned) {
    return `
    ${card("Usage filters", renderTrafficFilters(data, filters, "usage"), "panel panel--span-12 panel--measure")}
    ${card("Usage by provider", `
        <div class="stack">
          ${renderUsageProviderRows(data.providerEntries)}
        </div>
      `, "panel panel--span-8")}
    ${card("Usage inspector", renderTrafficInspector({
        filters,
        summaryIntro: requestPinned
            ? "Request pinning narrows only request and error feeds. Usage stays aggregate here."
            : "Select one provider or key row, then return to requests only when grouped usage exposed the next target.",
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
        emptySelectionMessage: "Select one provider or API-key row to inspect aggregate usage.",
    }), "panel panel--span-4 panel--aside")}
    ${card("Usage by key", `
        ${requestPinned ? '<div class="banner banner--warn">Request pinning narrows only recent requests and errors. Usage rows stay aggregate.</div>' : ""}
        ${renderUsageKeyRows(data.keyEntries)}
      `, "panel panel--span-8")}
    ${card("Next handoff", `
        <div class="stack">
          ${renderDefinitionList([
        {
            label: "Aggregate scope",
            value: requestPinned ? "Usage stays unpinned" : "Following active filters",
            note: requestPinned
                ? "Request pinning only narrows recent request and error feeds."
                : "Provider, model, key, and source filters still drive grouped usage.",
        },
        {
            label: "Best next move",
            value: data.keyEntries.length ? "Inspect the noisiest key" : "Open request traffic",
            note: data.keyEntries.length
                ? "Use the key table to see which path deserves a request-level drill-down."
                : "No key rollups yet, so move back to recent requests.",
        },
        {
            label: "Logs handoff",
            value: filters.requestId ? "Ready for the pinned request" : "Needs one request selection",
            note: filters.requestId
                ? "Open raw logs with the same request id applied."
                : "Pin a request from Requests or Errors before escalating into raw logs.",
        },
    ], "Grouped usage handoff is unavailable.")}
          <div class="toolbar">
            <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-requests"))}">Open requests</a>
            <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Open errors</a>
            <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(filters.requestId, filters))}">Open logs</a>
          </div>
          ${renderGuideLinks([
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Use the grouped-usage path when the first question is where traffic went.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Open once grouped usage pointed at the next request or provider surface.",
        },
    ], {
        collapsibleSummary: "Operator guides",
        compact: true,
    })}
        </div>
      `, "panel panel--span-4 panel--aside")}
  `;
}
function renderTrafficFilters(data, filters, variant) {
    const requestFilterOptions = asRecord(data.requestsPayload.available_filters);
    const errorFilterOptions = asRecord(data.errorsPayload.available_filters);
    const usageKeyFilterOptions = asRecord(data.usageKeysPayload.available_filters);
    const usageProviderFilterOptions = asRecord(data.usageProvidersPayload.available_filters);
    const providerOptions = [
        ...asArray(requestFilterOptions.provider),
        ...asArray(errorFilterOptions.provider),
        ...asArray(usageKeyFilterOptions.provider),
        ...asArray(usageProviderFilterOptions.provider),
    ];
    const modelOptions = [
        ...asArray(requestFilterOptions.model),
        ...asArray(errorFilterOptions.model),
        ...asArray(usageKeyFilterOptions.model),
        ...asArray(usageProviderFilterOptions.model),
    ];
    const intro = variant === "overview"
        ? ""
        : variant === "requests"
            ? "Requests first."
            : variant === "errors"
                ? "Errors first."
                : "Usage first.";
    const primarySection = variant === "usage"
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
                ${renderFilterSelectOptions(filters.source, asArray(usageKeyFilterOptions.source))}
              </select>
            </label>
            <label class="field">
              <span>API key name</span>
              <select name="api_key_name">
                ${renderFilterSelectOptions(filters.apiKeyName, asArray(usageProviderFilterOptions.api_key_name))}
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
                ${renderFilterSelectOptions(filters.endpoint, asArray(requestFilterOptions.endpoint))}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderFilterSelectOptions(filters.method, asArray(requestFilterOptions.method))}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderFilterSelectOptions(filters.statusCode, [
            ...asArray(requestFilterOptions.status_code),
            ...asArray(errorFilterOptions.status_code),
        ])}
              </select>
            </label>
          </div>
          ${variant === "requests"
            ? ""
            : `
                <div class="dual-grid">
                  <label class="field">
                    <span>Error type</span>
                    <select name="error_type">
                      ${renderFilterSelectOptions(filters.errorType, asArray(errorFilterOptions.error_type))}
                    </select>
                  </label>
                  <div class="surface">
                    <p class="muted">
                      ${escapeHtml(variant === "overview"
                ? "Open Errors when failures become primary."
                : "Open Logs only after one error row is pinned.")}
                    </p>
                  </div>
                </div>
              `}
        `;
    return `
    <form id="traffic-filters-form" class="form-shell form-shell--compact">
      ${intro ? `<div class="form-shell__intro"><p class="muted">${escapeHtml(intro)}</p></div>` : ""}
      ${renderFormSection({
        title: variant === "overview"
            ? "Scope"
            : variant === "requests"
                ? "Request scope"
                : variant === "errors"
                    ? "Error scope"
                    : "Usage scope",
        intro: variant === "usage" ? "Usage stays aggregate." : undefined,
        body: primarySection,
    })}
      ${renderFormSection({
        title: "Request pinning",
        body: `
          <div class="dual-grid">
            <label class="field">
              <span>Request id</span>
              <input
                name="request_id"
                value="${escapeHtml(filters.requestId)}"
                placeholder="Pin one request"
              />
            </label>
            <div class="surface">
              <p class="muted">
                ${escapeHtml(variant === "usage"
            ? "Usage stays aggregate even with a request pin."
            : "Pinned request ids keep Requests, Errors, and Logs aligned.")}
              </p>
            </div>
          </div>
        `,
    })}
      <div class="toolbar">
        <button class="button" type="submit">Apply filters</button>
        <span class="muted">Scope carries across pages.</span>
      </div>
    </form>
  `;
}
function renderTrafficInspector(options) {
    return `
    <div class="stack traffic-inspector" id="traffic-selection-inspector" tabindex="-1">
      ${options.summaryIntro ? `<p class="muted">${escapeHtml(options.summaryIntro)}</p>` : ""}
      ${renderFormSection({
        title: "Current posture",
        body: renderStatLines(options.statItems, "No traffic rows are loaded yet."),
    })}
      ${renderFormSection({
        title: "Selection",
        body: `
          <div id="traffic-selection-summary">
            ${renderDefinitionList(buildTrafficSelectionSummary(options.filters), options.emptySelectionMessage ?? "Select a request, error, or usage row.")}
          </div>
          <div class="toolbar" id="traffic-selection-actions">
            ${renderTrafficSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null }, options.filters)}
          </div>
        `,
    })}
      <details class="details-disclosure" id="traffic-detail-disclosure">
        <summary id="traffic-detail-summary">Current scope snapshot</summary>
        <p class="field-note">Open only if the summary is not enough.</p>
        <pre class="code-block code-block--tall" id="traffic-detail">${escapeHtml(JSON.stringify(options.rawPayload, null, 2))}</pre>
      </details>
    </div>
  `;
}
function renderTrafficOverviewAside(data, filters, requestPinned) {
    const activeFilters = summarizeTrafficFilters(filters);
    const errorTypeCount = new Set(data.errorEvents.map((item) => String(item.error_type ?? "").trim()).filter(Boolean)).size;
    return `
    <div class="stack">
      ${renderDefinitionList([
        {
            label: "Active scope",
            value: activeFilters || "Recent traffic window",
            note: requestPinned
                ? "The request pin stays aligned across requests, errors, and logs."
                : "Use filters first; pin only after the table isolates one target.",
        },
        {
            label: "Request posture",
            value: requestPinned ? "Pinned request" : "Broad request inventory",
            note: requestPinned ? filters.requestId : "Requests remain primary on this page.",
        },
        {
            label: "Error pressure",
            value: `${formatNumber(data.errorEvents.length)} rows / ${formatNumber(errorTypeCount)} types`,
            note: data.errorEvents.length
                ? "Open the error lane when failure patterns become the main question."
                : "No recent failures matched the current scope.",
        },
        {
            label: "Usage posture",
            value: `${formatNumber(data.providerEntries.length)} providers / ${formatNumber(data.keyEntries.length)} keys`,
            note: "Grouped usage is secondary here. Open Usage when rollups matter more than individual requests.",
        },
    ], "Traffic scope summary is unavailable.")}
      <div class="toolbar">
        <a class="button" href="${escapeHtml(buildTrafficUrl(filters, "traffic-errors"))}">Open errors</a>
        <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(filters, "traffic-usage"))}">Open usage</a>
        <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(filters.requestId, filters))}">Open logs</a>
      </div>
    </div>
  `;
}
function renderTrafficPreviewLane(options) {
    return `
    <div class="stack">
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
function renderRequestPreviewRows(events, filters) {
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
function renderErrorPreviewRows(events, filters) {
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
function renderUsagePreviewRows(entries) {
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
              ${escapeHtml(`${formatNumber(entry.request_count ?? 0)} requests · ${formatNumber(entry.error_count ?? 0)} errors`)}
            </p>
            <p class="muted">
              ${escapeHtml(`${apiKeys.length} keys · ${models.length} models`)}
            </p>
          </div>
        </article>
      `;
    })
        .join("");
}
export function resolveTrafficElements(pageContent) {
    const detailDisclosure = pageContent.querySelector("#traffic-detail-disclosure");
    const detailSummaryNode = pageContent.querySelector("#traffic-detail-summary");
    const detailNode = pageContent.querySelector("#traffic-detail");
    const filtersForm = pageContent.querySelector("#traffic-filters-form");
    const inspectorNode = pageContent.querySelector("#traffic-selection-inspector");
    const summaryNode = pageContent.querySelector("#traffic-selection-summary");
    const actionNode = pageContent.querySelector("#traffic-selection-actions");
    const resetButton = document.getElementById("reset-traffic-filters");
    if (!detailDisclosure ||
        !detailSummaryNode ||
        !detailNode ||
        !filtersForm ||
        !inspectorNode ||
        !summaryNode ||
        !actionNode ||
        !resetButton) {
        return null;
    }
    return {
        actionNode,
        detailDisclosure,
        detailSummaryNode,
        detailNode,
        filtersForm,
        inspectorNode,
        resetButton,
        summaryNode,
    };
}
