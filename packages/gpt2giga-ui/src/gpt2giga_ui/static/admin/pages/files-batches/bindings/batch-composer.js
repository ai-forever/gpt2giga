import { withBusyState } from "../../../forms.js";
import { formatTimestamp, safeJsonParse } from "../../../utils.js";
import { clearFilesBatchesPageDataCache, createBatch, validateBatchInput } from "../api.js";
import { extractErrorReason } from "../serializers.js";
import { INVALID_JSON } from "../state.js";
import { buildBatchInlineRequestsTemplate, buildBatchValidationMarkup, buildStoredFileValidationSnapshot, formatApiFormatLabel, OPENAI_BATCH_ENDPOINT_OPTIONS, readInlineRequestsPayload, } from "./helpers.js";
import { buildBatchValidationRequest, getBatchFormatHint, readBatchApiFormatValue, readConfiguredFallbackModel, resolveBatchEndpointValue, resolveComposerDisplayName, resolveDisplayedFileValidationSnapshot as resolveDisplayedFileValidationSnapshotState, } from "./batch-composer-state.js";
export function createBatchComposerBindings(deps) {
    const { app, elements, inventory, page, state, callbacks, cacheBatchRecord, cacheValidationSnapshotForFile, replaceStateForPage, runWorkflowAction, setWorkflowSummary, } = deps;
    const readBatchApiFormat = () => readBatchApiFormatValue(elements.batchApiFormat?.value);
    const readRuntimeFallbackModel = () => readConfiguredFallbackModel(app.runtime?.gigachat_model);
    const resolveBatchEndpoint = (apiFormat = readBatchApiFormat()) => resolveBatchEndpointValue({
        apiFormat,
        selectedEndpoint: elements.batchEndpoint?.value,
        batchModel: elements.batchModel?.value,
        fallbackModel: readRuntimeFallbackModel(),
    });
    const syncBatchEndpointControl = (apiFormat) => {
        if (!elements.batchEndpoint) {
            return;
        }
        if (apiFormat === "openai") {
            const selectedEndpoint = resolveBatchEndpoint("openai");
            elements.batchEndpoint.replaceChildren(...OPENAI_BATCH_ENDPOINT_OPTIONS.map((value) => new Option(value, value, value === selectedEndpoint, value === selectedEndpoint)));
            elements.batchEndpoint.disabled = false;
            elements.batchEndpoint.value = selectedEndpoint;
            return;
        }
        const providerEndpoint = resolveBatchEndpoint(apiFormat);
        elements.batchEndpoint.replaceChildren(new Option(providerEndpoint, providerEndpoint, true, true));
        elements.batchEndpoint.disabled = true;
    };
    const readBatchEndpoint = () => resolveBatchEndpoint();
    const readInlinePayload = () => readInlineRequestsPayload(elements.batchInlineRequests?.value ?? "");
    const buildCurrentBatchValidationRequest = () => buildBatchValidationRequest({
        apiFormat: readBatchApiFormat(),
        endpoint: readBatchEndpoint(),
        inputFileId: elements.batchInput?.value,
        fallbackModel: elements.batchModel?.value,
        inlinePayload: readInlinePayload(),
    });
    const resolveDisplayedFileValidationSnapshot = (fileId, source) => resolveDisplayedFileValidationSnapshotState({
        fileId,
        source,
        currentRequest: buildCurrentBatchValidationRequest(),
        state,
    });
    const updateBatchValidationSurface = () => {
        if (!elements.batchValidationNode) {
            return;
        }
        const currentRequest = buildCurrentBatchValidationRequest();
        elements.batchValidationNode.innerHTML = buildBatchValidationMarkup({
            state,
            selectedFormatLabel: formatApiFormatLabel(readBatchApiFormat()),
            detectedFormatLabel: state.validationReport?.detected_format
                ? formatApiFormatLabel(state.validationReport.detected_format)
                : "n/a",
            detectedFormatNote: state.validationReport?.detected_format
                ? "Detected from the current batch row shape."
                : "Detection appears after a successful validation run.",
            inputSourceLabel: currentRequest.sourceLabel,
            inputSourceNote: currentRequest.sourceNote,
            lastValidationLabel: state.validationValidatedAt
                ? formatTimestamp(state.validationValidatedAt)
                : "n/a",
            lastValidationNote: state.validationDirty
                ? "Composer inputs changed after the last report."
                : state.validationReport
                    ? "Report matches the current composer input."
                    : "No validation run for the current composer input yet.",
            endpointLabel: readBatchApiFormat() === "openai" ? readBatchEndpoint() : undefined,
        });
    };
    const updateBatchCreateAvailability = () => {
        if (!elements.batchCreateButton) {
            return;
        }
        const hasFreshBlockingErrors = state.validationReport !== null &&
            !state.validationDirty &&
            state.validationReport.summary.error_count > 0;
        elements.batchCreateButton.disabled =
            state.validationInFlight || hasFreshBlockingErrors;
        elements.batchCreateButton.title = state.validationInFlight
            ? "Validation is running."
            : hasFreshBlockingErrors
                ? "Fix validation errors or change the current composer input first."
                : "";
    };
    const clearValidationRefreshTimer = () => {
        if (state.validationRefreshTimer !== null) {
            window.clearTimeout(state.validationRefreshTimer);
            state.validationRefreshTimer = null;
        }
    };
    const invalidateBatchValidation = (options) => {
        const hadValidationState = state.validationReport !== null || state.validationValidatedAt !== null;
        state.validationDirty = hadValidationState;
        state.validationMessage = null;
        updateBatchValidationSurface();
        updateBatchCreateAvailability();
        callbacks.refreshSelectedFileValidationSurface();
        if (!options?.auto || !hadValidationState) {
            clearValidationRefreshTimer();
            return;
        }
        clearValidationRefreshTimer();
        state.validationRefreshTimer = window.setTimeout(() => {
            state.validationRefreshTimer = null;
            void runBatchValidation(null, { automatic: true });
        }, 250);
    };
    const runBatchValidation = async (button, options) => {
        const requestPayload = buildCurrentBatchValidationRequest();
        if (!requestPayload.signature || requestPayload.error) {
            state.validationMessage =
                requestPayload.error ??
                    "Validation needs a staged input file or inline requests.";
            updateBatchValidationSurface();
            updateBatchCreateAvailability();
            if (!options?.automatic) {
                app.pushAlert(state.validationMessage, "warn");
            }
            return;
        }
        state.validationMessage = null;
        state.validationInFlight = true;
        updateBatchValidationSurface();
        updateBatchCreateAvailability();
        const runId = ++state.validationRunId;
        try {
            const report = await withBusyState({
                root: elements.batchForm,
                button,
                pendingLabel: "Validating…",
                action: async () => validateBatchInput(app, {
                    apiFormat: requestPayload.apiFormat,
                    inputFileId: requestPayload.inputFileId,
                    model: requestPayload.model,
                    requests: requestPayload.requests,
                }),
            });
            if (runId !== state.validationRunId) {
                return;
            }
            state.validationReport = report;
            state.validationSignature = requestPayload.signature;
            state.validationValidatedAt = Math.floor(Date.now() / 1000);
            state.validationDirty = false;
            if (requestPayload.inputFileId && !requestPayload.requests?.length) {
                cacheValidationSnapshotForFile(requestPayload.inputFileId, buildStoredFileValidationSnapshot(report, state.validationValidatedAt));
            }
            callbacks.refreshSelectedFileValidationSurface();
            setWorkflowSummary([
                { label: "Workflow state", value: "Batch input validated" },
                { label: "API format", value: formatApiFormatLabel(report.api_format) },
                {
                    label: "Status",
                    value: report.valid ? "Ready to create" : "Needs fixes",
                    note: `${report.summary.error_count} errors · ${report.summary.warning_count} warnings`,
                },
                {
                    label: "Input source",
                    value: requestPayload.sourceLabel,
                    note: requestPayload.sourceNote,
                },
            ]);
            if (!options?.automatic) {
                app.pushAlert(report.valid
                    ? `Validation passed for ${formatApiFormatLabel(report.api_format)} batch input.`
                    : `Validation found ${report.summary.error_count} blocking issue${report.summary.error_count === 1 ? "" : "s"}.`, report.valid ? "info" : "warn");
            }
        }
        catch (error) {
            if (runId !== state.validationRunId) {
                return;
            }
            const message = error instanceof Error ? error.message : String(error);
            state.validationMessage = extractErrorReason(message);
            if (!options?.automatic) {
                app.pushAlert(state.validationMessage, "danger");
            }
        }
        finally {
            if (runId === state.validationRunId) {
                state.validationInFlight = false;
                updateBatchValidationSurface();
                updateBatchCreateAvailability();
            }
        }
    };
    const ensureFreshBatchValidation = async (button) => {
        const currentRequest = buildCurrentBatchValidationRequest();
        if (currentRequest.error) {
            state.validationMessage = currentRequest.error;
            updateBatchValidationSurface();
            updateBatchCreateAvailability();
            app.pushAlert(currentRequest.error, "warn");
            return false;
        }
        const hasFreshValidation = state.validationReport !== null &&
            !state.validationDirty &&
            state.validationSignature !== null &&
            state.validationSignature === currentRequest.signature;
        if (!hasFreshValidation) {
            await runBatchValidation(button, { automatic: false });
        }
        const latestRequest = buildCurrentBatchValidationRequest();
        const hasBlockingErrors = state.validationReport !== null &&
            !state.validationDirty &&
            state.validationSignature !== null &&
            state.validationSignature === latestRequest.signature &&
            state.validationReport.summary.error_count > 0;
        return !state.validationInFlight && !latestRequest.error && !hasBlockingErrors;
    };
    const syncBatchInlineRequestsTemplate = (options) => {
        if (!elements.batchInlineRequests) {
            return;
        }
        const nextTemplate = buildBatchInlineRequestsTemplate({
            apiFormat: readBatchApiFormat(),
            fallbackModel: elements.batchModel?.value.trim() || readRuntimeFallbackModel(),
            endpoint: readBatchEndpoint(),
        });
        elements.batchInlineRequests.placeholder = nextTemplate;
        const currentValue = elements.batchInlineRequests.value.trim();
        if (options?.forceValue ||
            (currentValue && currentValue === state.lastInlineRequestsTemplate)) {
            elements.batchInlineRequests.value = nextTemplate;
        }
        state.lastInlineRequestsTemplate = nextTemplate;
    };
    const syncBatchComposerFormat = (apiFormat, options) => {
        if (elements.batchApiFormat) {
            elements.batchApiFormat.value = apiFormat;
        }
        syncBatchEndpointControl(apiFormat);
        if (elements.batchInput) {
            elements.batchInput.required = false;
        }
        if (elements.batchInlineRequestsField && elements.batchInlineRequests) {
            elements.batchInlineRequestsField.hidden = false;
            syncBatchInlineRequestsTemplate({
                forceValue: options?.forceInlineTemplate,
            });
        }
        if (elements.batchModelField && elements.batchModel) {
            elements.batchModelField.hidden = false;
            elements.batchModel.required = false;
            if (!elements.batchModel.value.trim()) {
                elements.batchModel.value = readRuntimeFallbackModel();
            }
        }
        if (elements.batchDisplayNameField && elements.batchDisplayName) {
            const showDisplayName = apiFormat === "gemini";
            elements.batchDisplayNameField.hidden = !showDisplayName;
            if (!showDisplayName) {
                elements.batchDisplayName.value = "";
            }
            else {
                elements.batchDisplayName.value = resolveComposerDisplayName({
                    apiFormat,
                    currentValue: elements.batchDisplayName.value,
                    inputFileId: options?.inputFileId?.trim() ?? elements.batchInput?.value.trim() ?? "",
                });
            }
        }
        if (elements.batchHint) {
            elements.batchHint.textContent = getBatchFormatHint(apiFormat);
        }
        updateBatchValidationSurface();
        updateBatchCreateAvailability();
    };
    const bindBatchSubmit = () => {
        elements.batchForm?.addEventListener("submit", async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const fields = form.elements;
            const apiFormat = readBatchApiFormat();
            const metadataText = fields.metadata.value.trim();
            const metadata = metadataText
                ? safeJsonParse(metadataText, INVALID_JSON)
                : undefined;
            const inlinePayload = readInlinePayload();
            const inlineRequests = inlinePayload.requests;
            if (metadata === INVALID_JSON ||
                (metadata !== undefined &&
                    (metadata === null || Array.isArray(metadata) || typeof metadata !== "object"))) {
                app.pushAlert("Batch metadata must be a JSON object.", "danger");
                return;
            }
            if (inlinePayload.error) {
                state.validationMessage = inlinePayload.error;
                updateBatchValidationSurface();
                updateBatchCreateAvailability();
                app.pushAlert(inlinePayload.error, "danger");
                return;
            }
            const inputFileId = fields.input_file_id.value.trim();
            if (!inputFileId && !inlineRequests?.length) {
                app.pushAlert(`${formatApiFormatLabel(apiFormat)} batches need either a staged input file id or inline requests.`, "warn");
                return;
            }
            const submitter = event.submitter;
            const button = submitter instanceof HTMLButtonElement
                ? submitter
                : form.querySelector('button[type="submit"]');
            if (!(await ensureFreshBatchValidation(button))) {
                if (state.validationReport &&
                    !state.validationDirty &&
                    state.validationReport.summary.error_count > 0) {
                    app.pushAlert("Fix validation errors before creating the batch.", "warn");
                }
                return;
            }
            await runWorkflowAction({
                root: form,
                button,
                pendingLabel: "Creating…",
                pendingSummary: [
                    { label: "Workflow state", value: "Creating batch" },
                    { label: "API format", value: apiFormat },
                    {
                        label: "Input source",
                        value: inputFileId
                            ? `file ${inputFileId}`
                            : inlineRequests?.length
                                ? `${inlineRequests.length} inline request${inlineRequests.length === 1 ? "" : "s"}`
                                : "missing",
                    },
                    {
                        label: "Endpoint",
                        value: readBatchEndpoint(),
                    },
                ],
                successSummary: (response) => [
                    { label: "Workflow state", value: "Batch created" },
                    { label: "Batch id", value: String(response.id ?? "unknown") },
                    { label: "API format", value: String(response.api_format ?? apiFormat) },
                    {
                        label: "Next step",
                        value: "Inspect lifecycle",
                        note: "The page refreshes into the new batch selection so output polling starts from the focused batches inspector.",
                    },
                ],
                action: async () => {
                    const response = await createBatch(app, {
                        apiFormat,
                        endpoint: readBatchEndpoint(),
                        inputFileId,
                        metadata,
                        displayName: fields.display_name.value.trim() || undefined,
                        model: fields.model.value.trim() || undefined,
                        requests: inlineRequests,
                    });
                    cacheBatchRecord(response);
                    app.queueAlert(`Created ${String(response.api_format ?? apiFormat)} batch ${String(response.id ?? "")}.`, "info");
                    replaceStateForPage(page, {
                        composeInputFileId: inputFileId,
                        selectedBatchId: String(response.id ?? ""),
                    });
                    clearFilesBatchesPageDataCache();
                    await app.render(page);
                    return response;
                },
            });
        });
    };
    const bindBatchControls = () => {
        elements.batchValidateButton?.addEventListener("click", async () => {
            await runBatchValidation(elements.batchValidateButton, { automatic: false });
        });
        elements.batchApiFormat?.addEventListener("change", () => {
            syncBatchComposerFormat(readBatchApiFormat(), {
                inputFileId: elements.batchInput?.value.trim() ?? "",
            });
            invalidateBatchValidation({ auto: true });
        });
        elements.batchEndpoint?.addEventListener("change", () => {
            if (readBatchApiFormat() !== "openai") {
                invalidateBatchValidation({ auto: true });
                return;
            }
            syncBatchInlineRequestsTemplate();
            invalidateBatchValidation({ auto: true });
        });
        elements.batchModel?.addEventListener("input", () => {
            if (readBatchApiFormat() === "gemini") {
                syncBatchEndpointControl("gemini");
            }
            syncBatchInlineRequestsTemplate();
            invalidateBatchValidation();
        });
        elements.batchModel?.addEventListener("change", () => {
            if (readBatchApiFormat() === "gemini") {
                syncBatchEndpointControl("gemini");
            }
            invalidateBatchValidation({ auto: true });
        });
        elements.batchInput?.addEventListener("input", () => {
            invalidateBatchValidation();
        });
        elements.batchInput?.addEventListener("change", () => {
            invalidateBatchValidation({ auto: true });
        });
        elements.batchInlineRequestsExampleButton?.addEventListener("click", () => {
            syncBatchInlineRequestsTemplate({ forceValue: true });
            elements.batchInlineRequests?.focus();
            invalidateBatchValidation({ auto: true });
        });
        elements.batchInlineRequests?.addEventListener("input", () => {
            invalidateBatchValidation();
        });
        elements.batchInlineRequests?.addEventListener("change", () => {
            invalidateBatchValidation({ auto: true });
        });
    };
    return {
        initialize(routeState) {
            updateBatchValidationSurface();
            updateBatchCreateAvailability();
            bindBatchSubmit();
            bindBatchControls();
            if (routeState.composeInputFileId && elements.batchInput) {
                elements.batchInput.value = routeState.composeInputFileId;
                const source = inventory.fileLookup.get(routeState.composeInputFileId);
                const apiFormat = source?.api_format === "anthropic" || source?.api_format === "gemini"
                    ? source.api_format
                    : readBatchApiFormat();
                syncBatchComposerFormat(apiFormat, {
                    inputFileId: routeState.composeInputFileId,
                });
                invalidateBatchValidation();
                setWorkflowSummary([
                    { label: "Workflow state", value: "Batch composer primed" },
                    { label: "API format", value: apiFormat },
                    { label: "Input file", value: routeState.composeInputFileId },
                    {
                        label: "Next step",
                        value: "Review format settings and validate batch input",
                    },
                ]);
                return;
            }
            syncBatchComposerFormat(readBatchApiFormat());
        },
        readBatchApiFormat,
        syncBatchComposerFormat,
        invalidateBatchValidation,
        resolveDisplayedFileValidationSnapshot,
    };
}
