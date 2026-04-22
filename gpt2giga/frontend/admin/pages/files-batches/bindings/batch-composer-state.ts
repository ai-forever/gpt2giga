import type {
  ArtifactApiFormat,
  FileRecord,
  FileValidationSnapshot,
} from "../state.js";
import { isBatchValidationCandidate } from "../serializers.js";
import {
  ANTHROPIC_BATCH_ENDPOINT,
  buildStoredFileValidationSnapshot,
  formatApiFormatLabel,
  GEMINI_BATCH_ENDPOINT_TEMPLATE,
  normalizeGeminiBatchModel,
  OPENAI_BATCH_ENDPOINT_OPTIONS,
  type FilesBatchesBindingState,
  type InlineRequestsPayload,
} from "./helpers.js";

export interface BatchValidationRequestDraft {
  apiFormat: ArtifactApiFormat;
  endpoint: string;
  inputFileId?: string;
  model?: string;
  requests?: Array<Record<string, unknown>>;
  signature?: string;
  sourceLabel: string;
  sourceNote?: string;
  error?: string;
}

export function readBatchApiFormatValue(
  value: string | null | undefined,
): ArtifactApiFormat {
  const normalized = value?.trim();
  if (normalized === "anthropic" || normalized === "gemini") {
    return normalized;
  }
  return "openai";
}

export function readConfiguredFallbackModel(
  runtimeModel: string | null | undefined,
): string {
  return runtimeModel?.trim() || "gemini-2.5-flash";
}

export function resolveGeminiBatchEndpointValue(
  modelValue: string | null | undefined,
  fallbackModel: string,
): string {
  const normalizedModel = normalizeGeminiBatchModel(modelValue || fallbackModel);
  return GEMINI_BATCH_ENDPOINT_TEMPLATE.replace(
    "{model}",
    normalizedModel || "{model}",
  );
}

export function resolveBatchEndpointValue(options: {
  apiFormat: ArtifactApiFormat;
  selectedEndpoint: string | null | undefined;
  batchModel: string | null | undefined;
  fallbackModel: string;
}): string {
  const { apiFormat, selectedEndpoint, batchModel, fallbackModel } = options;
  if (apiFormat === "anthropic") {
    return ANTHROPIC_BATCH_ENDPOINT;
  }
  if (apiFormat === "gemini") {
    return resolveGeminiBatchEndpointValue(batchModel, fallbackModel);
  }
  return OPENAI_BATCH_ENDPOINT_OPTIONS.includes(
    (selectedEndpoint?.trim() ?? "") as (typeof OPENAI_BATCH_ENDPOINT_OPTIONS)[number],
  )
    ? selectedEndpoint?.trim() ?? "/v1/chat/completions"
    : "/v1/chat/completions";
}

export function getBatchFormatHint(apiFormat: ArtifactApiFormat): string {
  if (apiFormat === "anthropic") {
    return "Anthropic batches accept either a staged JSONL file shaped like `{custom_id, params}` per line or an inline JSON array shaped like `[{custom_id, params}]`. Provide a fallback model when rows omit `params.model`.";
  }
  if (apiFormat === "gemini") {
    return "Gemini batches accept either a staged JSONL file shaped like `{key, request}` per line or an inline JSON array shaped like `[{key?, request, metadata?}]`. Provide a fallback model when file rows omit `request.model`.";
  }
  return "OpenAI batches accept either a staged JSONL file in OpenAI batch input format or an inline JSON array shaped like `[{custom_id, method, url, body}]`. Provide a fallback model when rows omit `body.model`.";
}

export function buildBatchValidationRequest(options: {
  apiFormat: ArtifactApiFormat;
  endpoint: string;
  inputFileId: string | null | undefined;
  fallbackModel: string | null | undefined;
  inlinePayload: InlineRequestsPayload;
}): BatchValidationRequestDraft {
  const { apiFormat, endpoint, inputFileId, fallbackModel, inlinePayload } = options;
  const normalizedInputFileId = inputFileId?.trim() ?? "";
  const model = fallbackModel?.trim() || undefined;
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
      model,
      requests: inlineRequests,
      signature: JSON.stringify({
        apiFormat,
        endpoint,
        model: model ?? "",
        requests: inlineRequests,
      }),
      sourceLabel: `${inlineRequests.length} inline request${inlineRequests.length === 1 ? "" : "s"}`,
      sourceNote: normalizedInputFileId
        ? `Inline requests override staged file ${normalizedInputFileId} for validation and batch creation.`
        : "Inline requests are the active batch source.",
    };
  }

  if (normalizedInputFileId) {
    return {
      apiFormat,
      endpoint,
      inputFileId: normalizedInputFileId,
      model,
      signature: JSON.stringify({
        apiFormat,
        endpoint,
        inputFileId: normalizedInputFileId,
        model: model ?? "",
      }),
      sourceLabel: `Staged file ${normalizedInputFileId}`,
      sourceNote: "Validation reads the staged JSONL file through the admin API.",
    };
  }

  return {
    apiFormat,
    endpoint,
    sourceLabel: "No active input",
    error: `${formatApiFormatLabel(apiFormat)} batches need a staged input file id or inline requests before validation.`,
  };
}

export function resolveComposerDisplayName(options: {
  apiFormat: ArtifactApiFormat;
  currentValue: string | null | undefined;
  inputFileId: string | null | undefined;
}): string {
  if (options.apiFormat !== "gemini") {
    return "";
  }
  const currentValue = options.currentValue?.trim() ?? "";
  if (currentValue) {
    return currentValue;
  }
  const inputFileId = options.inputFileId?.trim() ?? "";
  return inputFileId ? `gemini-${inputFileId}` : "gemini-batch";
}

export function resolveDisplayedFileValidationSnapshot(options: {
  fileId: string;
  source?: FileRecord;
  currentRequest: BatchValidationRequestDraft;
  state: Pick<
    FilesBatchesBindingState,
    | "validationReport"
    | "validationDirty"
    | "validationSignature"
    | "validationValidatedAt"
  >;
}): FileValidationSnapshot | null {
  const { fileId, source, currentRequest, state } = options;
  if (!isBatchValidationCandidate(source)) {
    return source?.validation ?? null;
  }

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
}
