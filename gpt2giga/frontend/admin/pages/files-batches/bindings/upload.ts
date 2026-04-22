import type { AdminApp } from "../../../app.js";
import { withBusyState } from "../../../forms.js";
import type { FilesBatchesPageData } from "../api.js";
import { uploadFile, validateBatchInput } from "../api.js";
import type {
  ArtifactApiFormat,
  DefinitionItem,
  FileRecord,
  FilesBatchesPage,
} from "../state.js";
import type { FilesBatchesPageElements } from "../view.js";
import {
  buildStoredFileValidationSnapshot,
  buildUploadValidationMarkup,
  encodeBytesToBase64,
  formatApiFormatLabel,
  type FilesBatchesBindingState,
  type WorkflowActionRunner,
} from "./helpers.js";

interface UploadBindingsDeps {
  app: AdminApp;
  data: FilesBatchesPageData;
  elements: FilesBatchesPageElements;
  page: FilesBatchesPage;
  state: FilesBatchesBindingState;
  cacheFileRecord: (payload: FileRecord) => FileRecord;
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

export interface UploadBindings {
  initialize(): void;
  readUploadApiFormat(): ArtifactApiFormat;
}

export function createUploadBindings(deps: UploadBindingsDeps): UploadBindings {
  const {
    app,
    data,
    elements,
    page,
    state,
    cacheFileRecord,
    replaceStateForPage,
    runWorkflowAction,
    setWorkflowSummary,
  } = deps;

  const readUploadSelectedFile = (): File | null =>
    elements.uploadForm
      ?.querySelector<HTMLInputElement>('input[name="file"]')
      ?.files?.[0] ?? null;

  const readUploadApiFormat = (): ArtifactApiFormat => {
    const normalized = elements.uploadApiFormat?.value.trim();
    if (normalized === "anthropic" || normalized === "gemini") {
      return normalized;
    }
    return "openai";
  };

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
    state.uploadValidationReport = null;
    state.uploadValidationMessage = null;
    state.uploadValidationSignature = null;
    state.uploadValidationValidatedAt = null;
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

  const updateUploadValidationSurface = (): void => {
    if (!elements.uploadValidationNode) {
      return;
    }

    const selectedFileLabel = readUploadSelectedFile()?.name ?? "No file chosen";
    elements.uploadValidationNode.innerHTML = buildUploadValidationMarkup({
      report: state.uploadValidationReport,
      message: state.uploadValidationMessage,
      inFlight: state.uploadValidationInFlight,
      validatedAt: state.uploadValidationValidatedAt,
      purpose: elements.uploadPurpose?.value ?? "",
      selectedFileLabel,
    });
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

  const bindUploadSubmit = (): void => {
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
          { label: "Source", value: upload.name, note: `${upload.size} bytes` },
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
            state.uploadValidationReport !== null &&
            state.uploadValidationSignature !== null &&
            state.uploadValidationSignature === buildUploadValidationSignature();
          const mergedResponse =
            validatedThisSelection && state.uploadValidationReport
              ? {
                  ...response,
                  validation: buildStoredFileValidationSnapshot(
                    state.uploadValidationReport,
                    state.uploadValidationValidatedAt,
                  ),
                }
              : response;
          cacheFileRecord(mergedResponse);
          data.files = data.files;
          app.queueAlert(`Uploaded file ${String(response.id ?? "")}.`, "info");
          replaceStateForPage(page, {
            selectedFileId: String(response.id ?? ""),
          });
          await app.render(page);
          return mergedResponse;
        },
      });
    });
  };

  const bindUploadValidation = (): void => {
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
        state.uploadValidationMessage =
          "Validation is available only when purpose is batch.";
        updateUploadValidateAvailability();
        updateUploadValidationSurface();
        app.pushAlert(state.uploadValidationMessage, "warn");
        return;
      }
      if (!upload) {
        state.uploadValidationMessage = "Choose a file before validation.";
        updateUploadValidationSurface();
        app.pushAlert(state.uploadValidationMessage, "warn");
        return;
      }

      state.uploadValidationMessage = null;
      state.uploadValidationReport = null;
      state.uploadValidationSignature = buildUploadValidationSignature();
      state.uploadValidationValidatedAt = null;
      state.uploadValidationInFlight = true;
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
        state.uploadValidationReport = report;
        state.uploadValidationValidatedAt = Math.floor(Date.now() / 1000);
        updateUploadValidationSurface();
        setWorkflowSummary([
          { label: "Workflow state", value: "Batch validated" },
          { label: "API format", value: formatApiFormatLabel(report.api_format) },
          {
            label: "Result",
            value: report.valid ? "Batch valid" : "Batch invalid",
            note: `${report.summary.error_count} errors · ${report.summary.warning_count} warnings`,
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
        state.uploadValidationMessage = message;
        updateUploadValidationSurface();
        app.pushAlert(state.uploadValidationMessage, "danger");
      } finally {
        state.uploadValidationInFlight = false;
        updateUploadValidateAvailability();
        updateUploadValidationSurface();
      }
    });
  };

  return {
    initialize(): void {
      syncUploadComposerFormat(readUploadApiFormat());
      updateUploadValidateAvailability();
      updateUploadValidationSurface();
      bindUploadSubmit();
      bindUploadValidation();
    },
    readUploadApiFormat,
  };
}
