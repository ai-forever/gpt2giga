import { card, kpi } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatBytes, formatTimestamp, safeJsonParse, } from "../utils.js";
export async function renderFilesBatches(app, token) {
    const [filesPayload, batchesPayload] = await Promise.all([
        app.api.json("/v1/files?order=desc&limit=100", {}, true),
        app.api.json("/v1/batches?limit=100", {}, true),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const files = asArray(filesPayload.data);
    const batches = asArray(batchesPayload.data);
    const completedBatches = batches.filter((batch) => batch.status === "completed").length;
    const activeBatches = batches.length - completedBatches;
    app.setHeroActions(`
    <button class="button button--secondary" id="refresh-files-batches" type="button">Refresh inventory</button>
    <a class="button" href="/admin/playground">Open playground</a>
  `);
    app.setContent(`
    ${kpi("Files", files.length)}
    ${kpi("Batches", batches.length)}
    ${kpi("Completed", completedBatches)}
    ${kpi("Active", activeBatches)}
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
        <div class="stack">
          <div class="banner">Select a file or batch to inspect metadata. Loading file content is separate so large JSONL payloads stay explicit.</div>
          <pre class="code-block" id="files-batches-detail">No selection yet.</pre>
          <pre class="code-block" id="files-batches-content">No file content loaded.</pre>
        </div>
      `, "panel panel--span-4")}
    ${card("Stored files", files.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>File</th><th>Purpose</th><th>Size</th><th>Created</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${files
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
                              <button class="button button--secondary" data-file-view="${escapeHtml(id)}" type="button">View</button>
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
        : "<p>No files uploaded yet.</p>", "panel panel--span-6")}
    ${card("Batch jobs", batches.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Batch</th><th>Status</th><th>Endpoint</th><th>Output</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${batches
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
                              <button class="button button--secondary" data-batch-view="${escapeHtml(id)}" type="button">View</button>
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
        : "<p>No batch jobs yet.</p>", "panel panel--span-6")}
  `);
    const detailNode = app.pageContent.querySelector("#files-batches-detail");
    const contentNode = app.pageContent.querySelector("#files-batches-content");
    const batchInput = app.pageContent.querySelector("#batch-input-file-id");
    if (!detailNode || !contentNode || !batchInput) {
        return;
    }
    document.getElementById("refresh-files-batches")?.addEventListener("click", () => {
        void app.render("files-batches");
    });
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
            detailNode.textContent = JSON.stringify(payload, null, 2);
        });
    });
    app.pageContent.querySelectorAll("[data-file-use]").forEach((button) => {
        button.addEventListener("click", () => {
            const fileId = button.dataset.fileUse;
            if (!fileId) {
                return;
            }
            batchInput.value = fileId;
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
            detailNode.textContent = JSON.stringify(payload, null, 2);
        });
    });
    app.pageContent.querySelectorAll("[data-batch-output]").forEach((button) => {
        button.addEventListener("click", async () => {
            const fileId = button.dataset.batchOutput;
            if (!fileId) {
                return;
            }
            contentNode.textContent = "Loading batch output…";
            contentNode.textContent = await app.api.text(`/v1/files/${encodeURIComponent(fileId)}/content`, {}, true);
        });
    });
}
