import type { AdminApp } from "../../app.js";
import { withBusyState } from "../../forms.js";
import { banner, pill, renderDefinitionList } from "../../templates.js";
import {
  escapeHtml,
  formatBytes,
  formatNumber,
  formatTimestamp,
  safeJsonParse,
} from "../../utils.js";
import {
  clearFilesBatchesPageDataCache,
  createBatch,
  deleteFile,
  fetchBatchMetadata,
  fetchFileContent,
  fetchFileMetadata,
  type FilesBatchesPageData,
  syncFilesBatchesPageDataCache,
  uploadFile,
  validateBatchInput,
} from "./api.js";
import {
  buildBatchActionHint,
  buildContentPreviewSummary,
  buildFilePreview,
  buildFilesBatchesUrl,
  describeFileValidationSnapshot,
  extractErrorReason,
  getLatestLinkedBatch,
  getLatestOutputBatch,
  getLinkedBatchesForFile,
  humanizeBatchLifecycle,
  inferDownloadMimeType,
  isBatchValidationCandidate,
  readFilesBatchesRouteState,
  renderInspectorActions,
  scopeFilesBatchesFilters,
  summarizeBatchRequestCounts,
  summarizePreviewOutcome,
} from "./serializers.js";
import type {
  ArtifactApiFormat,
  BatchRecord,
  BatchValidationIssue,
  BatchValidationReport,
  DefinitionItem,
  FileRecord,
  FileValidationSnapshot,
  FilesBatchesFilters,
  FilesBatchesInventory,
  FilesBatchesPage,
  InspectorSelection,
} from "./state.js";
import { INVALID_JSON } from "./state.js";
import type { FilesBatchesPageElements } from "./view.js";

interface BindFilesBatchesPageOptions {
  app: AdminApp;
  data: FilesBatchesPageData;
  elements: FilesBatchesPageElements;
  filters: FilesBatchesFilters;
  inventory: FilesBatchesInventory;
  page: FilesBatchesPage;
}

const OPENAI_BATCH_ENDPOINT_OPTIONS = [
  "/v1/chat/completions",
  "/v1/responses",
  "/v1/embeddings",
] as const;
const ANTHROPIC_BATCH_ENDPOINT = "/v1/messages";
const GEMINI_BATCH_ENDPOINT_TEMPLATE = "/v1beta/models/{model}:generateContent";
const BATCH_PREVIEW_BYTES = 256 * 1024;

