import type { AdminApp } from "../app.js";
import { withBusyState } from "../forms.js";
import { card, kpi, pill, renderDefinitionList } from "../templates.js";
import {
  asArray,
  escapeHtml,
  formatBytes,
  formatTimestamp,
  safeJsonParse,
} from "../utils.js";

interface FilesBatchesFilters {
  query: string;
  purpose: string;
  batchStatus: string;
  endpoint: string;
}

interface FilesBatchesRouteState {
  selectedFileId: string;
  selectedBatchId: string;
  composeInputFileId: string;
}

interface FilePreview {
  kind: "text" | "image" | "binary";
  filename: string;
  mimeType: string;
  textFallback: string;
  byteLength: number;
  lineCount: number;
  formatLabel: string;
  formatNote: string;
  contentKind?: string;
  contentKindNote?: string;
  sampleLabel?: string;
  sampleValue?: string;
  sampleNote?: string;
  dimensionsNote?: string;
}

interface DefinitionItem {
  label: string;
  value: string;
  note?: string;
}

interface InspectorSelection {
  kind: "idle" | "file" | "batch";
  fileId?: string;
  batchId?: string;
  inputFileId?: string;
  outputFileId?: string;
}

type FileRecord = Record<string, unknown>;
type BatchRecord = Record<string, unknown>;

const INVALID_JSON = "__invalid__";

