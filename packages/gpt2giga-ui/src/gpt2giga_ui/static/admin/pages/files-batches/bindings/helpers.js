import { banner, pill, renderDefinitionList } from "../../../templates.js";
import { escapeHtml, formatNumber, formatTimestamp, safeJsonParse } from "../../../utils.js";
import { INVALID_JSON } from "../state.js";
export const OPENAI_BATCH_ENDPOINT_OPTIONS = [
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/embeddings",
];
export const ANTHROPIC_BATCH_ENDPOINT = "/v1/messages";
export const GEMINI_BATCH_ENDPOINT_TEMPLATE = "/v1beta/models/{model}:generateContent";
export const BATCH_PREVIEW_BYTES = 256 * 1024;
export function createFilesBatchesBindingState() {
    return {
        selection: { kind: "idle" },
        previewObjectUrl: null,
        lastInlineRequestsTemplate: "",
        validationReport: null,
        validationSignature: null,
        validationValidatedAt: null,
        validationDirty: false,
        validationInFlight: false,
        validationMessage: null,
        validationRefreshTimer: null,
        validationRunId: 0,
        uploadValidationReport: null,
        uploadValidationMessage: null,
        uploadValidationInFlight: false,
        uploadValidationSignature: null,
        uploadValidationValidatedAt: null,
    };
}
export function setDefinitionBlock(node, items, emptyMessage) {
    node.innerHTML = renderDefinitionList(items, emptyMessage);
}
export function formatApiFormatLabel(apiFormat) {
    if (apiFormat === "anthropic") {
        return "Anthropic";
    }
    if (apiFormat === "gemini") {
        return "Gemini";
    }
    return "OpenAI";
}
export function normalizeGeminiBatchModel(value) {
    let normalized = value?.trim() ?? "";
    if (!normalized) {
        return "";
    }
    try {
        const parsed = new URL(normalized);
        normalized = parsed.pathname.trim();
    }
    catch {
        // Keep non-URL forms untouched.
    }
    normalized = normalized.replace(/^\/+|\/+$/g, "");
    if (normalized.includes("/models/")) {
        normalized = normalized.split("/models/").at(-1) ?? normalized;
    }
    else if (normalized.startsWith("models/")) {
        normalized = normalized.slice("models/".length);
    }
    if (normalized.includes(":")) {
        normalized = normalized.split(":", 1)[0] ?? normalized;
    }
    return normalized.trim();
}
export function readInlineRequestsPayload(rawValue) {
    const inlineRequestsText = rawValue.trim();
    if (!inlineRequestsText) {
        return { provided: false };
    }
    const parsed = safeJsonParse(inlineRequestsText, INVALID_JSON);
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
}
export function buildStoredFileValidationSnapshot(report, validatedAt) {
    return {
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
    };
}
export function resolveValidationStatus(state) {
    if (state.validationInFlight) {
        return { label: "Validating", tone: "default" };
    }
    if (state.validationDirty) {
        return { label: "Stale report", tone: "warn" };
    }
    if (!state.validationReport) {
        return { label: "Not validated", tone: "default" };
    }
    if (!state.validationReport.valid) {
        return { label: "Invalid", tone: "warn" };
    }
    if (state.validationReport.summary.warning_count > 0) {
        return { label: "Valid with warnings", tone: "warn" };
    }
    return { label: "Valid", tone: "good" };
}
export function renderValidationIssueRows(issues) {
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
        const severityLabel = issue.severity.charAt(0).toUpperCase() + issue.severity.slice(1);
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
                      ${issue.hint
            ? `<span class="muted">Hint: ${escapeHtml(issue.hint)}</span>`
            : ""}
                      <span class="muted">Code: ${escapeHtml(issue.code)}</span>
                      ${issue.raw_excerpt
            ? `<pre class="batch-validation__excerpt">${escapeHtml(issue.raw_excerpt)}</pre>`
            : ""}
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
}
export function buildBatchInlineRequestsTemplate(options) {
    const { apiFormat, fallbackModel, endpoint } = options;
    if (apiFormat === "anthropic") {
        return JSON.stringify([
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
        ], null, 2);
    }
    if (apiFormat === "gemini") {
        const requestModel = fallbackModel.startsWith("models/")
            ? fallbackModel
            : `models/${fallbackModel}`;
        return JSON.stringify([
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
        ], null, 2);
    }
    if (endpoint === "/v1/embeddings") {
        return JSON.stringify([
            {
                custom_id: "openai-row-1",
                method: "POST",
                url: "/v1/embeddings",
                body: {
                    model: fallbackModel,
                    input: "hello openai",
                },
            },
        ], null, 2);
    }
    if (endpoint === "/v1/responses") {
        return JSON.stringify([
            {
                custom_id: "openai-row-1",
                method: "POST",
                url: "/v1/responses",
                body: {
                    model: fallbackModel,
                    input: "hello openai",
                },
            },
        ], null, 2);
    }
    return JSON.stringify([
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
    ], null, 2);
}
export function buildUploadValidationMarkup(options) {
    const { report, message, inFlight, validatedAt, purpose, selectedFileLabel } = options;
    const isBatchPurpose = purpose === "batch";
    const statusLabel = inFlight
        ? "Validating"
        : report
            ? report.valid
                ? "Batch valid"
                : "Batch invalid"
            : isBatchPurpose
                ? "Not validated"
                : "Unavailable";
    const statusTone = inFlight
        ? "default"
        : report
            ? report.valid
                ? "good"
                : "warn"
            : isBatchPurpose
                ? "default"
                : "warn";
    const metaPills = [pill(statusLabel, statusTone)];
    if (report) {
        metaPills.push(pill(`${formatNumber(report.summary.total_rows)} rows`));
        metaPills.push(pill(`${formatNumber(report.summary.error_count)} errors`));
        metaPills.push(pill(`${formatNumber(report.summary.warning_count)} warnings`));
    }
    let statusBanner = "";
    if (!isBatchPurpose) {
        statusBanner = banner("Select purpose `batch` to validate the chosen file as batch input.", "warn");
    }
    else if (message) {
        statusBanner = banner(message, "danger");
    }
    else if (inFlight) {
        statusBanner = banner("Validating the selected file without uploading it.", "info");
    }
    else if (report?.valid) {
        statusBanner = banner("Batch valid.", "info");
    }
    else if (report) {
        statusBanner = banner("Batch invalid.", "danger");
    }
    else {
        statusBanner = banner("Choose a file and run Validate to check whether the batch is valid.", "info");
    }
    const summaryItems = [
        { label: "Status", value: statusLabel },
        { label: "Purpose", value: purpose || "n/a" },
        { label: "Selected file", value: selectedFileLabel },
        {
            label: "Result",
            value: report
                ? report.valid
                    ? "Batch valid"
                    : "Batch invalid"
                : isBatchPurpose
                    ? "Awaiting validation"
                    : "Validation disabled",
            note: validatedAt
                ? `Validated at ${formatTimestamp(validatedAt)}.`
                : "Validation reads the selected local file without staging it.",
        },
    ];
    return `
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
        <span class="muted">${report ? `${formatNumber(report.issues.length)} reported` : "No issues to show yet."}</span>
      </div>
      ${report
        ? renderValidationIssueRows(report.issues)
        : '<p class="muted">Validation details appear here after you run Validate.</p>'}
    </div>
  `;
}
export function buildBatchValidationMarkup(options) {
    const { state, selectedFormatLabel, detectedFormatLabel, detectedFormatNote, inputSourceLabel, inputSourceNote, lastValidationLabel, lastValidationNote, endpointLabel, } = options;
    const status = resolveValidationStatus(state);
    const summaryItems = [
        { label: "Status", value: status.label },
        { label: "Selected format", value: selectedFormatLabel },
        {
            label: "Detected format",
            value: detectedFormatLabel,
            note: detectedFormatNote,
        },
        {
            label: "Input source",
            value: inputSourceLabel,
            note: inputSourceNote,
        },
        {
            label: "Last validation",
            value: lastValidationLabel,
            note: lastValidationNote,
        },
    ];
    if (endpointLabel) {
        summaryItems.push({
            label: "Endpoint target",
            value: endpointLabel,
        });
    }
    const metaPills = [pill(status.label, status.tone)];
    if (state.validationReport && !state.validationDirty) {
        metaPills.push(pill(`${formatNumber(state.validationReport.summary.total_rows)} rows`));
        metaPills.push(pill(`${formatNumber(state.validationReport.summary.error_count)} errors`));
        metaPills.push(pill(`${formatNumber(state.validationReport.summary.warning_count)} warnings`));
    }
    let reportBanner = "";
    if (state.validationMessage) {
        reportBanner = banner(state.validationMessage, state.validationMessage.includes("JSON array") ? "danger" : "warn");
    }
    else if (state.validationInFlight) {
        reportBanner = banner("Validation is running for the current composer input.", "info");
    }
    else if (state.validationDirty) {
        reportBanner = banner("The last validation report is stale. Re-run validation before creating the batch.", "warn");
    }
    else if (state.validationReport && !state.validationReport.valid) {
        reportBanner = banner("Validation found blocking errors. Fix them or change the selected format before creating the batch.", "danger");
    }
    else if (state.validationReport &&
        state.validationReport.summary.warning_count > 0) {
        reportBanner = banner("Validation passed with warnings. Batch creation stays enabled.", "warn");
    }
    else if (state.validationReport) {
        reportBanner = banner("Validation passed with no blocking issues.", "info");
    }
    else {
        reportBanner = banner("Run Validate file to get row-level diagnostics before queueing the batch.", "info");
    }
    return `
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
        <span class="muted">${state.validationReport && !state.validationDirty
        ? `${formatNumber(state.validationReport.issues.length)} reported`
        : state.validationReport && state.validationDirty
            ? "Showing the previous report until validation is re-run."
            : "No issues to show yet."}</span>
      </div>
      ${state.validationReport
        ? renderValidationIssueRows(state.validationReport.issues)
        : '<p class="muted">Validate the current composer input to populate the issue list.</p>'}
    </div>
  `;
}
export function encodeBytesToBase64(bytes) {
    let binary = "";
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
        const chunk = bytes.subarray(index, index + chunkSize);
        binary += String.fromCharCode(...chunk);
    }
    return btoa(binary);
}