export function bindFilesBatchesPage(options: BindFilesBatchesPageOptions): void {
  const { app, data, elements, filters, inventory, page } = options;

  let selection: InspectorSelection = { kind: "idle" };
  let previewObjectUrl: string | null = null;
  let lastInlineRequestsTemplate = "";
  let validationReport: BatchValidationReport | null = null;
  let validationSignature: string | null = null;
  let validationValidatedAt: number | null = null;
  let validationDirty = false;
  let validationInFlight = false;
  let validationMessage: string | null = null;
  let validationRefreshTimer: number | null = null;
  let validationRunId = 0;
  let uploadValidationReport: BatchValidationReport | null = null;
  let uploadValidationMessage: string | null = null;
  let uploadValidationInFlight = false;
  let uploadValidationSignature: string | null = null;
  let uploadValidationValidatedAt: number | null = null;

  const cacheFileRecord = (payload: FileRecord): FileRecord => {
    const fileId = String(payload.id ?? "");
    if (!fileId) {
      return payload;
    }
    const existing = inventory.fileLookup.get(fileId);
    const mergedPayload =
      payload.validation !== undefined || !existing?.validation
        ? payload
        : { ...payload, validation: existing.validation };
    inventory.fileLookup.set(fileId, mergedPayload);
    const existingIndex = data.files.findIndex(
      (item) => String(item.id ?? "") === fileId,
    );
    if (existingIndex >= 0) {
      data.files[existingIndex] = mergedPayload;
    } else {
      data.files.unshift(mergedPayload);
    }
    syncFilesBatchesPageDataCache(data);
    return mergedPayload;
  };

  const cacheBatchRecord = (payload: BatchRecord): BatchRecord => {
    const batchId = String(payload.id ?? "");
    if (!batchId) {
      return payload;
    }
    inventory.batchLookup.set(batchId, payload);
    const existingIndex = data.batches.findIndex(
      (item) => String(item.id ?? "") === batchId,
    );
    if (existingIndex >= 0) {
      data.batches[existingIndex] = payload;
    } else {
      data.batches.unshift(payload);
    }
    syncFilesBatchesPageDataCache(data);
    return payload;
  };

  const removeFileRecord = (fileId: string): FileRecord | null => {
    const existing = inventory.fileLookup.get(fileId) ?? null;
    if (!existing) {
      return null;
    }
    inventory.fileLookup.delete(fileId);
    const existingIndex = data.files.findIndex(
      (item) => String(item.id ?? "") === fileId,
    );
    if (existingIndex >= 0) {
      data.files.splice(existingIndex, 1);
    }
    syncFilesBatchesPageDataCache(data);
    return existing;
  };

  const setDefinitionBlock = (
    node: HTMLElement,
    items: DefinitionItem[],
    emptyMessage: string,
  ): void => {
    node.innerHTML = renderDefinitionList(items, emptyMessage);
  };

  const setSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(elements.summaryNode, items, "No selection yet.");
  };

  const setWorkflowSummary = (items: DefinitionItem[]): void => {
    setDefinitionBlock(elements.workflowNode, items, "No workflow state reported.");
  };

  const updateUploadValidateAvailability = (): void => {
    if (!elements.uploadValidateButton) {
      return;
    }
    const isBatchPurpose = elements.uploadPurpose?.value === "batch";
    elements.uploadValidateButton.disabled = !isBatchPurpose;
    elements.uploadValidateButton.title = isBatchPurpose
      ? "Validate the selected file as batch input without uploading it."
      : "Validation is available only when purpose is batch.";
  };

  const readUploadSelectedFile = (): File | null =>
    elements.uploadForm
      ?.querySelector<HTMLInputElement>('input[name="file"]')
      ?.files?.[0] ?? null;

  const buildUploadValidationSignature = (): string | null => {
    const selectedFile = readUploadSelectedFile();
    if (!selectedFile) {
      return null;
    }
    return JSON.stringify({
      apiFormat: readUploadApiFormat(),
      purpose: elements.uploadPurpose?.value ?? "",
      name: selectedFile.name,
      size: selectedFile.size,
      lastModified: selectedFile.lastModified,
    });
  };

  const resetUploadValidation = (): void => {
    uploadValidationReport = null;
    uploadValidationMessage = null;
    uploadValidationSignature = null;
    uploadValidationValidatedAt = null;
  };

  const encodeBytesToBase64 = (bytes: Uint8Array): string => {
    let binary = "";
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
      const chunk = bytes.subarray(index, index + chunkSize);
      binary += String.fromCharCode(...chunk);
    }
    return btoa(binary);
  };

  const updateUploadValidationSurface = (): void => {
    if (!elements.uploadValidationNode) {
      return;
    }

    const purpose = elements.uploadPurpose?.value ?? "";
    const selectedFile = readUploadSelectedFile();
    const selectedFileLabel = selectedFile?.name ?? "No file chosen";
    const isBatchPurpose = purpose === "batch";
    const statusLabel = uploadValidationInFlight
      ? "Validating"
      : uploadValidationReport
        ? uploadValidationReport.valid
          ? "Batch valid"
          : "Batch invalid"
        : isBatchPurpose
          ? "Not validated"
          : "Unavailable";
    const statusTone =
      uploadValidationInFlight
        ? "default"
        : uploadValidationReport
          ? uploadValidationReport.valid
            ? "good"
            : "warn"
          : isBatchPurpose
            ? "default"
            : "warn";
    const metaPills = [pill(statusLabel, statusTone)];

    if (uploadValidationReport) {
      metaPills.push(
        pill(`${formatNumber(uploadValidationReport.summary.total_rows)} rows`),
      );
      metaPills.push(
        pill(`${formatNumber(uploadValidationReport.summary.error_count)} errors`),
      );
      metaPills.push(
        pill(`${formatNumber(uploadValidationReport.summary.warning_count)} warnings`),
      );
    }

    let statusBanner = "";
    if (!isBatchPurpose) {
      statusBanner = banner(
        "Select purpose `batch` to validate the chosen file as batch input.",
        "warn",
      );
    } else if (uploadValidationMessage) {
      statusBanner = banner(uploadValidationMessage, "danger");
    } else if (uploadValidationInFlight) {
      statusBanner = banner("Validating the selected file without uploading it.", "info");
    } else if (uploadValidationReport?.valid) {
      statusBanner = banner("Batch valid.", "info");
    } else if (uploadValidationReport) {
      statusBanner = banner("Batch invalid.", "danger");
    } else {
      statusBanner = banner(
        "Choose a file and run Validate to check whether the batch is valid.",
        "info",
      );
    }

    const summaryItems: DefinitionItem[] = [
      { label: "Status", value: statusLabel },
      { label: "Purpose", value: purpose || "n/a" },
      { label: "Selected file", value: selectedFileLabel },
      {
        label: "Result",
        value: uploadValidationReport
          ? uploadValidationReport.valid
            ? "Batch valid"
            : "Batch invalid"
          : isBatchPurpose
            ? "Awaiting validation"
            : "Validation disabled",
        note: uploadValidationValidatedAt
          ? `Validated at ${formatTimestamp(uploadValidationValidatedAt)}.`
          : "Validation reads the selected local file without staging it.",
      },
    ];

    elements.uploadValidationNode.innerHTML = `
      <div class="batch-validation__header">
        <div>
          <h4>Batch validation</h4>
          <p class="muted">Validate the selected file before creating a batch.</p>
        </div>
        <div class="batch-validation__meta">
          ${metaPills.join("")}
        </div>
      </div>
      ${statusBanner}
      <div class="batch-validation__summary">
        ${renderDefinitionList(summaryItems, "No validation report yet.")}
      </div>
      <div class="batch-validation__issues">
        <div class="surface__header">
          <h4>Issues</h4>
          <span class="muted">${
            uploadValidationReport
              ? `${formatNumber(uploadValidationReport.issues.length)} reported`
              : "No issues to show yet."
          }</span>
        </div>
        ${
          uploadValidationReport
            ? renderValidationIssueRows(uploadValidationReport.issues)
            : '<p class="muted">Validation details appear here after you run Validate.</p>'
        }
      </div>
    `;
  };

  const setDetailSurface = (
    title: string,
    items: DefinitionItem[],
    payload: string,
    open = false,
  ): void => {
    elements.detailSummaryTitleNode.textContent = title;
    setDefinitionBlock(elements.detailSummaryNode, items, "No detail payload loaded.");
    elements.detailNode.textContent = payload;
    elements.detailDisclosure.open = open;
  };

  const setContentSurface = (
    title: string,
    items: DefinitionItem[],
    payload: string,
    open = false,
  ): void => {
    elements.contentSummaryTitleNode.textContent = title;
    setDefinitionBlock(elements.contentSummaryNode, items, "No file content loaded.");
    elements.contentNode.textContent = payload;
    elements.contentDisclosure.open = open;
  };

  const resetContentSurface = (): void => {
    clearMediaPreview();
    setContentSurface(
      "Content preview",
      [
        { label: "Preview surface", value: "Idle" },
        { label: "Loaded content", value: "No file content loaded" },
      ],
      "No file content loaded.",
      false,
    );
  };

  const clearMediaPreview = (): void => {
    elements.mediaNode.innerHTML = "";
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl);
      previewObjectUrl = null;
    }
  };

  const updateInspectorActions = (): void => {
    elements.actionNode.innerHTML = renderInspectorActions(
      page,
      selection,
      inventory.fileLookup,
      inventory.batchLookup,
      data.batches,
    );
  };

  const clearSelectionHandoff = (): void => {
    delete selection.handoffRequestId;
    delete selection.handoffRequestCount;
  };

  const findBatchByOutputFileId = (fileId: string): BatchRecord | null =>
    data.batches.find(
      (entry) => String(entry.output_file_id ?? "") === fileId,
    ) ?? null;

  const resolveContentPathForFile = (
    fileId: string,
    source: FileRecord | undefined,
    relatedBatch?: BatchRecord | null,
  ): string | undefined => {
    const batchOutputPath =
      (relatedBatch &&
      String(relatedBatch.output_file_id ?? "") === fileId
        ? relatedBatch.output_path
        : null) ||
      findBatchByOutputFileId(fileId)?.output_path;
    return batchOutputPath?.trim() || source?.content_path?.trim() || undefined;
  };

  const resolveDownloadPathForFile = (
    fileId: string,
    source: FileRecord | undefined,
  ): string | undefined =>
    findBatchByOutputFileId(fileId)?.output_path?.trim() ||
    source?.download_path?.trim() ||
    source?.content_path?.trim() ||
    undefined;

  const replaceStateForPage = (
    targetPage: FilesBatchesPage,
    routeState?: Parameters<typeof buildFilesBatchesUrl>[1],
  ): void => {
    window.history.replaceState(
      {},
      "",
      buildFilesBatchesUrl(
        scopeFilesBatchesFilters(targetPage, filters),
        routeState,
        targetPage,
      ),
    );
  };

  const navigateToPage = (
    targetPage: FilesBatchesPage,
    routeState?: Parameters<typeof buildFilesBatchesUrl>[1],
  ): void => {
    window.history.pushState(
      {},
      "",
      buildFilesBatchesUrl(
        scopeFilesBatchesFilters(targetPage, filters),
        routeState,
        targetPage,
      ),
    );
    void app.render(targetPage);
  };

  const syncSelectionRouteState = (nextSelection: InspectorSelection): void => {
    if (page === "files") {
      replaceStateForPage(page, {
        selectedFileId: nextSelection.kind === "file" ? nextSelection.fileId : "",
      });
      return;
    }
    if (page === "batches") {
      replaceStateForPage(page, {
        composeInputFileId: elements.batchInput?.value.trim() ?? "",
        selectedBatchId: nextSelection.kind === "batch" ? nextSelection.batchId : "",
      });
      return;
    }
    replaceStateForPage(page, {
      selectedFileId: nextSelection.kind === "file" ? nextSelection.fileId : "",
      selectedBatchId: nextSelection.kind === "batch" ? nextSelection.batchId : "",
      composeInputFileId: elements.batchInput?.value.trim() ?? "",
    });
  };

  const readBatchApiFormat = (): ArtifactApiFormat => {
    const normalized = elements.batchApiFormat?.value.trim();
    if (normalized === "anthropic" || normalized === "gemini") {
      return normalized;
    }
    return "openai";
  };

  const readUploadApiFormat = (): ArtifactApiFormat => {
    const normalized = elements.uploadApiFormat?.value.trim();
    if (normalized === "anthropic" || normalized === "gemini") {
      return normalized;
    }
    return "openai";
  };

  const getBatchFormatHint = (apiFormat: ArtifactApiFormat): string => {
    if (apiFormat === "anthropic") {
      return "Anthropic batches accept either a staged JSONL file shaped like `{custom_id, params}` per line or an inline JSON array shaped like `[{custom_id, params}]`. Provide a fallback model when rows omit `params.model`.";
    }
    if (apiFormat === "gemini") {
      return "Gemini batches accept either a staged JSONL file shaped like `{key, request}` per line or an inline JSON array shaped like `[{key?, request, metadata?}]`. Provide a fallback model when file rows omit `request.model`.";
    }
    return "OpenAI batches accept either a staged JSONL file in OpenAI batch input format or an inline JSON array shaped like `[{custom_id, method, url, body}]`. Provide a fallback model when rows omit `body.model`.";
  };

  const normalizeGeminiBatchModel = (value: string | null | undefined): string => {
    let normalized = value?.trim() ?? "";
    if (!normalized) {
      return "";
    }

    try {
      const parsed = new URL(normalized);
      normalized = parsed.pathname.trim();
    } catch {
      // Keep non-URL forms untouched.
    }

    normalized = normalized.replace(/^\/+|\/+$/g, "");
    if (normalized.includes("/models/")) {
      normalized = normalized.split("/models/").at(-1) ?? normalized;
    } else if (normalized.startsWith("models/")) {
      normalized = normalized.slice("models/".length);
    }
    if (normalized.includes(":")) {
      normalized = normalized.split(":", 1)[0] ?? normalized;
    }
    return normalized.trim();
  };

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

  const syncBatchEndpointControl = (
    apiFormat: ArtifactApiFormat,
  ): void => {
    if (!elements.batchEndpoint) {
      return;
    }

    if (apiFormat === "openai") {
      const selectedEndpoint = resolveBatchEndpoint("openai");
      elements.batchEndpoint.replaceChildren(
        ...OPENAI_BATCH_ENDPOINT_OPTIONS.map(
          (value) => new Option(value, value, value === selectedEndpoint, value === selectedEndpoint),
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

  const readConfiguredFallbackModel = (): string =>
    app.runtime?.gigachat_model?.trim() || "gemini-2.5-flash";

  const formatApiFormatLabel = (
    apiFormat: ArtifactApiFormat | null | undefined,
  ): string => {
    if (apiFormat === "anthropic") {
      return "Anthropic";
    }
    if (apiFormat === "gemini") {
      return "Gemini";
    }
    return "OpenAI";
  };

  const readInlineRequestsPayload = (): {
    provided: boolean;
    requests?: Array<Record<string, unknown>>;
    error?: string;
  } => {
    const inlineRequestsText = elements.batchInlineRequests?.value.trim() ?? "";
    if (!inlineRequestsText) {
      return { provided: false };
    }
    const parsed = safeJsonParse<
      Array<Record<string, unknown>> | typeof INVALID_JSON
    >(inlineRequestsText, INVALID_JSON);
    if (parsed === INVALID_JSON || !Array.isArray(parsed)) {
      return {
        provided: true,
        error: "Inline requests must be a JSON array.",
      };
    }
    return {
      provided: true,
      requests: parsed,
    };
  };

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
    const inlinePayload = readInlineRequestsPayload();
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

  const buildStoredFileValidationSnapshot = (
    report: BatchValidationReport,
    validatedAt: number | null,
  ): FileValidationSnapshot => ({
    status: !report.valid
      ? "invalid"
      : report.summary.warning_count > 0
        ? "valid_with_warnings"
        : "valid",
    total_rows: report.summary.total_rows,
    error_count: report.summary.error_count,
    warning_count: report.summary.warning_count,
    detected_format: report.detected_format ?? null,
    validated_at: validatedAt,
  });

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
      validationReport &&
      !validationDirty &&
      validationSignature !== null &&
      validationSignature === currentRequest.signature
    ) {
      return buildStoredFileValidationSnapshot(
        validationReport,
        validationValidatedAt,
      );
    }

    if (validationDirty) {
      if (storedSnapshot) {
        return { ...storedSnapshot, status: "stale" };
      }
      if (validationReport) {
        return {
          ...buildStoredFileValidationSnapshot(
            validationReport,
            validationValidatedAt,
          ),
          status: "stale",
        };
      }
    }

    return storedSnapshot ?? { status: "not_validated" };
  };

  const cacheValidationSnapshotForFile = (
    fileId: string,
    snapshot: FileValidationSnapshot | null,
  ): void => {
    const existing = inventory.fileLookup.get(fileId);
    if (!existing) {
      return;
    }
    cacheFileRecord({
      ...existing,
      validation: snapshot,
    });
  };

  const applyFileSelectionSurfaces = (
    fileId: string,
    source: FileRecord | undefined,
    mode: "inspect" | "composer",
    detailPayload: string,
  ): void => {
    const linkedBatches = getLinkedBatchesForFile(fileId, data.batches);
    const readyOutputs = linkedBatches.filter((batch) =>
      Boolean(String(batch.output_file_id ?? "")),
    ).length;
    const validationSnapshot = resolveDisplayedFileValidationSnapshot(fileId, source);
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
    const lastValidationItem =
      validationSnapshot?.validated_at != null
        ? [
            {
              label: "Last validation",
              value: formatTimestamp(validationSnapshot.validated_at),
              note:
                validationSnapshot.status === "stale"
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
      setDetailSurface(
        "Composer handoff",
        [
          { label: "Detail surface", value: "Composer handoff" },
          { label: "Selected input", value: fileId },
          { label: "Endpoint target", value: "Choose an endpoint in the batch form" },
          ...validationItem,
          ...lastValidationItem,
        ],
        detailPayload,
        false,
      );
      return;
    }

    setSummary([
      { label: "Selection", value: "File" },
      { label: "File id", value: fileId },
      { label: "Purpose", value: String(source?.purpose ?? "user_data") },
      { label: "Filename", value: String(source?.filename ?? fileId) },
      {
        label: "Created",
        value: formatTimestamp(source?.created_at),
        note: formatBytes(source?.bytes),
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
    setDetailSurface(
      "Selection metadata snapshot",
      [
        { label: "Detail surface", value: "File metadata" },
        { label: "Linked batches", value: String(linkedBatches.length) },
        { label: "Stored bytes", value: formatBytes(source?.bytes) },
        { label: "Status", value: String(source?.status ?? "processed") },
        ...validationItem,
        ...lastValidationItem,
      ],
      detailPayload,
      true,
    );
  };

  const refreshSelectedFileValidationSurface = (): void => {
    if (selection.kind !== "file" || !selection.fileId) {
      return;
    }
    const source = inventory.fileLookup.get(selection.fileId);
    const mode =
      elements.batchInput?.value.trim() === selection.fileId
        ? "composer"
        : "inspect";
    applyFileSelectionSurfaces(
      selection.fileId,
      source,
      mode,
      mode === "composer"
        ? `Selected ${selection.fileId} as batch input.`
        : JSON.stringify(source ?? { id: selection.fileId }, null, 2),
    );
  };

  const resolveValidationStatus = (): {
    label: string;
    tone: "default" | "good" | "warn";
  } => {
    if (validationInFlight) {
      return { label: "Validating", tone: "default" };
    }
    if (validationDirty) {
      return { label: "Stale report", tone: "warn" };
    }
    if (!validationReport) {
      return { label: "Not validated", tone: "default" };
    }
    if (!validationReport.valid) {
      return { label: "Invalid", tone: "warn" };
    }
    if (validationReport.summary.warning_count > 0) {
      return { label: "Valid with warnings", tone: "warn" };
    }
    return { label: "Valid", tone: "good" };
  };

  const renderValidationIssueRows = (
    issues: BatchValidationIssue[],
  ): string => {
    if (!issues.length) {
      return '<p class="muted">No line-level issues were reported for the current validation run.</p>';
    }

    return `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Line</th>
              <th>Severity</th>
              <th>Field</th>
              <th>Issue</th>
            </tr>
          </thead>
          <tbody>
            ${issues
              .map((issue) => {
                const severityLabel =
                  issue.severity.charAt(0).toUpperCase() + issue.severity.slice(1);
                const location = issue.line
                  ? issue.column
                    ? `${issue.line}:${issue.column}`
                    : String(issue.line)
                  : "File";
                return `
                  <tr>
                    <td>${escapeHtml(location)}</td>
                    <td>
                      <span class="batch-validation__severity batch-validation__severity--${escapeHtml(issue.severity)}">
                        ${escapeHtml(severityLabel)}
                      </span>
                    </td>
                    <td>${escapeHtml(issue.field || "n/a")}</td>
                    <td>
                      <div class="batch-validation__message">
                        <strong>${escapeHtml(issue.message)}</strong>
                        ${
                          issue.hint
                            ? `<span class="muted">Hint: ${escapeHtml(issue.hint)}</span>`
                            : ""
                        }
                        <span class="muted">Code: ${escapeHtml(issue.code)}</span>
                        ${
                          issue.raw_excerpt
                            ? `<pre class="batch-validation__excerpt">${escapeHtml(issue.raw_excerpt)}</pre>`
                            : ""
                        }
                      </div>
                    </td>
                  </tr>
                `;
              })
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  };

  const updateBatchValidationSurface = (): void => {
    if (!elements.batchValidationNode) {
      return;
    }

    const status = resolveValidationStatus();
    const currentRequest = buildBatchValidationRequest();
    const summaryItems: DefinitionItem[] = [
      { label: "Status", value: status.label },
      {
        label: "Selected format",
        value: formatApiFormatLabel(readBatchApiFormat()),
      },
      {
        label: "Detected format",
        value: validationReport?.detected_format
          ? formatApiFormatLabel(validationReport.detected_format)
          : "n/a",
        note: validationReport?.detected_format
          ? "Detected from the current batch row shape."
          : "Detection appears after a successful validation run.",
      },
      {
        label: "Input source",
        value: currentRequest.sourceLabel,
        note: currentRequest.sourceNote,
      },
      {
        label: "Last validation",
        value: validationValidatedAt
          ? formatTimestamp(validationValidatedAt)
          : "n/a",
        note: validationDirty
          ? "Composer inputs changed after the last report."
          : validationReport
            ? "Report matches the current composer input."
            : "No validation run for the current composer input yet.",
      },
    ];
    if (readBatchApiFormat() === "openai") {
      summaryItems.push({
        label: "Endpoint target",
        value: readBatchEndpoint(),
      });
    }

    const metaPills = [pill(status.label, status.tone)];
    if (validationReport && !validationDirty) {
      metaPills.push(
        pill(`${formatNumber(validationReport.summary.total_rows)} rows`),
      );
      metaPills.push(
        pill(`${formatNumber(validationReport.summary.error_count)} errors`),
      );
      metaPills.push(
        pill(`${formatNumber(validationReport.summary.warning_count)} warnings`),
      );
    }

    let reportBanner = "";
    if (validationMessage) {
      reportBanner = banner(
        validationMessage,
        validationMessage.includes("JSON array") ? "danger" : "warn",
      );
    } else if (validationInFlight) {
      reportBanner = banner(
        "Validation is running for the current composer input.",
        "info",
      );
    } else if (validationDirty) {
      reportBanner = banner(
        "The last validation report is stale. Re-run validation before creating the batch.",
        "warn",
      );
    } else if (validationReport && !validationReport.valid) {
      reportBanner = banner(
        "Validation found blocking errors. Fix them or change the selected format before creating the batch.",
        "danger",
      );
    } else if (validationReport && validationReport.summary.warning_count > 0) {
      reportBanner = banner(
        "Validation passed with warnings. Batch creation stays enabled.",
        "warn",
      );
    } else if (validationReport) {
      reportBanner = banner(
        "Validation passed with no blocking issues.",
        "info",
      );
    } else {
      reportBanner = banner(
        "Run Validate file to get row-level diagnostics before queueing the batch.",
        "info",
      );
    }

    elements.batchValidationNode.innerHTML = `
      <div class="batch-validation__header">
        <div>
          <h4>Validation report</h4>
          <p class="muted">Run preflight validation before creating a batch.</p>
        </div>
        <div class="batch-validation__meta">
          ${metaPills.join("")}
        </div>
      </div>
      ${reportBanner}
      <div class="batch-validation__summary">
        ${renderDefinitionList(summaryItems, "No validation report yet.")}
      </div>
      <div class="batch-validation__issues">
        <div class="surface__header">
          <h4>Issues</h4>
          <span class="muted">${
            validationReport && !validationDirty
              ? `${formatNumber(validationReport.issues.length)} reported`
              : validationReport && validationDirty
                ? "Showing the previous report until validation is re-run."
                : "No issues to show yet."
          }</span>
        </div>
        ${validationReport ? renderValidationIssueRows(validationReport.issues) : '<p class="muted">Validate the current composer input to populate the issue list.</p>'}
      </div>
    `;
  };

  const updateBatchCreateAvailability = (): void => {
    if (!elements.batchCreateButton) {
      return;
    }
    const hasFreshBlockingErrors =
      Boolean(validationReport) &&
      !validationDirty &&
      validationReport!.summary.error_count > 0;
    elements.batchCreateButton.disabled =
      validationInFlight || hasFreshBlockingErrors;
    elements.batchCreateButton.title = validationInFlight
      ? "Validation is running."
      : hasFreshBlockingErrors
        ? "Fix validation errors or change the current composer input first."
        : "";
  };

  const clearValidationRefreshTimer = (): void => {
    if (validationRefreshTimer !== null) {
      window.clearTimeout(validationRefreshTimer);
      validationRefreshTimer = null;
    }
  };

  const invalidateBatchValidation = (options?: { auto?: boolean }): void => {
    const hadValidationState =
      validationReport !== null || validationValidatedAt !== null;
    validationDirty = hadValidationState;
    validationMessage = null;
    updateBatchValidationSurface();
    updateBatchCreateAvailability();
    refreshSelectedFileValidationSurface();
    if (!options?.auto || !hadValidationState) {
      clearValidationRefreshTimer();
      return;
    }
    clearValidationRefreshTimer();
    validationRefreshTimer = window.setTimeout(() => {
      validationRefreshTimer = null;
      void runBatchValidation(null, { automatic: true });
    }, 250);
  };

  const runBatchValidation = async (
    button: HTMLButtonElement | null,
    options?: { automatic?: boolean },
  ): Promise<void> => {
    const requestPayload = buildBatchValidationRequest();
    if (!requestPayload.signature || requestPayload.error) {
      validationMessage =
        requestPayload.error ??
        "Validation needs a staged input file or inline requests.";
      updateBatchValidationSurface();
      updateBatchCreateAvailability();
      if (!options?.automatic) {
        app.pushAlert(validationMessage, "warn");
      }
      return;
    }

    validationMessage = null;
    validationInFlight = true;
    updateBatchValidationSurface();
    updateBatchCreateAvailability();
    const runId = ++validationRunId;

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
      if (runId !== validationRunId) {
        return;
      }
      validationReport = report;
      validationSignature = requestPayload.signature;
      validationValidatedAt = Math.floor(Date.now() / 1000);
      validationDirty = false;
      if (requestPayload.inputFileId && !requestPayload.requests?.length) {
        cacheValidationSnapshotForFile(
          requestPayload.inputFileId,
          buildStoredFileValidationSnapshot(report, validationValidatedAt),
        );
      }
      refreshSelectedFileValidationSurface();
      setWorkflowSummary([
        { label: "Workflow state", value: "Batch input validated" },
        { label: "API format", value: formatApiFormatLabel(report.api_format) },
        {
          label: "Status",
          value: report.valid ? "Ready to create" : "Needs fixes",
          note: `${formatNumber(report.summary.error_count)} errors · ${formatNumber(report.summary.warning_count)} warnings`,
        },
        {
          label: "Input source",
          value: requestPayload.sourceLabel,
          note: requestPayload.sourceNote,
        },
      ]);
      if (!options?.automatic) {
        const alertTone = report.valid ? "info" : "warn";
        app.pushAlert(
          report.valid
            ? `Validation passed for ${formatApiFormatLabel(report.api_format)} batch input.`
            : `Validation found ${report.summary.error_count} blocking issue${report.summary.error_count === 1 ? "" : "s"}.`,
          alertTone,
        );
      }
    } catch (error) {
      if (runId !== validationRunId) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      validationMessage = extractErrorReason(message);
      if (!options?.automatic) {
        app.pushAlert(validationMessage, "danger");
      }
    } finally {
      if (runId === validationRunId) {
        validationInFlight = false;
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
      validationMessage = currentRequest.error;
      updateBatchValidationSurface();
      updateBatchCreateAvailability();
      app.pushAlert(currentRequest.error, "warn");
      return false;
    }

    const hasFreshValidation =
      validationReport !== null &&
      !validationDirty &&
      validationSignature !== null &&
      validationSignature === currentRequest.signature;
    if (!hasFreshValidation) {
      await runBatchValidation(button, { automatic: false });
    }

    const latestRequest = buildBatchValidationRequest();
    const hasBlockingErrors =
      validationReport !== null &&
      !validationDirty &&
      validationSignature !== null &&
      validationSignature === latestRequest.signature &&
      validationReport.summary.error_count > 0;
    return !validationInFlight && !latestRequest.error && !hasBlockingErrors;
  };

  const buildBatchInlineRequestsTemplate = (
    apiFormat: ArtifactApiFormat,
  ): string => {
    const fallbackModel =
      elements.batchModel?.value.trim() || readConfiguredFallbackModel();
    if (apiFormat === "anthropic") {
      return JSON.stringify(
        [
          {
            custom_id: "anthropic-row-1",
            params: {
              model: fallbackModel,
              max_tokens: 64,
              messages: [
                {
                  role: "user",
                  content: "hello anthropic",
                },
              ],
            },
          },
        ],
        null,
        2,
      );
    }
    if (apiFormat === "gemini") {
      const normalizedModel = fallbackModel;
      const requestModel = normalizedModel.startsWith("models/")
        ? normalizedModel
        : `models/${normalizedModel}`;
      return JSON.stringify(
        [
          {
            request: {
              contents: [
                {
                  role: "user",
                  parts: [{ text: "hello gemini" }],
                },
              ],
              model: requestModel,
            },
            metadata: {
              requestLabel: "row-1",
            },
          },
        ],
        null,
        2,
      );
    }

    const endpoint = readBatchEndpoint();
    if (endpoint === "/v1/embeddings") {
      return JSON.stringify(
        [
          {
            custom_id: "openai-row-1",
            method: "POST",
            url: "/v1/embeddings",
            body: {
              model: fallbackModel,
              input: "hello openai",
            },
          },
        ],
        null,
        2,
      );
    }
    if (endpoint === "/v1/responses") {
      return JSON.stringify(
        [
          {
            custom_id: "openai-row-1",
            method: "POST",
            url: "/v1/responses",
            body: {
              model: fallbackModel,
              input: "hello openai",
            },
          },
        ],
        null,
        2,
      );
    }
    return JSON.stringify(
      [
        {
          custom_id: "openai-row-1",
          method: "POST",
          url: "/v1/chat/completions",
          body: {
            model: fallbackModel,
            messages: [
              {
                role: "user",
                content: "hello openai",
              },
            ],
          },
        },
      ],
      null,
      2,
    );
  };

  const syncBatchInlineRequestsTemplate = (options?: {
    forceValue?: boolean;
  }): void => {
    if (!elements.batchInlineRequests) {
      return;
    }
    const nextTemplate = buildBatchInlineRequestsTemplate(readBatchApiFormat());
    elements.batchInlineRequests.placeholder = nextTemplate;
    const currentValue = elements.batchInlineRequests.value.trim();
    if (
      options?.forceValue ||
      (currentValue && currentValue === lastInlineRequestsTemplate)
    ) {
      elements.batchInlineRequests.value = nextTemplate;
    }
    lastInlineRequestsTemplate = nextTemplate;
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
      const showModel = true;
      elements.batchModelField.hidden = !showModel;
      elements.batchModel.required = false;
      if (!showModel) {
        elements.batchModel.value = "";
      } else if (!elements.batchModel.value.trim()) {
        elements.batchModel.value = readConfiguredFallbackModel();
      }
    }
    if (elements.batchDisplayNameField && elements.batchDisplayName) {
      const showDisplayName = apiFormat === "gemini";
      elements.batchDisplayNameField.hidden = !showDisplayName;
      if (!showDisplayName) {
        elements.batchDisplayName.value = "";
      } else if (!elements.batchDisplayName.value.trim()) {
        const inputFileId = options?.inputFileId?.trim() ?? elements.batchInput?.value.trim() ?? "";
        elements.batchDisplayName.value = inputFileId
          ? `gemini-${inputFileId}`
          : "gemini-batch";
      }
    }
    if (elements.batchHint) {
      elements.batchHint.textContent = getBatchFormatHint(apiFormat);
    }
  };

  const getUploadFormatHint = (apiFormat: ArtifactApiFormat): string => {
    if (apiFormat === "anthropic") {
      return "Anthropic staging keeps the file on the shared files surface but marks it as Anthropic-oriented so the batch composer can default correctly later.";
    }
    if (apiFormat === "gemini") {
      return "Gemini staging stores Gemini-specific metadata such as display name and MIME type so the inventory stays provider-aware.";
    }
    return "OpenAI uploads stage one file through the gateway files surface. Switch formats here when this artifact is meant for Anthropic or Gemini flows.";
  };

  const syncUploadComposerFormat = (apiFormat: ArtifactApiFormat): void => {
    if (elements.uploadApiFormat) {
      elements.uploadApiFormat.value = apiFormat;
    }
    if (elements.uploadDisplayNameField && elements.uploadDisplayName) {
      const showDisplayName = apiFormat === "gemini";
      elements.uploadDisplayNameField.hidden = !showDisplayName;
      if (!showDisplayName) {
        elements.uploadDisplayName.value = "";
      }
    }
    const uploadHint = document.getElementById("upload-format-hint");
    if (uploadHint) {
      uploadHint.textContent = getUploadFormatHint(apiFormat);
    }
  };

  const runWorkflowAction = async <T>({
    button,
    root,
    pendingLabel,
    pendingSummary,
    successSummary,
    action,
  }: {
    button?: HTMLButtonElement | null;
    root?: Element | DocumentFragment | null;
    pendingLabel: string;
    pendingSummary: DefinitionItem[];
    successSummary: (result: T) => DefinitionItem[];
    action: () => Promise<T>;
  }): Promise<T> => {
    setWorkflowSummary(pendingSummary);
    try {
      const result = await withBusyState({
        root,
        button,
        pendingLabel,
        action,
      });
      setWorkflowSummary(successSummary(result));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setWorkflowSummary([
        { label: "Workflow state", value: "Action failed" },
        { label: "Failed step", value: pendingSummary[0]?.value ?? "Unknown action" },
        { label: "Reason", value: extractErrorReason(message) },
      ]);
      throw error;
    }
  };

  const focusBatchComposer = (fileId: string): void => {
    if (!elements.batchInput) {
      navigateToPage("batches", { composeInputFileId: fileId });
      return;
    }
    const source = inventory.fileLookup.get(fileId);
    const preferredApiFormat =
      source?.api_format === "anthropic" || source?.api_format === "gemini"
        ? source.api_format
        : "openai";
    elements.batchInput.value = fileId;
    syncBatchComposerFormat(preferredApiFormat, { inputFileId: fileId });
    invalidateBatchValidation();
    selection = { kind: "file", fileId };
    clearSelectionHandoff();
    resetContentSurface();
    syncSelectionRouteState(selection);
    applyFileSelectionSurfaces(
      fileId,
      source,
      "composer",
      `Selected ${fileId} as batch input.`,
    );
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

  const previewFileContent = async (
    fileId: string,
    button: HTMLButtonElement | null,
    options?: {
      label?: string;
      support?: string;
      relatedBatch?: BatchRecord | null;
    },
  ): Promise<void> => {
    const source = inventory.fileLookup.get(fileId);
    const label = options?.label ?? "File content preview";
    setContentSurface(
      label,
      [
        { label: "Preview surface", value: label },
        { label: "File id", value: fileId },
        {
          label: "Loaded content",
          value: "Loading…",
          note: options?.support ?? String(source?.filename ?? fileId),
        },
      ],
      "Loading file content…",
      true,
    );
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
                value:
                  (preview.handoffRequestCount ?? 0) > 1
                    ? "Sample request scoped"
                    : "Request scoped",
                note:
                  (preview.handoffRequestCount ?? 0) > 1
                    ? `Traffic and Logs can open with sample request ${preview.handoffRequestId} from ${preview.handoffRequestCount} decoded result rows.`
                    : `Traffic and Logs can open directly with request ${preview.handoffRequestId}.`,
              },
            ]
          : []),
      ],
      action: async () => {
        const previewBytes = resolvePreviewBytes(source, options);
        const { bytes, totalBytes } = await fetchFileContent(
          app,
          fileId,
          resolveContentPathForFile(fileId, source, options?.relatedBatch),
          previewBytes,
        );
        const preview = buildFilePreview(bytes, String(source?.filename ?? fileId), {
          previewByteLimit: BATCH_PREVIEW_BYTES,
          previewTextCharLimit: 100_000,
          totalByteLength: totalBytes ?? undefined,
        });
        if (preview.handoffRequestId && options?.relatedBatch) {
          selection = {
            kind: "batch",
            batchId: String(options.relatedBatch.id ?? selection.batchId ?? ""),
            inputFileId:
              String(options.relatedBatch.input_file_id ?? selection.inputFileId ?? "") ||
              undefined,
            outputFileId: fileId,
            handoffRequestId: preview.handoffRequestId,
            handoffRequestCount: preview.handoffRequestCount,
          };
          updateInspectorActions();
        } else if (selection.kind === "batch") {
          clearSelectionHandoff();
          updateInspectorActions();
        }
        setContentSurface(
          label,
          buildContentPreviewSummary(preview, fileId, label, {
            support: options?.support ?? String(source?.filename ?? fileId),
            file: source,
            relatedBatch: options?.relatedBatch ?? null,
          }),
          preview.textFallback,
          true,
        );
        if (preview.kind === "image") {
          clearMediaPreview();
          const blobBytes = new Uint8Array(bytes.byteLength);
          blobBytes.set(bytes);
          const blob = new Blob([blobBytes], { type: preview.mimeType });
          previewObjectUrl = URL.createObjectURL(blob);
          const figure = document.createElement("figure");
          figure.className = "surface";
          const image = document.createElement("img");
          image.alt = String(preview.filename ?? fileId);
          image.src = previewObjectUrl;
          image.style.display = "block";
          image.style.maxWidth = "100%";
          image.style.height = "auto";
          image.style.borderRadius = "12px";
          figure.append(image);
          elements.mediaNode.replaceChildren(figure);
        } else {
          clearMediaPreview();
        }
        return preview;
      },
    });
  };

  const downloadFileContent = async (
    fileId: string,
    filename: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
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
        const { bytes, mimeType } = await fetchFileContent(
          app,
          fileId,
          resolveDownloadPathForFile(fileId, source),
        );
        const blobBytes = new Uint8Array(bytes.byteLength);
        blobBytes.set(bytes);
        const objectUrl = URL.createObjectURL(
          new Blob([blobBytes], {
            type: inferDownloadMimeType(filename, mimeType, bytes),
          }),
        );
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

  const resolveDownloadFilename = (fileId: string): string => {
    const source = inventory.fileLookup.get(fileId);
    const filename = String(source?.filename ?? "").trim();
    return filename || `file-${fileId}.bin`;
  };

  const resolvePreviewBytes = (
    source: FileRecord | undefined,
    options?: {
      relatedBatch?: BatchRecord | null;
    },
  ): number | undefined => {
    if (options?.relatedBatch) {
      return BATCH_PREVIEW_BYTES;
    }
    const filename = String(source?.filename ?? "").trim().toLowerCase();
    if (
      filename.endsWith(".jsonl") ||
      filename.endsWith(".json") ||
      filename.endsWith(".txt") ||
      filename.endsWith(".log")
    ) {
      return BATCH_PREVIEW_BYTES;
    }
    return undefined;
  };

  const inspectFile = async (
    fileId: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
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
        selection = { kind: "file", fileId };
        clearSelectionHandoff();
        resetContentSurface();
        syncSelectionRouteState(selection);
        applyFileSelectionSurfaces(
          fileId,
          source,
          "inspect",
          JSON.stringify(payload, null, 2),
        );
        updateInspectorActions();
        return payload;
      },
    });
    if (shouldRefreshPage) {
      await app.render(page);
    }
  };

  const inspectBatch = async (
    batchId: string,
    button: HTMLButtonElement | null,
  ): Promise<void> => {
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
            value: selection.outputFileId
              ? "Preview output or inspect input"
              : "Preview input and refresh status",
            note: selection.outputFileId
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
        selection = {
          kind: "batch",
          batchId,
          inputFileId: inputFileId || undefined,
          outputFileId: outputFileId || undefined,
        };
        clearSelectionHandoff();
        resetContentSurface();
        syncSelectionRouteState(selection);
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
        setDetailSurface(
          "Selection metadata snapshot",
          [
            { label: "Detail surface", value: "Batch metadata" },
            { label: "Lifecycle posture", value: humanizeBatchLifecycle(source.status) },
            { label: "Input file", value: inputFileId || "missing" },
            { label: "Output file", value: outputFileId || "not ready" },
            { label: "Requests", value: summarizeBatchRequestCounts(source.request_counts) },
          ],
          JSON.stringify(payload, null, 2),
          true,
        );
        updateInspectorActions();
        return payload;
      },
    });
    if (shouldRefreshPage) {
      await app.render(page);
    }
  };

  updateInspectorActions();
  resetContentSurface();
  syncUploadComposerFormat(readUploadApiFormat());
  updateUploadValidateAvailability();
  updateUploadValidationSurface();
  updateBatchValidationSurface();
  updateBatchCreateAvailability();
  setDetailSurface(
    "Selection metadata snapshot",
    [
      { label: "Detail surface", value: "Idle" },
      { label: "Loaded object", value: "No file or batch metadata loaded" },
    ],
    "No selection yet.",
    false,
  );

  elements.filtersForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      query?: HTMLInputElement;
      purpose?: HTMLSelectElement;
      batch_status?: HTMLSelectElement;
      endpoint?: HTMLSelectElement;
      file_sort?: HTMLSelectElement;
    };

    const nextFilters: FilesBatchesFilters = {
      query: fields.query?.value.trim() ?? "",
      purpose: fields.purpose?.value ?? "",
      batchStatus: fields.batch_status?.value ?? "",
      endpoint: fields.endpoint?.value ?? "",
      fileSort:
        (fields.file_sort?.value as FilesBatchesFilters["fileSort"] | undefined) ??
        filters.fileSort,
    };
    window.history.replaceState(
      {},
      "",
      buildFilesBatchesUrl(nextFilters, undefined, page),
    );
    void app.render(page);
  });

  elements.uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      api_format: HTMLSelectElement;
      display_name?: HTMLInputElement;
      purpose: HTMLSelectElement;
      file: HTMLInputElement;
    };
    const upload = fields.file.files?.[0];
    const apiFormat = readUploadApiFormat();
    if (!upload) {
      app.pushAlert("Choose a file before uploading.", "warn");
      return;
    }
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');

    await runWorkflowAction({
      root: form,
      button,
      pendingLabel: "Uploading…",
      pendingSummary: [
        { label: "Workflow state", value: "Uploading file" },
        { label: "API format", value: apiFormat },
        { label: "Purpose", value: fields.purpose.value },
        { label: "Source", value: upload.name, note: formatBytes(upload.size) },
      ],
      successSummary: (response) => [
        { label: "Workflow state", value: "File uploaded" },
        { label: "File id", value: String(response.id ?? "unknown") },
        { label: "API format", value: String(response.api_format ?? apiFormat) },
        {
          label: "Next step",
          value: "Inspect or open batches",
          note: "The page refreshes into the new file selection so the files inspector stays on the fresh upload.",
        },
      ],
      action: async () => {
        const response = await uploadFile(app, {
          apiFormat,
          purpose: fields.purpose.value,
          file: upload,
          displayName: fields.display_name?.value,
        });
        const validatedThisSelection =
          fields.purpose.value === "batch" &&
          uploadValidationReport !== null &&
          uploadValidationSignature !== null &&
          uploadValidationSignature === buildUploadValidationSignature();
        const latestUploadValidationReport = uploadValidationReport;
        const mergedResponse = validatedThisSelection
          && latestUploadValidationReport
          ? {
              ...response,
              validation: buildStoredFileValidationSnapshot(
                latestUploadValidationReport,
                uploadValidationValidatedAt,
              ),
            }
          : response;
        cacheFileRecord(mergedResponse);
        app.queueAlert(`Uploaded file ${String(response.id ?? "")}.`, "info");
        replaceStateForPage(page, {
          selectedFileId: String(response.id ?? ""),
        });
        await app.render(page);
        return mergedResponse;
      },
    });
  });

  elements.uploadApiFormat?.addEventListener("change", () => {
    syncUploadComposerFormat(readUploadApiFormat());
    resetUploadValidation();
    updateUploadValidationSurface();
  });
  elements.uploadPurpose?.addEventListener("change", () => {
    resetUploadValidation();
    updateUploadValidateAvailability();
    updateUploadValidationSurface();
  });
  elements.uploadForm
    ?.querySelector<HTMLInputElement>('input[name="file"]')
    ?.addEventListener("change", () => {
      resetUploadValidation();
      updateUploadValidationSurface();
    });
  elements.uploadValidateButton?.addEventListener("click", async () => {
    const form = elements.uploadForm;
    if (!form) {
      return;
    }
    const fields = form.elements as typeof form.elements & {
      api_format: HTMLSelectElement;
      display_name?: HTMLInputElement;
      purpose: HTMLSelectElement;
      file: HTMLInputElement;
    };
    const upload = fields.file.files?.[0];
    const apiFormat = readUploadApiFormat();
    if (fields.purpose.value !== "batch") {
      uploadValidationMessage = "Validation is available only when purpose is batch.";
      updateUploadValidateAvailability();
      updateUploadValidationSurface();
      app.pushAlert(uploadValidationMessage, "warn");
      return;
    }
    if (!upload) {
      uploadValidationMessage = "Choose a file before validation.";
      updateUploadValidationSurface();
      app.pushAlert(uploadValidationMessage, "warn");
      return;
    }

    uploadValidationMessage = null;
    uploadValidationReport = null;
    uploadValidationSignature = buildUploadValidationSignature();
    uploadValidationValidatedAt = null;
    uploadValidationInFlight = true;
    updateUploadValidateAvailability();
    updateUploadValidationSurface();

    try {
      const inputContentBase64 = encodeBytesToBase64(
        new Uint8Array(await upload.arrayBuffer()),
      );
      const report = await withBusyState({
        root: form,
        button: elements.uploadValidateButton,
        pendingLabel: "Validating…",
        action: async () =>
          validateBatchInput(app, {
            apiFormat,
            inputContentBase64,
          }),
      });
      uploadValidationReport = report;
      uploadValidationValidatedAt = Math.floor(Date.now() / 1000);
      updateUploadValidationSurface();
      setWorkflowSummary([
        { label: "Workflow state", value: "Batch validated" },
        { label: "API format", value: formatApiFormatLabel(report.api_format) },
        {
          label: "Result",
          value: report.valid ? "Batch valid" : "Batch invalid",
          note: `${formatNumber(report.summary.error_count)} errors · ${formatNumber(report.summary.warning_count)} warnings`,
        },
        {
          label: "Validated file",
          value: upload.name,
          note: "The selected local file was validated without staging it.",
        },
      ]);
      app.pushAlert(
        report.valid ? "Batch valid." : "Batch invalid.",
        report.valid ? "info" : "warn",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      uploadValidationMessage = extractErrorReason(message);
      updateUploadValidationSurface();
      app.pushAlert(uploadValidationMessage, "danger");
    } finally {
      uploadValidationInFlight = false;
      updateUploadValidateAvailability();
      updateUploadValidationSurface();
    }
  });

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
    const inlinePayload = readInlineRequestsPayload();
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
      validationMessage = inlinePayload.error;
      updateBatchValidationSurface();
      updateBatchCreateAvailability();
      app.pushAlert(inlinePayload.error, "danger");
      return;
    }
    const inputFileId = fields.input_file_id.value.trim();
    if (!inputFileId && !inlineRequests?.length) {
      const formatLabel =
        apiFormat === "anthropic"
          ? "Anthropic"
          : apiFormat === "gemini"
            ? "Gemini"
            : "OpenAI";
      app.pushAlert(
        `${formatLabel} batches need either a staged input file id or inline requests.`,
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
        validationReport &&
        !validationDirty &&
        validationReport.summary.error_count > 0
      ) {
        app.pushAlert(
          "Fix validation errors before creating the batch.",
          "warn",
        );
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

  elements.batchValidateButton?.addEventListener("click", async () => {
    await runBatchValidation(elements.batchValidateButton, { automatic: false });
  });

  elements.actionNode.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest<HTMLButtonElement>("[data-inspector-action]");
    if (!button) {
      return;
    }
    const action = button.dataset.inspectorAction;
    if (!action) {
      return;
    }
    if (action === "inspect-file" && selection.fileId) {
      await inspectFile(selection.fileId, button);
      return;
    }
    if (action === "use-file" && selection.fileId) {
      focusBatchComposer(selection.fileId);
      return;
    }
    if (action === "preview-file" && selection.fileId) {
      await previewFileContent(selection.fileId, button);
      return;
    }
    if (action === "download-file" && selection.fileId) {
      await downloadFileContent(
        selection.fileId,
        resolveDownloadFilename(selection.fileId),
        button,
      );
      return;
    }
    if (action === "inspect-batch" && selection.batchId) {
      await inspectBatch(selection.batchId, button);
      return;
    }
    if (action === "batch-input" && selection.inputFileId) {
      await inspectFile(selection.inputFileId, button);
      return;
    }
    if (action === "preview-batch-input" && selection.inputFileId && selection.batchId) {
      await previewFileContent(selection.inputFileId, button, {
        label: "Batch input preview",
        support: `Batch ${selection.batchId}`,
        relatedBatch: inventory.batchLookup.get(selection.batchId) ?? null,
      });
      return;
    }
    if (action === "use-batch-input" && selection.inputFileId) {
      focusBatchComposer(selection.inputFileId);
      return;
    }
    if (action === "batch-output" && selection.outputFileId && selection.batchId) {
      await previewFileContent(selection.outputFileId, button, {
        label: "Batch output preview",
        support: `Batch ${selection.batchId}`,
        relatedBatch: inventory.batchLookup.get(selection.batchId) ?? null,
      });
      return;
    }
    if (action === "inspect-output-file" && selection.outputFileId) {
      await inspectFile(selection.outputFileId, button);
      return;
    }
    if (action === "inspect-linked-batch" && selection.fileId) {
      const latestBatch = getLatestLinkedBatch(selection.fileId, data.batches);
      if (latestBatch) {
        await inspectBatch(String(latestBatch.id ?? ""), button);
      }
      return;
    }
    if (action === "preview-linked-output" && selection.fileId) {
      const latestOutputBatch = getLatestOutputBatch(selection.fileId, data.batches);
      const outputFileId = String(latestOutputBatch?.output_file_id ?? "");
      if (!outputFileId) {
        return;
      }
      selection = {
        kind: "batch",
        batchId: String(latestOutputBatch?.id ?? ""),
        inputFileId: String(latestOutputBatch?.input_file_id ?? "") || undefined,
        outputFileId,
      };
      clearSelectionHandoff();
      syncSelectionRouteState(selection);
      setSummary([
        { label: "Selection", value: "Linked batch output" },
        { label: "Output file", value: outputFileId },
        { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
        { label: "Endpoint", value: String(latestOutputBatch?.endpoint ?? "n/a") },
      ]);
      setDetailSurface(
        "Selection metadata snapshot",
        [
          { label: "Detail surface", value: "Latest linked output" },
          { label: "Batch id", value: String(latestOutputBatch?.id ?? "unknown") },
          { label: "Output file", value: outputFileId },
          {
            label: "Requests",
            value: summarizeBatchRequestCounts(latestOutputBatch?.request_counts),
          },
        ],
        JSON.stringify(
          {
            latest_linked_batch: latestOutputBatch,
            output_file_id: outputFileId,
          },
          null,
          2,
        ),
        true,
      );
      updateInspectorActions();
      await previewFileContent(outputFileId, button, {
        label: "Latest linked output",
        support: `Batch ${String(latestOutputBatch?.id ?? "unknown")}`,
        relatedBatch: latestOutputBatch ?? null,
      });
    }
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-view]").forEach((item) => {
    item.addEventListener("click", async () => {
      await inspectFile(
        item.dataset.fileView ?? "",
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-use]").forEach((item) => {
    item.addEventListener("click", () => {
      const fileId = item.dataset.fileUse;
      if (!fileId) {
        return;
      }
      focusBatchComposer(fileId);
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-content]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.fileContent;
      if (!fileId) {
        return;
      }
      selection = { kind: "file", fileId };
      clearSelectionHandoff();
      syncSelectionRouteState(selection);
      updateInspectorActions();
      await previewFileContent(
        fileId,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-download]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.fileDownload;
      if (!fileId) {
        return;
      }
      const filename =
        item.dataset.fileDownloadName?.trim() || resolveDownloadFilename(fileId);
      await downloadFileContent(
        fileId,
        filename,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-file-delete]").forEach((item) => {
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
            app.pushAlert(
              `Delete is unavailable for ${fileId} in the current API format.`,
              "warn",
            );
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

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-view]").forEach((item) => {
    item.addEventListener("click", async () => {
      await inspectBatch(
        item.dataset.batchView ?? "",
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-output]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.batchOutput;
      if (!fileId) {
        return;
      }
      const batch = data.batches.find(
        (entry) => String(entry.output_file_id ?? "") === fileId,
      );
      selection = {
        kind: "batch",
        batchId: String(batch?.id ?? ""),
        inputFileId: String(batch?.input_file_id ?? "") || undefined,
        outputFileId: fileId,
      };
      clearSelectionHandoff();
      syncSelectionRouteState(selection);
      setSummary([
        { label: "Selection", value: "Batch output" },
        { label: "Output file", value: fileId },
        { label: "Batch id", value: String(batch?.id ?? "unknown") },
        { label: "Endpoint", value: String(batch?.endpoint ?? "n/a") },
      ]);
      setDetailSurface(
        "Selection metadata snapshot",
        [
          { label: "Detail surface", value: "Batch output handoff" },
          { label: "Batch id", value: String(batch?.id ?? "unknown") },
          { label: "Output file", value: fileId },
        ],
        JSON.stringify(
          {
            batch_output_handoff: batch ?? null,
            output_file_id: fileId,
          },
          null,
          2,
        ),
        true,
      );
      updateInspectorActions();
      await previewFileContent(
        fileId,
        item instanceof HTMLButtonElement ? item : null,
        {
          label: "Batch output preview",
          support: `Batch ${String(batch?.id ?? "unknown")}`,
          relatedBatch: batch ?? null,
        },
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-download]").forEach((item) => {
    item.addEventListener("click", async () => {
      const fileId = item.dataset.batchDownload;
      if (!fileId) {
        return;
      }
      const filename =
        item.dataset.batchDownloadName?.trim() || `batch-output-${fileId}.jsonl`;
      await downloadFileContent(
        fileId,
        filename,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-batch-input]").forEach((item) => {
    item.addEventListener("click", async () => {
      const batchId = item.dataset.batchInput;
      const batch = inventory.batchLookup.get(batchId ?? "");
      const inputFileId = String(batch?.input_file_id ?? "");
      if (!inputFileId) {
        return;
      }
      await inspectFile(
        inputFileId,
        item instanceof HTMLButtonElement ? item : null,
      );
    });
  });

  app.pageContent
    .querySelectorAll<HTMLElement>("[data-batch-input-preview]")
    .forEach((item) => {
      item.addEventListener("click", async () => {
        const batchId = item.dataset.batchInputPreview;
        const batch = inventory.batchLookup.get(batchId ?? "");
        const inputFileId = String(batch?.input_file_id ?? "");
        if (!inputFileId) {
          return;
        }
        selection = {
          kind: "batch",
          batchId: String(batch?.id ?? ""),
          inputFileId: inputFileId || undefined,
          outputFileId: String(batch?.output_file_id ?? "") || undefined,
        };
        clearSelectionHandoff();
        syncSelectionRouteState(selection);
        updateInspectorActions();
        await previewFileContent(
          inputFileId,
          item instanceof HTMLButtonElement ? item : null,
          {
            label: "Batch input preview",
            support: `Batch ${String(batch?.id ?? "unknown")}`,
            relatedBatch: batch ?? null,
          },
        );
      });
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

  const routeState = readFilesBatchesRouteState(page);
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
      { label: "Next step", value: "Review format settings and validate batch input" },
    ]);
  } else {
    syncBatchComposerFormat(readBatchApiFormat());
    updateBatchValidationSurface();
    updateBatchCreateAvailability();
  }
  if (
    routeState.selectedBatchId &&
    inventory.batchLookup.has(routeState.selectedBatchId)
  ) {
    void inspectBatch(routeState.selectedBatchId, null);
    return;
  }
  if (
    routeState.selectedFileId &&
    inventory.fileLookup.has(routeState.selectedFileId)
  ) {
    void inspectFile(routeState.selectedFileId, null);
  }
}
