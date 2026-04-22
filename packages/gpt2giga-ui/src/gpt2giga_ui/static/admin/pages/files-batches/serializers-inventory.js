import { pill } from "../../templates.js";
import { escapeHtml, setQueryParamIfPresent } from "../../utils.js";
import { DEFAULT_FILE_SORT } from "./state.js";
export function buildFilesBatchesInventory(data, filters) {
    const filteredFiles = data.files
        .filter((item) => matchesFile(item, filters))
        .sort((left, right) => compareFiles(left, right, filters.fileSort));
    const filteredBatches = data.batches.filter((item) => matchesBatch(item, filters));
    return {
        filteredFiles,
        filteredBatches,
        attentionBatches: filteredBatches.filter((batch) => isAttentionBatchStatus(batch.status)).length,
        outputReadyBatches: filteredBatches.filter((batch) => Boolean(String(batch.output_file_id ?? ""))).length,
        fileLookup: new Map(data.files.map((item) => [String(item.id ?? ""), item])),
        batchLookup: new Map(data.batches.map((item) => [String(item.id ?? ""), item])),
    };
}
export function buildIdleSelectionSummary(page, filteredFiles, totalFiles, filteredBatches, totalBatches, filters) {
    if (page === "files") {
        return [
            { label: "Selection", value: "No file selected" },
            { label: "Files shown", value: `${filteredFiles}/${totalFiles}` },
            { label: "Current focus", value: "Upload, inspect, or preview one stored file" },
            { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
        ];
    }
    if (page === "batches") {
        return [
            { label: "Selection", value: "No batch selected" },
            { label: "Batches shown", value: `${filteredBatches}/${totalBatches}` },
            {
                label: "Current focus",
                value: "Inspect lifecycle, preview output, or queue the next job",
            },
            { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
        ];
    }
    return [
        { label: "Selection", value: "No file or batch selected" },
        { label: "Files shown", value: `${filteredFiles}/${totalFiles}` },
        { label: "Batches shown", value: `${filteredBatches}/${totalBatches}` },
        { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
    ];
}
export function buildIdleWorkflowSummary(page) {
    if (page === "files") {
        return [
            { label: "Workflow state", value: "Idle" },
            { label: "Current posture", value: "No file action in progress" },
            {
                label: "Next step",
                value: "Stage or inspect one file",
                note: "Upload a new artifact or select one stored file to unlock preview and batch handoff.",
            },
        ];
    }
    if (page === "batches") {
        return [
            { label: "Workflow state", value: "Idle" },
            { label: "Current posture", value: "No batch action in progress" },
            {
                label: "Next step",
                value: "Inspect one batch",
                note: "Select a batch to unlock input preview, output preview, and request-scoped handoff.",
            },
        ];
    }
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
export function renderInspectorActions(page, selection, fileLookup, batchLookup, batches) {
    if (selection.kind === "file" && selection.fileId) {
        const source = fileLookup.get(selection.fileId);
        const latestBatch = getLatestLinkedBatch(selection.fileId, batches);
        const latestOutputBatch = getLatestOutputBatch(selection.fileId, batches);
        return `
      <div class="toolbar">
        <button class="button button--secondary" data-inspector-action="inspect-file" type="button">Refresh metadata</button>
        <button class="button button--secondary" data-inspector-action="preview-file" type="button">Preview content</button>
        <button class="button button--secondary" data-inspector-action="download-file" type="button">Download file</button>
        <button class="button" data-inspector-action="use-file" type="button">${page === "files" ? "Open batch composer" : "Use for batch"}</button>
        <button class="button button--secondary" ${latestBatch ? 'data-inspector-action="inspect-linked-batch"' : 'disabled title="No linked batch record yet"'} type="button">Inspect latest batch</button>
        <button class="button button--secondary" ${latestOutputBatch ? 'data-inspector-action="preview-linked-output"' : 'disabled title="No linked output file yet"'} type="button">Preview latest output</button>
      </div>
      <p class="muted">
        ${escapeHtml(source
            ? page === "files"
                ? `${String(source.filename ?? selection.fileId)} stays file-first on this page. Open the dedicated batches surface when the next move is queueing a job.`
                : `${String(source.filename ?? selection.fileId)} can feed a new batch immediately. Linked batch actions unlock as downstream jobs appear.`
            : page === "files"
                ? "This file can be previewed here, then handed off into the dedicated batches page when queueing is next."
                : "This file can be previewed, queued as batch input, or handed off into the latest linked batch context.")}
        ${escapeHtml(latestOutputBatch
            ? " Preview the latest output to unlock request-scoped Traffic and Logs handoff."
            : "")}
      </p>
    `;
    }
    if (selection.kind === "batch" && selection.batchId) {
        const source = batchLookup.get(selection.batchId);
        const handoffActions = renderBatchHandoffActions(selection);
        return `
      <div class="toolbar">
        <button class="button button--secondary" data-inspector-action="inspect-batch" type="button">Refresh batch</button>
        <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="batch-input"' : 'disabled title="Input file metadata is missing"'} type="button">Inspect input</button>
        <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="preview-batch-input"' : 'disabled title="Input preview is unavailable without an input file"'} type="button">Preview input</button>
        <button class="button button--secondary" ${selection.inputFileId ? 'data-inspector-action="use-batch-input"' : 'disabled title="Input file is required to retry this batch"'} type="button">Queue with input</button>
        <button class="button button--secondary" ${selection.outputFileId ? 'data-inspector-action="inspect-output-file"' : 'disabled title="Output metadata appears after the provider creates output_file_id"'} type="button">Inspect output file</button>
        <button class="button" ${selection.outputFileId ? 'data-inspector-action="batch-output"' : 'disabled title="Output preview unlocks after completion"'} type="button">Preview output</button>
      </div>
      ${handoffActions}
      <p class="muted">${escapeHtml(buildBatchActionHint(source, selection))}</p>
    `;
    }
    return `
    <div class="toolbar">
      <span class="muted">Select a file or batch to unlock context-aware actions.</span>
    </div>
  `;
}
export function getLinkedBatchesForFile(fileId, batches) {
    return batches
        .filter((batch) => {
        const inputFileId = String(batch.input_file_id ?? "");
        const outputFileId = String(batch.output_file_id ?? "");
        return inputFileId === fileId || outputFileId === fileId;
    })
        .sort((left, right) => Number(right.created_at ?? 0) - Number(left.created_at ?? 0));
}
export function getLatestLinkedBatch(fileId, batches) {
    return getLinkedBatchesForFile(fileId, batches)[0] ?? null;
}
export function getLatestOutputBatch(fileId, batches) {
    return (getLinkedBatchesForFile(fileId, batches).find((batch) => Boolean(String(batch.output_file_id ?? ""))) ?? null);
}
export function summarizeBatchRequestCounts(value) {
    if (!value || typeof value !== "object") {
        return "counts unavailable";
    }
    const counts = value;
    const total = Number(counts.total ?? counts.request_count ?? 0);
    const completed = Number(counts.completed ?? counts.succeeded ?? 0);
    const failed = Number(counts.failed ?? counts.error ?? 0);
    if (!Number.isFinite(total) || total <= 0) {
        return "counts unavailable";
    }
    return `${completed}/${total} completed${failed > 0 ? ` · ${failed} failed` : ""}`;
}
export function buildBatchActionHint(batch, selection) {
    if (!batch) {
        return "Refresh this batch to load lifecycle posture and linked input/output files.";
    }
    const status = String(batch.status ?? "unknown");
    const outputFileId = String(batch.output_file_id ?? "");
    const handoffRequestId = selection?.handoffRequestId?.trim() ?? "";
    const handoffRequestCount = selection?.handoffRequestCount ?? 0;
    if (outputFileId) {
        if (handoffRequestId) {
            return handoffRequestCount > 1
                ? `Batch ${String(batch.id ?? "unknown")} is ${status}; output preview decoded ${handoffRequestCount} request ids, and scoped Traffic/Logs handoff is ready from sample request ${handoffRequestId}.`
                : `Batch ${String(batch.id ?? "unknown")} is ${status}; output preview decoded request ${handoffRequestId}, so scoped Traffic/Logs handoff is ready.`;
        }
        return `Batch ${String(batch.id ?? "unknown")} is ${status}; output preview is available from ${outputFileId}. Preview one output first to unlock request-scoped Traffic and Logs handoff.`;
    }
    if (isAttentionBatchStatus(status)) {
        return `Batch ${String(batch.id ?? "unknown")} needs operator follow-up. Inspect the input payload and refresh metadata for the latest error posture.`;
    }
    return `Batch ${String(batch.id ?? "unknown")} is ${status}. Preview the input payload now and refresh until output_file_id appears.`;
}
export function isAttentionBatchStatus(value) {
    const status = String(value ?? "").toLowerCase();
    return ["failed", "cancelled", "expired"].includes(status);
}
export function renderBatchStatus(value) {
    const normalized = value || "unknown";
    if (normalized === "completed") {
        return pill(normalized, "good");
    }
    if (isAttentionBatchStatus(normalized)) {
        return pill(normalized, "warn");
    }
    return pill(normalized);
}
export function humanizeBatchLifecycle(value) {
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
        filters.fileSort !== DEFAULT_FILE_SORT
            ? `sort=${describeFileSort(filters.fileSort)}`
            : "",
    ]
        .filter(Boolean)
        .join(" · ");
}
function compareFiles(left, right, sort) {
    const createdComparison = compareNumbers(Number(left.created_at ?? 0), Number(right.created_at ?? 0));
    const nameComparison = compareText(fileDisplayName(left), fileDisplayName(right));
    const sizeComparison = compareNumbers(Number(left.bytes ?? 0), Number(right.bytes ?? 0));
    switch (sort) {
        case "created_asc":
            return createdComparison || nameComparison;
        case "name_asc":
            return nameComparison || -createdComparison;
        case "name_desc":
            return -nameComparison || -createdComparison;
        case "size_desc":
            return -sizeComparison || -createdComparison || nameComparison;
        case "size_asc":
            return sizeComparison || -createdComparison || nameComparison;
        case "created_desc":
        default:
            return -createdComparison || nameComparison;
    }
}
function fileDisplayName(item) {
    return String(item.filename ?? item.id ?? "");
}
function compareNumbers(left, right) {
    return left - right;
}
function compareText(left, right) {
    return left.localeCompare(right, undefined, {
        numeric: true,
        sensitivity: "base",
    });
}
function describeFileSort(sort) {
    switch (sort) {
        case "created_asc":
            return "oldest";
        case "name_asc":
            return "name-a-z";
        case "name_desc":
            return "name-z-a";
        case "size_desc":
            return "largest";
        case "size_asc":
            return "smallest";
        case "created_desc":
        default:
            return "newest";
    }
}
function renderBatchHandoffActions(selection) {
    const requestId = selection.handoffRequestId?.trim() ?? "";
    if (!requestId) {
        return "";
    }
    const scopedLabel = (selection.handoffRequestCount ?? 0) > 1 ? "sample result" : "request";
    return `
    <div class="toolbar">
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForBatchResult(requestId))}">Open traffic for ${escapeHtml(scopedLabel)}</a>
      <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForBatchResult(requestId))}">Open logs for ${escapeHtml(scopedLabel)}</a>
    </div>
  `;
}
function buildTrafficUrlForBatchResult(requestId) {
    const params = new URLSearchParams();
    setQueryParamIfPresent(params, "request_id", requestId.trim());
    const query = params.toString();
    return query ? `/admin/traffic?${query}` : "/admin/traffic";
}
function buildLogsUrlForBatchResult(requestId) {
    const params = new URLSearchParams();
    setQueryParamIfPresent(params, "request_id", requestId.trim());
    const query = params.toString();
    return query ? `/admin/logs?${query}` : "/admin/logs";
}
