import {
  card,
  kpi,
  renderDefinitionList,
  renderFilterSelectOptions,
  renderStaticSelectOptions,
} from "../../templates.js";
import { escapeHtml, formatBytes, formatTimestamp } from "../../utils.js";
import type { FilesBatchesPageData } from "./api.js";
import {
  buildIdleSelectionSummary,
  buildIdleWorkflowSummary,
  renderBatchStatus,
} from "./serializers.js";
import type { FilesBatchesFilters, FilesBatchesInventory } from "./state.js";

export interface FilesBatchesPageElements {
  actionNode: HTMLElement;
  batchForm: HTMLFormElement;
  batchInput: HTMLInputElement;
  contentNode: HTMLPreElement;
  contentSummaryNode: HTMLElement;
  detailNode: HTMLPreElement;
  detailSummaryNode: HTMLElement;
  filtersForm: HTMLFormElement;
  mediaNode: HTMLElement;
  refreshButton: HTMLButtonElement;
  resetButton: HTMLButtonElement;
  summaryNode: HTMLElement;
  uploadForm: HTMLFormElement;
  workflowNode: HTMLElement;
}

export function renderFilesBatchesHeroActions(): string {
  return `
    <button class="button button--secondary" id="reset-files-batches-filters" type="button">Reset filters</button>
    <button class="button button--secondary" id="refresh-files-batches" type="button">Refresh inventory</button>
    <a class="button" href="/admin/playground">Open playground</a>
  `;
}

export function renderFilesBatchesPage(
  data: FilesBatchesPageData,
  inventory: FilesBatchesInventory,
  filters: FilesBatchesFilters,
): string {
  return `
    ${kpi("Files shown", `${inventory.filteredFiles.length}/${data.files.length}`)}
    ${kpi("Batches shown", `${inventory.filteredBatches.length}/${data.batches.length}`)}
    ${kpi("Output ready", inventory.outputReadyBatches)}
    ${kpi("Needs attention", inventory.attentionBatches)}
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
                ${renderFilterSelectOptions(
                  filters.purpose,
                  data.files.map((item) => item.purpose),
                )}
              </select>
            </label>
            <label class="field">
              <span>Batch status</span>
              <select name="batch_status">
                ${renderFilterSelectOptions(
                  filters.batchStatus,
                  data.batches.map((item) => item.status),
                )}
              </select>
            </label>
            <label class="field">
              <span>Endpoint</span>
              <select name="endpoint">
                ${renderFilterSelectOptions(
                  filters.endpoint,
                  data.batches.map((item) => item.endpoint),
                )}
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
              ${renderStaticSelectOptions("/v1/chat/completions", ["/v1/chat/completions", "/v1/responses", "/v1/embeddings"])}
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
              ${renderDefinitionList(
                buildIdleSelectionSummary(
                  inventory.filteredFiles.length,
                  data.files.length,
                  inventory.filteredBatches.length,
                  data.batches.length,
                  filters,
                ),
                "No selection yet.",
              )}
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
      inventory.filteredFiles.length
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
        : "<p>No files matched the current filters.</p>",
      "panel panel--span-6",
    )}
    ${card(
      "Batch jobs",
      inventory.filteredBatches.length
        ? `
            <div class="table-wrap">
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
        : "<p>No batches matched the current filters.</p>",
      "panel panel--span-6",
    )}
  `;
}

export function resolveFilesBatchesElements(
  pageContent: HTMLElement,
): FilesBatchesPageElements | null {
  const detailNode = pageContent.querySelector<HTMLPreElement>("#files-batches-detail");
  const contentNode = pageContent.querySelector<HTMLPreElement>("#files-batches-content");
  const mediaNode = pageContent.querySelector<HTMLElement>("#files-batches-media");
  const summaryNode = pageContent.querySelector<HTMLElement>("#files-batches-summary");
  const workflowNode = pageContent.querySelector<HTMLElement>("#files-batches-workflow");
  const detailSummaryNode = pageContent.querySelector<HTMLElement>(
    "#files-batches-detail-summary",
  );
  const contentSummaryNode = pageContent.querySelector<HTMLElement>(
    "#files-batches-content-summary",
  );
  const actionNode = pageContent.querySelector<HTMLElement>("#files-batches-actions");
  const batchInput = pageContent.querySelector<HTMLInputElement>("#batch-input-file-id");
  const filtersForm = pageContent.querySelector<HTMLFormElement>(
    "#files-batches-filters-form",
  );
  const uploadForm = pageContent.querySelector<HTMLFormElement>("#files-upload-form");
  const batchForm = pageContent.querySelector<HTMLFormElement>("#batch-create-form");
  const refreshButton = document.getElementById(
    "refresh-files-batches",
  ) as HTMLButtonElement | null;
  const resetButton = document.getElementById(
    "reset-files-batches-filters",
  ) as HTMLButtonElement | null;

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
    !batchForm ||
    !refreshButton ||
    !resetButton
  ) {
    return null;
  }

  return {
    actionNode,
    batchForm,
    batchInput,
    contentNode,
    contentSummaryNode,
    detailNode,
    detailSummaryNode,
    filtersForm,
    mediaNode,
    refreshButton,
    resetButton,
    summaryNode,
    uploadForm,
    workflowNode,
  };
}
