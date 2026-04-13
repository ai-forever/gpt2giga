import { card, kpi, renderDefinitionList } from "../templates.js";
import { asArray, escapeHtml, formatBytes, formatTimestamp, safeJsonParse, } from "../utils.js";
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
    const completedBatches = filteredBatches.filter((batch) => batch.status === "completed").length;
    const activeBatches = filteredBatches.length - completedBatches;
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
    ${kpi("Completed", completedBatches)}
    ${kpi("Active", activeBatches)}
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
              ${renderDefinitionList([
        { label: "Selection", value: "No file or batch selected" },
        { label: "Files shown", value: `${filteredFiles.length}/${files.length}` },
        { label: "Batches shown", value: `${filteredBatches.length}/${batches.length}` },
        { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
    ], "No selection yet.")}
            </div>
            <pre class="code-block" id="files-batches-detail">No selection yet.</pre>
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
                          <td>${escapeHtml(item.status ?? "unknown")}</td>
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
    const batchInput = app.pageContent.querySelector("#batch-input-file-id");
    const filtersForm = app.pageContent.querySelector("#files-batches-filters-form");
    if (!detailNode || !contentNode || !summaryNode || !batchInput || !filtersForm) {
        return;
    }
    document.getElementById("refresh-files-batches")?.addEventListener("click", () => {
        void app.render("files-batches");
    });
    document
        .getElementById("reset-files-batches-filters")
        ?.addEventListener("click", () => {
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
    const setSummary = (items) => {
        summaryNode.innerHTML = renderDefinitionList(items, "No selection yet.");
    };
    app.pageContent
        .querySelector("#files-upload-form")
        ?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const upload = fields.file.files?.[0];
        if (!upload) {
            app.pushAlert("Choose a file before uploading.", "warn");
            return;
        }
        const body = new FormData();
        body.set("purpose", fields.purpose.value);
        body.set("file", upload, upload.name);
        const response = await app.api.json("/v1/files", { method: "POST", body }, true);
        app.queueAlert(`Uploaded file ${String(response.id ?? "")}.`, "info");
        await app.render("files-batches");
    });
    app.pageContent
        .querySelector("#batch-create-form")
        ?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const metadataText = fields.metadata.value.trim();
        const metadata = metadataText ? safeJsonParse(metadataText, "__invalid__") : undefined;
        if (metadata === "__invalid__" ||
            (metadata !== undefined &&
                (metadata === null || Array.isArray(metadata) || typeof metadata !== "object"))) {
            app.pushAlert("Batch metadata must be a JSON object.", "danger");
            return;
        }
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
    });
    app.pageContent.querySelectorAll("[data-file-view]").forEach((button) => {
        button.addEventListener("click", async () => {
            const fileId = button.dataset.fileView;
            if (!fileId) {
                return;
            }
            const payload = await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, {}, true);
            const source = fileLookup.get(fileId) ?? payload;
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
            detailNode.textContent = JSON.stringify(payload, null, 2);
        });
    });
    app.pageContent.querySelectorAll("[data-file-use]").forEach((button) => {
        button.addEventListener("click", () => {
            const fileId = button.dataset.fileUse;
            if (!fileId) {
                return;
            }
            const source = fileLookup.get(fileId);
            batchInput.value = fileId;
            setSummary([
                { label: "Selection", value: "Batch input ready" },
                { label: "File id", value: fileId },
                { label: "Purpose", value: String(source?.purpose ?? "batch") },
                { label: "Filename", value: String(source?.filename ?? fileId) },
                { label: "Next step", value: "Create batch", note: "The input field has been populated for the batch form." },
            ]);
            detailNode.textContent = `Selected ${fileId} as batch input.`;
            batchInput.focus();
        });
    });
    app.pageContent.querySelectorAll("[data-file-content]").forEach((button) => {
        button.addEventListener("click", async () => {
            const fileId = button.dataset.fileContent;
            if (!fileId) {
                return;
            }
            const source = fileLookup.get(fileId);
            setSummary([
                { label: "Selection", value: "File content preview" },
                { label: "File id", value: fileId },
                { label: "Filename", value: String(source?.filename ?? fileId) },
                { label: "Purpose", value: String(source?.purpose ?? "user_data") },
            ]);
            contentNode.textContent = "Loading file content…";
            contentNode.textContent = await app.api.text(`/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
        });
    });
    app.pageContent.querySelectorAll("[data-file-delete]").forEach((button) => {
        button.addEventListener("click", async () => {
            const fileId = button.dataset.fileDelete;
            if (!fileId) {
                return;
            }
            await app.api.json(`/v1/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }, true);
            app.queueAlert(`Deleted file ${fileId}.`, "info");
            await app.render("files-batches");
        });
    });
    app.pageContent.querySelectorAll("[data-batch-view]").forEach((button) => {
        button.addEventListener("click", async () => {
            const batchId = button.dataset.batchView;
            if (!batchId) {
                return;
            }
            const payload = await app.api.json(`/v1/batches/${encodeURIComponent(batchId)}`, {}, true);
            const source = batchLookup.get(batchId) ?? payload;
            setSummary([
                { label: "Selection", value: "Batch" },
                { label: "Batch id", value: batchId },
                { label: "Status", value: String(source.status ?? "unknown") },
                { label: "Endpoint", value: String(source.endpoint ?? "n/a") },
                {
                    label: "Output file",
                    value: String(source.output_file_id ?? "n/a"),
                    note: String(source.input_file_id ?? "no input file"),
                },
            ]);
            detailNode.textContent = JSON.stringify(payload, null, 2);
        });
    });
    app.pageContent.querySelectorAll("[data-batch-output]").forEach((button) => {
        button.addEventListener("click", async () => {
            const fileId = button.dataset.batchOutput;
            if (!fileId) {
                return;
            }
            const batch = batches.find((item) => String(item.output_file_id ?? "") === fileId);
            setSummary([
                { label: "Selection", value: "Batch output" },
                { label: "Output file", value: fileId },
                { label: "Batch id", value: String(batch?.id ?? "unknown") },
                { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
            ]);
            contentNode.textContent = "Loading batch output…";
            contentNode.textContent = await app.api.text(`/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
        });
    });
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
