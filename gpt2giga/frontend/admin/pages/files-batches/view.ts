import { pathForPage } from "../../routes.js";
import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import {
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderFilterSelectOptions,
  renderFormSection,
  renderGuideLinks,
  renderStaticSelectOptions,
  renderWorkflowCard,
} from "../../templates.js";
import { escapeHtml, formatBytes, formatTimestamp } from "../../utils.js";
import type { FilesBatchesPageData } from "./api.js";
import {
  buildFilesBatchesUrl,
  buildIdleSelectionSummary,
  buildIdleWorkflowSummary,
  describeFileValidationSnapshot,
  getLatestLinkedBatch,
  isBatchValidationCandidate,
  renderBatchStatus,
} from "./serializers.js";
import type {
  ArtifactApiFormat,
  FileSort,
  FilesBatchesFilters,
  FilesBatchesInventory,
  FilesBatchesPage,
} from "./state.js";
import { DEFAULT_FILE_SORT } from "./state.js";

export interface FilesBatchesPageElements {
  actionNode: HTMLElement;
  batchApiFormat: HTMLSelectElement | null;
  batchCreateButton: HTMLButtonElement | null;
  batchDisplayName: HTMLInputElement | null;
  batchDisplayNameField: HTMLElement | null;
  batchForm: HTMLFormElement | null;
  batchInput: HTMLInputElement | null;
  batchHint: HTMLElement | null;
  batchInlineRequestsExampleButton: HTMLButtonElement | null;
  batchInlineRequests: HTMLTextAreaElement | null;
  batchInlineRequestsField: HTMLElement | null;
  batchModel: HTMLInputElement | null;
  batchModelField: HTMLElement | null;
  batchEndpoint: HTMLSelectElement | null;
  batchValidateButton: HTMLButtonElement | null;
  batchValidationNode: HTMLElement | null;
  contentNode: HTMLPreElement;
  contentDisclosure: HTMLDetailsElement;
  contentSummaryNode: HTMLElement;
  contentSummaryTitleNode: HTMLElement;
  detailNode: HTMLPreElement;
  detailDisclosure: HTMLDetailsElement;
  detailSummaryNode: HTMLElement;
  detailSummaryTitleNode: HTMLElement;
  filtersForm: HTMLFormElement | null;
  mediaNode: HTMLElement;
  summaryNode: HTMLElement;
  uploadApiFormat: HTMLSelectElement | null;
  uploadDisplayName: HTMLInputElement | null;
  uploadDisplayNameField: HTMLElement | null;
  uploadForm: HTMLFormElement | null;
  uploadPurpose: HTMLSelectElement | null;
  uploadValidateButton: HTMLButtonElement | null;
  workflowNode: HTMLElement;
}

