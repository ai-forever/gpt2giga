import type { AdminApp } from "../../app.js";
import { withBusyState } from "../../forms.js";
import { extractErrorReason, scopeFilesBatchesFilters } from "./serializers.js";
import type {
  BatchRecord,
  DefinitionItem,
  FileRecord,
  FilesBatchesFilters,
  FilesBatchesInventory,
  FilesBatchesPage,
} from "./state.js";
import type { FilesBatchesPageElements } from "./view.js";
import { bindFilesBatchesFilters } from "./bindings/filters.js";
import {
  createFilesBatchesBindingState,
  setDefinitionBlock,
  type WorkflowActionOptions,
} from "./bindings/helpers.js";
import { createUploadBindings } from "./bindings/upload.js";
import { createBatchComposerBindings } from "./bindings/batch-composer.js";
import { createInventoryBindings } from "./bindings/inventory.js";
import {
  buildFilesBatchesUrl,
  readFilesBatchesRouteState,
} from "./serializers.js";
import type { FilesBatchesPageData } from "./api.js";
import { syncFilesBatchesPageDataCache } from "./api.js";

interface BindFilesBatchesPageOptions {
  app: AdminApp;
  data: FilesBatchesPageData;
  elements: FilesBatchesPageElements;
  filters: FilesBatchesFilters;
  inventory: FilesBatchesInventory;
  page: FilesBatchesPage;
}

