import { describeFileValidationSnapshot, getLinkedBatchesForFile, humanizeBatchLifecycle, summarizeBatchRequestCounts, } from "../serializers.js";
export function findBatchByOutputFileId(fileId, batches) {
    return (batches.find((entry) => String(entry.output_file_id ?? "") === fileId) ?? null);
}
export function resolveContentPathForFile(options) {
    const { fileId, source, relatedBatch, batches } = options;
    const batchOutputPath = (relatedBatch && String(relatedBatch.output_file_id ?? "") === fileId
        ? relatedBatch.output_path
        : null) || findBatchByOutputFileId(fileId, batches)?.output_path;
    return batchOutputPath?.trim() || source?.content_path?.trim() || undefined;
}
export function resolveDownloadPathForFile(options) {
    const { fileId, source, batches } = options;
    return (findBatchByOutputFileId(fileId, batches)?.output_path?.trim() ||
        source?.download_path?.trim() ||
        source?.content_path?.trim() ||
        undefined);
}
export function resolveDownloadFilename(fileId, source) {
    const filename = String(source?.filename ?? "").trim();
    return filename || `file-${fileId}.bin`;
}
export function resolvePreviewBytes(options) {
    const { source, relatedBatch, previewByteLimit } = options;
    if (relatedBatch) {
        return previewByteLimit;
    }
    const filename = String(source?.filename ?? "").trim().toLowerCase();
    if (filename.endsWith(".jsonl") ||
        filename.endsWith(".json") ||
        filename.endsWith(".txt") ||
        filename.endsWith(".log")) {
        return previewByteLimit;
    }
    return undefined;
}
export function buildFileSelectionSurface(options) {
    const { fileId, source, mode, detailPayload, batches, validationSnapshot } = options;
    const linkedBatches = getLinkedBatchesForFile(fileId, batches);
    const readyOutputs = linkedBatches.filter((batch) => Boolean(String(batch.output_file_id ?? ""))).length;
    const validationSummary = validationSnapshot
        ? describeFileValidationSnapshot(validationSnapshot)
        : null;
    const validationItem = validationSummary
        ? [
            {
                label: "Validation",
                value: validationSummary.label,
                note: validationSummary.note,
            },
        ]
        : [];
    const lastValidationItem = validationSnapshot?.validated_at != null
        ? [
            {
                label: "Last validation",
                value: String(validationSnapshot.validated_at),
                note: validationSnapshot.status === "stale"
                    ? "The stored report no longer matches the current composer input."
                    : "Most recent staged-file validation snapshot.",
            },
        ]
        : [];
    if (mode === "composer") {
        return {
            summary: [
                { label: "Selection", value: "Batch input ready" },
                { label: "File id", value: fileId },
                { label: "Purpose", value: String(source?.purpose ?? "batch") },
                { label: "Filename", value: String(source?.filename ?? fileId) },
                { label: "API format", value: String(source?.api_format ?? "openai") },
                ...validationItem,
                {
                    label: "Next step",
                    value: "Create batch",
                    note: "The input field has been populated for the batch form.",
                },
            ],
            detailTitle: "Composer handoff",
            detailItems: [
                { label: "Detail surface", value: "Composer handoff" },
                { label: "Selected input", value: fileId },
                { label: "Endpoint target", value: "Choose an endpoint in the batch form" },
                ...validationItem,
                ...lastValidationItem,
            ],
            detailPayload,
            detailOpen: false,
        };
    }
    return {
        summary: [
            { label: "Selection", value: "File" },
            { label: "File id", value: fileId },
            { label: "Purpose", value: String(source?.purpose ?? "user_data") },
            { label: "Filename", value: String(source?.filename ?? fileId) },
            {
                label: "Created",
                value: String(source?.created_at ?? "n/a"),
                note: String(source?.bytes ?? "n/a"),
            },
            ...validationItem,
            {
                label: "Batch linkage",
                value: `${linkedBatches.length} linked batch${linkedBatches.length === 1 ? "" : "es"}`,
                note: readyOutputs
                    ? `${readyOutputs} output file${readyOutputs === 1 ? "" : "s"} ready`
                    : "No completed output linked yet.",
            },
        ],
        detailTitle: "Selection metadata snapshot",
        detailItems: [
            { label: "Detail surface", value: "File metadata" },
            { label: "Linked batches", value: String(linkedBatches.length) },
            { label: "Stored bytes", value: String(source?.bytes ?? "n/a") },
            { label: "Status", value: String(source?.status ?? "processed") },
            ...validationItem,
            ...lastValidationItem,
        ],
        detailPayload,
        detailOpen: true,
    };
}
export function buildBatchSelectionSurface(options) {
    const { batchId, source, detailPayload } = options;
    const inputFileId = String(source.input_file_id ?? "");
    const outputFileId = String(source.output_file_id ?? "");
    return {
        summary: [
            { label: "Selection", value: "Batch" },
            { label: "Batch id", value: batchId },
            { label: "Status", value: String(source.status ?? "unknown") },
            { label: "Endpoint", value: String(source.endpoint ?? "n/a") },
            {
                label: "Output file",
                value: outputFileId || "n/a",
                note: inputFileId || "no input file",
            },
        ],
        detailTitle: "Selection metadata snapshot",
        detailItems: [
            { label: "Detail surface", value: "Batch metadata" },
            { label: "Lifecycle posture", value: humanizeBatchLifecycle(source.status) },
            { label: "Input file", value: inputFileId || "missing" },
            { label: "Output file", value: outputFileId || "not ready" },
            { label: "Requests", value: summarizeBatchRequestCounts(source.request_counts) },
        ],
        detailPayload,
        detailOpen: true,
    };
}
export function buildBatchOutputSelectionSurface(options) {
    const { outputFileId, batch, variant } = options;
    const batchId = String(batch?.id ?? "unknown");
    if (variant === "latest-linked-output") {
        return {
            summary: [
                { label: "Selection", value: "Linked batch output" },
                { label: "Output file", value: outputFileId },
                { label: "Batch id", value: batchId },
                { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
            ],
            detailTitle: "Selection metadata snapshot",
            detailItems: [
                { label: "Detail surface", value: "Latest linked output" },
                { label: "Batch id", value: batchId },
                { label: "Output file", value: outputFileId },
                {
                    label: "Requests",
                    value: summarizeBatchRequestCounts(batch?.request_counts),
                },
            ],
            detailPayload: JSON.stringify({
                latest_linked_batch: batch ?? null,
                output_file_id: outputFileId,
            }, null, 2),
            detailOpen: true,
        };
    }
    return {
        summary: [
            { label: "Selection", value: "Batch output" },
            { label: "Output file", value: outputFileId },
            { label: "Batch id", value: batchId },
            { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
        ],
        detailTitle: "Selection metadata snapshot",
        detailItems: [
            { label: "Detail surface", value: "Batch output handoff" },
            { label: "Batch id", value: batchId },
            { label: "Output file", value: outputFileId },
        ],
        detailPayload: JSON.stringify({
            batch_output_handoff: batch ?? null,
            output_file_id: outputFileId,
        }, null, 2),
        detailOpen: true,
    };
}
