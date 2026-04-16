import { card, kpi, renderDefinitionList, renderFilterSelectOptions, renderStaticSelectOptions, renderStatLines, } from "../../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber } from "../../utils.js";
import { buildLogsUrlForRequest, buildTrafficScopeSummary, buildTrafficSelectionSummary, renderErrorRows, renderRequestRows, renderTrafficSelectionActions, renderUsageKeyRows, renderUsageProviderRows, } from "./serializers.js";
export function renderTrafficHeroActions(filters) {
    const logsHref = buildLogsUrlForRequest(filters.requestId, filters);
    const logsLabel = filters.requestId ? "Open pinned logs" : "Open logs with current filters";
    return `
    <button class="button button--secondary" id="reset-traffic-filters" type="button">Reset filters</button>
    <a class="button" href="${escapeHtml(logsHref)}">
      ${escapeHtml(logsLabel)}
    </a>
  `;
}
export function renderTrafficPage(data, filters) {
    const requestPinned = Boolean(filters.requestId);
    const scopeSummary = buildTrafficScopeSummary(filters, data.requestEvents, data.errorEvents, data.providerEntries, data.providerSummary);
    return `
    ${kpi(requestPinned ? "Pinned requests" : "Requests", formatNumber(scopeSummary.requestCount))}
    ${kpi(requestPinned ? "Pinned errors" : "Errors", formatNumber(scopeSummary.errorCount))}
    ${kpi(requestPinned ? "Pinned tokens" : "Tokens", formatNumber(scopeSummary.totalTokens))}
    ${kpi(requestPinned ? "Providers in scope" : "Providers", formatNumber(scopeSummary.providerCount))}
    ${card(requestPinned ? "Observe workflow" : "Summary-first observe workflow", renderTrafficWorkflowGuide(filters, requestPinned), "panel panel--span-12")}
    ${card("Traffic filters", `
        <form id="traffic-filters-form" class="stack">
          <div class="triple-grid">
            <label class="field">
              <span>Provider</span>
              <select name="provider">
                ${renderFilterSelectOptions(filters.provider, [
        ...asArray(asRecord(data.requestsPayload.available_filters).provider),
        ...asArray(asRecord(data.errorsPayload.available_filters).provider),
        ...asArray(asRecord(data.usageKeysPayload.available_filters).provider),
        ...asArray(asRecord(data.usageProvidersPayload.available_filters).provider),
    ])}
              </select>
            </label>
            <label class="field">
              <span>Model</span>
              <select name="model">
                ${renderFilterSelectOptions(filters.model, [
        ...asArray(asRecord(data.requestsPayload.available_filters).model),
        ...asArray(asRecord(data.errorsPayload.available_filters).model),
        ...asArray(asRecord(data.usageKeysPayload.available_filters).model),
        ...asArray(asRecord(data.usageProvidersPayload.available_filters).model),
    ])}
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
                ${renderFilterSelectOptions(filters.endpoint, asArray(asRecord(data.requestsPayload.available_filters).endpoint))}
              </select>
            </label>
            <label class="field">
              <span>Method</span>
              <select name="method">
                ${renderFilterSelectOptions(filters.method, asArray(asRecord(data.requestsPayload.available_filters).method))}
              </select>
            </label>
            <label class="field">
              <span>Status code</span>
              <select name="status_code">
                ${renderFilterSelectOptions(filters.statusCode, [
        ...asArray(asRecord(data.requestsPayload.available_filters).status_code),
        ...asArray(asRecord(data.errorsPayload.available_filters).status_code),
    ])}
              </select>
            </label>
          </div>
          <div class="triple-grid">
            <label class="field">
              <span>Error type</span>
              <select name="error_type">
                ${renderFilterSelectOptions(filters.errorType, asArray(asRecord(data.errorsPayload.available_filters).error_type))}
              </select>
            </label>
            <label class="field">
              <span>Key source</span>
              <select name="source">
                ${renderFilterSelectOptions(filters.source, asArray(asRecord(data.usageKeysPayload.available_filters).source))}
              </select>
            </label>
            <label class="field">
              <span>API key name</span>
              <select name="api_key_name">
                ${renderFilterSelectOptions(filters.apiKeyName, asArray(asRecord(data.usageProvidersPayload.available_filters).api_key_name))}
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
      `, "panel panel--span-12")}
    ${card("Recent requests", renderRequestRows(data.requestEvents, filters), "panel panel--span-8")}
    ${card("Selected payload", `
        <div class="stack">
          ${renderStatLines([
        { label: "Request events", value: formatNumber(data.requestEvents.length) },
        { label: "Error events", value: formatNumber(data.errorEvents.length) },
        { label: "Usage key rows", value: formatNumber(data.keyEntries.length) },
        { label: "Usage provider rows", value: formatNumber(data.providerEntries.length) },
    ], "No traffic rows are loaded yet.")}
          <div id="traffic-selection-summary">
            ${renderDefinitionList(buildTrafficSelectionSummary(filters), "Select a request, error, or usage row.")}
          </div>
          <div class="toolbar" id="traffic-selection-actions">
            ${renderTrafficSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null }, filters)}
          </div>
          <pre class="code-block code-block--tall" id="traffic-detail">${escapeHtml(JSON.stringify({
        active_filters: filters,
        usage_summary: data.providerSummary,
    }, null, 2))}</pre>
        </div>
      `, "panel panel--span-4")}
    ${card("Recent errors", renderErrorRows(data.errorEvents, filters), "panel panel--span-8")}
    ${card("Usage summary", `
        ${requestPinned ? '<div class="banner banner--warn">Usage rollups below still follow provider/model/key filters, but request-id pinning only scopes recent request and error feeds.</div>' : ""}
        ${renderStatLines([
        {
            label: "Successful requests",
            value: formatNumber(data.providerSummary.success_count ?? 0),
            tone: "good",
        },
        {
            label: "Errored requests",
            value: formatNumber(data.providerSummary.error_count ?? 0),
            tone: Number(data.providerSummary.error_count ?? 0) > 0 ? "warn" : "default",
        },
        { label: "Prompt tokens", value: formatNumber(data.providerSummary.prompt_tokens ?? 0) },
        {
            label: "Completion tokens",
            value: formatNumber(data.providerSummary.completion_tokens ?? 0),
        },
    ], "Usage totals are empty.")}
      `, "panel panel--span-4")}
    ${card("Usage by key", renderUsageKeyRows(data.keyEntries), "panel panel--span-6")}
    ${card("Usage by provider", renderUsageProviderRows(data.providerEntries), "panel panel--span-6")}
  `;
}
function renderTrafficWorkflowGuide(filters, requestPinned) {
    const logsHref = buildLogsUrlForRequest(filters.requestId, filters);
    return `
    <div class="workflow-grid">
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Observe</span>
          <h4>${escapeHtml(requestPinned ? "Stay scoped to one request" : "Stay here for the broad request picture")}</h4>
          <p>${escapeHtml(requestPinned
        ? "Traffic is already narrowed to one request id. Use this page to compare the pinned request, matching error rows, and aggregate usage before deciding whether raw logs are necessary."
        : "Traffic is the summary-first surface: recent requests, recent errors, and usage rollups stay visible together so you can narrow down one request or failure without starting in raw logs.")}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button button--secondary" href="/admin/traffic">${escapeHtml(requestPinned ? "Return to broad traffic" : "Reset traffic scope")}</a>
        </div>
      </article>
      <article class="workflow-card">
        <div class="workflow-card__header">
          <span class="eyebrow">Diagnose</span>
          <h4>${escapeHtml(requestPinned ? "Escalate only when raw context is needed" : "Escalate to Logs only after one request stands out")}</h4>
          <p>${escapeHtml(requestPinned
        ? "Open Logs when the pinned request now needs raw line-by-line context, tail-derived request correlation, or a live stream follow-up."
        : "Pick one request or error row first, then move into Logs with the same request id and compatible filters already applied.")}</p>
        </div>
        <div class="workflow-card__actions">
          <a class="button" href="${escapeHtml(logsHref)}">${escapeHtml(requestPinned ? "Open pinned logs" : "Open logs with current filters")}</a>
        </div>
      </article>
    </div>
  `;
}
export function resolveTrafficElements(pageContent) {
    const detailNode = pageContent.querySelector("#traffic-detail");
    const filtersForm = pageContent.querySelector("#traffic-filters-form");
    const summaryNode = pageContent.querySelector("#traffic-selection-summary");
    const actionNode = pageContent.querySelector("#traffic-selection-actions");
    const resetButton = document.getElementById("reset-traffic-filters");
    if (!detailNode || !filtersForm || !summaryNode || !actionNode || !resetButton) {
        return null;
    }
    return {
        actionNode,
        detailNode,
        filtersForm,
        resetButton,
        summaryNode,
    };
}
