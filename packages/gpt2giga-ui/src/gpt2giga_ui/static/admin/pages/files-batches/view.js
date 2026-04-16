import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import { card, kpi, pill, renderDefinitionList, renderFilterSelectOptions, renderGuideLinks, renderStaticSelectOptions, renderWorkflowCard, } from "../../templates.js";
import { escapeHtml, formatBytes, formatTimestamp } from "../../utils.js";
import { buildIdleSelectionSummary, buildIdleWorkflowSummary, renderBatchStatus, } from "./serializers.js";
export function renderFilesBatchesHeroActions() {
    return `
    <button class="button button--secondary" id="reset-files-batches-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-files-batches" type="button">Refresh inventory</button>
    <a class="button" href="/admin/playground">Open playground</a>
  `;
}
export function renderFilesBatchesPage(data, inventory, filters) {
    return `
    ${kpi("Files shown", `${inventory.filteredFiles.length}/${data.files.length}`)}
    ${kpi("Batches shown", `${inventory.filteredBatches.length}/${data.batches.length}`)}
    ${kpi("Output ready", inventory.outputReadyBatches)}
    ${kpi("Needs attention", inventory.attentionBatches)}
    ${card("Staged files and batch workflow", `
        <div class="step-grid">
          ${renderWorkflowCard({
        workflow: "start",
        title: "Stage or reuse one input file",
        note: "Start with one JSONL input or stored artifact before touching the batch composer.",
        pills: [pill("Upload"), pill("Inspect")],
        actions: [
            { label: "Stage input", href: "#files-batches-upload", primary: true },
            { label: "Open playground", href: "/admin/playground" },
        ],
    })}
          ${renderWorkflowCard({
        workflow: "diagnose",
        title: "Inspect lifecycle before retrying",
        note: "Use the inspector to confirm file metadata, batch posture, and output availability before queuing another job.",
        pills: [pill("Metadata"), pill("Lifecycle"), pill("Output", "good")],
        actions: [
            { label: "Open inspector", href: "#files-batches-inspector", primary: true },
            { label: "Jump to batches", href: "#files-batches-batches" },
        ],
    })}
          ${renderWorkflowCard({
        workflow: "observe",
        title: "Escalate only when execution context is needed",
        note: "Once one batch or output needs request-level evidence, hand off into Traffic or Logs with the broader gateway context.",
        pills: [pill("Traffic"), pill("Logs"), pill("Downstream handoff")],
        actions: [
            { label: "Open traffic", href: "/admin/traffic", primary: true },
            { label: "Open logs", href: "/admin/logs" },
        ],
    })}
        </div>
      `, "panel panel--span-12")}
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
                ${renderFilterSelectOptions(filters.purpose, data.files.map((item) => item.purpose))}
              </select>
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
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Apply filters</button>
            <span class="muted">Filters work on the loaded gateway inventory so inspection stays local and immediate.</span>
          </div>
        </form>
      `, "panel panel--span-12")}
    ${card("Stage 1 · Upload input", `
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
    ${card("Stage 2 · Queue batch job", `
        <div class="stack">
          <p class="muted">
            Use this after selecting or uploading an input file. The composer stays separate from the inspector so retries remain deliberate.
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
    ${card("Inspector and staged handoff", `
        <div class="surface" id="files-batches-inspector">
          <div class="stack">
            <div class="workflow-card">
              <div class="workflow-card__header">
                <span class="eyebrow">Diagnose</span>
                <h4>Keep inventory summary-first</h4>
                <p>
                  Select one file or batch first. Raw metadata and content previews stay secondary until one object actually needs deeper inspection.
                </p>
              </div>
            </div>
            <div id="files-batches-summary">
              ${renderDefinitionList(buildIdleSelectionSummary(inventory.filteredFiles.length, data.files.length, inventory.filteredBatches.length, data.batches.length, filters), "No selection yet.")}
            </div>
            <div id="files-batches-workflow">
              ${renderDefinitionList(buildIdleWorkflowSummary(), "No workflow state reported.")}
            </div>
            <div id="files-batches-actions">
              <div class="toolbar">
                <span class="muted">Select a file or batch to unlock context-aware actions.</span>
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
      `, "panel panel--span-4")}
    ${card("Guide and troubleshooting", renderGuideLinks([
        {
            label: "Files and batches lifecycle",
            href: OPERATOR_GUIDE_LINKS.filesBatches,
            note: "Follow the staged operator path for uploads, queued jobs, output inspection, and the downstream request-evidence handoff.",
        },
        {
            label: "Traffic workflow guide",
            href: OPERATOR_GUIDE_LINKS.traffic,
            note: "Open this when a batch output now needs request-level evidence and the next move is the broader recent-traffic summary.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the escalation map when the problem moved from stored artifacts into runtime failures, provider posture, or log evidence.",
        },
    ], "Files and batch work stays local until one stored artifact needs runtime evidence. These guide links show when to stay on the workbench and when to branch into the broader operator flow."), "panel panel--span-4")}
    ${card("Stored files", inventory.filteredFiles.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>File</th><th>Purpose</th><th>Size</th><th>Created</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${inventory.filteredFiles
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
        : "<p>No batches matched the current filters.</p>", "panel panel--span-6")}
  `;
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
    const batchInput = pageContent.querySelector("#batch-input-file-id");
    const filtersForm = pageContent.querySelector("#files-batches-filters-form");
    const uploadForm = pageContent.querySelector("#files-upload-form");
    const batchForm = pageContent.querySelector("#batch-create-form");
    const refreshButton = document.getElementById("refresh-files-batches");
    const resetButton = document.getElementById("reset-files-batches-filters");
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
        !actionNode ||
        !batchInput ||
        !filtersForm ||
        !uploadForm ||
        !batchForm ||
        !refreshButton ||
        !resetButton) {
        return null;
    }
    return {
        actionNode,
        batchForm,
        batchInput,
        contentNode,
        contentDisclosure,
        contentSummaryNode,
        contentSummaryTitleNode,
        detailNode,
        detailDisclosure,
        detailSummaryNode,
        detailSummaryTitleNode,
        filtersForm,
        mediaNode,
        refreshButton,
        resetButton,
        summaryNode,
        uploadForm,
        workflowNode,
    };
}
