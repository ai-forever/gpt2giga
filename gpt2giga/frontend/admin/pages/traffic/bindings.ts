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
  TrafficPage,
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
  page: TrafficPage;
}

const INSPECTOR_HIGHLIGHT_CLASS = "traffic-inspector--active";

export function bindTrafficPage(options: BindTrafficPageOptions): void {
  const { app, data, elements, filters, page } = options;
  const requestLookup = indexEventsByRequestId(data.requestEvents);
  const errorLookup = indexEventsByRequestId(data.errorEvents);
  const inspectPayloads: Record<TrafficDetailKind, Record<string, unknown>[]> = {
    request: data.requestEvents,
    error: data.errorEvents,
    key: data.keyEntries,
    provider: data.providerEntries,
  };
  let inspectorHighlightTimer: number | null = null;

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

  const revealSelectionInspector = (): void => {
    const rect = elements.inspectorNode.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const inspectorOutsideViewport = rect.top < 96 || rect.bottom > viewportHeight - 32;

    if (inspectorOutsideViewport) {
      elements.inspectorNode.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    elements.inspectorNode.focus({ preventScroll: true });
    elements.inspectorNode.classList.remove(INSPECTOR_HIGHLIGHT_CLASS);
    void elements.inspectorNode.offsetWidth;
    elements.inspectorNode.classList.add(INSPECTOR_HIGHLIGHT_CLASS);

    if (inspectorHighlightTimer !== null) {
      window.clearTimeout(inspectorHighlightTimer);
    }

    inspectorHighlightTimer = window.setTimeout(() => {
      elements.inspectorNode.classList.remove(INSPECTOR_HIGHLIGHT_CLASS);
      inspectorHighlightTimer = null;
    }, 1400);
  };

  const selectTrafficEvent = (
    kind: "request" | "error",
    item: TrafficEvent,
    revealInspector = true,
  ): void => {
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
      kind === "error" ? "Selected error snapshot" : "Selected request snapshot",
      {
        selected_event: item,
        counterpart_event: counterpart,
        active_filters: filters,
      },
    );

    if (revealInspector) {
      revealSelectionInspector();
    }
  };

  const selectUsageRow = (kind: "key" | "provider", item: UsageEntry, revealInspector = true): void => {
    setSelectionSummary(buildUsageSelectionSummary(kind, item, filters));
    setSelectionActions({ requestId: null, counterpartKind: null, counterpartIndex: null });
    setDetailState(
      kind === "key" ? "Selected usage-by-key snapshot" : "Selected usage-by-provider snapshot",
      {
        selected_usage_entry: item,
        usage_summary: data.providerSummary,
        active_filters: filters,
      },
    );

    if (revealInspector) {
      revealSelectionInspector();
    }
  };

  app.registerCleanup(() => {
    if (inspectorHighlightTimer !== null) {
      window.clearTimeout(inspectorHighlightTimer);
      inspectorHighlightTimer = null;
    }
    elements.inspectorNode.classList.remove(INSPECTOR_HIGHLIGHT_CLASS);
  });

  setDetailState(
    "Current scope snapshot",
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

  seedTrafficSelection(filters, requestLookup, errorLookup, (kind, item) => {
    selectTrafficEvent(kind, item, false);
  });
}
