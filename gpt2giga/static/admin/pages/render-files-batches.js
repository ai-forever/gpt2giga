import { withBusyState } from "../forms.js";
import { card, kpi, pill, renderDefinitionList } from "../templates.js";
import { asArray, escapeHtml, formatBytes, formatTimestamp, safeJsonParse, } from "../utils.js";
const INVALID_JSON = "__invalid__";
export async function renderFilesBatches(app, token) {
    const filters = readFilesBatchesFilters();
    const [filesPayload, batchesPayload] = await Promise.all([
        app.api.json("/v1/files?order=desc&limit=100", {}, true),
        app.api.json("/v1/batches?limit=100", {}, true),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const files = asArray(filesPayload.data);
    const batches = asArray(batchesPayload.data);
    const filteredFiles = files.filter((item) => matchesFile(item, filters));
    const filteredBatches = batches.filter((item) => matchesBatch(item, filters));
    const attentionBatches = filteredBatches.filter((batch) => isAttentionBatchStatus(batch.status)).length;
    const outputReadyBatches = filteredBatches.filter((batch) => Boolean(String(batch.output_file_id ?? ""))).length;
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
    ${card("Inventory filters", `
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
      `, "panel panel--span-12")}
    ${card("Upload file", `
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
      `, "panel panel--span-4")}
    ${card("Create batch", `
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
      `, "panel panel--span-4")}
    ${card("Inspector", `
        <div class="surface">
          <div class="stack">
            <div id="files-batches-summary">
              ${renderDefinitionList(buildIdleSelectionSummary(filteredFiles.length, files.length, filteredBatches.length, batches.length, filters), "No selection yet.")}
            </div>
            <div class="toolbar" id="files-batches-actions">
              <span class="muted">Select a file or batch to unlock context-aware actions.</span>
            </div>
            <div id="files-batches-detail-summary">
              ${renderDefinitionList([
        { label: "Detail surface", value: "Idle" },
        { label: "Loaded object", value: "No file or batch metadata loaded" },
    ], "No detail payload loaded.")}
            </div>
            <pre class="code-block" id="files-batches-detail">No selection yet.</pre>
            <div id="files-batches-content-summary">
              ${renderDefinitionList([
        { label: "Preview surface", value: "Idle" },
        { label: "Loaded content", value: "No file content loaded" },
    ], "No file content loaded.")}
            </div>
            <pre class="code-block" id="files-batches-content">No file content loaded.</pre>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Stored files", filteredFiles.length
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
        : "<p>No files matched the current filters.</p>", "panel panel--span-6")}
    ${card("Batch jobs", filteredBatches.length
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
                              <button class="button button--secondary" ${outputFile ? `data-batch-output="${escapeHtml(outputFile)}"` : "disabled"} type="button">Output</button>
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
        : "<p>No batches matched the current filters.</p>", "panel panel--span-6")}
  `);
    const detailNode = app.pageContent.querySelector("#files-batches-detail");
    const contentNode = app.pageContent.querySelector("#files-batches-content");
    const summaryNode = app.pageContent.querySelector("#files-batches-summary");
    const detailSummaryNode = app.pageContent.querySelector("#files-batches-detail-summary");
    const contentSummaryNode = app.pageContent.querySelector("#files-batches-content-summary");
    const actionNode = app.pageContent.querySelector("#files-batches-actions");
    const batchInput = app.pageContent.querySelector("#batch-input-file-id");
    const filtersForm = app.pageContent.querySelector("#files-batches-filters-form");
    const uploadForm = app.pageContent.querySelector("#files-upload-form");
    const batchForm = app.pageContent.querySelector("#batch-create-form");
    if (!detailNode ||
        !contentNode ||
        !summaryNode ||
        !detailSummaryNode ||
        !contentSummaryNode ||
        !actionNode ||
        !batchInput ||
        !filtersForm ||
        !uploadForm ||
        !batchForm) {
        return;
    }
    let selection = { kind: "idle" };
    const setDefinitionBlock = (node, items, emptyMessage) => {
        node.innerHTML = renderDefinitionList(items, emptyMessage);
    };
    const setSummary = (items) => {
        setDefinitionBlock(summaryNode, items, "No selection yet.");
    };
    const setDetailSummary = (items) => {
        setDefinitionBlock(detailSummaryNode, items, "No detail payload loaded.");
    };
    const setContentSummary = (items) => {
        setDefinitionBlock(contentSummaryNode, items, "No file content loaded.");
    };
    const updateInspectorActions = () => {
        actionNode.innerHTML = renderInspectorActions(selection);
    };
    const focusBatchComposer = (fileId) => {
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
        updateInspectorActions();
        batchInput.focus();
    };
    const previewFileContent = async (fileId, button, options) => {
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
        contentNode.textContent = "Loading file content…";
        await withBusyState({
            button,
            pendingLabel: "Loading…",
            action: async () => {
                const text = await app.api.text(`/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
                setContentSummary(buildContentPreviewSummary(text, fileId, label, options?.support ?? String(source?.filename ?? fileId)));
                contentNode.textContent = text;
            },
        });
    };
    const inspectFile = async (fileId, button) => {
        await withBusyState({
            button,
            pendingLabel: "Loading…",
            action: async () => {
                const payload = await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, {}, true);
                const source = fileLookup.get(fileId) ?? payload;
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
                ]);
                setDetailSummary([
                    { label: "Detail surface", value: "File metadata" },
                    { label: "Linked batches", value: String(countLinkedBatches(fileId, batches)) },
                    { label: "Stored bytes", value: formatBytes(source.bytes) },
                ]);
                detailNode.textContent = JSON.stringify(payload, null, 2);
                updateInspectorActions();
            },
        });
    };
    const inspectBatch = async (batchId, button) => {
        await withBusyState({
            button,
            pendingLabel: "Loading…",
            action: async () => {
                const payload = await app.api.json(`/v1/batches/${encodeURIComponent(batchId)}`, {}, true);
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
                ]);
                detailNode.textContent = JSON.stringify(payload, null, 2);
                updateInspectorActions();
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
        const form = event.currentTarget;
        const fields = form.elements;
        const nextFilters = {
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
        const form = event.currentTarget;
        const fields = form.elements;
        const upload = fields.file.files?.[0];
        if (!upload) {
            app.pushAlert("Choose a file before uploading.", "warn");
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : form.querySelector('button[type="submit"]');
        await withBusyState({
            root: form,
            button,
            pendingLabel: "Uploading…",
            action: async () => {
                const body = new FormData();
                body.set("purpose", fields.purpose.value);
                body.set("file", upload, upload.name);
                const response = await app.api.json("/v1/files", { method: "POST", body }, true);
                app.queueAlert(`Uploaded file ${String(response.id ?? "")}.`, "info");
                await app.render("files-batches");
            },
        });
    });
    batchForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const metadataText = fields.metadata.value.trim();
        const metadata = metadataText ? safeJsonParse(metadataText, INVALID_JSON) : undefined;
        if (metadata === INVALID_JSON ||
            (metadata !== undefined &&
                (metadata === null || Array.isArray(metadata) || typeof metadata !== "object"))) {
            app.pushAlert("Batch metadata must be a JSON object.", "danger");
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : form.querySelector('button[type="submit"]');
        await withBusyState({
            root: form,
            button,
            pendingLabel: "Creating…",
            action: async () => {
                const response = await app.api.json("/v1/batches", {
                    method: "POST",
                    json: {
                        endpoint: fields.endpoint.value,
                        input_file_id: fields.input_file_id.value.trim(),
                        completion_window: "24h",
                        metadata,
                    },
                }, true);
                app.queueAlert(`Created batch ${String(response.id ?? "")} for ${String(response.endpoint ?? "")}.`, "info");
                await app.render("files-batches");
            },
        });
    });
    actionNode.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
            return;
        }
        const button = target.closest("[data-inspector-action]");
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
        if (action === "batch-output" && selection.outputFileId && selection.batchId) {
            await previewFileContent(selection.outputFileId, button, {
                label: "Batch output preview",
                support: `Batch ${selection.batchId}`,
            });
            return;
        }
        if (action === "inspect-output-file" && selection.outputFileId) {
            await inspectFile(selection.outputFileId, button);
        }
    });
    app.pageContent.querySelectorAll("[data-file-view]").forEach((item) => {
        item.addEventListener("click", async () => {
            await inspectFile(item.dataset.fileView ?? "", item instanceof HTMLButtonElement ? item : null);
        });
    });
    app.pageContent.querySelectorAll("[data-file-use]").forEach((item) => {
        item.addEventListener("click", () => {
            const fileId = item.dataset.fileUse;
            if (!fileId) {
                return;
            }
            focusBatchComposer(fileId);
        });
    });
    app.pageContent.querySelectorAll("[data-file-content]").forEach((item) => {
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
    app.pageContent.querySelectorAll("[data-file-delete]").forEach((item) => {
        item.addEventListener("click", async () => {
            const fileId = item.dataset.fileDelete;
            if (!fileId) {
                return;
            }
            if (!window.confirm(`Delete file ${fileId}?`)) {
                return;
            }
            await withBusyState({
                button: item instanceof HTMLButtonElement ? item : null,
                pendingLabel: "Deleting…",
                action: async () => {
                    await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
                    app.queueAlert(`Deleted file ${fileId}.`, "info");
                    await app.render("files-batches");
                },
            });
        });
    });
    app.pageContent.querySelectorAll("[data-batch-view]").forEach((item) => {
        item.addEventListener("click", async () => {
            await inspectBatch(item.dataset.batchView ?? "", item instanceof HTMLButtonElement ? item : null);
        });
    });
    app.pageContent.querySelectorAll("[data-batch-output]").forEach((item) => {
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
            });
        });
    });
}
function buildIdleSelectionSummary(filteredFiles, totalFiles, filteredBatches, totalBatches, filters) {
    return [
        { label: "Selection", value: "No file or batch selected" },
        { label: "Files shown", value: `${filteredFiles}/${totalFiles}` },
        { label: "Batches shown", value: `${filteredBatches}/${totalBatches}` },
        { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
    ];
}
function renderInspectorActions(selection) {
    if (selection.kind === "file" && selection.fileId) {
        return `
      <button class="button button--secondary" data-inspector-action="inspect-file" type="button">Refresh metadata</button>
      <button class="button button--secondary" data-inspector-action="preview-file" type="button">Preview content</button>
      <button class="button" data-inspector-action="use-file" type="button">Use for batch</button>
    `;
    }
    if (selection.kind === "batch" && selection.batchId) {
        return `
      <button class="button button--secondary" data-inspector-action="inspect-batch" type="button">Refresh batch</button>
      <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="batch-input"' : "disabled"} type="button">Inspect input</button>
      <button class="button button--secondary" ${selection.outputFileId ? 'data-inspector-action="inspect-output-file"' : "disabled"} type="button">Inspect output file</button>
      <button class="button" ${selection.outputFileId ? 'data-inspector-action="batch-output"' : "disabled"} type="button">Preview output</button>
    `;
    }
    return `<span class="muted">Select a file or batch to unlock context-aware actions.</span>`;
}
function buildContentPreviewSummary(text, fileId, label, support) {
    const lines = text ? text.split(/\r?\n/).length : 0;
    const nonEmptyLines = text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    const trimmed = text.trim();
    const json = trimmed ? safeJsonParse(trimmed, INVALID_JSON) : INVALID_JSON;
    let formatLabel = "text";
    let formatNote = lines <= 1 ? "single payload" : "plain text or JSON fragments";
    if (json !== INVALID_JSON) {
        if (Array.isArray(json)) {
            const records = json;
            formatLabel = "json array";
            formatNote = `${records.length} top-level item${records.length === 1 ? "" : "s"}`;
        }
        else if (json && typeof json === "object") {
            const fieldCount = Object.keys(json).length;
            formatLabel = "json object";
            formatNote = `${fieldCount} top-level field${fieldCount === 1 ? "" : "s"}`;
        }
        else {
            formatLabel = "json scalar";
        }
    }
    else if (nonEmptyLines.length > 0 &&
        nonEmptyLines.every((line) => safeJsonParse(line, INVALID_JSON) !== INVALID_JSON)) {
        formatLabel = "jsonl";
        formatNote = `${nonEmptyLines.length} record${nonEmptyLines.length === 1 ? "" : "s"}`;
    }
    return [
        { label: "Preview surface", value: label, note: support },
        { label: "File id", value: fileId },
        { label: "Format", value: formatLabel, note: formatNote },
        {
            label: "Payload size",
            value: `${lines} line${lines === 1 ? "" : "s"}`,
            note: formatBytes(new TextEncoder().encode(text).length),
        },
    ];
}
function readFilesBatchesFilters() {
    const params = new URLSearchParams(window.location.search);
    return {
        query: params.get("query") || "",
        purpose: params.get("purpose") || "",
        batchStatus: params.get("batch_status") || "",
        endpoint: params.get("endpoint") || "",
    };
}
function buildFilesBatchesUrl(filters) {
    const params = new URLSearchParams();
    setIfPresent(params, "query", filters.query);
    setIfPresent(params, "purpose", filters.purpose);
    setIfPresent(params, "batch_status", filters.batchStatus);
    setIfPresent(params, "endpoint", filters.endpoint);
    const query = params.toString();
    return query ? `/admin/files-batches?${query}` : "/admin/files-batches";
}
function matchesFile(item, filters) {
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
function matchesBatch(item, filters) {
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
function summarizeFilters(filters) {
    return [
        filters.query ? `text=${filters.query}` : "",
        filters.purpose ? `purpose=${filters.purpose}` : "",
        filters.batchStatus ? `status=${filters.batchStatus}` : "",
        filters.endpoint ? `endpoint=${filters.endpoint}` : "",
    ]
        .filter(Boolean)
        .join(" · ");
}
function renderSelectOptions(selected, values) {
    return [renderOption("", selected, "All"), ...values.map((value) => renderOption(value, selected))].join("");
}
function renderOption(value, selected, label) {
    return `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(label ?? value)}</option>`;
}
function uniqueOptions(values) {
    return Array.from(new Set(values
        .map((value) => String(value ?? "").trim())
        .filter(Boolean))).sort((left, right) => left.localeCompare(right));
}
function setIfPresent(params, key, value) {
    if (value) {
        params.set(key, value);
    }
}
function countLinkedBatches(fileId, batches) {
    return batches.filter((batch) => {
        const inputFileId = String(batch.input_file_id ?? "");
        const outputFileId = String(batch.output_file_id ?? "");
        return inputFileId === fileId || outputFileId === fileId;
    }).length;
}
function isAttentionBatchStatus(value) {
    const status = String(value ?? "").toLowerCase();
    return ["failed", "cancelled", "expired"].includes(status);
}
function renderBatchStatus(value) {
    const normalized = value || "unknown";
    if (normalized === "completed") {
        return pill(normalized, "good");
    }
    if (isAttentionBatchStatus(normalized)) {
        return pill(normalized, "warn");
    }
    return pill(normalized);
}
function humanizeBatchLifecycle(value) {
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