export function renderFilesBatchesHeroActions(page: FilesBatchesPage): string {
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

export function renderFilesBatchesPage(
  page: FilesBatchesPage,
  data: FilesBatchesPageData,
  inventory: FilesBatchesInventory,
  filters: FilesBatchesFilters,
): string {
  if (page === "files") {
    return renderFilesPage(data, inventory, filters);
  }
  if (page === "batches") {
    return renderBatchesPage(data, inventory, filters);
  }
  return renderFilesBatchesHub(data, inventory);
}

function renderFilesBatchesHub(
  data: FilesBatchesPageData,
  inventory: FilesBatchesInventory,
): string {
  const recentFiles = inventory.filteredFiles.slice(0, 5);
  const recentBatches = inventory.filteredBatches.slice(0, 5);

  return `
    ${kpi("Stored files", data.files.length)}
    ${kpi("Batch jobs", data.batches.length)}
    ${kpi("Output ready", inventory.outputReadyBatches)}
    ${kpi("Needs attention", inventory.attentionBatches)}
    ${card(
      "Shared workbench hub",
      `
        <div class="step-grid">
          ${renderWorkflowCard({
            workflow: "start",
            compact: true,
            title: "Stage one input on the files page",
            note: "Use Files for upload, inventory review, or preview.",
            pills: [pill("Upload"), pill("Inventory"), pill("Preview")],
            actions: [
              { label: "Open files", href: pathForPage("files"), primary: true },
              { label: "Open playground", href: pathForPage("playground") },
            ],
          })}
          ${renderWorkflowCard({
            workflow: "diagnose",
            compact: true,
            title: "Queue and inspect jobs on the batches page",
            note: "Use Batches for creation, lifecycle review, or output handoff.",
            pills: [pill("Composer"), pill("Lifecycle"), pill("Output", "good")],
            actions: [
              { label: "Open batches", href: pathForPage("batches"), primary: true },
              { label: "Open traffic", href: pathForPage("traffic") },
            ],
          })}
          ${renderWorkflowCard({
            workflow: "observe",
            compact: true,
            title: "Escalate only after one request is scoped",
            note: "Preview one output first, then hand off with request context.",
            pills: [pill("Traffic"), pill("Logs"), pill("Request scoped")],
            actions: [
              { label: "Open traffic", href: pathForPage("traffic"), primary: true },
              { label: "Open logs", href: pathForPage("logs") },
            ],
          })}
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Recent files",
      recentFiles.length
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
                      const validationSummary = isBatchValidationCandidate(item)
                        ? describeFileValidationSnapshot(item.validation)
                        : null;
                      return `
                        <tr>
                          <td><strong>${escapeHtml(item.filename ?? id)}</strong><br /><span class="muted">${escapeHtml(id)}</span>${validationSummary ? `<br />${pill(validationSummary.label, validationSummary.tone)} <span class="muted">${escapeHtml(validationSummary.note)}</span>` : ""}</td>
                          <td>${escapeHtml(item.purpose ?? "user_data")}</td>
                          <td>${escapeHtml(formatBytes(item.bytes))}</td>
                          <td>${latestBatch ? `${escapeHtml(String(latestBatch.id ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(latestBatch.status ?? "unknown"))}</span>` : '<span class="muted">No linked batch</span>'}</td>
                          <td>
                            <div class="toolbar">
                              <a class="button button--secondary" href="${escapeHtml(
                                buildFilesBatchesUrl(
                                  emptyFilters(),
                                  { selectedFileId: id },
                                  "files",
                                ),
                              )}">Files</a>
                              <a class="button" href="${escapeHtml(
                                buildFilesBatchesUrl(
                                  emptyFilters(),
                                  { composeInputFileId: id },
                                  "batches",
                                ),
                              )}">Batch composer</a>
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
        : "<p>No files are stored yet. Start on the files page to upload the first input.</p>",
      "panel panel--span-6",
    )}
    ${card(
      "Recent batches",
      recentBatches.length
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
                              <a class="button button--secondary" href="${escapeHtml(
                                buildFilesBatchesUrl(
                                  emptyFilters(),
                                  { selectedBatchId: id },
                                  "batches",
                                ),
                              )}">Batches</a>
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
        : "<p>No batches are stored yet. Open the batches page when the first queued job is ready.</p>",
      "panel panel--span-6",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
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
        ],
        {
          compact: true,
          collapsibleSummary: "Operator guides",
          intro: "Use the hub for counts and recent activity only.",
        },
      ),
      "panel panel--span-12",
    )}
  `;
}

function renderFilesPage(
  data: FilesBatchesPageData,
  inventory: FilesBatchesInventory,
  filters: FilesBatchesFilters,
): string {
  return `
    ${kpi("Files shown", `${inventory.filteredFiles.length}/${data.files.length}`)}
    ${kpi(
      "Filtered bytes",
      formatBytes(
        inventory.filteredFiles.reduce(
          (total, item) => total + Number(item.bytes ?? 0),
          0,
        ),
      ),
    )}
    ${kpi(
      "Linked batches",
      inventory.filteredFiles.reduce(
        (count, item) =>
          count + (getLatestLinkedBatch(String(item.id ?? ""), data.batches) ? 1 : 0),
        0,
      ),
    )}
    ${kpi("Ready outputs", inventory.outputReadyBatches)}
    ${card(
      "Files workbench",
      `
        <div class="stack">
          <p class="muted">Upload one artifact, inspect metadata, then preview content.</p>
          <div class="toolbar">
            <a class="button" href="${pathForPage("batches")}">Open batches</a>
            <a class="button button--secondary" href="${pathForPage("traffic")}">Open traffic</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${renderFiltersCard("files", data, filters)}
    ${card(
      "Upload input",
      `
        <div class="stack" id="files-batches-upload">
          <form id="files-upload-form" class="form-shell form-shell--compact">
            ${renderFormSection({
              title: "Upload source",
              intro: "Add one staged artifact and keep its intended API format attached.",
              body: `
                <label class="field">
                  <span>API format</span>
                  <select id="upload-api-format" name="api_format">
                    ${renderBatchApiFormatOptions("openai")}
                  </select>
                </label>
                <label class="field">
                  <span>Purpose</span>
                  <select id="upload-purpose" name="purpose">
                    ${renderStaticSelectOptions("batch", ["batch", "assistants", "user_data"])}
                  </select>
                </label>
                <label class="field" id="upload-display-name-field" hidden>
                  <span>Display name</span>
                  <input id="upload-display-name" name="display_name" placeholder="gemini-reference-artifact" />
                </label>
                <label class="field">
                  <span>File</span>
                  <input name="file" type="file" required />
                </label>
                <div class="banner" id="upload-format-hint">OpenAI uploads stage one file through the gateway files surface. Switch formats here when this artifact is meant for Anthropic or Gemini flows.</div>
              `,
            })}
            <div class="form-actions">
              <button class="button" type="submit">Upload file</button>
              <button
                class="button button--secondary"
                id="upload-and-validate-button"
                type="submit"
              >
                Upload and validate
              </button>
            </div>
          </form>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${renderInspectorCard(
      "files",
      inventory,
      data,
      filters,
      "File selection and preview",
      "Select one file to unlock metadata, preview, and batch handoff.",
      "panel panel--span-8",
    )}
    ${card(
      "Stored files",
      inventory.filteredFiles.length
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
                      const hasContent = Boolean(item.content_path);
                      const hasDownload = Boolean(item.download_path || item.content_path);
                      const hasDelete = Boolean(item.delete_path);
                      const validationSummary = isBatchValidationCandidate(item)
                        ? describeFileValidationSnapshot(item.validation)
                        : null;
                      return `
                        <tr>
                          <td><strong>${escapeHtml(item.filename ?? id)}</strong><br /><span class="muted">${escapeHtml(id)} · ${escapeHtml(String(item.api_format ?? "openai"))}</span>${validationSummary ? `<br />${pill(validationSummary.label, validationSummary.tone)} <span class="muted">${escapeHtml(validationSummary.note)}</span>` : ""}</td>
                          <td>${escapeHtml(item.purpose ?? "user_data")}</td>
                          <td>${escapeHtml(formatBytes(item.bytes))}</td>
                          <td>${latestBatch ? `${escapeHtml(String(latestBatch.id ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(latestBatch.status ?? "unknown"))}</span>` : '<span class="muted">No linked batch</span>'}</td>
                          <td>
                            <div class="toolbar">
                              <button class="button button--secondary" data-file-view="${escapeHtml(id)}" type="button">Inspect</button>
                              <button class="button button--secondary" ${hasContent ? `data-file-content="${escapeHtml(id)}"` : 'disabled title="Content preview is unavailable for this file"'} type="button">Content</button>
                              <button class="button button--secondary" ${hasDownload ? `data-file-download="${escapeHtml(id)}" data-file-download-name="${escapeHtml(String(item.filename ?? `file-${id}.bin`))}"` : 'disabled title="Download is unavailable for this file"'} type="button">Download</button>
                              <button class="button" data-file-use="${escapeHtml(id)}" type="button">Open batches</button>
                              <button class="button button--danger" ${hasDelete ? `data-file-delete="${escapeHtml(id)}"` : 'disabled title="Delete is unavailable for this file"'} type="button">Delete</button>
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
      "panel panel--span-8",
    )}
    ${card(
      "Next operator move",
      renderGuideLinks(
        [
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
        ],
        {
          compact: true,
          collapsibleSummary: "Operator guides",
          intro: "File preview and metadata stay primary here.",
        },
      ),
      "panel panel--span-4",
    )}
  `;
}

function renderBatchesPage(
  data: FilesBatchesPageData,
  inventory: FilesBatchesInventory,
  filters: FilesBatchesFilters,
): string {
  return `
    ${kpi("Batches shown", `${inventory.filteredBatches.length}/${data.batches.length}`)}
    ${kpi("Output ready", inventory.outputReadyBatches)}
    ${kpi("Needs attention", inventory.attentionBatches)}
    ${kpi(
      "Endpoints",
      new Set(inventory.filteredBatches.map((item) => String(item.endpoint ?? ""))).size,
    )}
    ${card(
      "Batch jobs workbench",
      `
        <div class="stack">
          <p class="muted">Queue one job, inspect lifecycle, then preview input or output.</p>
          <div class="toolbar">
            <a class="button" href="${pathForPage("files")}">Open files</a>
            <a class="button button--secondary" href="${pathForPage("logs")}">Open logs</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${renderFiltersCard("batches", data, filters)}
    ${card(
      "Queue batch job",
      `
        <div class="stack">
          <form id="batch-create-form" class="form-shell form-shell--compact">
            ${renderFormSection({
              title: "Queue one job",
              intro: "Use this after staging an input file, then choose the target API format.",
              body: `
                <label class="field">
                  <span>API format</span>
                  <select id="batch-api-format" name="api_format">
                    ${renderBatchApiFormatOptions("openai")}
                  </select>
                </label>
                <label class="field">
                  <span>Endpoint</span>
                  <select id="batch-endpoint" name="endpoint">
                    ${renderStaticSelectOptions("/v1/chat/completions", ["/v1/chat/completions", "/v1/responses", "/v1/embeddings"])}
                  </select>
                </label>
                <label class="field"><span>Input file id</span><input id="batch-input-file-id" name="input_file_id" placeholder="file-... (optional when using inline requests)" /></label>
                <label class="field" id="batch-inline-requests-field">
                  <span class="field__header">
                    <span>Inline requests (JSON array)</span>
                    <button class="button button--secondary button--inline" id="batch-inline-requests-example" type="button">Use example</button>
                  </span>
                  <textarea id="batch-inline-requests" name="requests" placeholder='[{"custom_id":"openai-row-1","method":"POST","url":"/v1/chat/completions","body":{"model":"gpt-4.1-mini","messages":[{"role":"user","content":"hello openai"}]}}]'></textarea>
                  <p class="field-note">Leave this empty to use <code>input_file_id</code>. Use the example button only when you want inline requests to be the active source.</p>
                </label>
                <label class="field" id="batch-model-field" hidden><span>Fallback model (optional)</span><input id="batch-model" name="model" placeholder="gemini-2.5-flash" /></label>
                <label class="field" id="batch-display-name-field" hidden><span>Display name</span><input id="batch-display-name" name="display_name" placeholder="nightly-gemini-import" /></label>
                <label class="field"><span>Metadata (optional JSON object)</span><textarea name="metadata" placeholder='{"label":"nightly-import"}'></textarea></label>
                <div class="banner banner--warn" id="batch-format-hint">OpenAI batches accept either a staged JSONL file in OpenAI batch input format or an inline JSON array shaped like [{custom_id, method, url, body}].</div>
              `,
            })}
            <div class="form-actions">
              <button class="button button--secondary" id="batch-validate-button" type="button">Validate file</button>
              <button class="button" id="batch-create-button" type="submit">Create batch job</button>
              <span class="muted">Validate first to get line-level diagnostics before queueing the batch.</span>
            </div>
            <div class="surface batch-validation" id="batch-validation-report">
              <div class="batch-validation__header">
                <div>
                  <h4>Validation report</h4>
                  <p class="muted">Run preflight validation before creating a batch.</p>
                </div>
                <div class="batch-validation__meta">
                  ${pill("Not validated")}
                </div>
              </div>
              <div class="batch-validation__summary">
                ${renderDefinitionList(
                  [
                    { label: "Status", value: "No report yet" },
                    { label: "Selected format", value: "OpenAI" },
                    { label: "Input source", value: "Choose a staged file or inline requests" },
                    { label: "Next step", value: "Run Validate file" },
                  ],
                  "No validation report yet.",
                )}
              </div>
              <p class="muted">The report will show detected format, row counts, and line-by-line issues for the current composer input.</p>
            </div>
          </form>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${renderInspectorCard(
      "batches",
      inventory,
      data,
      filters,
      "Batch lifecycle and output",
      "Select one batch to inspect lifecycle, preview input or output, and unlock request handoff.",
      "panel panel--span-8",
    )}
    ${card(
      "Batch jobs",
      inventory.filteredBatches.length
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
                      const outputReady = Boolean(item.output_path || outputFile);
                      return `
                        <tr>
                          <td><strong>${escapeHtml(id)}</strong><br /><span class="muted">${escapeHtml(String(item.input_file_id ?? "no input file"))} · ${escapeHtml(String(item.api_format ?? "openai"))}</span></td>
                          <td>${renderBatchStatus(String(item.status ?? "unknown"))}</td>
                          <td>${escapeHtml(item.endpoint ?? "n/a")}</td>
                          <td>${escapeHtml(outputFile || "n/a")}</td>
                          <td>
                            <div class="toolbar">
                              <button class="button button--secondary" data-batch-view="${escapeHtml(id)}" type="button">Inspect</button>
                              <button class="button button--secondary" ${item.input_file_id ? `data-batch-input="${escapeHtml(id)}"` : 'disabled title="Input file metadata is missing"'} type="button">Input</button>
                              <button class="button button--secondary" ${item.input_file_id ? `data-batch-input-preview="${escapeHtml(id)}"` : 'disabled title="Input preview is unavailable without an input file"'} type="button">Preview input</button>
                              <button class="button button--secondary" ${outputReady ? `data-batch-output="${escapeHtml(outputFile)}"` : 'disabled title="Output unlocks when the batch exposes a preview path"'} type="button">Preview output</button>
                              <button class="button button--secondary" ${outputReady ? `data-batch-download="${escapeHtml(outputFile)}" data-batch-download-name="${escapeHtml(`batch-output-${id}.jsonl`)}"` : 'disabled title="Download unlocks when the batch exposes a preview path"'} type="button">Download output</button>
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
      "panel panel--span-8",
    )}
    ${card(
      "Input staging handoff",
      renderGuideLinks(
        [
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
        ],
        {
          compact: true,
          collapsibleSummary: "Operator guides",
          intro: "Batch creation and lifecycle stay primary here.",
        },
      ),
      "panel panel--span-4",
    )}
  `;
}

function renderFiltersCard(
  page: FilesBatchesPage,
  data: FilesBatchesPageData,
  filters: FilesBatchesFilters,
): string {
  const fileFields = `
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
      <span>Sort by</span>
      <select name="file_sort">
        ${renderFileSortOptions(filters.fileSort)}
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
  `;

  return card(
    page === "files" ? "File filters" : "Batch filters",
    `
      <form id="files-batches-filters-form" class="form-shell form-shell--compact">
        ${renderFormSection({
          title: page === "files" ? "Inventory scope" : "Lifecycle scope",
          intro:
            page === "files"
              ? "Keep the inventory narrow enough for one-file review."
              : "Narrow lifecycle review before opening one batch or one output.",
          body: `
            <div class="${page === "files" ? "triple-grid" : "quad-grid"}">
              ${page === "files" ? fileFields : batchFields}
            </div>
          `,
        })}
        <div class="form-actions">
          <button class="button" type="submit">Apply filters</button>
          <span class="muted">${page === "files" ? "Keep the inventory small." : "Narrow review before opening one batch or output."}</span>
        </div>
      </form>
    `,
    "panel panel--span-12",
  );
}

function renderInspectorCard(
  page: FilesBatchesPage,
  inventory: FilesBatchesInventory,
  data: FilesBatchesPageData,
  filters: FilesBatchesFilters,
  title: string,
  intro: string,
  panelClass: string,
): string {
  return card(
    title,
    `
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
            ${renderDefinitionList(
              buildIdleSelectionSummary(
                page,
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
            ${renderDefinitionList(
              buildIdleWorkflowSummary(page),
              "No workflow state reported.",
            )}
          </div>
          <div id="files-batches-actions">
            <div class="toolbar">
              <span class="muted">${page === "files" ? "Select a file to unlock preview and batch handoff." : "Select a batch to unlock input, output, and lifecycle actions."}</span>
            </div>
          </div>
          <details class="details-disclosure" id="files-batches-detail-disclosure">
            <summary id="files-batches-detail-summary-label">Selection metadata snapshot</summary>
            <p class="field-note">
              Open this only when the selection summary is not enough.
            </p>
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
          </details>
          <details class="details-disclosure" id="files-batches-content-disclosure">
            <summary id="files-batches-content-summary-label">Content preview</summary>
            <p class="field-note">
              Content preview stays secondary until one file or batch output needs inspection.
            </p>
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
          </details>
        </div>
      </div>
    `,
    panelClass,
  );
}

export function resolveFilesBatchesElements(
  pageContent: HTMLElement,
): FilesBatchesPageElements | null {
  const detailNode = pageContent.querySelector<HTMLPreElement>("#files-batches-detail");
  const contentNode = pageContent.querySelector<HTMLPreElement>("#files-batches-content");
  const detailDisclosure = pageContent.querySelector<HTMLDetailsElement>(
    "#files-batches-detail-disclosure",
  );
  const contentDisclosure = pageContent.querySelector<HTMLDetailsElement>(
    "#files-batches-content-disclosure",
  );
  const detailSummaryTitleNode = pageContent.querySelector<HTMLElement>(
    "#files-batches-detail-summary-label",
  );
  const contentSummaryTitleNode = pageContent.querySelector<HTMLElement>(
    "#files-batches-content-summary-label",
  );
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

  if (
    !detailNode ||
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
    !actionNode
  ) {
    return null;
  }

  return {
    actionNode,
    batchApiFormat: pageContent.querySelector<HTMLSelectElement>("#batch-api-format"),
    batchCreateButton: pageContent.querySelector<HTMLButtonElement>(
      "#batch-create-button",
    ),
    batchDisplayName: pageContent.querySelector<HTMLInputElement>(
      "#batch-display-name",
    ),
    batchDisplayNameField: pageContent.querySelector<HTMLElement>(
      "#batch-display-name-field",
    ),
    batchForm: pageContent.querySelector<HTMLFormElement>("#batch-create-form"),
    batchInput: pageContent.querySelector<HTMLInputElement>("#batch-input-file-id"),
    batchHint: pageContent.querySelector<HTMLElement>("#batch-format-hint"),
    batchInlineRequestsExampleButton: pageContent.querySelector<HTMLButtonElement>(
      "#batch-inline-requests-example",
    ),
    batchInlineRequests: pageContent.querySelector<HTMLTextAreaElement>(
      "#batch-inline-requests",
    ),
    batchInlineRequestsField: pageContent.querySelector<HTMLElement>(
      "#batch-inline-requests-field",
    ),
    batchModel: pageContent.querySelector<HTMLInputElement>("#batch-model"),
    batchModelField: pageContent.querySelector<HTMLElement>("#batch-model-field"),
    batchEndpoint: pageContent.querySelector<HTMLSelectElement>("#batch-endpoint"),
    batchValidateButton: pageContent.querySelector<HTMLButtonElement>(
      "#batch-validate-button",
    ),
    batchValidationNode: pageContent.querySelector<HTMLElement>(
      "#batch-validation-report",
    ),
    contentNode,
    contentDisclosure,
    contentSummaryNode,
    contentSummaryTitleNode,
    detailNode,
    detailDisclosure,
    detailSummaryNode,
    detailSummaryTitleNode,
    filtersForm: pageContent.querySelector<HTMLFormElement>("#files-batches-filters-form"),
    mediaNode,
    summaryNode,
    uploadApiFormat: pageContent.querySelector<HTMLSelectElement>("#upload-api-format"),
    uploadDisplayName: pageContent.querySelector<HTMLInputElement>("#upload-display-name"),
    uploadDisplayNameField: pageContent.querySelector<HTMLElement>(
      "#upload-display-name-field",
    ),
    uploadForm: pageContent.querySelector<HTMLFormElement>("#files-upload-form"),
    uploadPurpose: pageContent.querySelector<HTMLSelectElement>("#upload-purpose"),
    uploadValidateButton: pageContent.querySelector<HTMLButtonElement>(
      "#upload-and-validate-button",
    ),
    workflowNode,
  };
}

function renderBatchApiFormatOptions(selected: ArtifactApiFormat): string {
  const options: Array<[ArtifactApiFormat, string]> = [
    ["openai", "OpenAI"],
    ["anthropic", "Anthropic"],
    ["gemini", "Gemini"],
  ];
  return options
    .map(
      ([value, label]) =>
        `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`,
    )
    .join("");
}

function emptyFilters(): FilesBatchesFilters {
  return {
    query: "",
    purpose: "",
    batchStatus: "",
    endpoint: "",
    fileSort: DEFAULT_FILE_SORT,
  };
}

function renderFileSortOptions(selected: FileSort): string {
  return [
    { value: DEFAULT_FILE_SORT, label: "Newest first" },
    { value: "created_asc", label: "Oldest first" },
    { value: "name_asc", label: "Name (A-Z)" },
    { value: "name_desc", label: "Name (Z-A)" },
    { value: "size_desc", label: "Size (largest)" },
    { value: "size_asc", label: "Size (smallest)" },
  ]
    .map(
      ({ value, label }) =>
        `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`,
    )
    .join("");
}