export function bindFilesBatchesPage(options: BindFilesBatchesPageOptions): void {
  const { app, data, elements, filters, inventory, page } = options;
  const state = createFilesBatchesBindingState();

  const cacheFileRecord = (payload: FileRecord): FileRecord => {
    const fileId = String(payload.id ?? "");
    if (!fileId) {
      return payload;
    }
    const existing = inventory.fileLookup.get(fileId);
    const mergedPayload =
      payload.validation !== undefined || !existing?.validation
        ? payload
        : { ...payload, validation: existing.validation };
    inventory.fileLookup.set(fileId, mergedPayload);
    const existingIndex = data.files.findIndex(
      (item) => String(item.id ?? "") === fileId,
    );
    if (existingIndex >= 0) {
      data.files[existingIndex] = mergedPayload;
    } else {
      data.files.unshift(mergedPayload);
    }
    syncFilesBatchesPageDataCache(data);
    return mergedPayload;
  };

  const cacheBatchRecord = (payload: BatchRecord): BatchRecord => {
    const batchId = String(payload.id ?? "");
    if (!batchId) {
      return payload;
    }
    inventory.batchLookup.set(batchId, payload);
    const existingIndex = data.batches.findIndex(
      (item) => String(item.id ?? "") === batchId,
    );
    if (existingIndex >= 0) {
      data.batches[existingIndex] = payload;
    } else {
      data.batches.unshift(payload);
    }
    syncFilesBatchesPageDataCache(data);
    return payload;
  };

  const removeFileRecord = (fileId: string): FileRecord | null => {
    const existing = inventory.fileLookup.get(fileId) ?? null;
    if (!existing) {
      return null;
    }
    inventory.fileLookup.delete(fileId);
    const existingIndex = data.files.findIndex(
      (item) => String(item.id ?? "") === fileId,
    );
    if (existingIndex >= 0) {
      data.files.splice(existingIndex, 1);
    }
    syncFilesBatchesPageDataCache(data);
    return existing;
  };

  const setSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(elements.summaryNode, items, "No selection yet.");
  };

  const setWorkflowSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(elements.workflowNode, items, "No workflow state reported.");
  };

  const setDetailSurface = (
    title: string,
    items: DefinitionItem[],
    payload: string,
    open = false,
  ): void => {
    elements.detailSummaryTitleNode.textContent = title;
    setDefinitionBlock(elements.detailSummaryNode, items, "No detail payload loaded.");
    elements.detailNode.textContent = payload;
    elements.detailDisclosure.open = open;
  };

  const setContentSurface = (
    title: string,
    items: DefinitionItem[],
    payload: string,
    open = false,
  ): void => {
    elements.contentSummaryTitleNode.textContent = title;
    setDefinitionBlock(elements.contentSummaryNode, items, "No file content loaded.");
    elements.contentNode.textContent = payload;
    elements.contentDisclosure.open = open;
  };

  const clearMediaPreview = (): void => {
    elements.mediaNode.innerHTML = "";
    if (state.previewObjectUrl) {
      URL.revokeObjectURL(state.previewObjectUrl);
      state.previewObjectUrl = null;
    }
  };

  const resetContentSurface = (): void => {
    clearMediaPreview();
    setContentSurface(
      "Content preview",
      [
        { label: "Preview surface", value: "Idle" },
        { label: "Loaded content", value: "No file content loaded" },
      ],
      "No file content loaded.",
      false,
    );
  };

  const replaceStateForPage = (
    targetPage: FilesBatchesPage,
    routeState?: Parameters<typeof buildFilesBatchesUrl>[1],
  ): void => {
    window.history.replaceState(
      {},
      "",
      buildFilesBatchesUrl(
        scopeFilesBatchesFilters(targetPage, filters),
        routeState,
        targetPage,
      ),
    );
  };

  const navigateToPage = (
    targetPage: FilesBatchesPage,
    routeState?: Parameters<typeof buildFilesBatchesUrl>[1],
  ): void => {
    window.history.pushState(
      {},
      "",
      buildFilesBatchesUrl(
        scopeFilesBatchesFilters(targetPage, filters),
        routeState,
        targetPage,
      ),
    );
    void app.render(targetPage);
  };

  const syncSelectionRouteState = (): void => {
    if (page === "files") {
      replaceStateForPage(page, {
        selectedFileId:
          state.selection.kind === "file" ? state.selection.fileId : "",
      });
      return;
    }
    if (page === "batches") {
      replaceStateForPage(page, {
        composeInputFileId: elements.batchInput?.value.trim() ?? "",
        selectedBatchId:
          state.selection.kind === "batch" ? state.selection.batchId : "",
      });
      return;
    }
    replaceStateForPage(page, {
      selectedFileId: state.selection.kind === "file" ? state.selection.fileId : "",
      selectedBatchId:
        state.selection.kind === "batch" ? state.selection.batchId : "",
      composeInputFileId: elements.batchInput?.value.trim() ?? "",
    });
  };

  const runWorkflowAction = async <T>(
    workflow: WorkflowActionOptions<T>,
  ): Promise<T> => {
    setWorkflowSummary(workflow.pendingSummary);
    try {
      const result = await withBusyState({
        root: workflow.root,
        button: workflow.button,
        pendingLabel: workflow.pendingLabel,
        action: workflow.action,
      });
      setWorkflowSummary(workflow.successSummary(result));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setWorkflowSummary([
        { label: "Workflow state", value: "Action failed" },
        {
          label: "Failed step",
          value: workflow.pendingSummary[0]?.value ?? "Unknown action",
        },
        { label: "Reason", value: extractErrorReason(message) },
      ]);
      throw error;
    }
  };

  const cacheValidationSnapshotForFile = (
    fileId: string,
    snapshot: FileRecord["validation"],
  ): void => {
    const existing = inventory.fileLookup.get(fileId);
    if (!existing) {
      return;
    }
    cacheFileRecord({
      ...existing,
      validation: snapshot,
    });
  };

  const callbacks = {
    refreshSelectedFileValidationSurface: (): void => {},
  };

  const batchComposer = createBatchComposerBindings({
    app,
    data,
    elements,
    inventory,
    page,
    state,
    callbacks,
    cacheBatchRecord,
    cacheValidationSnapshotForFile,
    replaceStateForPage,
    runWorkflowAction,
    setWorkflowSummary,
  });

  const uploadBindings = createUploadBindings({
    app,
    data,
    elements,
    page,
    state,
    cacheFileRecord,
    replaceStateForPage,
    runWorkflowAction,
    setWorkflowSummary,
  });

  const inventoryBindings = createInventoryBindings({
    app,
    data,
    elements,
    inventory,
    page,
    state,
    batchComposer,
    cacheFileRecord,
    cacheBatchRecord,
    removeFileRecord,
    setSummary,
    setWorkflowSummary,
    setDetailSurface,
    setContentSurface,
    resetContentSurface,
    clearMediaPreview,
    replaceStateForPage,
    navigateToPage,
    syncSelectionRouteState,
    runWorkflowAction,
  });

  callbacks.refreshSelectedFileValidationSurface =
    inventoryBindings.refreshSelectedFileValidationSurface;

  resetContentSurface();
  bindFilesBatchesFilters({ app, elements, filters, page });
  uploadBindings.initialize();
  batchComposer.initialize(readFilesBatchesRouteState(page));
  inventoryBindings.initialize(readFilesBatchesRouteState(page));
}
