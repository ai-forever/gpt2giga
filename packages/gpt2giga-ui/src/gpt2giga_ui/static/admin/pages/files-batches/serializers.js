import { pill } from "../../templates.js";
import { escapeHtml, formatBytes, formatNumber, formatTimestamp, safeJsonParse, setQueryParamIfPresent, } from "../../utils.js";
import { DEFAULT_FILE_SORT, INVALID_JSON } from "./state.js";
const DEFAULT_PREVIEW_BYTE_LIMIT = 256 * 1024;
const DEFAULT_PREVIEW_TEXT_CHAR_LIMIT = 100_000;
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
export function buildContentPreviewSummary(preview, fileId, label, options) {
    const summary = [
        { label: "Preview surface", value: label, note: options?.support },
        { label: "File id", value: fileId },
        { label: "Format", value: preview.formatLabel, note: preview.formatNote },
        {
            label: preview.kind === "image" ? "Binary size" : "Payload size",
            value: preview.kind === "image"
                ? formatBytes(preview.byteLength)
                : preview.sampled
                    ? `${preview.lineCount} sampled line${preview.lineCount === 1 ? "" : "s"}`
                    : `${preview.lineCount} line${preview.lineCount === 1 ? "" : "s"}`,
            note: preview.kind === "image"
                ? preview.dimensionsNote ?? "Rendered as image preview."
                : preview.sampled
                    ? `Preview limited to first ${formatBytes(preview.sampledByteLength ?? preview.byteLength)} of ${formatBytes(preview.byteLength)}.`
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
    if (preview.handoffRequestId) {
        summary.push({
            label: "Downstream handoff",
            value: (preview.handoffRequestCount ?? 0) > 1
                ? "Sample request scoped"
                : "Request scoped",
            note: (preview.handoffRequestCount ?? 0) > 1
                ? `Traffic and Logs can open with sample request ${preview.handoffRequestId} from ${preview.handoffRequestCount} decoded result rows.`
                : `Traffic and Logs can open directly with request ${preview.handoffRequestId}.`,
        });
    }
    return summary;
}
export function readFilesBatchesFilters() {
    const params = new URLSearchParams(window.location.search);
    return scopeFilesBatchesFilters("files-batches", {
        query: params.get("query") || "",
        purpose: params.get("purpose") || "",
        batchStatus: params.get("batch_status") || "",
        endpoint: params.get("endpoint") || "",
        fileSort: parseFileSort(params.get("file_sort")),
    });
}
export function readFilesBatchesFiltersForPage(page) {
    const params = new URLSearchParams(window.location.search);
    return scopeFilesBatchesFilters(page, {
        query: params.get("query") || "",
        purpose: params.get("purpose") || "",
        batchStatus: params.get("batch_status") || "",
        endpoint: params.get("endpoint") || "",
        fileSort: parseFileSort(params.get("file_sort")),
    });
}
export function readFilesBatchesRouteState(page = "files-batches") {
    const params = new URLSearchParams(window.location.search);
    return scopeFilesBatchesRouteState(page, {
        selectedFileId: params.get("selected_file") || "",
        selectedBatchId: params.get("selected_batch") || "",
        composeInputFileId: params.get("compose_input") || "",
    });
}
export function buildFilesBatchesUrl(filters, routeState, page = "files-batches") {
    const scopedFilters = scopeFilesBatchesFilters(isFilesBatchesPage(page) ? page : "files-batches", filters);
    const scopedRouteState = scopeFilesBatchesRouteState(isFilesBatchesPage(page) ? page : "files-batches", routeState);
    const params = new URLSearchParams();
    setQueryParamIfPresent(params, "query", scopedFilters.query);
    setQueryParamIfPresent(params, "purpose", scopedFilters.purpose);
    setQueryParamIfPresent(params, "batch_status", scopedFilters.batchStatus);
    setQueryParamIfPresent(params, "endpoint", scopedFilters.endpoint);
    setQueryParamIfPresent(params, "file_sort", scopedFilters.fileSort === DEFAULT_FILE_SORT ? "" : scopedFilters.fileSort);
    setQueryParamIfPresent(params, "selected_file", scopedRouteState.selectedFileId);
    setQueryParamIfPresent(params, "selected_batch", scopedRouteState.selectedBatchId);
    setQueryParamIfPresent(params, "compose_input", scopedRouteState.composeInputFileId);
    const query = params.toString();
    const pathname = page === "overview" ? "/admin" : `/admin/${page}`;
    return query ? `${pathname}?${query}` : pathname;
}
export function scopeFilesBatchesFilters(page, filters) {
    return {
        query: filters.query,
        purpose: page === "batches" ? "" : filters.purpose,
        batchStatus: page === "files" ? "" : filters.batchStatus,
        endpoint: page === "files" ? "" : filters.endpoint,
        fileSort: page === "batches" ? DEFAULT_FILE_SORT : parseFileSort(filters.fileSort),
    };
}
export function scopeFilesBatchesRouteState(page, routeState) {
    return {
        selectedFileId: page === "batches" ? "" : routeState?.selectedFileId?.trim() ?? "",
        selectedBatchId: page === "files" ? "" : routeState?.selectedBatchId?.trim() ?? "",
        composeInputFileId: page === "files-batches" || page === "batches"
            ? routeState?.composeInputFileId?.trim() ?? ""
            : "",
    };
}
export function extractErrorReason(message) {
    const lines = String(message)
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
    if (!lines.length) {
        return "Unknown error";
    }
    const payloadText = lines.length > 1 ? lines.slice(1).join("\n") : lines[0];
    const payload = safeJsonParse(payloadText, null);
    const summary = summarizeErrorPayload(payload);
    if (summary) {
        return summary;
    }
    if (lines.length > 1) {
        return lines.slice(1).join(" ");
    }
    return lines[0];
}
function summarizeErrorPayload(payload) {
    if (typeof payload === "string") {
        return payload.trim();
    }
    if (typeof payload === "number" ||
        typeof payload === "boolean" ||
        typeof payload === "bigint") {
        return String(payload);
    }
    if (Array.isArray(payload)) {
        return payload
            .map((item) => summarizeErrorPayload(item))
            .filter(Boolean)
            .join("; ");
    }
    if (!payload || typeof payload !== "object") {
        return "";
    }
    const record = payload;
    const directMessage = typeof record.message === "string" ? record.message.trim() : "";
    if (directMessage) {
        return directMessage;
    }
    const validationMessage = summarizeValidationError(record);
    if (validationMessage) {
        return validationMessage;
    }
    for (const preferredKey of ["detail", "error"]) {
        const nestedSummary = summarizeErrorPayload(record[preferredKey]);
        if (nestedSummary) {
            return nestedSummary;
        }
    }
    const fieldSummaries = Object.entries(record)
        .filter(([key]) => key !== "url")
        .map(([key, value]) => {
        const entrySummary = summarizeErrorPayload(value);
        if (!entrySummary) {
            return "";
        }
        return `${key}: ${entrySummary}`;
    })
        .filter(Boolean);
    return fieldSummaries.join("; ");
}
function summarizeValidationError(record) {
    const message = typeof record.msg === "string" ? record.msg.trim() : "";
    if (!message) {
        return "";
    }
    const location = Array.isArray(record.loc)
        ? record.loc
            .map((part) => String(part ?? "").trim())
            .filter(Boolean)
            .join(".")
        : "";
    return location ? `${location}: ${message}` : message;
}
export function summarizePreviewOutcome(preview) {
    return [
        preview.formatLabel,
        preview.contentKind,
        preview.handoffRequestId
            ? (preview.handoffRequestCount ?? 0) > 1
                ? `sample request ${preview.handoffRequestId}`
                : `request ${preview.handoffRequestId}`
            : "",
        preview.kind === "image"
            ? formatBytes(preview.byteLength)
            : preview.sampled
                ? `${preview.lineCount} sampled line${preview.lineCount === 1 ? "" : "s"}`
                : `${preview.lineCount} line${preview.lineCount === 1 ? "" : "s"}`,
    ]
        .filter(Boolean)
        .join(" · ");
}
export function buildFilePreview(bytes, filename, options) {
    const totalByteLength = Math.max(bytes.length, Number(options?.totalByteLength ?? bytes.length));
    const previewByteLimit = Math.max(1, Number(options?.previewByteLimit ?? DEFAULT_PREVIEW_BYTE_LIMIT));
    const previewTextCharLimit = Math.max(1, Number(options?.previewTextCharLimit ?? DEFAULT_PREVIEW_TEXT_CHAR_LIMIT));
    const sampledBytes = bytes.length > previewByteLimit ? bytes.slice(0, previewByteLimit) : bytes;
    const sampled = sampledBytes.length < totalByteLength;
    const imageMimeType = detectImageMimeType(bytes, filename);
    if (imageMimeType) {
        return {
            kind: "image",
            filename,
            mimeType: imageMimeType,
            textFallback: `Binary image preview loaded for ${filename}.\nMIME type: ${imageMimeType}\nSize: ${formatBytes(totalByteLength)}`,
            byteLength: totalByteLength,
            lineCount: 0,
            sampled,
            sampledByteLength: sampledBytes.length,
            formatLabel: "image",
            formatNote: imageMimeType,
            contentKind: "Image asset",
            contentKindNote: "Rendered inline so the operator can inspect the payload without opening raw bytes.",
            sampleLabel: "Filename",
            sampleValue: filename,
            dimensionsNote: "Image preview available inline.",
        };
    }
    const decoded = decodeBytesAsText(sampledBytes);
    if (decoded.isText) {
        const analysis = analyzeContentText(decoded.text, {
            sampled,
            sampledByteLength: sampledBytes.length,
            textCharLimit: previewTextCharLimit,
            totalByteLength,
        });
        return {
            kind: "text",
            filename,
            mimeType: inferTextMimeType(filename, decoded.text),
            ...analysis,
        };
    }
    return {
        kind: "binary",
        filename,
        mimeType: inferDownloadMimeType(filename, null, bytes),
        textFallback: renderBinaryPreview(sampledBytes, {
            sampled,
            totalByteLength,
        }),
        byteLength: totalByteLength,
        lineCount: 1,
        sampled,
        sampledByteLength: sampledBytes.length,
        formatLabel: "binary",
        formatNote: sampled ? "Non-text payload · sampled preview" : "Non-text payload",
        contentKind: "Binary asset",
        contentKindNote: "Rendered as a short byte preview instead of lossy text decoding.",
        sampleLabel: "Magic bytes",
        sampleValue: renderHexPrefix(sampledBytes),
        sampleNote: filename,
    };
}
export function inferDownloadMimeType(filename, responseMimeType, bytes) {
    const normalizedResponseMimeType = responseMimeType?.trim().toLowerCase() ?? "";
    if (normalizedResponseMimeType &&
        normalizedResponseMimeType !== "application/octet-stream" &&
        normalizedResponseMimeType !== "application/binary") {
        return normalizedResponseMimeType;
    }
    const imageMimeType = bytes ? detectImageMimeType(bytes, filename) : null;
    if (imageMimeType) {
        return imageMimeType;
    }
    const lowerFilename = filename.toLowerCase();
    if (lowerFilename.endsWith(".jsonl")) {
        return "application/jsonl";
    }
    if (lowerFilename.endsWith(".json")) {
        return "application/json";
    }
    if (lowerFilename.endsWith(".svg")) {
        return "image/svg+xml";
    }
    if (lowerFilename.endsWith(".txt") ||
        lowerFilename.endsWith(".log") ||
        lowerFilename.endsWith(".md")) {
        return "text/plain";
    }
    return normalizedResponseMimeType || "application/octet-stream";
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
export function isBatchValidationCandidate(file) {
    if (!file) {
        return false;
    }
    const purpose = String(file.purpose ?? "").toLowerCase();
    const contentKind = String(file.content_kind ?? "").toLowerCase();
    if (purpose === "batch_output" || contentKind === "batch_output") {
        return false;
    }
    return purpose === "batch" || contentKind === "jsonl";
}
export function describeFileValidationSnapshot(snapshot) {
    if (!snapshot || snapshot.status === "not_validated") {
        return {
            label: "Not validated",
            tone: "default",
            note: "Run Validate file from the batch composer to get row-level diagnostics.",
        };
    }
    const errorCount = Number(snapshot.error_count ?? 0);
    const warningCount = Number(snapshot.warning_count ?? 0);
    const totalRows = Number(snapshot.total_rows ?? 0);
    const counts = `${totalRows} rows · ${errorCount} errors · ${warningCount} warnings`;
    const detectedFormat = snapshot.detected_format
        ? `Detected ${snapshot.detected_format}.`
        : "Format detection is unavailable.";
    if (snapshot.status === "valid") {
        return {
            label: "Valid",
            tone: "good",
            note: `${counts}. ${detectedFormat}`,
        };
    }
    if (snapshot.status === "valid_with_warnings") {
        return {
            label: "Valid with warnings",
            tone: "warn",
            note: `${counts}. ${detectedFormat}`,
        };
    }
    if (snapshot.status === "invalid") {
        return {
            label: "Invalid",
            tone: "warn",
            note: `${counts}. Fix blocking issues before creating the batch.`,
        };
    }
    return {
        label: "Stale report",
        tone: "warn",
        note: `${counts}. Re-run validation after changing the current composer input.`,
    };
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
function isFilesBatchesPage(value) {
    return value === "files-batches" || value === "files" || value === "batches";
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
function parseFileSort(value) {
    switch (value) {
        case "created_asc":
        case "name_asc":
        case "name_desc":
        case "size_desc":
        case "size_asc":
            return value;
        case "created_desc":
        default:
            return DEFAULT_FILE_SORT;
    }
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
function analyzeContentText(text, options) {
    const textCharLimit = Math.max(1, Number(options?.textCharLimit ?? DEFAULT_PREVIEW_TEXT_CHAR_LIMIT));
    const sampled = Boolean(options?.sampled);
    const sampledByteLength = Number(options?.sampledByteLength ?? text.length);
    const totalByteLength = Math.max(sampledByteLength, Number(options?.totalByteLength ?? sampledByteLength));
    const truncatedText = text.length > textCharLimit ? text.slice(0, textCharLimit) : text;
    const textWasTrimmed = truncatedText.length < text.length;
    const sampledPreview = sampled || textWasTrimmed;
    const lines = truncatedText ? truncatedText.split(/\r?\n/).length : 0;
    const nonEmptyLines = truncatedText
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    const trimmed = truncatedText.trim();
    const json = trimmed ? safeJsonParse(trimmed, INVALID_JSON) : INVALID_JSON;
    let formatLabel = "text";
    let formatNote = lines <= 1 ? "single payload" : "plain text or JSON fragments";
    let contentKind;
    let contentKindNote;
    let sampleLabel;
    let sampleValue;
    let sampleNote;
    let handoffRequestId;
    let handoffRequestCount;
    if (json !== INVALID_JSON) {
        if (Array.isArray(json)) {
            const records = json;
            formatLabel = "json array";
            formatNote = `${records.length} top-level item${records.length === 1 ? "" : "s"}`;
        }
        else if (json && typeof json === "object") {
            const objectValue = json;
            const fieldCount = Object.keys(objectValue).length;
            formatLabel = "json object";
            formatNote = `${fieldCount} top-level field${fieldCount === 1 ? "" : "s"}`;
            sampleLabel = "Top-level keys";
            sampleValue = Object.keys(objectValue).slice(0, 3).join(", ") || "none";
            if ("data" in objectValue && Array.isArray(objectValue.data)) {
                contentKind = "List payload";
                contentKindNote = `${objectValue.data.length} entries`;
            }
        }
        else {
            formatLabel = "json scalar";
        }
    }
    else if (nonEmptyLines.length > 0 &&
        nonEmptyLines.every((line) => safeJsonParse(line, INVALID_JSON) !== INVALID_JSON)) {
        const parsedLines = nonEmptyLines
            .map((line) => safeJsonParse(line, INVALID_JSON))
            .filter((row) => row !== INVALID_JSON);
        formatLabel = "jsonl";
        formatNote = `${nonEmptyLines.length} record${nonEmptyLines.length === 1 ? "" : "s"}`;
        const inputRows = parsedLines.filter((row) => isBatchInputRow(row));
        const outputRows = parsedLines.filter((row) => isBatchOutputRow(row));
        if (inputRows.length === parsedLines.length) {
            const sampleRow = inputRows[0] ?? {};
            contentKind = "Batch input";
            contentKindNote = `${inputRows.length} queued request${inputRows.length === 1 ? "" : "s"}`;
            sampleLabel = "Sample request";
            sampleValue = String(sampleRow.custom_id ?? sampleRow.id ?? "batch-request");
            sampleNote = `${String(sampleRow.method ?? "POST")} ${String(sampleRow.url ?? "/v1/chat/completions")}`;
        }
        else if (outputRows.length === parsedLines.length) {
            const errorCount = outputRows.filter((row) => Boolean(row.error)).length;
            const successCount = outputRows.length - errorCount;
            const sampleRow = outputRows[0] ?? {};
            const requestIds = Array.from(new Set(outputRows
                .map((row) => extractBatchOutputRequestId(row))
                .filter((value) => value.length > 0)));
            contentKind = "Batch output";
            contentKindNote = `${successCount} success · ${errorCount} error`;
            sampleLabel = "Sample result";
            sampleValue = String(sampleRow.custom_id ?? sampleRow.id ?? "batch-result");
            sampleNote = requestIds.length
                ? errorCount
                    ? `Contains at least one failed row. Sample request id: ${requestIds[0]}.`
                    : `Rows decode cleanly into transformed results. Sample request id: ${requestIds[0]}.`
                : errorCount
                    ? "Contains at least one failed row."
                    : "Rows decode cleanly into transformed results.";
            handoffRequestId = requestIds[0];
            handoffRequestCount = requestIds.length;
        }
    }
    if (sampledPreview) {
        formatNote = `${formatNote} · sampled preview`;
    }
    const textFallback = sampledPreview
        ? `${truncatedText}\n\n[preview truncated to first ${formatBytes(sampledByteLength)}${textWasTrimmed ? ` / ${formatNumber(textCharLimit)} chars shown` : ""}]`
        : truncatedText;
    return {
        textFallback,
        formatLabel,
        formatNote,
        lineCount: lines,
        byteLength: totalByteLength,
        sampled: sampledPreview,
        sampledByteLength,
        contentKind,
        contentKindNote,
        sampleLabel,
        sampleValue,
        sampleNote,
        handoffRequestId,
        handoffRequestCount,
    };
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
function extractBatchOutputRequestId(row) {
    const response = row.response;
    if (response && typeof response === "object" && !Array.isArray(response)) {
        const nestedRequestId = String(response.request_id ?? "").trim();
        if (nestedRequestId) {
            return nestedRequestId;
        }
    }
    return String(row.request_id ?? row.id ?? row.custom_id ?? "").trim();
}
function detectImageMimeType(bytes, filename) {
    if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
        return "image/jpeg";
    }
    if (bytes.length >= 8 &&
        bytes[0] === 0x89 &&
        bytes[1] === 0x50 &&
        bytes[2] === 0x4e &&
        bytes[3] === 0x47 &&
        bytes[4] === 0x0d &&
        bytes[5] === 0x0a &&
        bytes[6] === 0x1a &&
        bytes[7] === 0x0a) {
        return "image/png";
    }
    if (bytes.length >= 12 &&
        bytes[0] === 0x52 &&
        bytes[1] === 0x49 &&
        bytes[2] === 0x46 &&
        bytes[3] === 0x46 &&
        bytes[8] === 0x57 &&
        bytes[9] === 0x45 &&
        bytes[10] === 0x42 &&
        bytes[11] === 0x50) {
        return "image/webp";
    }
    if (bytes.length >= 6) {
        const header = String.fromCharCode(...bytes.slice(0, 6));
        if (header === "GIF87a" || header === "GIF89a") {
            return "image/gif";
        }
    }
    if (filename.toLowerCase().endsWith(".svg")) {
        return "image/svg+xml";
    }
    return null;
}
function decodeBytesAsText(bytes) {
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
function inferTextMimeType(filename, text) {
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
function renderBinaryPreview(bytes, options) {
    return [
        options?.sampled ? "Binary file preview (sampled)" : "Binary file preview",
        `Size: ${formatBytes(options?.totalByteLength ?? bytes.length)}`,
        options?.sampled ? `Preview sample: ${formatBytes(bytes.length)}` : "",
        `Magic bytes: ${renderHexPrefix(bytes)}`,
        "Raw text preview is suppressed to avoid mojibake.",
    ].join("\n");
}
function renderHexPrefix(bytes, limit = 16) {
    return Array.from(bytes.slice(0, limit))
        .map((value) => value.toString(16).padStart(2, "0"))
        .join(" ");
}
function isBatchInputRow(value) {
    return Boolean(value &&
        typeof value === "object" &&
        ("body" in value ||
            "request" in value));
}
function isBatchOutputRow(value) {
    return Boolean(value &&
        typeof value === "object" &&
        ("response" in value ||
            "error" in value ||
            "custom_id" in value));
}
