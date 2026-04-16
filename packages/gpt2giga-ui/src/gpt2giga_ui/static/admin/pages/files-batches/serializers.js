import { pill } from "../../templates.js";
import { escapeHtml, formatBytes, formatTimestamp, safeJsonParse, setQueryParamIfPresent, } from "../../utils.js";
import { INVALID_JSON } from "./state.js";
export function buildFilesBatchesInventory(data, filters) {
    const filteredFiles = data.files.filter((item) => matchesFile(item, filters));
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
export function buildIdleSelectionSummary(filteredFiles, totalFiles, filteredBatches, totalBatches, filters) {
    return [
        { label: "Selection", value: "No file or batch selected" },
        { label: "Files shown", value: `${filteredFiles}/${totalFiles}` },
        { label: "Batches shown", value: `${filteredBatches}/${totalBatches}` },
        { label: "Filters", value: summarizeFilters(filters) || "No active filters" },
    ];
}
export function buildIdleWorkflowSummary() {
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
export function renderInspectorActions(selection, fileLookup, batchLookup, batches) {
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
        ${escapeHtml(source
            ? `${String(source.filename ?? selection.fileId)} can feed a new batch immediately. Linked batch actions unlock as downstream jobs appear.`
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
                : `${preview.lineCount} line${preview.lineCount === 1 ? "" : "s"}`,
            note: preview.kind === "image"
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
    return {
        query: params.get("query") || "",
        purpose: params.get("purpose") || "",
        batchStatus: params.get("batch_status") || "",
        endpoint: params.get("endpoint") || "",
    };
}
export function readFilesBatchesRouteState() {
    const params = new URLSearchParams(window.location.search);
    return {
        selectedFileId: params.get("selected_file") || "",
        selectedBatchId: params.get("selected_batch") || "",
        composeInputFileId: params.get("compose_input") || "",
    };
}
export function buildFilesBatchesUrl(filters, routeState) {
    const params = new URLSearchParams();
    setQueryParamIfPresent(params, "query", filters.query);
    setQueryParamIfPresent(params, "purpose", filters.purpose);
    setQueryParamIfPresent(params, "batch_status", filters.batchStatus);
    setQueryParamIfPresent(params, "endpoint", filters.endpoint);
    setQueryParamIfPresent(params, "selected_file", routeState?.selectedFileId ?? "");
    setQueryParamIfPresent(params, "selected_batch", routeState?.selectedBatchId ?? "");
    setQueryParamIfPresent(params, "compose_input", routeState?.composeInputFileId ?? "");
    const query = params.toString();
    return query ? `/admin/files-batches?${query}` : "/admin/files-batches";
}
export function firstErrorLine(message) {
    return message.split("\n").map((line) => line.trim()).find(Boolean) ?? "Unknown error";
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
            : `${preview.lineCount} line${preview.lineCount === 1 ? "" : "s"}`,
    ]
        .filter(Boolean)
        .join(" · ");
}
export function buildFilePreview(bytes, filename) {
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
    ]
        .filter(Boolean)
        .join(" · ");
}
function analyzeContentText(text) {
    const lines = text ? text.split(/\r?\n/).length : 0;
    const nonEmptyLines = text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    const trimmed = text.trim();
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
function renderBinaryPreview(bytes) {
    return [
        "Binary file preview",
        `Size: ${formatBytes(bytes.length)}`,
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
