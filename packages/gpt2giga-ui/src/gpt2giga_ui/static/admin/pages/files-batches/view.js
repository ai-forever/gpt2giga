import { pathForPage } from "../../routes.js";
import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import { card, kpi, pill, renderDefinitionList, renderFilterSelectOptions, renderGuideLinks, renderStaticSelectOptions, renderWorkflowCard, } from "../../templates.js";
import { escapeHtml, formatBytes, formatTimestamp } from "../../utils.js";
import { buildFilesBatchesUrl, buildIdleSelectionSummary, buildIdleWorkflowSummary, getLatestLinkedBatch, renderBatchStatus, } from "./serializers.js";
export function renderFilesBatchesHeroActions(page) {
    if (page === "files-batches") {
        return `
      <button class="button button--secondary" id="refresh-files-batches" type="button">Refresh inventory</button>
      <a class="button button--secondary" href="${pathForPage("files")}">Open files</a>
      <a class="button" href="${pathForPage("batches")}">Open batches</a>
    `;
    }
    return `
    <button class="button button--secondary" id="reset-files-batches-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-files-batches" type="button">Refresh inventory</button>
    <a class="button" href="${pathForPage(page === "files" ? "batches" : "files")}">${page === "files" ? "Open batches" : "Open files"}</a>
  `;
}
export function renderFilesBatchesPage(page, data, inventory, filters) {
    if (page === "files") {
        return renderFilesPage(data, inventory, filters);
    }
    if (page === "batches") {
        return renderBatchesPage(data, inventory, filters);
    }
    return renderFilesBatchesHub(data, inventory);
}
function renderFilesBatchesHub(data, inventory) {
    const recentFiles = inventory.filteredFiles.slice(0, 5);
    const recentBatches = inventory.filteredBatches.slice(0, 5);
    return `
    ${kpi("Stored files", data.files.length)}
    ${kpi("Batch jobs", data.batches.length)}
    ${kpi("Output ready", inventory.outputReadyBatches)}
    ${kpi("Needs attention", inventory.attentionBatches)}
    ${card("Shared workbench hub", `
        <div class="step-grid">
          ${renderWorkflowCard({
        workflow: "start",
        title: "Stage one input on the files page",
        note: "Use the dedicated files surface when the next operator move is upload, inventory review, or content preview.",
        pills: [pill("Upload"), pill("Inventory"), pill("Preview")],
        actions: [
            { label: "Open files", href: pathForPage("files"), primary: true },
            { label: "Open playground", href: pathForPage("playground") },
        ],
    })}
          ${renderWorkflowCard({
        workflow: "diagnose",
        title: "Queue and inspect jobs on the batches page",
        note: "Use the dedicated batches surface when the next move is creation, lifecycle review, or output handoff.",
        pills: [pill("Composer"), pill("Lifecycle"), pill("Output", "good")],
        actions: [
            { label: "Open batches", href: pathForPage("batches"), primary: true },
            { label: "Open traffic", href: pathForPage("traffic") },
        ],
    })}
          ${renderWorkflowCard({
        workflow: "observe",
        title: "Escalate only after one request is scoped",
        note: "Traffic and Logs stay downstream from the workbench. Preview one output first, then hand off with request context.",
        pills: [pill("Traffic"), pill("Logs"), pill("Request scoped")],
        actions: [
            { label: "Open traffic", href: pathForPage("traffic"), primary: true },
            { label: "Open logs", href: pathForPage("logs") },
        ],
    })}
        </div>
      `, "panel panel--span-12")}
    ${card("Recent files", recentFiles.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>File</th><th>Purpose</th><th>Size</th><th>Latest batch</th><th>Open</th></tr>
                </thead>
                <tbody>
                  ${recentFiles
            .map((item) => {
            const id = String(item.id ?? "");
            const latestBatch = getLatestLinkedBatch(id, data.batches);
            return `
                        <tr>
                          <td><strong>${escapeHtml(item.filename ?? id)}</strong><br /><span class="muted">${escapeHtml(id)}</span></td>
                          <td>${escapeHtml(item.purpose ?? "user_data")}</td>
                          <td>${escapeHtml(formatBytes(item.bytes))}</td>
                          <td>${latestBatch ? `${escapeHtml(String(latestBatch.id ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(latestBatch.status ?? "unknown"))}</span>` : '<span class="muted">No linked batch</span>'}</td>
                          <td>
                            <div class="toolbar">
                              <a class="button button--secondary" href="${escapeHtml(buildFilesBatchesUrl(emptyFilters(), { selectedFileId: id }, "files"))}">Files</a>
                              <a class="button" href="${escapeHtml(buildFilesBatchesUrl(emptyFilters(), { composeInputFileId: id }, "batches"))}">Batch composer</a>
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
        : "<p>No files are stored yet. Start on the files page to upload the first input.</p>", "panel panel--span-6")}
    ${card("Recent batches", recentBatches.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Batch</th><th>Status</th><th>Endpoint</th><th>Output</th><th>Open</th></tr>
                </thead>
                <tbody>
                  ${recentBatches
            .map((item) => {
            const id = String(item.id ?? "");
            return `
                        <tr>
                          <td><strong>${escapeHtml(id)}</strong><br /><span class="muted">${escapeHtml(String(item.input_file_id ?? "no input file"))}</span></td>
                          <td>${renderBatchStatus(String(item.status ?? "unknown"))}</td>
                          <td>${escapeHtml(item.endpoint ?? "n/a")}</td>
                          <td>${escapeHtml(String(item.output_file_id ?? "n/a"))}</td>
                          <td>
                            <div class="toolbar">
                              <a class="button button--secondary" href="${escapeHtml(buildFilesBatchesUrl(emptyFilters(), { selectedBatchId: id }, "batches"))}">Batches</a>
                              <a class="button button--secondary" href="${pathForPage("traffic")}">Traffic</a>
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
        : "<p>No batches are stored yet. Open the batches page when the first queued job is ready.</p>", "panel panel--span-6")}
    ${card("Guide and troubleshooting", renderGuideLinks([
        {
            label: "Files and batches lifecycle",
            href: OPERATOR_GUIDE_LINKS.filesBatches,
            note: "Follow the staged operator path for uploads, queued jobs, output inspection, and downstream request handoff.",
        },
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Open this when a decoded batch output now needs request-level evidence.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the escalation map once the issue moved from stored artifacts into runtime posture or log evidence.",
        },
    ], "Use the hub for counts and recent activity only. Open the focused pages when one stored object now needs real operator work."), "panel panel--span-12")}
  `;
}
function renderFilesPage(data, inventory, filters) {
    return `
    ${kpi("Files shown", `${inventory.filteredFiles.length}/${data.files.length}`)}
    ${kpi("Filtered bytes", formatBytes(inventory.filteredFiles.reduce((total, item) => total + Number(item.bytes ?? 0), 0)))}
    ${kpi("Linked batches", inventory.filteredFiles.reduce((count, item) => count + (getLatestLinkedBatch(String(item.id ?? ""), data.batches) ? 1 : 0), 0))}
    ${kpi("Ready outputs", inventory.outputReadyBatches)}
    ${card("Files workbench", `
        <div class="stack">
          <p class="muted">
            Keep this page file-first: upload one artifact, inspect stored metadata, and preview content before deciding whether the next move belongs on the batches page.
          </p>
          <div class="toolbar">
            <a class="button" href="${pathForPage("batches")}">Open batches</a>
            <a class="button button--secondary" href="${pathForPage("traffic")}">Open traffic</a>
          </div>
        </div>
      `, "panel panel--span-12")}
    ${renderFiltersCard("files", data, filters)}
    ${card("Upload input", `
        <div class="stack" id="files-batches-upload">
          <p class="muted">
            Start here when a fresh JSONL input or reference artifact needs to enter the gateway inventory.
          </p>
          <form id="files-upload-form" class="stack">
            <label class="field">
              <span>Purpose</span>
              <select name="purpose">
                ${renderStaticSelectOptions("batch", ["batch", "assistants", "user_data"])}
              </select>
            </label>
            <label class="field">
              <span>File</span>
              <input name="file" type="file" required />
            </label>
            <div class="banner">Uploads go through the OpenAI-compatible gateway surface and use the gateway API key from the rail.</div>
            <button class="button" type="submit">Upload file</button>
          </form>
        </div>
      `, "panel panel--span-4")}
    ${renderInspectorCard("files", inventory, data, filters, "File selection and preview", "Select one stored file to unlock metadata, content preview, and a clean handoff into the dedicated batch composer.", "panel panel--span-8")}
    ${card("Stored files", inventory.filteredFiles.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>File</th><th>Purpose</th><th>Size</th><th>Latest batch</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${inventory.filteredFiles
            .map((item) => {
            const id = String(item.id ?? "");
            const latestBatch = getLatestLinkedBatch(id, data.batches);
            return `
                        <tr>
                          <td><strong>${escapeHtml(item.filename ?? id)}</strong><br /><span class="muted">${escapeHtml(id)}</span></td>
                          <td>${escapeHtml(item.purpose ?? "user_data")}</td>
                          <td>${escapeHtml(formatBytes(item.bytes))}</td>
                          <td>${latestBatch ? `${escapeHtml(String(latestBatch.id ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(latestBatch.status ?? "unknown"))}</span>` : '<span class="muted">No linked batch</span>'}</td>
                          <td>
                            <div class="toolbar">
                              <button class="button button--secondary" data-file-view="${escapeHtml(id)}" type="button">Inspect</button>
                              <button class="button button--secondary" data-file-content="${escapeHtml(id)}" type="button">Content</button>
                              <button class="button" data-file-use="${escapeHtml(id)}" type="button">Open batches</button>
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
        : "<p>No files matched the current filters.</p>", "panel panel--span-8")}
    ${card("Next operator move", renderGuideLinks([
        {
            label: "Files and batches lifecycle",
            href: OPERATOR_GUIDE_LINKS.filesBatches,
            note: "Stay on this page while the task is still file-centric. Move to batches only once queueing or lifecycle review is next.",
        },
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Open Traffic only after one file output or batch result has been decoded into a request-level clue.",
        },
    ], "File preview and metadata stay primary here. Batch creation, job history, and output triage live on the dedicated batches surface."), "panel panel--span-4")}
  `;
}
function renderBatchesPage(data, inventory, filters) {
    return `
    ${kpi("Batches shown", `${inventory.filteredBatches.length}/${data.batches.length}`)}
    ${kpi("Output ready", inventory.outputReadyBatches)}
    ${kpi("Needs attention", inventory.attentionBatches)}
    ${kpi("Endpoints", new Set(inventory.filteredBatches.map((item) => String(item.endpoint ?? ""))).size)}
    ${card("Batch jobs workbench", `
        <div class="stack">
          <p class="muted">
            Keep this page batch-first: queue one job, inspect lifecycle state, preview input or output, and only then branch into request-level Traffic or Logs.
          </p>
          <div class="toolbar">
            <a class="button" href="${pathForPage("files")}">Open files</a>
            <a class="button button--secondary" href="${pathForPage("logs")}">Open logs</a>
          </div>
        </div>
      `, "panel panel--span-12")}
    ${renderFiltersCard("batches", data, filters)}
    ${card("Queue batch job", `
        <div class="stack">
          <p class="muted">
            Use this after staging an input file. If a new file still needs upload, switch to the files page first.
          </p>
          <form id="batch-create-form" class="stack">
            <label class="field">
              <span>Endpoint</span>
              <select name="endpoint">
                ${renderStaticSelectOptions("/v1/chat/completions", ["/v1/chat/completions", "/v1/responses", "/v1/embeddings"])}
              </select>
            </label>
            <label class="field"><span>Input file id</span><input id="batch-input-file-id" name="input_file_id" placeholder="file-..." required /></label>
            <label class="field"><span>Metadata (optional JSON object)</span><textarea name="metadata" placeholder='{"label":"nightly-import"}'></textarea></label>
            <div class="banner banner--warn">Batch creation expects an uploaded JSONL file in OpenAI batch input format.</div>
            <button class="button" type="submit">Create batch job</button>
          </form>
        </div>
      `, "panel panel--span-4")}
    ${renderInspectorCard("batches", inventory, data, filters, "Batch lifecycle and output", "Select one batch to inspect lifecycle metadata, preview input or output, and unlock request-scoped handoff only when one output is decoded.", "panel panel--span-8")}
    ${card("Batch jobs", inventory.filteredBatches.length
        ? `
            <div class="table-wrap" id="files-batches-batches">
              <table>
                <thead>
                  <tr><th>Batch</th><th>Status</th><th>Endpoint</th><th>Output</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${inventory.filteredBatches
            .map((item) => {
            const id = String(item.id ?? "");
            const outputFile = String(item.output_file_id ?? "");
            return `
                        <tr>
                          <td><strong>${escapeHtml(id)}</strong><br /><span class="muted">${escapeHtml(String(item.input_file_id ?? "no input file"))}</span></td>
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
        : "<p>No batches matched the current filters.</p>", "panel panel--span-8")}
    ${card("Input staging handoff", renderGuideLinks([
        {
            label: "Files and batches lifecycle",
            href: OPERATOR_GUIDE_LINKS.filesBatches,
            note: "Open the files page when the missing piece is still upload, file metadata, or a clean content preview before retrying a job.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the broader map once batch lifecycle signals are no longer enough and the issue moved into provider posture or request logs.",
        },
    ], "Batch creation and lifecycle stay primary here. File staging is now a deliberate handoff back to the dedicated files page instead of another section on the same screen."), "panel panel--span-4")}
  `;
}
function renderFiltersCard(page, data, filters) {
    const fileFields = `
    <label class="field">
      <span>Search</span>
      <input name="query" value="${escapeHtml(filters.query)}" placeholder="Filter by id, filename, or metadata label" />
    </label>
    <label class="field">
      <span>File purpose</span>
      <select name="purpose">
        ${renderFilterSelectOptions(filters.purpose, data.files.map((item) => item.purpose))}
      </select>
    </label>
  `;
    const batchFields = `
    <label class="field">
      <span>Search</span>
      <input name="query" value="${escapeHtml(filters.query)}" placeholder="Filter by batch id, file id, or endpoint" />
    </label>
    <label class="field">
      <span>Batch status</span>
      <select name="batch_status">
        ${renderFilterSelectOptions(filters.batchStatus, data.batches.map((item) => item.status))}
      </select>
    </label>
    <label class="field">
      <span>Endpoint</span>
      <select name="endpoint">
        ${renderFilterSelectOptions(filters.endpoint, data.batches.map((item) => item.endpoint))}
      </select>
    </label>
  `;
    return card(page === "files" ? "File filters" : "Batch filters", `
      <form id="files-batches-filters-form" class="stack">
        <div class="${page === "files" ? "dual-grid" : "quad-grid"}">
          ${page === "files" ? fileFields : batchFields}
        </div>
        <div class="toolbar">
          <button class="button" type="submit">Apply filters</button>
          <span class="muted">${page === "files" ? "Keep the inventory small while preview and upload work stays local to one file." : "Narrow lifecycle review before opening one batch or output."}</span>
        </div>
      </form>
    `, "panel panel--span-12");
}
function renderInspectorCard(page, inventory, data, filters, title, intro, panelClass) {
    return card(title, `
      <div class="surface" id="files-batches-inspector">
        <div class="stack">
          <div class="workflow-card">
            <div class="workflow-card__header">
              <span class="eyebrow">${page === "files" ? "Files" : "Batches"}</span>
              <h4>${escapeHtml(title)}</h4>
              <p>${escapeHtml(intro)}</p>
            </div>
          </div>
          <div id="files-batches-summary">
            ${renderDefinitionList(buildIdleSelectionSummary(page, inventory.filteredFiles.length, data.files.length, inventory.filteredBatches.length, data.batches.length, filters), "No selection yet.")}
          </div>
          <div id="files-batches-workflow">
            ${renderDefinitionList(buildIdleWorkflowSummary(page), "No workflow state reported.")}
          </div>
          <div id="files-batches-actions">
            <div class="toolbar">
              <span class="muted">${page === "files" ? "Select a file to unlock preview and batch handoff." : "Select a batch to unlock input, output, and lifecycle actions."}</span>
            </div>
          </div>
          <details class="details-disclosure" id="files-batches-detail-disclosure">
            <summary id="files-batches-detail-summary-label">Selection metadata snapshot</summary>
            <p class="field-note">
              Open this only when the selection summary is not enough and raw file or batch metadata still matters.
            </p>
            <div id="files-batches-detail-summary">
              ${renderDefinitionList([
        { label: "Detail surface", value: "Idle" },
        { label: "Loaded object", value: "No file or batch metadata loaded" },
    ], "No detail payload loaded.")}
            </div>
            <pre class="code-block code-block--tall" id="files-batches-detail">No selection yet.</pre>
          </details>
          <details class="details-disclosure" id="files-batches-content-disclosure">
            <summary id="files-batches-content-summary-label">Content preview</summary>
            <p class="field-note">
              Content preview stays secondary until one file or batch output actually needs inspection.
            </p>
            <div id="files-batches-content-summary">
              ${renderDefinitionList([
        { label: "Preview surface", value: "Idle" },
        { label: "Loaded content", value: "No file content loaded" },
    ], "No file content loaded.")}
            </div>
            <div id="files-batches-media"></div>
            <pre class="code-block code-block--tall" id="files-batches-content">No file content loaded.</pre>
          </details>
        </div>
      </div>
    `, panelClass);
}
export function resolveFilesBatchesElements(pageContent) {
    const detailNode = pageContent.querySelector("#files-batches-detail");
    const contentNode = pageContent.querySelector("#files-batches-content");
    const detailDisclosure = pageContent.querySelector("#files-batches-detail-disclosure");
    const contentDisclosure = pageContent.querySelector("#files-batches-content-disclosure");
    const detailSummaryTitleNode = pageContent.querySelector("#files-batches-detail-summary-label");
    const contentSummaryTitleNode = pageContent.querySelector("#files-batches-content-summary-label");
    const mediaNode = pageContent.querySelector("#files-batches-media");
    const summaryNode = pageContent.querySelector("#files-batches-summary");
    const workflowNode = pageContent.querySelector("#files-batches-workflow");
    const detailSummaryNode = pageContent.querySelector("#files-batches-detail-summary");
    const contentSummaryNode = pageContent.querySelector("#files-batches-content-summary");
    const actionNode = pageContent.querySelector("#files-batches-actions");
    if (!detailNode ||
        !contentNode ||
        !detailDisclosure ||
        !contentDisclosure ||
        !detailSummaryTitleNode ||
        !contentSummaryTitleNode ||
        !mediaNode ||
        !summaryNode ||
        !workflowNode ||
        !detailSummaryNode ||
        !contentSummaryNode ||
        !actionNode) {
        return null;
    }
    return {
        actionNode,
        batchForm: pageContent.querySelector("#batch-create-form"),
        batchInput: pageContent.querySelector("#batch-input-file-id"),
        contentNode,
        contentDisclosure,
        contentSummaryNode,
        contentSummaryTitleNode,
        detailNode,
        detailDisclosure,
        detailSummaryNode,
        detailSummaryTitleNode,
        filtersForm: pageContent.querySelector("#files-batches-filters-form"),
        mediaNode,
        summaryNode,
        uploadForm: pageContent.querySelector("#files-upload-form"),
        workflowNode,
    };
}
function emptyFilters() {
    return {
        query: "",
        purpose: "",
        batchStatus: "",
        endpoint: "",
    };
}
