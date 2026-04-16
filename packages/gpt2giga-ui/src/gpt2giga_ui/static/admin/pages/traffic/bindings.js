import { renderDefinitionList } from "../../templates.js";
import { buildTrafficEventSelectionSummary, buildTrafficUrl, buildUsageSelectionSummary, indexEventsByRequestId, normalizeOptionalText, renderTrafficSelectionActions, seedTrafficSelection, } from "./serializers.js";
import { DEFAULT_LIMIT } from "./state.js";
export function bindTrafficPage(options) {
    const { app, data, elements, filters, page } = options;
    const requestLookup = indexEventsByRequestId(data.requestEvents);
    const errorLookup = indexEventsByRequestId(data.errorEvents);
    const inspectPayloads = {
        request: data.requestEvents,
        error: data.errorEvents,
        key: data.keyEntries,
        provider: data.providerEntries,
    };
    const setSelectionSummary = (items) => {
        elements.summaryNode.innerHTML = renderDefinitionList(items, "Select a request, error, or usage row.");
    };
    const setSelectionActions = (selection) => {
        elements.actionNode.innerHTML = renderTrafficSelectionActions(selection, filters);
    };
    const setDetailState = (summary, payload, open = true) => {
        elements.detailSummaryNode.textContent = summary;
        elements.detailNode.textContent = JSON.stringify(payload, null, 2);
        elements.detailDisclosure.open = open;
    };
    const selectTrafficEvent = (kind, item) => {
        const requestId = normalizeOptionalText(item.request_id);
        const counterpartKind = kind === "request" ? "error" : "request";
        const counterpartRows = counterpartKind === "error" ? data.errorEvents : data.requestEvents;
        const counterpartIndex = requestId
            ? counterpartRows.findIndex((candidate) => normalizeOptionalText(candidate.request_id) === requestId)
            : -1;
        const counterpart = requestId && kind === "request"
            ? (errorLookup.get(requestId) ?? null)
            : requestId
                ? (requestLookup.get(requestId) ?? null)
                : null;
        setSelectionSummary(buildTrafficEventSelectionSummary(kind, item, counterpart));
        setSelectionActions({
            requestId: requestId || null,
            counterpartKind: counterpartIndex >= 0 ? counterpartKind : null,
            counterpartIndex: counterpartIndex >= 0 ? counterpartIndex : null,
        });
        setDetailState(kind === "error" ? "Selected error snapshot" : "Selected request snapshot", {
            selected_event: item,
            counterpart_event: counterpart,
            active_filters: filters,
        });
    };
    const selectUsageRow = (kind, item) => {
        setSelectionSummary(buildUsageSelectionSummary(kind, item, filters));
        setSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null });
        setDetailState(kind === "key" ? "Selected usage-by-key snapshot" : "Selected usage-by-provider snapshot", {
            selected_usage_entry: item,
            usage_summary: data.providerSummary,
            active_filters: filters,
        });
    };
    setDetailState("Current scope snapshot", {
        active_filters: filters,
        usage_summary: data.providerSummary,
    }, false);
    elements.filtersForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const nextFilters = {
            limit: fields.limit.value || DEFAULT_LIMIT,
            requestId: fields.request_id.value.trim(),
            provider: fields.provider.value,
            endpoint: fields.endpoint.value,
            method: fields.method.value,
            statusCode: fields.status_code.value,
            model: fields.model.value,
            errorType: fields.error_type.value,
            source: fields.source.value,
            apiKeyName: fields.api_key_name.value,
        };
        window.history.replaceState({}, "", buildTrafficUrl(nextFilters, page));
        void app.render(page);
    });
    elements.resetButton.addEventListener("click", () => {
        window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId: "", provider: "", endpoint: "", method: "", statusCode: "", model: "", errorType: "", source: "", apiKeyName: "", limit: DEFAULT_LIMIT }, page));
        void app.render(page);
    });
    elements.actionNode.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        const button = target.closest("[data-traffic-action]");
        if (!button) {
            return;
        }
        const action = button.dataset.trafficAction;
        if (action === "scope-request") {
            const requestId = button.dataset.requestId?.trim();
            if (!requestId) {
                return;
            }
            window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId }, page));
            void app.render(page);
            return;
        }
        if (action === "clear-request-scope") {
            window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId: "" }, page));
            void app.render(page);
            return;
        }
        if (action === "inspect-counterpart") {
            const kind = button.dataset.counterpartKind;
            const indexValue = button.dataset.counterpartIndex;
            if ((kind !== "request" && kind !== "error") || indexValue === undefined) {
                return;
            }
            const item = inspectPayloads[kind][Number(indexValue)];
            if (!item) {
                return;
            }
            selectTrafficEvent(kind, item);
        }
    });
    app.pageContent.querySelectorAll("[data-traffic-detail]").forEach((button) => {
        button.addEventListener("click", () => {
            const kind = button.dataset.trafficKind;
            const indexValue = button.dataset.trafficDetail;
            if ((kind !== "request" && kind !== "error" && kind !== "key" && kind !== "provider") ||
                indexValue === undefined) {
                return;
            }
            const item = inspectPayloads[kind][Number(indexValue)];
            if (!item) {
                return;
            }
            if (kind === "request" || kind === "error") {
                selectTrafficEvent(kind, item);
                return;
            }
            selectUsageRow(kind, item);
        });
    });
    seedTrafficSelection(filters, requestLookup, errorLookup, selectTrafficEvent);
}
