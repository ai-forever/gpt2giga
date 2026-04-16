import type { AdminApp } from "../../app.js";
import { renderDefinitionList } from "../../templates.js";
import type { TrafficPageData } from "./api.js";
import {
  buildTrafficEventSelectionSummary,
  buildTrafficUrl,
  buildUsageSelectionSummary,
  indexEventsByRequestId,
  normalizeOptionalText,
  renderTrafficSelectionActions,
  seedTrafficSelection,
} from "./serializers.js";
import type {
  TrafficDetailKind,
  TrafficEvent,
  TrafficFilters,
  TrafficSelection,
  UsageEntry,
} from "./state.js";
import { DEFAULT_LIMIT } from "./state.js";
import type { TrafficPageElements } from "./view.js";

interface BindTrafficPageOptions {
  app: AdminApp;
  data: TrafficPageData;
  elements: TrafficPageElements;
  filters: TrafficFilters;
}

export function bindTrafficPage(options: BindTrafficPageOptions): void {
  const { app, data, elements, filters } = options;
  const requestLookup = indexEventsByRequestId(data.requestEvents);
  const errorLookup = indexEventsByRequestId(data.errorEvents);
  const inspectPayloads: Record<TrafficDetailKind, Record<string, unknown>[]> = {
    request: data.requestEvents,
    error: data.errorEvents,
    key: data.keyEntries,
    provider: data.providerEntries,
  };

  const setSelectionSummary = (items: { label: string; value: string; note?: string }[]): void => {
    elements.summaryNode.innerHTML = renderDefinitionList(items, "Select a request, error, or usage row.");
  };

  const setSelectionActions = (selection: TrafficSelection): void => {
    elements.actionNode.innerHTML = renderTrafficSelectionActions(selection, filters);
  };

  const setDetailState = (summary: string, payload: Record<string, unknown>, open = true): void => {
    elements.detailSummaryNode.textContent = summary;
    elements.detailNode.textContent = JSON.stringify(payload, null, 2);
    elements.detailDisclosure.open = open;
  };

  const selectTrafficEvent = (kind: "request" | "error", item: TrafficEvent): void => {
    const requestId = normalizeOptionalText(item.request_id);
    const counterpartKind = kind === "request" ? "error" : "request";
    const counterpartRows = counterpartKind === "error" ? data.errorEvents : data.requestEvents;
    const counterpartIndex = requestId
      ? counterpartRows.findIndex((candidate) => normalizeOptionalText(candidate.request_id) === requestId)
      : -1;
    const counterpart =
      requestId && kind === "request"
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
    setDetailState(
      kind === "error" ? "Raw error event payload" : "Raw request event payload",
      {
        selected_event: item,
        counterpart_event: counterpart,
        active_filters: filters,
      },
    );
  };

  const selectUsageRow = (kind: "key" | "provider", item: UsageEntry): void => {
    setSelectionSummary(buildUsageSelectionSummary(kind, item, filters));
    setSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null });
    setDetailState(
      kind === "key" ? "Raw usage-by-key payload" : "Raw usage-by-provider payload",
      {
        selected_usage_entry: item,
        usage_summary: data.providerSummary,
        active_filters: filters,
      },
    );
  };

  setDetailState(
    "Raw payload snapshot",
    {
      active_filters: filters,
      usage_summary: data.providerSummary,
    },
    false,
  );

  elements.filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      limit: HTMLSelectElement;
      request_id: HTMLInputElement;
      provider: HTMLSelectElement;
      endpoint: HTMLSelectElement;
      method: HTMLSelectElement;
      status_code: HTMLSelectElement;
      model: HTMLSelectElement;
      error_type: HTMLSelectElement;
      source: HTMLSelectElement;
      api_key_name: HTMLSelectElement;
    };

    const nextFilters: TrafficFilters = {
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
    window.history.replaceState({}, "", buildTrafficUrl(nextFilters));
    void app.render("traffic");
  });

  elements.resetButton.addEventListener("click", () => {
    window.history.replaceState({}, "", "/admin/traffic");
    void app.render("traffic");
  });

  elements.actionNode.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>("[data-traffic-action]");
    if (!button) {
      return;
    }
    const action = button.dataset.trafficAction;
    if (action === "scope-request") {
      const requestId = button.dataset.requestId?.trim();
      if (!requestId) {
        return;
      }
      window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId }));
      void app.render("traffic");
      return;
    }
    if (action === "clear-request-scope") {
      window.history.replaceState({}, "", buildTrafficUrl({ ...filters, requestId: "" }));
      void app.render("traffic");
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

  app.pageContent.querySelectorAll<HTMLElement>("[data-traffic-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.trafficKind;
      const indexValue = button.dataset.trafficDetail;
      if (
        (kind !== "request" && kind !== "error" && kind !== "key" && kind !== "provider") ||
        indexValue === undefined
      ) {
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
