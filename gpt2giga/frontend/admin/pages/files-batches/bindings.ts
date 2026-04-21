import type { AdminApp } from "../../app.js";
import { withBusyState } from "../../forms.js";
import { renderDefinitionList } from "../../templates.js";
import { formatBytes, formatTimestamp, safeJsonParse } from "../../utils.js";
import {
  createBatch,
  deleteFile,
  fetchBatchMetadata,
  fetchFileContent,
  fetchFileMetadata,
  type FilesBatchesPageData,
  uploadFile,
} from "./api.js";
import {
  buildBatchActionHint,
  buildContentPreviewSummary,
  buildFilePreview,
  buildFilesBatchesUrl,
  extractErrorReason,
  getLatestLinkedBatch,
  getLatestOutputBatch,
  getLinkedBatchesForFile,
  humanizeBatchLifecycle,
  readFilesBatchesRouteState,
  renderInspectorActions,
  scopeFilesBatchesFilters,
  summarizeBatchRequestCounts,
  summarizePreviewOutcome,
} from "./serializers.js";
import type {
  ArtifactApiFormat,
  BatchRecord,
  DefinitionItem,
  FileRecord,
  FilesBatchesFilters,
  FilesBatchesInventory,
  FilesBatchesPage,
  InspectorSelection,
} from "./state.js";
import { INVALID_JSON } from "./state.js";
import type { FilesBatchesPageElements } from "./view.js";

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

  let selection: InspectorSelection = { kind: "idle" };
  let previewObjectUrl: string | null = null;
  let lastGeminiInlineRequestsTemplate = "";

  const cacheFileRecord = (payload: FileRecord): FileRecord => {
    const fileId = String(payload.id ?? "");
    if (!fileId) {
      return payload;
    }
    inventory.fileLookup.set(fileId, payload);
    const existingIndex = data.files.findIndex(
      (item) => String(item.id ?? "") === fileId,
    );
    if (existingIndex >= 0) {
      data.files[existingIndex] = payload;
    } else {
      data.files.unshift(payload);
    }
    return payload;
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
    return payload;
  };

  const setDefinitionBlock = (
    node: HTMLElement,
    items: DefinitionItem[],
    emptyMessage: string,
  ): void => {
    node.innerHTML = renderDefinitionList(items, emptyMessage);
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

  const clearMediaPreview = (): void => {
    elements.mediaNode.innerHTML = "";
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl);
      previewObjectUrl = null;
    }
  };

  const updateInspectorActions = (): void => {
    elements.actionNode.innerHTML = renderInspectorActions(
      page,
      selection,
      inventory.fileLookup,
      inventory.batchLookup,
      data.batches,
    );
  };

  const clearSelectionHandoff = (): void => {
    delete selection.handoffRequestId;
    delete selection.handoffRequestCount;
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

  const syncSelectionRouteState = (nextSelection: InspectorSelection): void => {
    if (page === "files") {
      replaceStateForPage(page, {
        selectedFileId: nextSelection.kind === "file" ? nextSelection.fileId : "",
      });
      return;
    }
    if (page === "batches") {
      replaceStateForPage(page, {
        composeInputFileId: elements.batchInput?.value.trim() ?? "",
        selectedBatchId: nextSelection.kind === "batch" ? nextSelection.batchId : "",
      });
      return;
    }
    replaceStateForPage(page, {
      selectedFileId: nextSelection.kind === "file" ? nextSelection.fileId : "",
      selectedBatchId: nextSelection.kind === "batch" ? nextSelection.batchId : "",
      composeInputFileId: elements.batchInput?.value.trim() ?? "",
    });
  };

  const readBatchApiFormat = (): ArtifactApiFormat => {
    const normalized = elements.batchApiFormat?.value.trim();
    if (normalized === "anthropic" || normalized === "gemini") {
      return normalized;
    }
    return "openai";
  };

  const readUploadApiFormat = (): ArtifactApiFormat => {
    const normalized = elements.uploadApiFormat?.value.trim();
    if (normalized === "anthropic" || normalized === "gemini") {
      return normalized;
    }
    return "openai";
  };

  const getBatchFormatHint = (apiFormat: ArtifactApiFormat): string => {
    if (apiFormat === "anthropic") {
      return "Anthropic batches load staged JSONL rows shaped like `{custom_id, params}` and convert them into message-batch requests.";
    }
    if (apiFormat === "gemini") {
      return "Gemini batches accept either a staged JSONL file shaped like `{key, request}` per line or an inline JSON array shaped like `[{key?, request, metadata?}]`. Provide a fallback model when file rows omit `request.model`.";
    }
    return "OpenAI batches expect a staged JSONL file in OpenAI batch input format.";
  };

  const buildGeminiInlineRequestsTemplate = (modelValue?: string): string => {
    const normalizedModel = modelValue?.trim() || "gemini-2.5-flash";
    const requestModel = normalizedModel.startsWith("models/")
      ? normalizedModel
      : `models/${normalizedModel}`;
    return JSON.stringify(
      [
        {
          request: {
            contents: [
              {
                role: "user",
                parts: [{ text: "hello gemini" }],
              },
            ],
            model: requestModel,
          },
          metadata: {
            requestLabel: "row-1",
          },
        },
      ],
      null,
      2,
    );
  };

  const syncGeminiInlineRequestsTemplate = (options?: {
    forceValue?: boolean;
  }): void => {
    if (!elements.batchInlineRequests) {
      return;
    }
    const nextTemplate = buildGeminiInlineRequestsTemplate(
      elements.batchModel?.value,
    );
    elements.batchInlineRequests.placeholder = nextTemplate;
    const currentValue = elements.batchInlineRequests.value.trim();
    if (
      options?.forceValue ||
      !currentValue ||
      currentValue === lastGeminiInlineRequestsTemplate
    ) {
      elements.batchInlineRequests.value = nextTemplate;
    }
    lastGeminiInlineRequestsTemplate = nextTemplate;
  };

  const syncBatchComposerFormat = (
    apiFormat: ArtifactApiFormat,
    options?: {
      inputFileId?: string;
    },
  ): void => {
    if (elements.batchApiFormat) {
      elements.batchApiFormat.value = apiFormat;
    }
    if (elements.batchEndpoint) {
      const openaiMode = apiFormat === "openai";
      elements.batchEndpoint.disabled = !openaiMode;
      if (!openaiMode) {
        elements.batchEndpoint.value = "/v1/chat/completions";
      }
    }
    if (elements.batchInput) {
      elements.batchInput.required = apiFormat !== "gemini";
    }
    if (elements.batchInlineRequestsField && elements.batchInlineRequests) {
      const showInlineRequests = apiFormat === "gemini";
      elements.batchInlineRequestsField.hidden = !showInlineRequests;
      if (!showInlineRequests) {
        elements.batchInlineRequests.value = "";
        elements.batchInlineRequests.placeholder = "";
      } else {
        syncGeminiInlineRequestsTemplate();
      }
    }
    if (elements.batchModelField && elements.batchModel) {
      const showModel = apiFormat === "gemini";
      elements.batchModelField.hidden = !showModel;
      elements.batchModel.required = false;
      if (!showModel) {
        elements.batchModel.value = "";
      }
    }
    if (elements.batchDisplayNameField && elements.batchDisplayName) {
      const showDisplayName = apiFormat === "gemini";
      elements.batchDisplayNameField.hidden = !showDisplayName;
      if (!showDisplayName) {
        elements.batchDisplayName.value = "";
      } else if (!elements.batchDisplayName.value.trim()) {
        const inputFileId = options?.inputFileId?.trim() ?? elements.batchInput?.value.trim() ?? "";
        elements.batchDisplayName.value = inputFileId
          ? `gemini-${inputFileId}`
          : "gemini-batch";
      }
    }
    if (elements.batchHint) {
      elements.batchHint.textContent = getBatchFormatHint(apiFormat);
    }
  };

  const getUploadFormatHint = (apiFormat: ArtifactApiFormat): string => {
    if (apiFormat === "anthropic") {
      return "Anthropic staging keeps the file on the shared files surface but marks it as Anthropic-oriented so the batch composer can default correctly later.";
    }
    if (apiFormat === "gemini") {
      return "Gemini staging stores Gemini-specific metadata such as display name and MIME type so the inventory stays provider-aware.";
    }
    return "OpenAI uploads stage one file through the gateway files surface. Switch formats here when this artifact is meant for Anthropic or Gemini flows.";
  };

  const syncUploadComposerFormat = (apiFormat: ArtifactApiFormat): void => {
    if (elements.uploadApiFormat) {
      elements.uploadApiFormat.value = apiFormat;
    }
    if (elements.uploadDisplayNameField && elements.uploadDisplayName) {
      const showDisplayName = apiFormat === "gemini";
      elements.uploadDisplayNameField.hidden = !showDisplayName;
      if (!showDisplayName) {
        elements.uploadDisplayName.value = "";
      }
    }
    const uploadHint = document.getElementById("upload-format-hint");
    if (uploadHint) {
      uploadHint.textContent = getUploadFormatHint(apiFormat);
    }
  };

  const runWorkflowAction = async <T>({
    button,
    root,
    pendingLabel,
    pendingSummary,
    successSummary,
    action,
  }: {
    button?: HTMLButtonElement | null;
    root?: Element | DocumentFragment | null;
    pendingLabel: string;
    pendingSummary: DefinitionItem[];
    successSummary: (result: T) => DefinitionItem[];
    action: () => Promise<T>;
  }): Promise<T> => {
    setWorkflowSummary(pendingSummary);
    try {
      const result = await withBusyState({
        root,
        button,
        pendingLabel,
        action,
      });
      setWorkflowSummary(successSummary(result));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setWorkflowSummary([
        { label: "Workflow state", value: "Action failed" },
        { label: "Failed step", value: pendingSummary[0]?.value ?? "Unknown action" },
        { label: "Reason", value: extractErrorReason(message) },
      ]);
      throw error;
    }
  };

  const focusBatchComposer = (fileId: string): void => {
    if (!elements.batchInput) {
      navigateToPage("batches", { composeInputFileId: fileId });
      return;
    }
    const source = inventory.fileLookup.get(fileId);
    const preferredApiFormat =
      source?.api_format === "anthropic" || source?.api_format === "gemini"
        ? source.api_format
        : "openai";
    elements.batchInput.value = fileId;
    syncBatchComposerFormat(preferredApiFormat, { inputFileId: fileId });
    selection = { kind: "file", fileId };
    clearSelectionHandoff();
    resetContentSurface();
    syncSelectionRouteState(selection);
    setSummary([
      { label: "Selection", value: "Batch input ready" },
      { label: "File id", value: fileId },
      { label: "Purpose", value: String(source?.purpose ?? "batch") },
      { label: "Filename", value: String(source?.filename ?? fileId) },
      { label: "API format", value: preferredApiFormat },
      {
        label: "Next step",
        value: "Create batch",
        note: "The input field has been populated for the batch form.",
      },
    ]);
    setDetailSurface(
      "Composer handoff",
      [
        { label: "Detail surface", value: "Composer handoff" },
        { label: "Selected input", value: fileId },
        { label: "Endpoint target", value: "Choose an endpoint in the batch form" },
      ],
      `Selected ${fileId} as batch input.`,
      false,
    );
    setWorkflowSummary([
      { label: "Workflow state", value: "Batch input primed" },
      { label: "Input file", value: fileId },
      {
        label: "Next step",
        value: "Create batch",
        note: "The batch form is prefilled so you can queue a new job immediately.",
      },
    ]);
    updateInspectorActions();
    elements.batchInput.focus();
  };

  const previewFileContent = async (
    fileId: string,
    button: HTMLButtonElement | null,
    options?: {
      label?: string;
      support?: string;
      relatedBatch?: BatchRecord | null;
    },
  ): Promise<void> => {
    const source = inventory.fileLookup.get(fileId);
    const label = options?.label ?? "File content preview";
    setContentSurface(
      label,
      [
        { label: "Preview surface", value: label },
        { label: "File id", value: fileId },
        {
          label: "Loaded content",
          value: "Loading…",
          note: options?.support ?? String(source?.filename ?? fileId),
        },
      ],
      "Loading file content…",
      true,
    );
    clearMediaPreview();

    await runWorkflowAction({
      root: elements.actionNode,
      button,
      pendingLabel: "Loading…",
      pendingSummary: [
        { label: "Workflow state", value: "Loading preview" },
        { label: "Preview target", value: fileId },
        {
          label: "Surface",
          value: label,
          note: options?.support ?? String(source?.filename ?? fileId),
        },
      ],
      successSummary: (preview) => [
        { label: "Workflow state", value: "Preview ready" },
        { label: "Preview target", value: fileId },
        {
          label: "Surface",
          value: label,
          note: summarizePreviewOutcome(preview),
        },
        ...(preview.handoffRequestId
          ? [
              {
                label: "Downstream handoff",
                value:
                  (preview.handoffRequestCount ?? 0) > 1
                    ? "Sample request scoped"
                    : "Request scoped",
                note:
                  (preview.handoffRequestCount ?? 0) > 1
                    ? `Traffic and Logs can open with sample request ${preview.handoffRequestId} from ${preview.handoffRequestCount} decoded result rows.`
                    : `Traffic and Logs can open directly with request ${preview.handoffRequestId}.`,
              },
            ]
          : []),
      ],
      action: async () => {
        const bytes = await fetchFileContent(
          app,
          fileId,
          source?.content_path ?? undefined,
        );
        const preview = buildFilePreview(bytes, String(source?.filename ?? fileId));
        if (preview.handoffRequestId && options?.relatedBatch) {
          selection = {
            kind: "batch",
            batchId: String(options.relatedBatch.id ?? selection.batchId ?? ""),
            inputFileId:
              String(options.relatedBatch.input_file_id ?? selection.inputFileId ?? "") ||
              undefined,
            outputFileId: fileId,
            handoffRequestId: preview.handoffRequestId,
            handoffRequestCount: preview.handoffRequestCount,
          };
          updateInspectorActions();
        } else if (selection.kind === "batch") {
          clearSelectionHandoff();
          updateInspectorActions();
        }
        setContentSurface(
          label,
          buildContentPreviewSummary(preview, fileId, label, {
            support: options?.support ?? String(source?.filename ?? fileId),
            file: source,
            relatedBatch: options?.relatedBatch ?? null,
          }),
          preview.textFallback,
          true,
        );
        if (preview.kind === "image") {
          clearMediaPreview();
          const blobBytes = new Uint8Array(bytes.byteLength);
          blobBytes.set(bytes);
          const blob = new Blob([blobBytes], { type: preview.mimeType });
          previewObjectUrl = URL.createObjectURL(blob);
          const figure = document.createElement("figure");
          figure.className = "surface";
          const image = document.createElement("img");
          image.alt = String(preview.filename ?? fileId);
          image.src = previewObjectUrl;
          image.style.display = "block";
          image.style.maxWidth = "100%";
          image.style.height = "auto";
          image.style.borderRadius = "12px";
          figure.append(image);
          elements.mediaNode.replaceChildren(figure);
        } else {
          clearMediaPreview();
        }
        return preview;
      },
    });
  };

  const downloadFileContent = async (
    fileId: string,
    filename: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
    await runWorkflowAction({
      root: button?.parentElement ?? elements.actionNode,
      button,
      pendingLabel: "Downloading…",
      pendingSummary: [
        { label: "Workflow state", value: "Downloading output" },
        { label: "File id", value: fileId },
        { label: "Filename", value: filename },
      ],
      successSummary: () => [
        { label: "Workflow state", value: "Output downloaded" },
        { label: "File id", value: fileId },
        { label: "Filename", value: filename },
      ],
      action: async () => {
        const source = inventory.fileLookup.get(fileId);
        const bytes = await fetchFileContent(
          app,
          fileId,
          source?.download_path ?? source?.content_path ?? undefined,
        );
        const mimeType = buildFilePreview(bytes, filename).mimeType;
        const blobBytes = new Uint8Array(bytes.byteLength);
        blobBytes.set(bytes);
        const objectUrl = URL.createObjectURL(
          new Blob([blobBytes], { type: mimeType }),
        );
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = filename;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      },
    });
  };

  const resolveDownloadFilename = (fileId: string): string => {
    const source = inventory.fileLookup.get(fileId);
    const filename = String(source?.filename ?? "").trim();
    return filename || `file-${fileId}.bin`;
  };

  const inspectFile = async (
    fileId: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
    const shouldRefreshPage = button !== null;
    await runWorkflowAction({
      root: elements.actionNode,
      button,
      pendingLabel: "Loading…",
      pendingSummary: [
        { label: "Workflow state", value: "Loading file metadata" },
        { label: "Selected file", value: fileId },
        { label: "Next step", value: "Populate inspector" },
      ],
      successSummary: (payload) => {
        const source = cacheFileRecord(payload);
        const linkedBatches = getLinkedBatchesForFile(fileId, data.batches);
        const latestBatch = linkedBatches[0];
        return [
          { label: "Workflow state", value: "File selected" },
          { label: "Selected file", value: fileId },
          {
            label: "Batch context",
            value: `${linkedBatches.length} linked batch${linkedBatches.length === 1 ? "" : "es"}`,
            note: latestBatch
              ? `Latest: ${String(latestBatch.id ?? "unknown")} (${String(latestBatch.status ?? "unknown")})`
              : "No linked batch records yet.",
          },
          {
            label: "Next step",
            value: linkedBatches.length
              ? "Inspect linked batch or preview content"
              : "Preview content or use for batch",
            note: linkedBatches.some((batch) => Boolean(String(batch.output_file_id ?? "")))
              ? "Preview the latest linked output to unlock request-scoped Traffic and Logs handoff."
              : String(source.filename ?? fileId),
          },
        ];
      },
      action: async () => {
        const payload = await fetchFileMetadata(app, fileId);
        const source = cacheFileRecord(payload);
        const linkedBatches = getLinkedBatchesForFile(fileId, data.batches);
        const readyOutputs = linkedBatches.filter((batch) =>
          Boolean(String(batch.output_file_id ?? "")),
        ).length;
        selection = { kind: "file", fileId };
        clearSelectionHandoff();
        resetContentSurface();
        syncSelectionRouteState(selection);
        setSummary([
          { label: "Selection", value: "File" },
          { label: "File id", value: fileId },
          { label: "Purpose", value: String(source.purpose ?? "user_data") },
          { label: "Filename", value: String(source.filename ?? fileId) },
          {
            label: "Created",
            value: formatTimestamp(source.created_at),
            note: formatBytes(source.bytes),
          },
          {
            label: "Batch linkage",
            value: `${linkedBatches.length} linked batch${linkedBatches.length === 1 ? "" : "es"}`,
            note: readyOutputs
              ? `${readyOutputs} output file${readyOutputs === 1 ? "" : "s"} ready`
              : "No completed output linked yet.",
          },
        ]);
        setDetailSurface(
          "Selection metadata snapshot",
          [
            { label: "Detail surface", value: "File metadata" },
            { label: "Linked batches", value: String(linkedBatches.length) },
            { label: "Stored bytes", value: formatBytes(source.bytes) },
            { label: "Status", value: String(source.status ?? "processed") },
          ],
          JSON.stringify(payload, null, 2),
          true,
        );
        updateInspectorActions();
        return payload;
      },
    });
    if (shouldRefreshPage) {
      await app.render(page);
    }
  };

  const inspectBatch = async (
    batchId: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
    const shouldRefreshPage = button !== null;
    await runWorkflowAction({
      root: elements.actionNode,
      button,
      pendingLabel: "Loading…",
      pendingSummary: [
        { label: "Workflow state", value: "Loading batch metadata" },
        { label: "Selected batch", value: batchId },
        { label: "Next step", value: "Populate lifecycle inspector" },
      ],
      successSummary: (payload) => {
        const source = cacheBatchRecord(payload);
        return [
          { label: "Workflow state", value: "Batch selected" },
          { label: "Selected batch", value: batchId },
          {
            label: "Lifecycle",
            value: humanizeBatchLifecycle(source.status),
            note: summarizeBatchRequestCounts(source.request_counts),
          },
          {
            label: "Next step",
            value: selection.outputFileId
              ? "Preview output or inspect input"
              : "Preview input and refresh status",
            note: selection.outputFileId
              ? "Preview one output to unlock request-scoped Traffic and Logs handoff."
              : buildBatchActionHint(source),
          },
        ];
      },
      action: async () => {
        const payload = await fetchBatchMetadata(app, batchId);
        const source = cacheBatchRecord(payload);
        const inputFileId = String(source.input_file_id ?? "");
        const outputFileId = String(source.output_file_id ?? "");
        selection = {
          kind: "batch",
          batchId,
          inputFileId: inputFileId || undefined,
          outputFileId: outputFileId || undefined,
        };
        clearSelectionHandoff();
        resetContentSurface();
        syncSelectionRouteState(selection);
        setSummary([
          { label: "Selection", value: "Batch" },
          { label: "Batch id", value: batchId },
          { label: "Status", value: String(source.status ?? "unknown") },
          { label: "Endpoint", value: String(source.endpoint ?? "n/a") },
          {
            label: "Output file",
            value: outputFileId || "n/a",
            note: inputFileId || "no input file",
          },
        ]);
        setDetailSurface(
          "Selection metadata snapshot",
          [
            { label: "Detail surface", value: "Batch metadata" },
            { label: "Lifecycle posture", value: humanizeBatchLifecycle(source.status) },
            { label: "Input file", value: inputFileId || "missing" },
            { label: "Output file", value: outputFileId || "not ready" },
            { label: "Requests", value: summarizeBatchRequestCounts(source.request_counts) },
          ],
          JSON.stringify(payload, null, 2),
          true,
        );
        updateInspectorActions();
        return payload;
      },
    });
    if (shouldRefreshPage) {
      await app.render(page);
    }
  };

  updateInspectorActions();
  resetContentSurface();
  syncUploadComposerFormat(readUploadApiFormat());
  setDetailSurface(
    "Selection metadata snapshot",
    [
      { label: "Detail surface", value: "Idle" },
      { label: "Loaded object", value: "No file or batch metadata loaded" },
    ],
    "No selection yet.",
    false,
  );

  elements.filtersForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      query?: HTMLInputElement;
      purpose?: HTMLSelectElement;
      batch_status?: HTMLSelectElement;
      endpoint?: HTMLSelectElement;
      file_sort?: HTMLSelectElement;
    };

    const nextFilters: FilesBatchesFilters = {
      query: fields.query?.value.trim() ?? "",
      purpose: fields.purpose?.value ?? "",
      batchStatus: fields.batch_status?.value ?? "",
      endpoint: fields.endpoint?.value ?? "",
      fileSort:
        (fields.file_sort?.value as FilesBatchesFilters["fileSort"] | undefined) ??
        filters.fileSort,
    };
    window.history.replaceState(
      {},
      "",
      buildFilesBatchesUrl(nextFilters, undefined, page),
    );
    void app.render(page);
  });

  elements.uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      api_format: HTMLSelectElement;
      display_name?: HTMLInputElement;
      purpose: HTMLSelectElement;
      file: HTMLInputElement;
    };
    const upload = fields.file.files?.[0];
    const apiFormat = readUploadApiFormat();
    if (!upload) {
      app.pushAlert("Choose a file before uploading.", "warn");
      return;
    }
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');

    await runWorkflowAction({
      root: form,
      button,
      pendingLabel: "Uploading…",
      pendingSummary: [
        { label: "Workflow state", value: "Uploading file" },
        { label: "API format", value: apiFormat },
        { label: "Purpose", value: fields.purpose.value },
        { label: "Source", value: upload.name, note: formatBytes(upload.size) },
      ],
      successSummary: (response) => [
        { label: "Workflow state", value: "File uploaded" },
        { label: "File id", value: String(response.id ?? "unknown") },
        { label: "API format", value: String(response.api_format ?? apiFormat) },
        {
          label: "Next step",
          value: "Inspect or open batches",
          note: "The page refreshes into the new file selection so the files inspector stays on the fresh upload.",
        },
      ],
      action: async () => {
        const response = await uploadFile(app, {
          apiFormat,
          purpose: fields.purpose.value,
          file: upload,
          displayName: fields.display_name?.value,
        });
        app.queueAlert(`Uploaded file ${String(response.id ?? "")}.`, "info");
        replaceStateForPage(page, {
          selectedFileId: String(response.id ?? ""),
        });
        await app.render(page);
        return response;
      },
    });
  });

  elements.uploadApiFormat?.addEventListener("change", () => {
    syncUploadComposerFormat(readUploadApiFormat());
  });

  elements.batchForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      api_format: HTMLSelectElement;
      display_name: HTMLInputElement;
      endpoint: HTMLSelectElement;
      input_file_id: HTMLInputElement;
      metadata: HTMLTextAreaElement;
      model: HTMLInputElement;
      requests?: HTMLTextAreaElement;
    };
    const apiFormat = readBatchApiFormat();
    const metadataText = fields.metadata.value.trim();
    const metadata = metadataText
      ? safeJsonParse<Record<string, unknown> | typeof INVALID_JSON>(
          metadataText,
          INVALID_JSON,
        )
      : undefined;
    const inlineRequestsText = fields.requests?.value.trim() ?? "";
    const inlineRequests = inlineRequestsText
      ? safeJsonParse<Array<Record<string, unknown>> | typeof INVALID_JSON>(
          inlineRequestsText,
          INVALID_JSON,
        )
      : undefined;
    if (
      metadata === INVALID_JSON ||
      (metadata !== undefined &&
        (metadata === null || Array.isArray(metadata) || typeof metadata !== "object"))
    ) {
      app.pushAlert("Batch metadata must be a JSON object.", "danger");
      return;
    }
    if (
      inlineRequests === INVALID_JSON ||
      (inlineRequests !== undefined && !Array.isArray(inlineRequests))
    ) {
      app.pushAlert("Inline Gemini requests must be a JSON array.", "danger");
      return;
    }
    const inputFileId = fields.input_file_id.value.trim();
    if (apiFormat === "gemini") {
      if (!inputFileId && !inlineRequests?.length) {
        app.pushAlert(
          "Gemini batches need either a staged input file id or inline requests.",
          "warn",
        );
        return;
      }
    } else if (!inputFileId) {
      app.pushAlert("Choose an input file before creating the batch.", "warn");
      return;
    }
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');

    await runWorkflowAction({
      root: form,
      button,
      pendingLabel: "Creating…",
      pendingSummary: [
        { label: "Workflow state", value: "Creating batch" },
        { label: "API format", value: apiFormat },
        {
          label: "Input source",
          value: inputFileId
            ? `file ${inputFileId}`
            : inlineRequests?.length
              ? `${inlineRequests.length} inline request${inlineRequests.length === 1 ? "" : "s"}`
              : "missing",
        },
        {
          label: "Endpoint",
          value:
            apiFormat === "openai"
              ? fields.endpoint.value
              : "/v1/chat/completions",
        },
      ],
      successSummary: (response) => [
        { label: "Workflow state", value: "Batch created" },
        { label: "Batch id", value: String(response.id ?? "unknown") },
        { label: "API format", value: String(response.api_format ?? apiFormat) },
        {
          label: "Next step",
          value: "Inspect lifecycle",
          note: "The page refreshes into the new batch selection so output polling starts from the focused batches inspector.",
        },
      ],
      action: async () => {
        const response = await createBatch(app, {
          apiFormat,
          endpoint:
            apiFormat === "openai"
              ? fields.endpoint.value
              : "/v1/chat/completions",
          inputFileId,
          metadata,
          displayName: fields.display_name.value.trim() || undefined,
          model: fields.model.value.trim() || undefined,
          requests: inlineRequests,
        });
        cacheBatchRecord(response);
        app.queueAlert(
          `Created ${String(response.api_format ?? apiFormat)} batch ${String(response.id ?? "")}.`,
          "info",
        );
        replaceStateForPage(page, {
          composeInputFileId: inputFileId,
          selectedBatchId: String(response.id ?? ""),
        });
        await app.render(page);
        return response;
      },
    });
  });

  elements.actionNode.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>("[data-inspector-action]");
    if (!button) {
      return;
    }
    const action = button.dataset.inspectorAction;
    if (!action) {
      return;
    }
    if (action === "inspect-file" && selection.fileId) {
      await inspectFile(selection.fileId, button);
      return;
    }
    if (action === "use-file" && selection.fileId) {
      focusBatchComposer(selection.fileId);
      return;
    }
    if (action === "preview-file" && selection.fileId) {
      await previewFileContent(selection.fileId, button);
      return;
    }
    if (action === "download-file" && selection.fileId) {
      await downloadFileContent(
        selection.fileId,
        resolveDownloadFilename(selection.fileId),
        button,
      );
      return;
    }
    if (action === "inspect-batch" && selection.batchId) {
      await inspectBatch(selection.batchId, button);
      return;
    }
    if (action === "batch-input" && selection.inputFileId) {
      await inspectFile(selection.inputFileId, button);
      return;
    }
    if (action === "preview-batch-input" && selection.inputFileId && selection.batchId) {
      await previewFileContent(selection.inputFileId, button, {
        label: "Batch input preview",
        support: `Batch ${selection.batchId}`,
        relatedBatch: inventory.batchLookup.get(selection.batchId) ?? null,
      });
      return;
    }
    if (action === "use-batch-input" && selection.inputFileId) {
      focusBatchComposer(selection.inputFileId);
      return;
    }
    if (action === "batch-output" && selection.outputFileId && selection.batchId) {
      await previewFileContent(selection.outputFileId, button, {
        label: "Batch output preview",
        support: `Batch ${selection.batchId}`,
        relatedBatch: inventory.batchLookup.get(selection.batchId) ?? null,
      });
      return;
    }
    if (action === "inspect-output-file" && selection.outputFileId) {
      await inspectFile(selection.outputFileId, button);
      return;
    }
    if (action === "inspect-linked-batch" && selection.fileId) {
      const latestBatch = getLatestLinkedBatch(selection.fileId, data.batches);
      if (latestBatch) {
        await inspectBatch(String(latestBatch.id ?? ""), button);
      }
      return;
    }
    if (action === "preview-linked-output" && selection.fileId) {
      const latestOutputBatch = getLatestOutputBatch(selection.fileId, data.batches);
      const outputFileId = String(latestOutputBatch?.output_file_id ?? "");
      if (!outputFileId) {
        return;
      }
      selection = {
        kind: "batch",
        batchId: String(latestOutputBatch?.id ?? ""),
        inputFileId: String(latestOutputBatch?.input_file_id ?? "") || undefined,
        outputFileId,
      };
      clearSelectionHandoff();
      syncSelectionRouteState(selection);
      setSummary([
        { label: "Selection", value: "Linked batch output" },
        { label: "Output file", value: outputFileId },
        { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
        { label: "Endpoint", value: String(latestOutputBatch?.endpoint ?? "n/a") },
      ]);
      setDetailSurface(
        "Selection metadata snapshot",
        [
          { label: "Detail surface", value: "Latest linked output" },
          { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
          { label: "Output file", value: outputFileId },
          {
            label: "Requests",
            value: summarizeBatchRequestCounts(latestOutputBatch?.request_counts),
          },
        ],
        JSON.stringify(
          {
            latest_linked_batch: latestOutputBatch,
            output_file_id: outputFileId,
          },
          null,
          2,
        ),
        true,
      );
      updateInspectorActions();
      await previewFileContent(outputFileId, button, {
        label: "Latest linked output",
        support: `Batch ${String(latestOutputBatch?.id ?? "unknown")}`,
        relatedBatch: latestOutputBatch ?? null,
      });
    }
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-view]").forEach((item) => {
    item.addEventListener("click", async () => {
      await inspectFile(
        item.dataset.fileView ?? "",
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-use]").forEach((item) => {
    item.addEventListener("click", () => {
      const fileId = item.dataset.fileUse;
      if (!fileId) {
        return;
      }
      focusBatchComposer(fileId);
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-content]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.fileContent;
      if (!fileId) {
        return;
      }
      selection = { kind: "file", fileId };
      clearSelectionHandoff();
      syncSelectionRouteState(selection);
      updateInspectorActions();
      await previewFileContent(
        fileId,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-download]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.fileDownload;
      if (!fileId) {
        return;
      }
      const filename =
        item.dataset.fileDownloadName?.trim() || resolveDownloadFilename(fileId);
      await downloadFileContent(
        fileId,
        filename,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-delete]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.fileDelete;
      if (!fileId) {
        return;
      }
      if (!window.confirm(`Delete file ${fileId}?`)) {
        return;
      }
      await withBusyState({
        root: item.parentElement,
        button: item instanceof HTMLButtonElement ? item : null,
        pendingLabel: "Deleting…",
        action: async () => {
          const source = inventory.fileLookup.get(fileId);
          if (!source?.delete_path) {
            app.pushAlert(
              `Delete is unavailable for ${fileId} in the current API format.`,
              "warn",
            );
            return;
          }
          setWorkflowSummary([
            { label: "Workflow state", value: "Deleting file" },
            { label: "File id", value: fileId },
            { label: "Next step", value: "Refresh inventory" },
          ]);
          await deleteFile(app, fileId, source.delete_path);
          app.queueAlert(`Deleted file ${fileId}.`, "info");
          replaceStateForPage(page, undefined);
          await app.render(page);
        },
      });
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-view]").forEach((item) => {
    item.addEventListener("click", async () => {
      await inspectBatch(
        item.dataset.batchView ?? "",
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-output]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.batchOutput;
      if (!fileId) {
        return;
      }
      const batch = data.batches.find(
        (entry) => String(entry.output_file_id ?? "") === fileId,
      );
      selection = {
        kind: "batch",
        batchId: String(batch?.id ?? ""),
        inputFileId: String(batch?.input_file_id ?? "") || undefined,
        outputFileId: fileId,
      };
      clearSelectionHandoff();
      syncSelectionRouteState(selection);
      setSummary([
        { label: "Selection", value: "Batch output" },
        { label: "Output file", value: fileId },
        { label: "Batch id", value: String(batch?.id ?? "unknown") },
        { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
      ]);
      setDetailSurface(
        "Selection metadata snapshot",
        [
          { label: "Detail surface", value: "Batch output handoff" },
          { label: "Batch id", value: String(batch?.id ?? "unknown") },
          { label: "Output file", value: fileId },
        ],
        JSON.stringify(
          {
            batch_output_handoff: batch ?? null,
            output_file_id: fileId,
          },
          null,
          2,
        ),
        true,
      );
      updateInspectorActions();
      await previewFileContent(
        fileId,
        item instanceof HTMLButtonElement ? item : null,
        {
          label: "Batch output preview",
          support: `Batch ${String(batch?.id ?? "unknown")}`,
          relatedBatch: batch ?? null,
        },
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-download]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.batchDownload;
      if (!fileId) {
        return;
      }
      const filename =
        item.dataset.batchDownloadName?.trim() || `batch-output-${fileId}.jsonl`;
      await downloadFileContent(
        fileId,
        filename,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-input]").forEach((item) => {
    item.addEventListener("click", async () => {
      const batchId = item.dataset.batchInput;
      const batch = inventory.batchLookup.get(batchId ?? "");
      const inputFileId = String(batch?.input_file_id ?? "");
      if (!inputFileId) {
        return;
      }
      await inspectFile(
        inputFileId,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent
    .querySelectorAll<HTMLElement>("[data-batch-input-preview]")
    .forEach((item) => {
      item.addEventListener("click", async () => {
        const batchId = item.dataset.batchInputPreview;
        const batch = inventory.batchLookup.get(batchId ?? "");
        const inputFileId = String(batch?.input_file_id ?? "");
        if (!inputFileId) {
          return;
        }
        selection = {
          kind: "batch",
          batchId: String(batch?.id ?? ""),
          inputFileId: inputFileId || undefined,
          outputFileId: String(batch?.output_file_id ?? "") || undefined,
        };
        clearSelectionHandoff();
        syncSelectionRouteState(selection);
        updateInspectorActions();
        await previewFileContent(
          inputFileId,
          item instanceof HTMLButtonElement ? item : null,
          {
            label: "Batch input preview",
            support: `Batch ${String(batch?.id ?? "unknown")}`,
            relatedBatch: batch ?? null,
          },
        );
      });
    });

  elements.batchApiFormat?.addEventListener("change", () => {
    syncBatchComposerFormat(readBatchApiFormat(), {
      inputFileId: elements.batchInput?.value.trim() ?? "",
    });
  });

  elements.batchModel?.addEventListener("input", () => {
    if (readBatchApiFormat() !== "gemini") {
      return;
    }
    syncGeminiInlineRequestsTemplate();
  });

  const routeState = readFilesBatchesRouteState(page);
  if (routeState.composeInputFileId && elements.batchInput) {
    elements.batchInput.value = routeState.composeInputFileId;
    const source = inventory.fileLookup.get(routeState.composeInputFileId);
    const apiFormat =
      source?.api_format === "anthropic" || source?.api_format === "gemini"
        ? source.api_format
        : readBatchApiFormat();
    syncBatchComposerFormat(apiFormat, {
      inputFileId: routeState.composeInputFileId,
    });
    setWorkflowSummary([
      { label: "Workflow state", value: "Batch composer primed" },
      { label: "API format", value: apiFormat },
      { label: "Input file", value: routeState.composeInputFileId },
      { label: "Next step", value: "Review format settings and create batch" },
    ]);
  } else {
    syncBatchComposerFormat(readBatchApiFormat());
  }
  if (
    routeState.selectedBatchId &&
    inventory.batchLookup.has(routeState.selectedBatchId)
  ) {
    void inspectBatch(routeState.selectedBatchId, null);
    return;
  }
  if (
    routeState.selectedFileId &&
    inventory.fileLookup.has(routeState.selectedFileId)
  ) {
    void inspectFile(routeState.selectedFileId, null);
  }
}