export async function renderFilesBatches(app: AdminApp, token: number): Promise<void> {
  const filters = readFilesBatchesFilters();
  const [filesPayload, batchesPayload] = await Promise.all([
    app.api.json<Record<string, unknown>>("/v1/files?order=desc&limit=100", {}, true),
    app.api.json<Record<string, unknown>>("/v1/batches?limit=100", {}, true),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const files = asArray<FileRecord>(filesPayload.data);
  const batches = asArray<BatchRecord>(batchesPayload.data);
  const filteredFiles = files.filter((item) => matchesFile(item, filters));
  const filteredBatches = batches.filter((item) => matchesBatch(item, filters));
  const attentionBatches = filteredBatches.filter((batch) =>
    isAttentionBatchStatus(batch.status),
  ).length;
  const outputReadyBatches = filteredBatches.filter((batch) =>
    Boolean(String(batch.output_file_id ?? "")),
  ).length;
  const fileLookup = new Map(files.map((item) => [String(item.id ?? ""), item]));
  const batchLookup = new Map(batches.map((item) => [String(item.id ?? ""), item]));

  app.setHeroActions(`
    <button class="button button--secondary" id="reset-files-batches-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-files-batches" type="button">Refresh inventory</button>
    <a class="button" href="/admin/playground">Open playground</a>
  `);

  app.setContent(`
    ${kpi("Files shown", `${filteredFiles.length}/${files.length}`)}
    ${kpi("Batches shown", `${filteredBatches.length}/${batches.length}`)}
    ${kpi("Output ready", outputReadyBatches)}
    ${kpi("Needs attention", attentionBatches)}
    ${card(
      "Inventory filters",
      `
        <form id="files-batches-filters-form" class="stack">
          <div class="quad-grid">
            <label class="field">
              <span>Search</span>
              <input name="query" value="${escapeHtml(filters.query)}" placeholder="Filter by id, filename, or metadata label" />
            </label>
            <label class="field">
              <span>File purpose</span>
              <select name="purpose">
                ${renderSelectOptions(filters.purpose, uniqueOptions(files.map((item) => item.purpose)))}
              </select>
            </label>
            <label class="field">
              <span>Batch status</span>
              <select name="batch_status">
                ${renderSelectOptions(filters.batchStatus, uniqueOptions(batches.map((item) => item.status)))}
              </select>
            </label>
            <label class="field">
              <span>Endpoint</span>
              <select name="endpoint">
                ${renderSelectOptions(filters.endpoint, uniqueOptions(batches.map((item) => item.endpoint)))}
              </select>
            </label>
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Apply filters</button>
            <span class="muted">Filters work on the loaded gateway inventory so inspection stays local and immediate.</span>
          </div>
        </form>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Upload file",
      `
        <form id="files-upload-form" class="stack">
          <label class="field">
            <span>Purpose</span>
            <select name="purpose">
              <option value="batch">batch</option>
              <option value="assistants">assistants</option>
              <option value="user_data">user_data</option>
            </select>
          </label>
          <label class="field">
            <span>File</span>
            <input name="file" type="file" required />
          </label>
          <div class="banner">Uploads go through the OpenAI-compatible gateway surface and use the gateway API key from the rail.</div>
          <button class="button" type="submit">Upload file</button>
        </form>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Create batch",
      `
        <form id="batch-create-form" class="stack">
          <label class="field">
            <span>Endpoint</span>
            <select name="endpoint">
              <option value="/v1/chat/completions">/v1/chat/completions</option>
              <option value="/v1/responses">/v1/responses</option>
              <option value="/v1/embeddings">/v1/embeddings</option>
            </select>
          </label>
          <label class="field"><span>Input file id</span><input id="batch-input-file-id" name="input_file_id" placeholder="file-..." required /></label>
          <label class="field"><span>Metadata (optional JSON object)</span><textarea name="metadata" placeholder='{"label":"nightly-import"}'></textarea></label>
          <div class="banner banner--warn">Batch creation expects an uploaded JSONL file in OpenAI batch input format.</div>
          <button class="button" type="submit">Create batch job</button>
        </form>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Inspector",
      `
        <div class="surface">
          <div class="stack">
            <div id="files-batches-summary">
              ${renderDefinitionList(buildIdleSelectionSummary(filteredFiles.length, files.length, filteredBatches.length, batches.length, filters), "No selection yet.")}
            </div>
            <div id="files-batches-workflow">
              ${renderDefinitionList(buildIdleWorkflowSummary(), "No workflow state reported.")}
            </div>
            <div id="files-batches-actions">
              <div class="toolbar">
                <span class="muted">Select a file or batch to unlock context-aware actions.</span>
              </div>
            </div>
            <div id="files-batches-detail-summary">
              ${renderDefinitionList(
                [
                  { label: "Detail surface", value: "Idle" },
                  { label: "Loaded object", value: "No file or batch metadata loaded" },
                ],
                "No detail payload loaded.",
              )}
            </div>
            <pre class="code-block code-block--tall" id="files-batches-detail">No selection yet.</pre>
            <div id="files-batches-content-summary">
              ${renderDefinitionList(
                [
                  { label: "Preview surface", value: "Idle" },
                  { label: "Loaded content", value: "No file content loaded" },
                ],
                "No file content loaded.",
              )}
            </div>
            <div id="files-batches-media"></div>
            <pre class="code-block code-block--tall" id="files-batches-content">No file content loaded.</pre>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Stored files",
      filteredFiles.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>File</th><th>Purpose</th><th>Size</th><th>Created</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${filteredFiles
                    .map((item) => {
                      const id = String(item.id ?? "");
                      return `
                        <tr>
                          <td><strong>${escapeHtml(item.filename ?? item.id ?? "")}</strong><br /><span class="muted">${escapeHtml(id)}</span></td>
                          <td>${escapeHtml(item.purpose ?? "user_data")}</td>
                          <td>${escapeHtml(formatBytes(item.bytes))}</td>
                          <td>${escapeHtml(formatTimestamp(item.created_at))}</td>
                          <td>
                            <div class="toolbar">
                              <button class="button button--secondary" data-file-view="${escapeHtml(id)}" type="button">Inspect</button>
                              <button class="button button--secondary" data-file-use="${escapeHtml(id)}" type="button">Use for batch</button>
                              <button class="button button--secondary" data-file-content="${escapeHtml(id)}" type="button">Content</button>
                              <button class="button button--danger" data-file-delete="${escapeHtml(id)}" type="button">Delete</button>
                            </div>
                          </td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            </div>
          `
        : "<p>No files matched the current filters.</p>",
      "panel panel--span-6",
    )}
    ${card(
      "Batch jobs",
      filteredBatches.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Batch</th><th>Status</th><th>Endpoint</th><th>Output</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${filteredBatches
                    .map((item) => {
                      const id = String(item.id ?? "");
                      const outputFile = String(item.output_file_id ?? "");
                      return `
                        <tr>
                          <td><strong>${escapeHtml(id)}</strong><br /><span class="muted">${escapeHtml(item.input_file_id ?? "no input file")}</span></td>
                          <td>${renderBatchStatus(String(item.status ?? "unknown"))}</td>
                          <td>${escapeHtml(item.endpoint ?? "n/a")}</td>
                          <td>${escapeHtml(outputFile || "n/a")}</td>
                          <td>
                            <div class="toolbar">
                              <button class="button button--secondary" data-batch-view="${escapeHtml(id)}" type="button">Inspect</button>
                              <button class="button button--secondary" ${item.input_file_id ? `data-batch-input="${escapeHtml(id)}"` : 'disabled title="Input file metadata is missing"'} type="button">Input</button>
                              <button class="button button--secondary" ${item.input_file_id ? `data-batch-input-preview="${escapeHtml(id)}"` : 'disabled title="Input preview is unavailable without an input file"'} type="button">Preview input</button>
                              <button class="button button--secondary" ${outputFile ? `data-batch-output="${escapeHtml(outputFile)}"` : 'disabled title="Output unlocks when the batch exposes output_file_id"'} type="button">Output</button>
                            </div>
                          </td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            </div>
          `
        : "<p>No batches matched the current filters.</p>",
      "panel panel--span-6",
    )}
  `);

  const detailNode = app.pageContent.querySelector<HTMLPreElement>("#files-batches-detail");
  const contentNode = app.pageContent.querySelector<HTMLPreElement>("#files-batches-content");
  const mediaNode = app.pageContent.querySelector<HTMLElement>("#files-batches-media");
  const summaryNode = app.pageContent.querySelector<HTMLElement>("#files-batches-summary");
  const workflowNode = app.pageContent.querySelector<HTMLElement>("#files-batches-workflow");
  const detailSummaryNode = app.pageContent.querySelector<HTMLElement>("#files-batches-detail-summary");
  const contentSummaryNode = app.pageContent.querySelector<HTMLElement>("#files-batches-content-summary");
  const actionNode = app.pageContent.querySelector<HTMLElement>("#files-batches-actions");
  const batchInput = app.pageContent.querySelector<HTMLInputElement>("#batch-input-file-id");
  const filtersForm = app.pageContent.querySelector<HTMLFormElement>("#files-batches-filters-form");
  const uploadForm = app.pageContent.querySelector<HTMLFormElement>("#files-upload-form");
  const batchForm = app.pageContent.querySelector<HTMLFormElement>("#batch-create-form");
  if (
    !detailNode ||
    !contentNode ||
    !mediaNode ||
    !summaryNode ||
    !workflowNode ||
    !detailSummaryNode ||
    !contentSummaryNode ||
    !actionNode ||
    !batchInput ||
    !filtersForm ||
    !uploadForm ||
    !batchForm
  ) {
    return;
  }

  let selection: InspectorSelection = { kind: "idle" };
  let previewObjectUrl: string | null = null;

  const setDefinitionBlock = (node: HTMLElement, items: DefinitionItem[], emptyMessage: string): void => {
    node.innerHTML = renderDefinitionList(items, emptyMessage);
  };

  const setSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(summaryNode, items, "No selection yet.");
  };

  const setWorkflowSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(workflowNode, items, "No workflow state reported.");
  };

  const setDetailSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(detailSummaryNode, items, "No detail payload loaded.");
  };

  const setContentSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(contentSummaryNode, items, "No file content loaded.");
  };

  const clearMediaPreview = (): void => {
    mediaNode.innerHTML = "";
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl);
      previewObjectUrl = null;
    }
  };

  const updateInspectorActions = (): void => {
    actionNode.innerHTML = renderInspectorActions(selection, fileLookup, batchLookup, batches);
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
    const source = fileLookup.get(fileId);
    batchInput.value = fileId;
    selection = { kind: "file", fileId };
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
    setDetailSummary([
      { label: "Detail surface", value: "Composer handoff" },
      { label: "Selected input", value: fileId },
      { label: "Endpoint target", value: "Choose an endpoint in the batch form" },
    ]);
    detailNode.textContent = `Selected ${fileId} as batch input.`;
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
    batchInput.focus();
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
    const source = fileLookup.get(fileId);
    const label = options?.label ?? "File content preview";
    setContentSummary([
      { label: "Preview surface", value: label },
      { label: "File id", value: fileId },
      {
        label: "Loaded content",
        value: "Loading…",
        note: options?.support ?? String(source?.filename ?? fileId),
      },
    ]);
    clearMediaPreview();
    contentNode.textContent = "Loading file content…";
    await runWorkflowAction({
      root: actionNode,
      button,
      pendingLabel: "Loading…",
      pendingSummary: [
        { label: "Workflow state", value: "Loading preview" },
        { label: "Preview target", value: fileId },
        { label: "Surface", value: label, note: options?.support ?? String(source?.filename ?? fileId) },
      ],
      successSummary: (preview) => [
        { label: "Workflow state", value: "Preview ready" },
        { label: "Preview target", value: fileId },
        {
          label: "Surface",
          value: label,
          note: summarizePreviewOutcome(preview),
        },
      ],
      action: async () => {
        const response = await app.api.raw(`/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
        const bytes = new Uint8Array(await response.arrayBuffer());
        const preview = buildFilePreview(bytes, String(source?.filename ?? fileId));
        setContentSummary(
          buildContentPreviewSummary(preview, fileId, label, {
            support: options?.support ?? String(source?.filename ?? fileId),
            file: source,
            relatedBatch: options?.relatedBatch ?? null,
          }),
        );
        if (preview.kind === "image") {
          const blob = new Blob([bytes], { type: preview.mimeType });
          previewObjectUrl = URL.createObjectURL(blob);
          mediaNode.innerHTML = `
            <figure class="surface">
              <img
                alt="${escapeHtml(preview.filename)}"
                src="${escapeHtml(previewObjectUrl)}"
                style="display:block;max-width:100%;height:auto;border-radius:12px;"
              />
            </figure>
          `;
          contentNode.textContent = preview.textFallback;
        } else {
          clearMediaPreview();
          contentNode.textContent = preview.textFallback;
        }
        return preview;
      },
    });
  };

  const inspectFile = async (fileId: string, button: HTMLButtonElement | null): Promise<void> => {
    await runWorkflowAction({
      root: actionNode,
      button,
      pendingLabel: "Loading…",
      pendingSummary: [
        { label: "Workflow state", value: "Loading file metadata" },
        { label: "Selected file", value: fileId },
        { label: "Next step", value: "Populate inspector" },
      ],
      successSummary: (payload) => {
        const source = fileLookup.get(fileId) ?? payload;
        const linkedBatches = getLinkedBatchesForFile(fileId, batches);
        const latestBatch = linkedBatches[0];
        return [
          { label: "Workflow state", value: "File selected" },
          { label: "Selected file", value: fileId },
          {
            label: "Batch context",
            value: `${linkedBatches.length} linked batch${linkedBatches.length === 1 ? "" : "es"}`,
            note: latestBatch ? `Latest: ${String(latestBatch.id ?? "unknown")} (${String(latestBatch.status ?? "unknown")})` : "No linked batch records yet.",
          },
          {
            label: "Next step",
            value: linkedBatches.length ? "Inspect linked batch or preview content" : "Preview content or use for batch",
            note: String(source.filename ?? fileId),
          },
        ];
      },
      action: async () => {
        const payload = await app.api.json<Record<string, unknown>>(
          `/v1/files/${encodeURIComponent(fileId)}`,
          {},
          true,
        );
        const source = fileLookup.get(fileId) ?? payload;
        const linkedBatches = getLinkedBatchesForFile(fileId, batches);
        const readyOutputs = linkedBatches.filter((batch) => Boolean(String(batch.output_file_id ?? ""))).length;
        selection = { kind: "file", fileId };
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
            note: readyOutputs ? `${readyOutputs} output file${readyOutputs === 1 ? "" : "s"} ready` : "No completed output linked yet.",
          },
        ]);
        setDetailSummary([
          { label: "Detail surface", value: "File metadata" },
          { label: "Linked batches", value: String(linkedBatches.length) },
          { label: "Stored bytes", value: formatBytes(source.bytes) },
          { label: "Status", value: String(source.status ?? "processed") },
        ]);
        detailNode.textContent = JSON.stringify(payload, null, 2);
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
      root: actionNode,
      button,
      pendingLabel: "Loading…",
      pendingSummary: [
        { label: "Workflow state", value: "Loading batch metadata" },
        { label: "Selected batch", value: batchId },
        { label: "Next step", value: "Populate lifecycle inspector" },
      ],
      successSummary: (payload) => {
        const source = batchLookup.get(batchId) ?? payload;
        const requestCounts = summarizeBatchRequestCounts(source.request_counts);
        return [
          { label: "Workflow state", value: "Batch selected" },
          { label: "Selected batch", value: batchId },
          {
            label: "Lifecycle",
            value: humanizeBatchLifecycle(source.status),
            note: requestCounts,
          },
          {
            label: "Next step",
            value: selection.outputFileId ? "Preview output or inspect input" : "Preview input and refresh status",
            note: buildBatchActionHint(source),
          },
        ];
      },
      action: async () => {
        const payload = await app.api.json<Record<string, unknown>>(
          `/v1/batches/${encodeURIComponent(batchId)}`,
          {},
          true,
        );
        const source = batchLookup.get(batchId) ?? payload;
        const inputFileId = String(source.input_file_id ?? "");
        const outputFileId = String(source.output_file_id ?? "");
        selection = {
          kind: "batch",
          batchId,
          inputFileId: inputFileId || undefined,
          outputFileId: outputFileId || undefined,
        };
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
        setDetailSummary([
          { label: "Detail surface", value: "Batch metadata" },
          { label: "Lifecycle posture", value: humanizeBatchLifecycle(source.status) },
          { label: "Input file", value: inputFileId || "missing" },
          { label: "Output file", value: outputFileId || "not ready" },
          { label: "Requests", value: summarizeBatchRequestCounts(source.request_counts) },
        ]);
        detailNode.textContent = JSON.stringify(payload, null, 2);
        updateInspectorActions();
        return payload;
      },
    });
  };

  updateInspectorActions();

  document.getElementById("refresh-files-batches")?.addEventListener("click", () => {
    void app.render("files-batches");
  });
  document.getElementById("reset-files-batches-filters")?.addEventListener("click", () => {
    window.history.replaceState({}, "", "/admin/files-batches");
    void app.render("files-batches");
  });

  filtersForm.addEventListener("submit", (event) => {
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

  uploadForm.addEventListener("submit", async (event) => {
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
        const body = new FormData();
        body.set("purpose", fields.purpose.value);
        body.set("file", upload, upload.name);
        const response = await app.api.json<Record<string, unknown>>(
          "/v1/files",
          { method: "POST", body },
          true,
        );
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

  batchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      endpoint: HTMLSelectElement;
      input_file_id: HTMLInputElement;
      metadata: HTMLTextAreaElement;
    };
    const metadataText = fields.metadata.value.trim();
    const metadata = metadataText ? safeJsonParse(metadataText, INVALID_JSON) : undefined;
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
        const response = await app.api.json<Record<string, unknown>>(
          "/v1/batches",
          {
            method: "POST",
            json: {
              endpoint: fields.endpoint.value,
              input_file_id: fields.input_file_id.value.trim(),
              completion_window: "24h",
              metadata,
            },
          },
          true,
        );
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

  actionNode.addEventListener("click", async (event) => {
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
        relatedBatch: batchLookup.get(selection.batchId) ?? null,
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
        relatedBatch: batchLookup.get(selection.batchId) ?? null,
      });
      return;
    }
    if (action === "inspect-output-file" && selection.outputFileId) {
      await inspectFile(selection.outputFileId, button);
      return;
    }
    if (action === "inspect-linked-batch" && selection.fileId) {
      const latestBatch = getLatestLinkedBatch(selection.fileId, batches);
      if (latestBatch) {
        await inspectBatch(String(latestBatch.id ?? ""), button);
      }
      return;
    }
    if (action === "preview-linked-output" && selection.fileId) {
      const latestOutputBatch = getLatestOutputBatch(selection.fileId, batches);
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
      setSummary([
        { label: "Selection", value: "Linked batch output" },
        { label: "Output file", value: outputFileId },
        { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
        { label: "Endpoint", value: String(latestOutputBatch?.endpoint ?? "n/a") },
      ]);
      setDetailSummary([
        { label: "Detail surface", value: "Latest linked output" },
        { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
        { label: "Output file", value: outputFileId },
        { label: "Requests", value: summarizeBatchRequestCounts(latestOutputBatch?.request_counts) },
      ]);
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
      await inspectFile(item.dataset.fileView ?? "", item instanceof HTMLButtonElement ? item : null);
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
      updateInspectorActions();
      await previewFileContent(fileId, item instanceof HTMLButtonElement ? item : null);
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
          await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
          app.queueAlert(`Deleted file ${fileId}.`, "info");
          await app.render("files-batches");
        },
      });
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-view]").forEach((item) => {
    item.addEventListener("click", async () => {
      await inspectBatch(item.dataset.batchView ?? "", item instanceof HTMLButtonElement ? item : null);
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-output]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.batchOutput;
      if (!fileId) {
        return;
      }
      const batch = batches.find((entry) => String(entry.output_file_id ?? "") === fileId);
      selection = {
        kind: "batch",
        batchId: String(batch?.id ?? ""),
        inputFileId: String(batch?.input_file_id ?? "") || undefined,
        outputFileId: fileId,
      };
      setSummary([
        { label: "Selection", value: "Batch output" },
        { label: "Output file", value: fileId },
        { label: "Batch id", value: String(batch?.id ?? "unknown") },
        { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
      ]);
      setDetailSummary([
        { label: "Detail surface", value: "Batch output handoff" },
        { label: "Batch id", value: String(batch?.id ?? "unknown") },
        { label: "Output file", value: fileId },
      ]);
      updateInspectorActions();
      await previewFileContent(fileId, item instanceof HTMLButtonElement ? item : null, {
        label: "Batch output preview",
        support: `Batch ${String(batch?.id ?? "unknown")}`,
        relatedBatch: batch ?? null,
      });
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-input]").forEach((item) => {
    item.addEventListener("click", async () => {
      const batchId = item.dataset.batchInput;
      const batch = batchLookup.get(batchId ?? "");
      const inputFileId = String(batch?.input_file_id ?? "");
      if (!inputFileId) {
        return;
      }
      await inspectFile(inputFileId, item instanceof HTMLButtonElement ? item : null);
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-input-preview]").forEach((item) => {
    item.addEventListener("click", async () => {
      const batchId = item.dataset.batchInputPreview;
      const batch = batchLookup.get(batchId ?? "");
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
      updateInspectorActions();
      await previewFileContent(inputFileId, item instanceof HTMLButtonElement ? item : null, {
        label: "Batch input preview",
        support: `Batch ${String(batch?.id ?? "unknown")}`,
        relatedBatch: batch ?? null,
      });
    });
  });

  const routeState = readFilesBatchesRouteState();
  if (routeState.composeInputFileId) {
    batchInput.value = routeState.composeInputFileId;
    setWorkflowSummary([
      { label: "Workflow state", value: "Batch composer primed" },
      { label: "Input file", value: routeState.composeInputFileId },
      { label: "Next step", value: "Choose endpoint and create batch" },
    ]);
  }
  if (routeState.selectedBatchId && batchLookup.has(routeState.selectedBatchId)) {
    await inspectBatch(routeState.selectedBatchId, null);
    return;
  }
  if (routeState.selectedFileId && fileLookup.has(routeState.selectedFileId)) {
    await inspectFile(routeState.selectedFileId, null);
  }
}

function buildIdleSelectionSummary(
  filteredFiles: number,
  totalFiles: number,
  filteredBatches: number,
  totalBatches: number,
  filters: FilesBatchesFilters,
): DefinitionItem[] {
  return [
    { label: "Selection", value: "No file or batch selected" },
    { label: "Files shown", value: `${filteredFiles}/${totalFiles}` },
    { label: "Batches shown", value: `${filteredBatches}/${totalBatches}` },
    { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
  ];
}

function buildIdleWorkflowSummary(): DefinitionItem[] {
  return [
    { label: "Workflow state", value: "Idle" },
    { label: "Current posture", value: "No pending file or batch action" },
    {
      label: "Next step",
      value: "Inspect inventory",
      note: "Select a file or batch to unlock preview and lifecycle actions.",
    },
  ];
}

function renderInspectorActions(
  selection: InspectorSelection,
  fileLookup: Map<string, FileRecord>,
  batchLookup: Map<string, BatchRecord>,
  batches: BatchRecord[],
): string {
  if (selection.kind === "file" && selection.fileId) {
    const source = fileLookup.get(selection.fileId);
    const latestBatch = getLatestLinkedBatch(selection.fileId, batches);
    const latestOutputBatch = getLatestOutputBatch(selection.fileId, batches);
    return `
      <div class="toolbar">
        <button class="button button--secondary" data-inspector-action="inspect-file" type="button">Refresh metadata</button>
        <button class="button button--secondary" data-inspector-action="preview-file" type="button">Preview content</button>
        <button class="button" data-inspector-action="use-file" type="button">Use for batch</button>
        <button class="button button--secondary" ${latestBatch ? 'data-inspector-action="inspect-linked-batch"' : 'disabled title="No linked batch record yet"'} type="button">Inspect latest batch</button>
        <button class="button button--secondary" ${latestOutputBatch ? 'data-inspector-action="preview-linked-output"' : 'disabled title="No linked output file yet"'} type="button">Preview latest output</button>
      </div>
      <p class="muted">
        ${escapeHtml(
          source
            ? `${String(source.filename ?? selection.fileId)} can feed a new batch immediately. Linked batch actions unlock as downstream jobs appear.`
            : "This file can be previewed, queued as batch input, or handed off into the latest linked batch context.",
        )}
      </p>
    `;
  }
  if (selection.kind === "batch" && selection.batchId) {
    const source = batchLookup.get(selection.batchId);
    return `
      <div class="toolbar">
        <button class="button button--secondary" data-inspector-action="inspect-batch" type="button">Refresh batch</button>
        <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="batch-input"' : 'disabled title="Input file metadata is missing"'} type="button">Inspect input</button>
        <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="preview-batch-input"' : 'disabled title="Input preview is unavailable without an input file"'} type="button">Preview input</button>
        <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="use-batch-input"' : 'disabled title="Input file is required to retry this batch"'} type="button">Queue with input</button>
        <button class="button button--secondary" ${selection.outputFileId ? 'data-inspector-action="inspect-output-file"' : 'disabled title="Output metadata appears after the provider creates output_file_id"'} type="button">Inspect output file</button>
        <button class="button" ${selection.outputFileId ? 'data-inspector-action="batch-output"' : 'disabled title="Output preview unlocks after completion"'} type="button">Preview output</button>
      </div>
      <p class="muted">${escapeHtml(buildBatchActionHint(source))}</p>
    `;
  }
  return `
    <div class="toolbar">
      <span class="muted">Select a file or batch to unlock context-aware actions.</span>
    </div>
  `;
}

function buildContentPreviewSummary(
  preview: FilePreview,
  fileId: string,
  label: string,
  options?: {
    support?: string;
    file?: FileRecord;
    relatedBatch?: BatchRecord | null;
  },
): DefinitionItem[] {
  const summary: DefinitionItem[] = [
    { label: "Preview surface", value: label, note: options?.support },
    { label: "File id", value: fileId },
    { label: "Format", value: preview.formatLabel, note: preview.formatNote },
    {
      label: preview.kind === "image" ? "Binary size" : "Payload size",
      value:
        preview.kind === "image"
          ? formatBytes(preview.byteLength)
          : `${preview.lineCount} line${preview.lineCount === 1 ? "" : "s"}`,
      note:
        preview.kind === "image"
          ? preview.dimensionsNote ?? "Rendered as image preview."
          : formatBytes(preview.byteLength),
    },
  ];

  if (preview.contentKind) {
    summary.push({
      label: "Content posture",
      value: preview.contentKind,
      note: preview.contentKindNote,
    });
  }

  if (preview.sampleValue) {
    summary.push({
      label: preview.sampleLabel ?? "Sample",
      value: preview.sampleValue,
      note: preview.sampleNote,
    });
  }

  if (options?.file) {
    summary.push({
      label: "Stored file",
      value: String(options.file.filename ?? fileId),
      note: String(options.file.purpose ?? "user_data"),
    });
  }

  if (options?.relatedBatch) {
    summary.push({
      label: "Batch context",
      value: String(options.relatedBatch.id ?? "unknown"),
      note: String(options.relatedBatch.status ?? "unknown"),
    });
  }

  return summary;
}

function analyzeContentText(text: string): Omit<FilePreview, "kind" | "filename" | "mimeType" | "textFallback" | "dimensionsNote"> {
  const lines = text ? text.split(/\r?\n/).length : 0;
  const nonEmptyLines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const trimmed = text.trim();
  const json = trimmed ? safeJsonParse(trimmed, INVALID_JSON) : INVALID_JSON;
  let formatLabel = "text";
  let formatNote = lines <= 1 ? "single payload" : "plain text or JSON fragments";
  let contentKind: string | undefined;
  let contentKindNote: string | undefined;
  let sampleLabel: string | undefined;
  let sampleValue: string | undefined;
  let sampleNote: string | undefined;

  if (json !== INVALID_JSON) {
    if (Array.isArray(json)) {
      const records = json as unknown[];
      formatLabel = "json array";
      formatNote = `${records.length} top-level item${records.length === 1 ? "" : "s"}`;
    } else if (json && typeof json === "object") {
      const objectValue = json as Record<string, unknown>;
      const fieldCount = Object.keys(objectValue).length;
      formatLabel = "json object";
      formatNote = `${fieldCount} top-level field${fieldCount === 1 ? "" : "s"}`;
      sampleLabel = "Top-level keys";
      sampleValue = Object.keys(objectValue).slice(0, 3).join(", ") || "none";
      if ("data" in objectValue && Array.isArray(objectValue.data)) {
        contentKind = "List payload";
        contentKindNote = `${objectValue.data.length} entries`;
      }
    } else {
      formatLabel = "json scalar";
    }
  } else if (
    nonEmptyLines.length > 0 &&
    nonEmptyLines.every((line) => safeJsonParse(line, INVALID_JSON) !== INVALID_JSON)
  ) {
    const parsedLines: unknown[] = nonEmptyLines
      .map((line) => safeJsonParse(line, INVALID_JSON))
      .filter((row) => row !== INVALID_JSON);
    formatLabel = "jsonl";
    formatNote = `${nonEmptyLines.length} record${nonEmptyLines.length === 1 ? "" : "s"}`;
    const inputRows = parsedLines.filter((row): row is Record<string, unknown> => isBatchInputRow(row));
    const outputRows = parsedLines.filter((row): row is Record<string, unknown> => isBatchOutputRow(row));
    if (inputRows.length === parsedLines.length) {
      const sampleRow = inputRows[0] ?? {};
      contentKind = "Batch input";
      contentKindNote = `${inputRows.length} queued request${inputRows.length === 1 ? "" : "s"}`;
      sampleLabel = "Sample request";
      sampleValue = String(sampleRow.custom_id ?? sampleRow.id ?? "batch-request");
      sampleNote = `${String(sampleRow.method ?? "POST")} ${String(sampleRow.url ?? "/v1/chat/completions")}`;
    } else if (outputRows.length === parsedLines.length) {
      const errorCount = outputRows.filter((row) => Boolean(row.error)).length;
      const successCount = outputRows.length - errorCount;
      const sampleRow = outputRows[0] ?? {};
      contentKind = "Batch output";
      contentKindNote = `${successCount} success · ${errorCount} error`;
      sampleLabel = "Sample result";
      sampleValue = String(sampleRow.custom_id ?? sampleRow.id ?? "batch-result");
      sampleNote = errorCount ? "Contains at least one failed row." : "Rows decode cleanly into transformed results.";
    }
  }

  return {
    formatLabel,
    formatNote,
    lineCount: lines,
    byteLength: new TextEncoder().encode(text).length,
    contentKind,
    contentKindNote,
    sampleLabel,
    sampleValue,
    sampleNote,
  };
}

function readFilesBatchesFilters(): FilesBatchesFilters {
  const params = new URLSearchParams(window.location.search);
  return {
    query: params.get("query") || "",
    purpose: params.get("purpose") || "",
    batchStatus: params.get("batch_status") || "",
    endpoint: params.get("endpoint") || "",
  };
}

function readFilesBatchesRouteState(): FilesBatchesRouteState {
  const params = new URLSearchParams(window.location.search);
  return {
    selectedFileId: params.get("selected_file") || "",
    selectedBatchId: params.get("selected_batch") || "",
    composeInputFileId: params.get("compose_input") || "",
  };
}

function buildFilesBatchesUrl(
  filters: FilesBatchesFilters,
  routeState?: Partial<FilesBatchesRouteState>,
): string {
  const params = new URLSearchParams();
  setIfPresent(params, "query", filters.query);
  setIfPresent(params, "purpose", filters.purpose);
  setIfPresent(params, "batch_status", filters.batchStatus);
  setIfPresent(params, "endpoint", filters.endpoint);
  setIfPresent(params, "selected_file", routeState?.selectedFileId ?? "");
  setIfPresent(params, "selected_batch", routeState?.selectedBatchId ?? "");
  setIfPresent(params, "compose_input", routeState?.composeInputFileId ?? "");
  const query = params.toString();
  return query ? `/admin/files-batches?${query}` : "/admin/files-batches";
}

function matchesFile(item: FileRecord, filters: FilesBatchesFilters): boolean {
  if (filters.purpose && String(item.purpose ?? "") !== filters.purpose) {
    return false;
  }
  if (!filters.query) {
    return true;
  }
  const query = filters.query.toLowerCase();
  return [item.id, item.filename, item.purpose]
    .map((value) => String(value ?? "").toLowerCase())
    .some((value) => value.includes(query));
}

function matchesBatch(item: BatchRecord, filters: FilesBatchesFilters): boolean {
  if (filters.batchStatus && String(item.status ?? "") !== filters.batchStatus) {
    return false;
  }
  if (filters.endpoint && String(item.endpoint ?? "") !== filters.endpoint) {
    return false;
  }
  if (!filters.query) {
    return true;
  }
  const query = filters.query.toLowerCase();
  return [item.id, item.input_file_id, item.output_file_id, item.endpoint]
    .map((value) => String(value ?? "").toLowerCase())
    .some((value) => value.includes(query));
}

function summarizeFilters(filters: FilesBatchesFilters): string {
  return [
    filters.query ? `text=${filters.query}` : "",
    filters.purpose ? `purpose=${filters.purpose}` : "",
    filters.batchStatus ? `status=${filters.batchStatus}` : "",
    filters.endpoint ? `endpoint=${filters.endpoint}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function renderSelectOptions(selected: string, values: string[]): string {
  return [renderOption("", selected, "All"), ...values.map((value) => renderOption(value, selected))].join("");
}

function renderOption(value: string, selected: string, label?: string): string {
  return `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(label ?? value)}</option>`;
}

function uniqueOptions(values: unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => String(value ?? "").trim())
        .filter(Boolean),
    ),
  ).sort((left, right) => left.localeCompare(right));
}

function setIfPresent(params: URLSearchParams, key: string, value: string): void {
  if (value) {
    params.set(key, value);
  }
}

function firstErrorLine(message: string): string {
  return message.split("\n").map((line) => line.trim()).find(Boolean) ?? "Unknown error";
}

function summarizePreviewOutcome(preview: FilePreview): string {
  return [
    preview.formatLabel,
    preview.contentKind,
    preview.kind === "image"
      ? formatBytes(preview.byteLength)
      : `${preview.lineCount} line${preview.lineCount === 1 ? "" : "s"}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

function buildFilePreview(bytes: Uint8Array, filename: string): FilePreview {
  const imageMimeType = detectImageMimeType(bytes, filename);
  if (imageMimeType) {
    return {
      kind: "image",
      filename,
      mimeType: imageMimeType,
      textFallback: `Binary image preview loaded for ${filename}.\nMIME type: ${imageMimeType}\nSize: ${formatBytes(bytes.length)}`,
      byteLength: bytes.length,
      lineCount: 0,
      formatLabel: "image",
      formatNote: imageMimeType,
      contentKind: "Image asset",
      contentKindNote: "Rendered inline so the operator can inspect the payload without opening raw bytes.",
      sampleLabel: "Filename",
      sampleValue: filename,
      dimensionsNote: "Image preview available inline.",
    };
  }

  const decoded = decodeBytesAsText(bytes);
  if (decoded.isText) {
    const analysis = analyzeContentText(decoded.text);
    return {
      kind: "text",
      filename,
      mimeType: inferTextMimeType(filename, decoded.text),
      textFallback: decoded.text,
      ...analysis,
    };
  }

  return {
    kind: "binary",
    filename,
    mimeType: "application/octet-stream",
    textFallback: renderBinaryPreview(bytes),
    byteLength: bytes.length,
    lineCount: 1,
    formatLabel: "binary",
    formatNote: "Non-text payload",
    contentKind: "Binary asset",
    contentKindNote: "Rendered as a short byte preview instead of lossy text decoding.",
    sampleLabel: "Magic bytes",
    sampleValue: renderHexPrefix(bytes),
    sampleNote: filename,
  };
}

function detectImageMimeType(bytes: Uint8Array, filename: string): string | null {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return "image/png";
  }
  if (
    bytes.length >= 12 &&
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50
  ) {
    return "image/webp";
  }
  if (bytes.length >= 6) {
    const header = String.fromCharCode(...bytes.slice(0, 6));
    if (header === "GIF87a" || header === "GIF89a") {
      return "image/gif";
    }
  }

  const lowerFilename = filename.toLowerCase();
  if (lowerFilename.endsWith(".svg")) {
    return "image/svg+xml";
  }

  return null;
}

function decodeBytesAsText(bytes: Uint8Array): { isText: boolean; text: string } {
  const sample = bytes.slice(0, Math.min(bytes.length, 2048));
  const binaryLike = sample.filter((value) => value === 0 || value < 0x09).length;
  if (sample.length > 0 && binaryLike / sample.length > 0.02) {
    return { isText: false, text: "" };
  }

  const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  const replacementCount = Array.from(text).filter((char) => char === "\ufffd").length;
  const ratio = text.length ? replacementCount / text.length : 0;
  return { isText: ratio < 0.02, text };
}

function inferTextMimeType(filename: string, text: string): string {
  const lowerFilename = filename.toLowerCase();
  if (lowerFilename.endsWith(".jsonl")) {
    return "application/jsonl";
  }
  if (lowerFilename.endsWith(".json")) {
    return "application/json";
  }
  if (lowerFilename.endsWith(".svg") || text.trimStart().startsWith("<svg")) {
    return "image/svg+xml";
  }
  return "text/plain";
}

function renderBinaryPreview(bytes: Uint8Array): string {
  return [
    "Binary file preview",
    `Size: ${formatBytes(bytes.length)}`,
    `Magic bytes: ${renderHexPrefix(bytes)}`,
    "Raw text preview is suppressed to avoid mojibake.",
  ].join("\n");
}

function renderHexPrefix(bytes: Uint8Array, limit = 16): string {
  return Array.from(bytes.slice(0, limit))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join(" ");
}

function getLinkedBatchesForFile(fileId: string, batches: BatchRecord[]): BatchRecord[] {
  return batches
    .filter((batch) => {
      const inputFileId = String(batch.input_file_id ?? "");
      const outputFileId = String(batch.output_file_id ?? "");
      return inputFileId === fileId || outputFileId === fileId;
    })
    .sort((left, right) => Number(right.created_at ?? 0) - Number(left.created_at ?? 0));
}

function getLatestLinkedBatch(fileId: string, batches: BatchRecord[]): BatchRecord | null {
  return getLinkedBatchesForFile(fileId, batches)[0] ?? null;
}

function getLatestOutputBatch(fileId: string, batches: BatchRecord[]): BatchRecord | null {
  return (
    getLinkedBatchesForFile(fileId, batches).find((batch) => Boolean(String(batch.output_file_id ?? ""))) ??
    null
  );
}

function summarizeBatchRequestCounts(value: unknown): string {
  if (!value || typeof value !== "object") {
    return "counts unavailable";
  }
  const counts = value as Record<string, unknown>;
  const total = Number(counts.total ?? counts.request_count ?? 0);
  const completed = Number(counts.completed ?? counts.succeeded ?? 0);
  const failed = Number(counts.failed ?? counts.error ?? 0);
  if (!Number.isFinite(total) || total <= 0) {
    return "counts unavailable";
  }
  return `${completed}/${total} completed${failed > 0 ? ` · ${failed} failed` : ""}`;
}

function buildBatchActionHint(batch: BatchRecord | undefined): string {
  if (!batch) {
    return "Refresh this batch to load lifecycle posture and linked input/output files.";
  }
  const status = String(batch.status ?? "unknown");
  const outputFileId = String(batch.output_file_id ?? "");
  if (outputFileId) {
    return `Batch ${String(batch.id ?? "unknown")} is ${status}; output preview is available from ${outputFileId}.`;
  }
  if (isAttentionBatchStatus(status)) {
    return `Batch ${String(batch.id ?? "unknown")} needs operator follow-up. Inspect the input payload and refresh metadata for the latest error posture.`;
  }
  return `Batch ${String(batch.id ?? "unknown")} is ${status}. Preview the input payload now and refresh until output_file_id appears.`;
}

function isBatchInputRow(value: unknown): boolean {
  return Boolean(
    value &&
      typeof value === "object" &&
      ("body" in (value as Record<string, unknown>) || "request" in (value as Record<string, unknown>)),
  );
}

function isBatchOutputRow(value: unknown): boolean {
  return Boolean(
    value &&
      typeof value === "object" &&
      ("response" in (value as Record<string, unknown>) ||
        "error" in (value as Record<string, unknown>) ||
        "custom_id" in (value as Record<string, unknown>)),
  );
}

function isAttentionBatchStatus(value: unknown): boolean {
  const status = String(value ?? "").toLowerCase();
  return ["failed", "cancelled", "expired"].includes(status);
}

function renderBatchStatus(value: string): string {
  const normalized = value || "unknown";
  if (normalized === "completed") {
    return pill(normalized, "good");
  }
  if (isAttentionBatchStatus(normalized)) {
    return pill(normalized, "warn");
  }
  return pill(normalized);
}

function humanizeBatchLifecycle(value: unknown): string {
  const status = String(value ?? "").toLowerCase();
  if (status === "completed") {
    return "output ready";
  }
  if (isAttentionBatchStatus(status)) {
    return "operator follow-up required";
  }
  if (status) {
    return "still processing";
  }
  return "unknown";
}
