import type { AdminApp } from "../../../app.js";
import { withBusyState } from "../../../forms.js";
import { formatTimestamp, safeJsonParse } from "../../../utils.js";
import type { FilesBatchesPageData } from "../api.js";
import { clearFilesBatchesPageDataCache, createBatch, validateBatchInput } from "../api.js";
import {
  extractErrorReason,
  isBatchValidationCandidate,
} from "../serializers.js";
import type {
  ArtifactApiFormat,
  BatchRecord,
  DefinitionItem,
  FileRecord,
  FileValidationSnapshot,
  FilesBatchesInventory,
  FilesBatchesPage,
  FilesBatchesRouteState,
} from "../state.js";
import { INVALID_JSON } from "../state.js";
import type { FilesBatchesPageElements } from "../view.js";
import {
  ANTHROPIC_BATCH_ENDPOINT,
  buildBatchInlineRequestsTemplate,
  buildBatchValidationMarkup,
  buildStoredFileValidationSnapshot,
  formatApiFormatLabel,
  GEMINI_BATCH_ENDPOINT_TEMPLATE,
  normalizeGeminiBatchModel,
  OPENAI_BATCH_ENDPOINT_OPTIONS,
  readInlineRequestsPayload,
  type FilesBatchesBindingState,
  type WorkflowActionRunner,
} from "./helpers.js";

interface RefreshCallbacks {
  refreshSelectedFileValidationSurface: () => void;
}

interface BatchComposerBindingsDeps {
  app: AdminApp;
  data: FilesBatchesPageData;
  elements: FilesBatchesPageElements;
  inventory: FilesBatchesInventory;
  page: FilesBatchesPage;
  state: FilesBatchesBindingState;
  callbacks: RefreshCallbacks;
  cacheBatchRecord: (payload: BatchRecord) => BatchRecord;
  cacheValidationSnapshotForFile: (
    fileId: string,
    snapshot: FileValidationSnapshot | null,
  ) => void;
  replaceStateForPage: (
    targetPage: FilesBatchesPage,
    routeState?: {
      selectedFileId?: string;
      selectedBatchId?: string;
      composeInputFileId?: string;
    },
  ) => void;
  runWorkflowAction: WorkflowActionRunner;
  setWorkflowSummary: (items: DefinitionItem[]) => void;
}

export interface BatchComposerBindings {
  initialize(routeState: FilesBatchesRouteState): void;
  readBatchApiFormat(): ArtifactApiFormat;
  syncBatchComposerFormat(
    apiFormat: ArtifactApiFormat,
    options?: {
      inputFileId?: string;
      forceInlineTemplate?: boolean;
    },
  ): void;
  invalidateBatchValidation(options?: { auto?: boolean }): void;
  resolveDisplayedFileValidationSnapshot(
    fileId: string,
    source?: FileRecord,
  ): FileValidationSnapshot | null;
}

