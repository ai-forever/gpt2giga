import { pathForPage } from "../../routes.js";
import { pill, renderDefinitionList, renderFormSection, renderStatLines, } from "../../templates.js";
import { asRecord, escapeHtml, formatNumber, formatTimestamp } from "../../utils.js";
import { buildLogsUrlForRequest, buildTrafficSelectionSummary, buildTrafficUrl, renderTrafficSelectionActions, summarizeTrafficFilters, } from "./serializers.js";
const PREVIEW_LIMIT = 4;
export function renderTrafficInspector(options) {
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
export function renderTrafficOverviewAside(options) {
    const activeFilters = summarizeTrafficFilters(options.filters);
    const errorTypeCount = new Set(options.errorEvents
        .map((item) => String(item.error_type ?? "").trim())
        .filter(Boolean)).size;
    return `
    <div class="stack">
      ${renderDefinitionList([
        {
            label: "Active scope",
            value: activeFilters || "Recent traffic window",
            note: options.requestPinned
                ? "The request pin stays aligned across requests, errors, and logs."
                : "Use filters first; pin only after the table isolates one target.",
        },
        {
            label: "Request posture",
            value: options.requestPinned ? "Pinned request" : "Broad request inventory",
            note: options.requestPinned
                ? options.filters.requestId
                : "Requests remain primary on this page.",
        },
        {
            label: "Error pressure",
            value: `${formatNumber(options.errorEvents.length)} rows / ${formatNumber(errorTypeCount)} types`,
            note: options.errorEvents.length
                ? "Open the error lane when failure patterns become the main question."
                : "No recent failures matched the current scope.",
        },
        {
            label: "Usage posture",
            value: `${formatNumber(options.providerEntryCount)} providers / ${formatNumber(options.keyEntryCount)} keys`,
            note: "Grouped usage is secondary here. Open Usage when rollups matter more than individual requests.",
        },
    ], "Traffic scope summary is unavailable.")}
      <div class="toolbar">
        <a class="button" href="${escapeHtml(buildTrafficUrl(options.filters, "traffic-errors"))}">Open errors</a>
        <a class="button button--secondary" href="${escapeHtml(buildTrafficUrl(options.filters, "traffic-usage"))}">Open usage</a>
        <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(options.filters.requestId, options.filters))}">Open logs</a>
      </div>
    </div>
  `;
}
export function renderTrafficPreviewLane(options) {
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
export function renderRequestPreviewRows(events, filters) {
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
export function renderErrorPreviewRows(events, filters) {
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
export function renderUsagePreviewRows(entries) {
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
