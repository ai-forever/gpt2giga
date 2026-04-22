import { withBusyState } from "../../../forms.js";
import { deleteFile, fetchBatchMetadata, fetchFileContent, fetchFileMetadata, } from "../api.js";
import { buildBatchActionHint, buildContentPreviewSummary, buildFilePreview, describeFileValidationSnapshot, getLatestLinkedBatch, getLatestOutputBatch, getLinkedBatchesForFile, humanizeBatchLifecycle, inferDownloadMimeType, summarizeBatchRequestCounts, summarizePreviewOutcome, renderInspectorActions, } from "../serializers.js";
import { BATCH_PREVIEW_BYTES, setDefinitionBlock, } from "./helpers.js";
export function createInventoryBindings(deps) {
    const { app, data, elements, inventory, page, state, batchComposer, cacheFileRecord, cacheBatchRecord, removeFileRecord, setSummary, setWorkflowSummary, setDetailSurface, setContentSurface, resetContentSurface, clearMediaPreview, replaceStateForPage, navigateToPage, syncSelectionRouteState, runWorkflowAction, } = deps;
    const updateInspectorActions = () => {
        elements.actionNode.innerHTML = renderInspectorActions(page, state.selection, inventory.fileLookup, inventory.batchLookup, data.batches);
    };
    const clearSelectionHandoff = () => {
        delete state.selection.handoffRequestId;
        delete state.selection.handoffRequestCount;
    };
    const findBatchByOutputFileId = (fileId) => data.batches.find((entry) => String(entry.output_file_id ?? "") === fileId) ?? null;
    const resolveContentPathForFile = (fileId, source, relatedBatch) => {
        const batchOutputPath = (relatedBatch && String(relatedBatch.output_file_id ?? "") === fileId
            ? relatedBatch.output_path
            : null) || findBatchByOutputFileId(fileId)?.output_path;
        return batchOutputPath?.trim() || source?.content_path?.trim() || undefined;
    };
    const resolveDownloadPathForFile = (fileId, source) => findBatchByOutputFileId(fileId)?.output_path?.trim() ||
        source?.download_path?.trim() ||
        source?.content_path?.trim() ||
        undefined;
    const applyFileSelectionSurfaces = (fileId, source, mode, detailPayload) => {
        const linkedBatches = getLinkedBatchesForFile(fileId, data.batches);
        const readyOutputs = linkedBatches.filter((batch) => Boolean(String(batch.output_file_id ?? ""))).length;
        const validationSnapshot = batchComposer.resolveDisplayedFileValidationSnapshot(fileId, source);
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
            setSummary([
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
            ]);
            setDetailSurface("Composer handoff", [
                { label: "Detail surface", value: "Composer handoff" },
                { label: "Selected input", value: fileId },
                { label: "Endpoint target", value: "Choose an endpoint in the batch form" },
                ...validationItem,
                ...lastValidationItem,
            ], detailPayload, false);
            return;
        }
        setSummary([
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
        ]);
        setDetailSurface("Selection metadata snapshot", [
            { label: "Detail surface", value: "File metadata" },
            { label: "Linked batches", value: String(linkedBatches.length) },
            { label: "Stored bytes", value: String(source?.bytes ?? "n/a") },
            { label: "Status", value: String(source?.status ?? "processed") },
            ...validationItem,
            ...lastValidationItem,
        ], detailPayload, true);
    };
    const refreshSelectedFileValidationSurface = () => {
        if (state.selection.kind !== "file" || !state.selection.fileId) {
            return;
        }
        const source = inventory.fileLookup.get(state.selection.fileId);
        const mode = elements.batchInput?.value.trim() === state.selection.fileId
            ? "composer"
            : "inspect";
        applyFileSelectionSurfaces(state.selection.fileId, source, mode, mode === "composer"
            ? `Selected ${state.selection.fileId} as batch input.`
            : JSON.stringify(source ?? { id: state.selection.fileId }, null, 2));
    };
    const focusBatchComposer = (fileId) => {
        if (!elements.batchInput) {
            navigateToPage("batches", { composeInputFileId: fileId });
            return;
        }
        const source = inventory.fileLookup.get(fileId);
        const preferredApiFormat = source?.api_format === "anthropic" || source?.api_format === "gemini"
            ? source.api_format
            : "openai";
        elements.batchInput.value = fileId;
        batchComposer.syncBatchComposerFormat(preferredApiFormat, { inputFileId: fileId });
        batchComposer.invalidateBatchValidation();
        state.selection = { kind: "file", fileId };
        clearSelectionHandoff();
        resetContentSurface();
        syncSelectionRouteState();
        applyFileSelectionSurfaces(fileId, source, "composer", `Selected ${fileId} as batch input.`);
        setWorkflowSummary([
            { label: "Workflow state", value: "Batch input primed" },
            { label: "Input file", value: fileId },
            {
                label: "Next step",
                value: "Create batch",
                note: "The batch form is prefilled so you can queue a new job immediately.",
            },
        ]);
        updateInspectorActions();
        elements.batchInput.focus();
    };
    const previewFileContent = async (fileId, button, options) => {
        const source = inventory.fileLookup.get(fileId);
        const label = options?.label ?? "File content preview";
        setContentSurface(label, [
            { label: "Preview surface", value: label },
            { label: "File id", value: fileId },
            {
                label: "Loaded content",
                value: "Loading…",
                note: options?.support ?? String(source?.filename ?? fileId),
            },
        ], "Loading file content…", true);
        clearMediaPreview();
        await runWorkflowAction({
            root: elements.actionNode,
            button,
            pendingLabel: "Loading…",
            pendingSummary: [
                { label: "Workflow state", value: "Loading preview" },
                { label: "Preview target", value: fileId },
                {
                    label: "Surface",
                    value: label,
                    note: options?.support ?? String(source?.filename ?? fileId),
                },
            ],
            successSummary: (preview) => [
                { label: "Workflow state", value: "Preview ready" },
                { label: "Preview target", value: fileId },
                {
                    label: "Surface",
                    value: label,
                    note: summarizePreviewOutcome(preview),
                },
                ...(preview.handoffRequestId
                    ? [
                        {
                            label: "Downstream handoff",
                            value: (preview.handoffRequestCount ?? 0) > 1
                                ? "Sample request scoped"
                                : "Request scoped",
                            note: (preview.handoffRequestCount ?? 0) > 1
                                ? `Traffic and Logs can open with sample request ${preview.handoffRequestId} from ${preview.handoffRequestCount} decoded result rows.`
                                : `Traffic and Logs can open directly with request ${preview.handoffRequestId}.`,
                        },
                    ]
                    : []),
            ],
            action: async () => {
                const previewBytes = resolvePreviewBytes(source, options);
                const { bytes, totalBytes } = await fetchFileContent(app, fileId, resolveContentPathForFile(fileId, source, options?.relatedBatch), previewBytes);
                const preview = buildFilePreview(bytes, String(source?.filename ?? fileId), {
                    previewByteLimit: BATCH_PREVIEW_BYTES,
                    previewTextCharLimit: 100_000,
                    totalByteLength: totalBytes ?? undefined,
                });
                if (preview.handoffRequestId && options?.relatedBatch) {
                    state.selection = {
                        kind: "batch",
                        batchId: String(options.relatedBatch.id ?? state.selection.batchId ?? ""),
                        inputFileId: String(options.relatedBatch.input_file_id ?? state.selection.inputFileId ?? "") || undefined,
                        outputFileId: fileId,
                        handoffRequestId: preview.handoffRequestId,
                        handoffRequestCount: preview.handoffRequestCount,
                    };
                    updateInspectorActions();
                }
                else if (state.selection.kind === "batch") {
                    clearSelectionHandoff();
                    updateInspectorActions();
                }
                setContentSurface(label, buildContentPreviewSummary(preview, fileId, label, {
                    support: options?.support ?? String(source?.filename ?? fileId),
                    file: source,
                    relatedBatch: options?.relatedBatch ?? null,
                }), preview.textFallback, true);
                if (preview.kind === "image") {
                    clearMediaPreview();
                    const blobBytes = new Uint8Array(bytes.byteLength);
                    blobBytes.set(bytes);
                    const blob = new Blob([blobBytes], { type: preview.mimeType });
                    state.previewObjectUrl = URL.createObjectURL(blob);
                    const figure = document.createElement("figure");
                    figure.className = "surface";
                    const image = document.createElement("img");
                    image.alt = String(preview.filename ?? fileId);
                    image.src = state.previewObjectUrl;
                    image.style.display = "block";
                    image.style.maxWidth = "100%";
                    image.style.height = "auto";
                    image.style.borderRadius = "12px";
                    figure.append(image);
                    elements.mediaNode.replaceChildren(figure);
                }
                else {
                    clearMediaPreview();
                }
                return preview;
            },
        });
    };
    const downloadFileContent = async (fileId, filename, button) => {
        await runWorkflowAction({
            root: button?.parentElement ?? elements.actionNode,
            button,
            pendingLabel: "Downloading…",
            pendingSummary: [
                { label: "Workflow state", value: "Downloading output" },
                { label: "File id", value: fileId },
                { label: "Filename", value: filename },
            ],
            successSummary: () => [
                { label: "Workflow state", value: "Output downloaded" },
                { label: "File id", value: fileId },
                { label: "Filename", value: filename },
            ],
            action: async () => {
                const source = inventory.fileLookup.get(fileId);
                const { bytes, mimeType } = await fetchFileContent(app, fileId, resolveDownloadPathForFile(fileId, source));
                const blobBytes = new Uint8Array(bytes.byteLength);
                blobBytes.set(bytes);
                const objectUrl = URL.createObjectURL(new Blob([blobBytes], {
                    type: inferDownloadMimeType(filename, mimeType, bytes),
                }));
                const link = document.createElement("a");
                link.href = objectUrl;
                link.download = filename;
                document.body.append(link);
                link.click();
                link.remove();
                setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
            },
        });
    };
    const resolveDownloadFilename = (fileId) => {
        const source = inventory.fileLookup.get(fileId);
        const filename = String(source?.filename ?? "").trim();
        return filename || `file-${fileId}.bin`;
    };
    const resolvePreviewBytes = (source, options) => {
        if (options?.relatedBatch) {
            return BATCH_PREVIEW_BYTES;
        }
        const filename = String(source?.filename ?? "").trim().toLowerCase();
        if (filename.endsWith(".jsonl") ||
            filename.endsWith(".json") ||
            filename.endsWith(".txt") ||
            filename.endsWith(".log")) {
            return BATCH_PREVIEW_BYTES;
        }
        return undefined;
    };
    const inspectFile = async (fileId, button) => {
        const shouldRefreshPage = button !== null;
        await runWorkflowAction({
            root: elements.actionNode,
            button,
            pendingLabel: "Loading…",
            pendingSummary: [
                { label: "Workflow state", value: "Loading file metadata" },
                { label: "Selected file", value: fileId },
                { label: "Next step", value: "Populate inspector" },
            ],
            successSummary: (payload) => {
                const source = cacheFileRecord(payload);
                const linkedBatches = getLinkedBatchesForFile(fileId, data.batches);
                const latestBatch = linkedBatches[0];
                return [
                    { label: "Workflow state", value: "File selected" },
                    { label: "Selected file", value: fileId },
                    {
                        label: "Batch context",
                        value: `${linkedBatches.length} linked batch${linkedBatches.length === 1 ? "" : "es"}`,
                        note: latestBatch
                            ? `Latest: ${String(latestBatch.id ?? "unknown")} (${String(latestBatch.status ?? "unknown")})`
                            : "No linked batch records yet.",
                    },
                    {
                        label: "Next step",
                        value: linkedBatches.length
                            ? "Inspect linked batch or preview content"
                            : "Preview content or use for batch",
                        note: linkedBatches.some((batch) => Boolean(String(batch.output_file_id ?? "")))
                            ? "Preview the latest linked output to unlock request-scoped Traffic and Logs handoff."
                            : String(source.filename ?? fileId),
                    },
                ];
            },
            action: async () => {
                const payload = await fetchFileMetadata(app, fileId);
                const source = cacheFileRecord(payload);
                state.selection = { kind: "file", fileId };
                clearSelectionHandoff();
                resetContentSurface();
                syncSelectionRouteState();
                applyFileSelectionSurfaces(fileId, source, "inspect", JSON.stringify(payload, null, 2));
                updateInspectorActions();
                return payload;
            },
        });
        if (shouldRefreshPage) {
            await app.render(page);
        }
    };
    const inspectBatch = async (batchId, button) => {
        const shouldRefreshPage = button !== null;
        await runWorkflowAction({
            root: elements.actionNode,
            button,
            pendingLabel: "Loading…",
            pendingSummary: [
                { label: "Workflow state", value: "Loading batch metadata" },
                { label: "Selected batch", value: batchId },
                { label: "Next step", value: "Populate lifecycle inspector" },
            ],
            successSummary: (payload) => {
                const source = cacheBatchRecord(payload);
                return [
                    { label: "Workflow state", value: "Batch selected" },
                    { label: "Selected batch", value: batchId },
                    {
                        label: "Lifecycle",
                        value: humanizeBatchLifecycle(source.status),
                        note: summarizeBatchRequestCounts(source.request_counts),
                    },
                    {
                        label: "Next step",
                        value: state.selection.outputFileId
                            ? "Preview output or inspect input"
                            : "Preview input and refresh status",
                        note: state.selection.outputFileId
                            ? "Preview one output to unlock request-scoped Traffic and Logs handoff."
                            : buildBatchActionHint(source),
                    },
                ];
            },
            action: async () => {
                const payload = await fetchBatchMetadata(app, batchId);
                const source = cacheBatchRecord(payload);
                const inputFileId = String(source.input_file_id ?? "");
                const outputFileId = String(source.output_file_id ?? "");
                state.selection = {
                    kind: "batch",
                    batchId,
                    inputFileId: inputFileId || undefined,
                    outputFileId: outputFileId || undefined,
                };
                clearSelectionHandoff();
                resetContentSurface();
                syncSelectionRouteState();
                setSummary([
                    { label: "Selection", value: "Batch" },
                    { label: "Batch id", value: batchId },
                    { label: "Status", value: String(source.status ?? "unknown") },
                    { label: "Endpoint", value: String(source.endpoint ?? "n/a") },
                    {
                        label: "Output file",
                        value: outputFileId || "n/a",
                        note: inputFileId || "no input file",
                    },
                ]);
                setDetailSurface("Selection metadata snapshot", [
                    { label: "Detail surface", value: "Batch metadata" },
                    { label: "Lifecycle posture", value: humanizeBatchLifecycle(source.status) },
                    { label: "Input file", value: inputFileId || "missing" },
                    { label: "Output file", value: outputFileId || "not ready" },
                    { label: "Requests", value: summarizeBatchRequestCounts(source.request_counts) },
                ], JSON.stringify(payload, null, 2), true);
                updateInspectorActions();
                return payload;
            },
        });
        if (shouldRefreshPage) {
            await app.render(page);
        }
    };
    const bindInspectorActions = () => {
        elements.actionNode.addEventListener("click", async (event) => {
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            const button = target.closest("[data-inspector-action]");
            if (!button) {
                return;
            }
            const action = button.dataset.inspectorAction;
            if (!action) {
                return;
            }
            if (action === "inspect-file" && state.selection.fileId) {
                await inspectFile(state.selection.fileId, button);
                return;
            }
            if (action === "use-file" && state.selection.fileId) {
                focusBatchComposer(state.selection.fileId);
                return;
            }
            if (action === "preview-file" && state.selection.fileId) {
                await previewFileContent(state.selection.fileId, button);
                return;
            }
            if (action === "download-file" && state.selection.fileId) {
                await downloadFileContent(state.selection.fileId, resolveDownloadFilename(state.selection.fileId), button);
                return;
            }
            if (action === "inspect-batch" && state.selection.batchId) {
                await inspectBatch(state.selection.batchId, button);
                return;
            }
            if (action === "batch-input" && state.selection.inputFileId) {
                await inspectFile(state.selection.inputFileId, button);
                return;
            }
            if (action === "preview-batch-input" &&
                state.selection.inputFileId &&
                state.selection.batchId) {
                await previewFileContent(state.selection.inputFileId, button, {
                    label: "Batch input preview",
                    support: `Batch ${state.selection.batchId}`,
                    relatedBatch: inventory.batchLookup.get(state.selection.batchId) ?? null,
                });
                return;
            }
            if (action === "use-batch-input" && state.selection.inputFileId) {
                focusBatchComposer(state.selection.inputFileId);
                return;
            }
            if (action === "batch-output" &&
                state.selection.outputFileId &&
                state.selection.batchId) {
                await previewFileContent(state.selection.outputFileId, button, {
                    label: "Batch output preview",
                    support: `Batch ${state.selection.batchId}`,
                    relatedBatch: inventory.batchLookup.get(state.selection.batchId) ?? null,
                });
                return;
            }
            if (action === "inspect-output-file" && state.selection.outputFileId) {
                await inspectFile(state.selection.outputFileId, button);
                return;
            }
            if (action === "inspect-linked-batch" && state.selection.fileId) {
                const latestBatch = getLatestLinkedBatch(state.selection.fileId, data.batches);
                if (latestBatch) {
                    await inspectBatch(String(latestBatch.id ?? ""), button);
                }
                return;
            }
            if (action === "preview-linked-output" && state.selection.fileId) {
                const latestOutputBatch = getLatestOutputBatch(state.selection.fileId, data.batches);
                const outputFileId = String(latestOutputBatch?.output_file_id ?? "");
                if (!outputFileId) {
                    return;
                }
                state.selection = {
                    kind: "batch",
                    batchId: String(latestOutputBatch?.id ?? ""),
                    inputFileId: String(latestOutputBatch?.input_file_id ?? "") || undefined,
                    outputFileId,
                };
                clearSelectionHandoff();
                syncSelectionRouteState();
                setSummary([
                    { label: "Selection", value: "Linked batch output" },
                    { label: "Output file", value: outputFileId },
                    { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
                    { label: "Endpoint", value: String(latestOutputBatch?.endpoint ?? "n/a") },
                ]);
                setDetailSurface("Selection metadata snapshot", [
                    { label: "Detail surface", value: "Latest linked output" },
                    { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
                    { label: "Output file", value: outputFileId },
                    {
                        label: "Requests",
                        value: summarizeBatchRequestCounts(latestOutputBatch?.request_counts),
                    },
                ], JSON.stringify({
                    latest_linked_batch: latestOutputBatch,
                    output_file_id: outputFileId,
                }, null, 2), true);
                updateInspectorActions();
                await previewFileContent(outputFileId, button, {
                    label: "Latest linked output",
                    support: `Batch ${String(latestOutputBatch?.id ?? "unknown")}`,
                    relatedBatch: latestOutputBatch ?? null,
                });
            }
        });
    };
    const bindPageInventoryActions = () => {
        app.pageContent.querySelectorAll("[data-file-view]").forEach((item) => {
            item.addEventListener("click", async () => {
                await inspectFile(item.dataset.fileView ?? "", item instanceof HTMLButtonElement ? item : null);
            });
        });
        app.pageContent.querySelectorAll("[data-file-use]").forEach((item) => {
            item.addEventListener("click", () => {
                const fileId = item.dataset.fileUse;
                if (!fileId) {
                    return;
                }
                focusBatchComposer(fileId);
            });
        });
        app.pageContent
            .querySelectorAll("[data-file-content]")
            .forEach((item) => {
            item.addEventListener("click", async () => {
                const fileId = item.dataset.fileContent;
                if (!fileId) {
                    return;
                }
                state.selection = { kind: "file", fileId };
                clearSelectionHandoff();
                syncSelectionRouteState();
                updateInspectorActions();
                await previewFileContent(fileId, item instanceof HTMLButtonElement ? item : null);
            });
        });
        app.pageContent
            .querySelectorAll("[data-file-download]")
            .forEach((item) => {
            item.addEventListener("click", async () => {
                const fileId = item.dataset.fileDownload;
                if (!fileId) {
                    return;
                }
                const filename = item.dataset.fileDownloadName?.trim() || resolveDownloadFilename(fileId);
                await downloadFileContent(fileId, filename, item instanceof HTMLButtonElement ? item : null);
            });
        });
        app.pageContent.querySelectorAll("[data-file-delete]").forEach((item) => {
            item.addEventListener("click", async () => {
                const fileId = item.dataset.fileDelete;
                if (!fileId) {
                    return;
                }
                if (!window.confirm(`Delete file ${fileId}?`)) {
                    return;
                }
                await withBusyState({
                    root: item.parentElement,
                    button: item instanceof HTMLButtonElement ? item : null,
                    pendingLabel: "Deleting…",
                    action: async () => {
                        const source = inventory.fileLookup.get(fileId);
                        if (!source?.delete_path) {
                            app.pushAlert(`Delete is unavailable for ${fileId} in the current API format.`, "warn");
                            return;
                        }
                        setWorkflowSummary([
                            { label: "Workflow state", value: "Deleting file" },
                            { label: "File id", value: fileId },
                            { label: "Next step", value: "Rebuild page from cached inventory" },
                        ]);
                        await deleteFile(app, fileId, source.delete_path);
                        removeFileRecord(fileId);
                        app.queueAlert(`Deleted file ${fileId}.`, "info");
                        replaceStateForPage(page, undefined);
                        await app.render(page);
                    },
                });
            });
        });
        app.pageContent.querySelectorAll("[data-batch-view]").forEach((item) => {
            item.addEventListener("click", async () => {
                await inspectBatch(item.dataset.batchView ?? "", item instanceof HTMLButtonElement ? item : null);
            });
        });
        app.pageContent
            .querySelectorAll("[data-batch-output]")
            .forEach((item) => {
            item.addEventListener("click", async () => {
                const fileId = item.dataset.batchOutput;
                if (!fileId) {
                    return;
                }
                const batch = data.batches.find((entry) => String(entry.output_file_id ?? "") === fileId);
                state.selection = {
                    kind: "batch",
                    batchId: String(batch?.id ?? ""),
                    inputFileId: String(batch?.input_file_id ?? "") || undefined,
                    outputFileId: fileId,
                };
                clearSelectionHandoff();
                syncSelectionRouteState();
                setSummary([
                    { label: "Selection", value: "Batch output" },
                    { label: "Output file", value: fileId },
                    { label: "Batch id", value: String(batch?.id ?? "unknown") },
                    { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
                ]);
                setDetailSurface("Selection metadata snapshot", [
                    { label: "Detail surface", value: "Batch output handoff" },
                    { label: "Batch id", value: String(batch?.id ?? "unknown") },
                    { label: "Output file", value: fileId },
                ], JSON.stringify({
                    batch_output_handoff: batch ?? null,
                    output_file_id: fileId,
                }, null, 2), true);
                updateInspectorActions();
                await previewFileContent(fileId, item instanceof HTMLButtonElement ? item : null, {
                    label: "Batch output preview",
                    support: `Batch ${String(batch?.id ?? "unknown")}`,
                    relatedBatch: batch ?? null,
                });
            });
        });
        app.pageContent
            .querySelectorAll("[data-batch-download]")
            .forEach((item) => {
            item.addEventListener("click", async () => {
                const fileId = item.dataset.batchDownload;
                if (!fileId) {
                    return;
                }
                const filename = item.dataset.batchDownloadName?.trim() ||
                    `batch-output-${fileId}.jsonl`;
                await downloadFileContent(fileId, filename, item instanceof HTMLButtonElement ? item : null);
            });
        });
        app.pageContent.querySelectorAll("[data-batch-input]").forEach((item) => {
            item.addEventListener("click", async () => {
                const batchId = item.dataset.batchInput;
                const batch = inventory.batchLookup.get(batchId ?? "");
                const inputFileId = String(batch?.input_file_id ?? "");
                if (!inputFileId) {
                    return;
                }
                await inspectFile(inputFileId, item instanceof HTMLButtonElement ? item : null);
            });
        });
        app.pageContent
            .querySelectorAll("[data-batch-input-preview]")
            .forEach((item) => {
            item.addEventListener("click", async () => {
                const batchId = item.dataset.batchInputPreview;
                const batch = inventory.batchLookup.get(batchId ?? "");
                const inputFileId = String(batch?.input_file_id ?? "");
                if (!inputFileId) {
                    return;
                }
                state.selection = {
                    kind: "batch",
                    batchId: String(batch?.id ?? ""),
                    inputFileId: inputFileId || undefined,
                    outputFileId: String(batch?.output_file_id ?? "") || undefined,
                };
                clearSelectionHandoff();
                syncSelectionRouteState();
                updateInspectorActions();
                await previewFileContent(inputFileId, item instanceof HTMLButtonElement ? item : null, {
                    label: "Batch input preview",
                    support: `Batch ${String(batch?.id ?? "unknown")}`,
                    relatedBatch: batch ?? null,
                });
            });
        });
    };
    return {
        initialize(routeState) {
            updateInspectorActions();
            setDetailSurface("Selection metadata snapshot", [
                { label: "Detail surface", value: "Idle" },
                { label: "Loaded object", value: "No file or batch metadata loaded" },
            ], "No selection yet.", false);
            bindInspectorActions();
            bindPageInventoryActions();
            if (routeState.selectedBatchId && inventory.batchLookup.has(routeState.selectedBatchId)) {
                void inspectBatch(routeState.selectedBatchId, null);
                return;
            }
            if (routeState.selectedFileId && inventory.fileLookup.has(routeState.selectedFileId)) {
                void inspectFile(routeState.selectedFileId, null);
            }
        },
        refreshSelectedFileValidationSurface,
    };
}
