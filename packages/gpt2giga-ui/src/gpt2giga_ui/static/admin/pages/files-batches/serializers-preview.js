import { formatBytes, formatNumber, safeJsonParse } from "../../utils.js";
import { INVALID_JSON } from "./state.js";
const DEFAULT_PREVIEW_BYTE_LIMIT = 256 * 1024;
const DEFAULT_PREVIEW_TEXT_CHAR_LIMIT = 100_000;
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