export function createBatchComposerBindings(
  deps: BatchComposerBindingsDeps,
): BatchComposerBindings {
  const {
    app,
    elements,
    inventory,
    page,
    state,
    callbacks,
    cacheBatchRecord,
    cacheValidationSnapshotForFile,
    replaceStateForPage,
    runWorkflowAction,
    setWorkflowSummary,
  } = deps;

  const readBatchApiFormat = (): ArtifactApiFormat => {
    const normalized = elements.batchApiFormat?.value.trim();
    if (normalized === "anthropic" || normalized === "gemini") {
      return normalized;
    }
    return "openai";
  };

  const readConfiguredFallbackModel = (): string =>
    app.runtime?.gigachat_model?.trim() || "gemini-2.5-flash";

  const resolveGeminiBatchEndpoint = (): string => {
    const normalizedModel = normalizeGeminiBatchModel(
      elements.batchModel?.value.trim() || readConfiguredFallbackModel(),
    );
    return GEMINI_BATCH_ENDPOINT_TEMPLATE.replace(
      "{model}",
      normalizedModel || "{model}",
    );
  };

  const resolveBatchEndpoint = (
    apiFormat: ArtifactApiFormat = readBatchApiFormat(),
  ): string => {
    if (apiFormat === "anthropic") {
      return ANTHROPIC_BATCH_ENDPOINT;
    }
    if (apiFormat === "gemini") {
      return resolveGeminiBatchEndpoint();
    }
    const selectedEndpoint = elements.batchEndpoint?.value.trim() ?? "";
    return OPENAI_BATCH_ENDPOINT_OPTIONS.includes(
      selectedEndpoint as (typeof OPENAI_BATCH_ENDPOINT_OPTIONS)[number],
    )
      ? selectedEndpoint
      : "/v1/chat/completions";
  };

  const syncBatchEndpointControl = (apiFormat: ArtifactApiFormat): void => {
    if (!elements.batchEndpoint) {
      return;
    }

    if (apiFormat === "openai") {
      const selectedEndpoint = resolveBatchEndpoint("openai");
      elements.batchEndpoint.replaceChildren(
        ...OPENAI_BATCH_ENDPOINT_OPTIONS.map(
          (value) =>
            new Option(
              value,
              value,
              value === selectedEndpoint,
              value === selectedEndpoint,
            ),
        ),
      );
      elements.batchEndpoint.disabled = false;
      elements.batchEndpoint.value = selectedEndpoint;
      return;
    }

    const providerEndpoint = resolveBatchEndpoint(apiFormat);
    elements.batchEndpoint.replaceChildren(
      new Option(providerEndpoint, providerEndpoint, true, true),
    );
    elements.batchEndpoint.disabled = true;
  };

  const readBatchEndpoint = (): string => resolveBatchEndpoint();

  const getBatchFormatHint = (apiFormat: ArtifactApiFormat): string => {
    if (apiFormat === "anthropic") {
      return "Anthropic batches accept either a staged JSONL file shaped like `{custom_id, params}` per line or an inline JSON array shaped like `[{custom_id, params}]`. Provide a fallback model when rows omit `params.model`.";
    }
    if (apiFormat === "gemini") {
      return "Gemini batches accept either a staged JSONL file shaped like `{key, request}` per line or an inline JSON array shaped like `[{key?, request, metadata?}]`. Provide a fallback model when file rows omit `request.model`.";
    }
    return "OpenAI batches accept either a staged JSONL file in OpenAI batch input format or an inline JSON array shaped like `[{custom_id, method, url, body}]`. Provide a fallback model when rows omit `body.model`.";
  };

  const readInlinePayload = (): {
    provided: boolean;
    requests?: Array<Record<string, unknown>>;
    error?: string;
  } => readInlineRequestsPayload(elements.batchInlineRequests?.value ?? "");

  const buildBatchValidationRequest = (): {
    apiFormat: ArtifactApiFormat;
    endpoint: string;
    inputFileId?: string;
    model?: string;
    requests?: Array<Record<string, unknown>>;
    signature?: string;
    sourceLabel: string;
    sourceNote?: string;
    error?: string;
  } => {
    const apiFormat = readBatchApiFormat();
    const endpoint = readBatchEndpoint();
    const inputFileId = elements.batchInput?.value.trim() ?? "";
    const fallbackModel = elements.batchModel?.value.trim() || undefined;
    const inlinePayload = readInlinePayload();
    if (inlinePayload.error) {
      return {
        apiFormat,
        endpoint,
        sourceLabel: "Inline requests",
        error: inlinePayload.error,
      };
    }

    const inlineRequests = inlinePayload.requests;
    if (inlineRequests && inlineRequests.length > 0) {
      return {
        apiFormat,
        endpoint,
        model: fallbackModel,
        requests: inlineRequests,
        signature: JSON.stringify({
          apiFormat,
          endpoint,
          model: fallbackModel ?? "",
          requests: inlineRequests,
        }),
        sourceLabel: `${inlineRequests.length} inline request${inlineRequests.length === 1 ? "" : "s"}`,
        sourceNote: inputFileId
          ? `Inline requests override staged file ${inputFileId} for validation and batch creation.`
          : "Inline requests are the active batch source.",
      };
    }

    if (inputFileId) {
      return {
        apiFormat,
        endpoint,
        inputFileId,
        model: fallbackModel,
        signature: JSON.stringify({
          apiFormat,
          endpoint,
          inputFileId,
          model: fallbackModel ?? "",
        }),
        sourceLabel: `Staged file ${inputFileId}`,
        sourceNote: "Validation reads the staged JSONL file through the admin API.",
      };
    }

    return {
      apiFormat,
      endpoint,
      sourceLabel: "No active input",
      error: `${formatApiFormatLabel(apiFormat)} batches need a staged input file id or inline requests before validation.`,
    };
  };

  const resolveDisplayedFileValidationSnapshot = (
    fileId: string,
    source?: FileRecord,
  ): FileValidationSnapshot | null => {
    if (!isBatchValidationCandidate(source)) {
      return source?.validation ?? null;
    }

    const currentRequest = buildBatchValidationRequest();
    const activeInputFileId =
      currentRequest.requests && currentRequest.requests.length > 0
        ? undefined
        : currentRequest.inputFileId;
    const storedSnapshot = source?.validation ?? null;

    if (activeInputFileId !== fileId) {
      return storedSnapshot ?? { status: "not_validated" };
    }

    if (
      state.validationReport &&
      !state.validationDirty &&
      state.validationSignature !== null &&
      state.validationSignature === currentRequest.signature
    ) {
      return buildStoredFileValidationSnapshot(
        state.validationReport,
        state.validationValidatedAt,
      );
    }

    if (state.validationDirty) {
      if (storedSnapshot) {
        return { ...storedSnapshot, status: "stale" };
      }
      if (state.validationReport) {
        return {
          ...buildStoredFileValidationSnapshot(
            state.validationReport,
            state.validationValidatedAt,
          ),
          status: "stale",
        };
      }
    }

    return storedSnapshot ?? { status: "not_validated" };
  };

  const updateBatchValidationSurface = (): void => {
    if (!elements.batchValidationNode) {
      return;
    }

    const currentRequest = buildBatchValidationRequest();
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
      endpointLabel:
        readBatchApiFormat() === "openai" ? readBatchEndpoint() : undefined,
    });
  };

  const updateBatchCreateAvailability = (): void => {
    if (!elements.batchCreateButton) {
      return;
    }
    const hasFreshBlockingErrors =
      state.validationReport !== null &&
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

  const clearValidationRefreshTimer = (): void => {
    if (state.validationRefreshTimer !== null) {
      window.clearTimeout(state.validationRefreshTimer);
      state.validationRefreshTimer = null;
    }
  };

  const invalidateBatchValidation = (options?: { auto?: boolean }): void => {
    const hadValidationState =
      state.validationReport !== null || state.validationValidatedAt !== null;
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

  const runBatchValidation = async (
    button: HTMLButtonElement | null,
    options?: { automatic?: boolean },
  ): Promise<void> => {
    const requestPayload = buildBatchValidationRequest();
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
        action: async () =>
          validateBatchInput(app, {
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
        cacheValidationSnapshotForFile(
          requestPayload.inputFileId,
          buildStoredFileValidationSnapshot(report, state.validationValidatedAt),
        );
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
        app.pushAlert(
          report.valid
            ? `Validation passed for ${formatApiFormatLabel(report.api_format)} batch input.`
            : `Validation found ${report.summary.error_count} blocking issue${report.summary.error_count === 1 ? "" : "s"}.`,
          report.valid ? "info" : "warn",
        );
      }
    } catch (error) {
      if (runId !== state.validationRunId) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      state.validationMessage = extractErrorReason(message);
      if (!options?.automatic) {
        app.pushAlert(state.validationMessage, "danger");
      }
    } finally {
      if (runId === state.validationRunId) {
        state.validationInFlight = false;
        updateBatchValidationSurface();
        updateBatchCreateAvailability();
      }
    }
  };

  const ensureFreshBatchValidation = async (
    button: HTMLButtonElement | null,
  ): Promise<boolean> => {
    const currentRequest = buildBatchValidationRequest();
    if (currentRequest.error) {
      state.validationMessage = currentRequest.error;
      updateBatchValidationSurface();
      updateBatchCreateAvailability();
      app.pushAlert(currentRequest.error, "warn");
      return false;
    }

    const hasFreshValidation =
      state.validationReport !== null &&
      !state.validationDirty &&
      state.validationSignature !== null &&
      state.validationSignature === currentRequest.signature;
    if (!hasFreshValidation) {
      await runBatchValidation(button, { automatic: false });
    }

    const latestRequest = buildBatchValidationRequest();
    const hasBlockingErrors =
      state.validationReport !== null &&
      !state.validationDirty &&
      state.validationSignature !== null &&
      state.validationSignature === latestRequest.signature &&
      state.validationReport.summary.error_count > 0;
    return !state.validationInFlight && !latestRequest.error && !hasBlockingErrors;
  };

  const syncBatchInlineRequestsTemplate = (options?: {
    forceValue?: boolean;
  }): void => {
    if (!elements.batchInlineRequests) {
      return;
    }
    const nextTemplate = buildBatchInlineRequestsTemplate({
      apiFormat: readBatchApiFormat(),
      fallbackModel:
        elements.batchModel?.value.trim() || readConfiguredFallbackModel(),
      endpoint: readBatchEndpoint(),
    });
    elements.batchInlineRequests.placeholder = nextTemplate;
    const currentValue = elements.batchInlineRequests.value.trim();
    if (
      options?.forceValue ||
      (currentValue && currentValue === state.lastInlineRequestsTemplate)
    ) {
      elements.batchInlineRequests.value = nextTemplate;
    }
    state.lastInlineRequestsTemplate = nextTemplate;
  };

  const syncBatchComposerFormat = (
    apiFormat: ArtifactApiFormat,
    options?: {
      inputFileId?: string;
      forceInlineTemplate?: boolean;
    },
  ): void => {
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
        elements.batchModel.value = readConfiguredFallbackModel();
      }
    }
    if (elements.batchDisplayNameField && elements.batchDisplayName) {
      const showDisplayName = apiFormat === "gemini";
      elements.batchDisplayNameField.hidden = !showDisplayName;
      if (!showDisplayName) {
        elements.batchDisplayName.value = "";
      } else if (!elements.batchDisplayName.value.trim()) {
        const inputFileId =
          options?.inputFileId?.trim() ?? elements.batchInput?.value.trim() ?? "";
        elements.batchDisplayName.value = inputFileId
          ? `gemini-${inputFileId}`
          : "gemini-batch";
      }
    }
    if (elements.batchHint) {
      elements.batchHint.textContent = getBatchFormatHint(apiFormat);
    }
    updateBatchValidationSurface();
    updateBatchCreateAvailability();
  };

  const bindBatchSubmit = (): void => {
    elements.batchForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget as HTMLFormElement;
      const fields = form.elements as typeof form.elements & {
        api_format: HTMLSelectElement;
        display_name: HTMLInputElement;
        endpoint: HTMLSelectElement;
        input_file_id: HTMLInputElement;
        metadata: HTMLTextAreaElement;
        model: HTMLInputElement;
        requests?: HTMLTextAreaElement;
      };
      const apiFormat = readBatchApiFormat();
      const metadataText = fields.metadata.value.trim();
      const metadata = metadataText
        ? safeJsonParse<Record<string, unknown> | typeof INVALID_JSON>(
            metadataText,
            INVALID_JSON,
          )
        : undefined;
      const inlinePayload = readInlinePayload();
      const inlineRequests = inlinePayload.requests;
      if (
        metadata === INVALID_JSON ||
        (metadata !== undefined &&
          (metadata === null || Array.isArray(metadata) || typeof metadata !== "object"))
      ) {
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
        app.pushAlert(
          `${formatApiFormatLabel(apiFormat)} batches need either a staged input file id or inline requests.`,
          "warn",
        );
        return;
      }
      const submitter = (event as SubmitEvent).submitter;
      const button =
        submitter instanceof HTMLButtonElement
          ? submitter
          : form.querySelector<HTMLButtonElement>('button[type="submit"]');
      if (!(await ensureFreshBatchValidation(button))) {
        if (
          state.validationReport &&
          !state.validationDirty &&
          state.validationReport.summary.error_count > 0
        ) {
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
          app.queueAlert(
            `Created ${String(response.api_format ?? apiFormat)} batch ${String(response.id ?? "")}.`,
            "info",
          );
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

  const bindBatchControls = (): void => {
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
    initialize(routeState: FilesBatchesRouteState): void {
      updateBatchValidationSurface();
      updateBatchCreateAvailability();
      bindBatchSubmit();
      bindBatchControls();
      if (routeState.composeInputFileId && elements.batchInput) {
        elements.batchInput.value = routeState.composeInputFileId;
        const source = inventory.fileLookup.get(routeState.composeInputFileId);
        const apiFormat =
          source?.api_format === "anthropic" || source?.api_format === "gemini"
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
