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
  firstErrorLine,
  getLatestLinkedBatch,
  getLatestOutputBatch,
  getLinkedBatchesForFile,
  humanizeBatchLifecycle,
  readFilesBatchesRouteState,
  renderInspectorActions,
  summarizeBatchRequestCounts,
  summarizePreviewOutcome,
} from "./serializers.js";
import type {
  BatchRecord,
  DefinitionItem,
  FilesBatchesFilters,
  FilesBatchesInventory,
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
}

export function bindFilesBatchesPage(options: BindFilesBatchesPageOptions): void {
  const { app, data, elements, filters, inventory } = options;

  let selection: InspectorSelection = { kind: "idle" };
  let previewObjectUrl: string | null = null;

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
        { label: "Reason", value: firstErrorLine(message) },
      ]);
      throw error;
    }
  };

  const focusBatchComposer = (fileId: string): void => {
    const source = inventory.fileLookup.get(fileId);
    elements.batchInput.value = fileId;
    selection = { kind: "file", fileId };
    clearSelectionHandoff();
    resetContentSurface();
    setSummary([
      { label: "Selection", value: "Batch input ready" },
      { label: "File id", value: fileId },
      { label: "Purpose", value: String(source?.purpose ?? "batch") },
      { label: "Filename", value: String(source?.filename ?? fileId) },
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
        const bytes = await fetchFileContent(app, fileId);
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
          const blobBytes = new Uint8Array(bytes.byteLength);
          blobBytes.set(bytes);
          const blob = new Blob([blobBytes], { type: preview.mimeType });
          previewObjectUrl = URL.createObjectURL(blob);
          elements.mediaNode.innerHTML = `
            <figure class="surface">
              <img
                alt="${preview.filename}"
                src="${previewObjectUrl}"
                style="display:block;max-width:100%;height:auto;border-radius:12px;"
              />
            </figure>
          `;
        } else {
          clearMediaPreview();
        }
        return preview;
      },
    });
  };

  const inspectFile = async (
    fileId: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
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
        const source = inventory.fileLookup.get(fileId) ?? payload;
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
        const source = inventory.fileLookup.get(fileId) ?? payload;
        const linkedBatches = getLinkedBatchesForFile(fileId, data.batches);
        const readyOutputs = linkedBatches.filter((batch) =>
          Boolean(String(batch.output_file_id ?? "")),
        ).length;
        selection = { kind: "file", fileId };
        clearSelectionHandoff();
        resetContentSurface();
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
  };

  const inspectBatch = async (
    batchId: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
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
        const source = inventory.batchLookup.get(batchId) ?? payload;
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
        const source = inventory.batchLookup.get(batchId) ?? payload;
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
  };

  updateInspectorActions();
  resetContentSurface();
  setDetailSurface(
    "Selection metadata snapshot",
    [
      { label: "Detail surface", value: "Idle" },
      { label: "Loaded object", value: "No file or batch metadata loaded" },
    ],
    "No selection yet.",
    false,
  );

  elements.refreshButton.addEventListener("click", () => {
    void app.render("files-batches");
  });

  elements.resetButton.addEventListener("click", () => {
    window.history.replaceState({}, "", "/admin/files-batches");
    void app.render("files-batches");
  });

  elements.filtersForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      query: HTMLInputElement;
      purpose: HTMLSelectElement;
      batch_status: HTMLSelectElement;
      endpoint: HTMLSelectElement;
    };

    const nextFilters: FilesBatchesFilters = {
      query: fields.query.value.trim(),
      purpose: fields.purpose.value,
      batchStatus: fields.batch_status.value,
      endpoint: fields.endpoint.value,
    };
    window.history.replaceState({}, "", buildFilesBatchesUrl(nextFilters));
    void app.render("files-batches");
  });

  elements.uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      purpose: HTMLSelectElement;
      file: HTMLInputElement;
    };
    const upload = fields.file.files?.[0];
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
        { label: "Purpose", value: fields.purpose.value },
        { label: "Source", value: upload.name, note: formatBytes(upload.size) },
      ],
      successSummary: (response) => [
        { label: "Workflow state", value: "File uploaded" },
        { label: "File id", value: String(response.id ?? "unknown") },
        {
          label: "Next step",
          value: "Inspect or use for batch",
          note: "The page refreshes into the new file selection so the inspector stays on the fresh upload.",
        },
      ],
      action: async () => {
        const response = await uploadFile(app, fields.purpose.value, upload);
        app.queueAlert(`Uploaded file ${String(response.id ?? "")}.`, "info");
        const routeState = readFilesBatchesRouteState();
        window.history.replaceState(
          {},
          "",
          buildFilesBatchesUrl(filters, {
            ...routeState,
            selectedFileId: String(response.id ?? ""),
            composeInputFileId: String(response.id ?? ""),
            selectedBatchId: "",
          }),
        );
        await app.render("files-batches");
        return response;
      },
    });
  });

  elements.batchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      endpoint: HTMLSelectElement;
      input_file_id: HTMLInputElement;
      metadata: HTMLTextAreaElement;
    };
    const metadataText = fields.metadata.value.trim();
    const metadata = metadataText
      ? safeJsonParse<Record<string, unknown> | typeof INVALID_JSON>(
          metadataText,
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
        { label: "Input file", value: fields.input_file_id.value.trim() || "missing" },
        { label: "Endpoint", value: fields.endpoint.value },
      ],
      successSummary: (response) => [
        { label: "Workflow state", value: "Batch created" },
        { label: "Batch id", value: String(response.id ?? "unknown") },
        {
          label: "Next step",
          value: "Inspect lifecycle",
          note: "The page refreshes into the new batch selection so output polling starts from the inspector.",
        },
      ],
      action: async () => {
        const response = await createBatch(app, {
          endpoint: fields.endpoint.value,
          inputFileId: fields.input_file_id.value.trim(),
          metadata,
        });
        app.queueAlert(
          `Created batch ${String(response.id ?? "")} for ${String(response.endpoint ?? "")}.`,
          "info",
        );
        const routeState = readFilesBatchesRouteState();
        window.history.replaceState(
          {},
          "",
          buildFilesBatchesUrl(filters, {
            ...routeState,
            selectedBatchId: String(response.id ?? ""),
            selectedFileId: "",
          }),
        );
        await app.render("files-batches");
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
      updateInspectorActions();
      await previewFileContent(
        fileId,
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
          setWorkflowSummary([
            { label: "Workflow state", value: "Deleting file" },
            { label: "File id", value: fileId },
            { label: "Next step", value: "Refresh inventory" },
          ]);
          await deleteFile(app, fileId);
          app.queueAlert(`Deleted file ${fileId}.`, "info");
          await app.render("files-batches");
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

  const routeState = readFilesBatchesRouteState();
  if (routeState.composeInputFileId) {
    elements.batchInput.value = routeState.composeInputFileId;
    setWorkflowSummary([
      { label: "Workflow state", value: "Batch composer primed" },
      { label: "Input file", value: routeState.composeInputFileId },
      { label: "Next step", value: "Choose endpoint and create batch" },
    ]);
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
