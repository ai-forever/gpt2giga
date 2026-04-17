import type { DiffEntry, PendingChangeSummary } from "./types.js";
import { normalizeComparableValue, parseCsv, safeJsonParse } from "./utils.js";

export const INVALID_JSON = "__invalid__";
const FORM_CONTROL_SELECTOR = "button, input, select, textarea";
const RESTART_SENSITIVE_FIELDS = new Set([
  "mode",
  "enabled_providers",
  "runtime_store_backend",
  "runtime_store_dsn",
  "runtime_store_namespace",
  "pass_token",
  "enable_api_key_auth",
  "cors_allow_origins",
  "cors_allow_methods",
  "cors_allow_headers",
  "log_level",
  "log_filename",
  "log_max_size",
]);
const SECRET_FIELDS = new Set([
  "credentials",
  "access_token",
  "api_key",
  "scoped_api_keys",
  "password",
  "key_file_password",
  "otlp_headers",
  "langfuse_public_key",
  "langfuse_secret_key",
  "phoenix_api_key",
]);

type FormControlElement =
  | HTMLButtonElement
  | HTMLInputElement
  | HTMLSelectElement
  | HTMLTextAreaElement;

interface ValidationOptions {
  report?: boolean;
}

interface SecretFieldBindingOptions {
  form: HTMLFormElement;
  fieldName: string;
  clearFieldName: string;
  preview: string;
}

interface ReplaceableFieldBindingOptions extends SecretFieldBindingOptions {
  clearPlaceholder: string;
  noteReplace: string;
  noteClear: string;
  noteKeep: string;
  messageReplace: string;
  messageClear: string;
  messageKeep: string;
}

export interface SecretFieldState {
  intent: "keep" | "replace" | "clear";
  message: string;
}

export interface PlannedApplyState {
  effectiveSummary: PendingChangeSummary;
  blockedLiveFields: string[];
}

export interface RuntimeImpactDescriptor {
  label: string;
  tone: "good" | "warn";
  detail: string;
}

export interface PersistOutcomeDescriptor {
  message: string;
  tone: "info" | "warn";
}

export function buildApplicationPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    mode: HTMLSelectElement;
    gigachat_api_mode: HTMLSelectElement;
    gigachat_responses_api_mode?: HTMLSelectElement;
    enabled_providers: HTMLInputElement;
    embeddings?: HTMLInputElement;
    enable_telemetry?: HTMLSelectElement;
    pass_model: HTMLSelectElement;
    pass_token: HTMLSelectElement;
    enable_reasoning?: HTMLSelectElement;
    observability_sinks?: HTMLInputElement;
    log_level?: HTMLSelectElement;
    runtime_store_backend?: HTMLSelectElement;
    runtime_store_namespace?: HTMLInputElement;
  };

  const payload: Record<string, unknown> = {
    mode: fields.mode.value,
    gigachat_api_mode: fields.gigachat_api_mode.value,
    enabled_providers: parseCsv(fields.enabled_providers.value),
    pass_model: fields.pass_model.value === "true",
    pass_token: fields.pass_token.value === "true",
  };

  if (fields.enable_telemetry) {
    payload.enable_telemetry = fields.enable_telemetry.value === "true";
  }
  if (fields.gigachat_responses_api_mode) {
    payload.gigachat_responses_api_mode =
      fields.gigachat_responses_api_mode.value || null;
  }
  if (fields.observability_sinks) {
    payload.observability_sinks = parseCsv(fields.observability_sinks.value);
  }

  if (fields.embeddings) {
    payload.embeddings = fields.embeddings.value.trim();
  }
  if (fields.enable_reasoning) {
    payload.enable_reasoning = fields.enable_reasoning.value === "true";
  }
  if (fields.log_level) {
    payload.log_level = fields.log_level.value;
  }
  if (fields.runtime_store_backend) {
    payload.runtime_store_backend = fields.runtime_store_backend.value;
  }
  if (fields.runtime_store_namespace) {
    payload.runtime_store_namespace = fields.runtime_store_namespace.value.trim();
  }

  return payload;
}

export function buildSecurityPayload(
  form: HTMLFormElement,
): Record<string, unknown> & { governance_limits?: unknown } {
  const fields = form.elements as typeof form.elements & {
    enable_api_key_auth: HTMLSelectElement;
    logs_ip_allowlist: HTMLInputElement;
    cors_allow_origins: HTMLInputElement;
    governance_limits?: HTMLTextAreaElement;
  };

  const payload: Record<string, unknown> & { governance_limits?: unknown } = {
    enable_api_key_auth: fields.enable_api_key_auth.value === "true",
    logs_ip_allowlist: parseCsv(fields.logs_ip_allowlist.value),
    cors_allow_origins: parseCsv(fields.cors_allow_origins.value),
  };

  if (fields.governance_limits) {
    payload.governance_limits = safeJsonParse(
      fields.governance_limits.value || "[]",
      INVALID_JSON,
    );
  }

  return payload;
}

export function buildObservabilityPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    enable_telemetry: HTMLSelectElement;
    sink_prometheus: HTMLInputElement;
    sink_otlp: HTMLInputElement;
    sink_langfuse: HTMLInputElement;
    sink_phoenix: HTMLInputElement;
    otlp_traces_endpoint: HTMLInputElement;
    otlp_service_name: HTMLInputElement;
    otlp_timeout_seconds: HTMLInputElement;
    otlp_max_pending_requests: HTMLInputElement;
    otlp_headers: HTMLTextAreaElement;
    otlp_clear_headers?: HTMLInputElement;
    langfuse_base_url: HTMLInputElement;
    langfuse_public_key: HTMLTextAreaElement;
    langfuse_clear_public_key?: HTMLInputElement;
    langfuse_secret_key: HTMLTextAreaElement;
    langfuse_clear_secret_key?: HTMLInputElement;
    phoenix_base_url: HTMLInputElement;
    phoenix_project_name: HTMLInputElement;
    phoenix_api_key: HTMLTextAreaElement;
    phoenix_clear_api_key?: HTMLInputElement;
  };

  const payload: Record<string, unknown> = {
    enable_telemetry: fields.enable_telemetry.value === "true",
    active_sinks: [
      fields.sink_prometheus.checked ? "prometheus" : null,
      fields.sink_otlp.checked ? "otlp" : null,
      fields.sink_langfuse.checked ? "langfuse" : null,
      fields.sink_phoenix.checked ? "phoenix" : null,
    ].filter((value): value is string => Boolean(value)),
    otlp: {
      traces_endpoint: trimToNull(fields.otlp_traces_endpoint.value),
      service_name: trimToNull(fields.otlp_service_name.value),
      timeout_seconds: parseOptionalNumber(fields.otlp_timeout_seconds.value),
      max_pending_requests: parseOptionalNumber(
        fields.otlp_max_pending_requests.value,
      ),
    },
    langfuse: {
      base_url: trimToNull(fields.langfuse_base_url.value),
    },
    phoenix: {
      base_url: trimToNull(fields.phoenix_base_url.value),
      project_name: trimToNull(fields.phoenix_project_name.value),
    },
  };

  const otlpPayload = payload.otlp as Record<string, unknown>;
  const otlpHeaders = parseOptionalJsonObject(fields.otlp_headers.value);
  if (otlpHeaders !== null) {
    otlpPayload.headers = otlpHeaders;
  } else if (fields.otlp_clear_headers?.checked) {
    otlpPayload.headers = null;
  }

  const langfusePayload = payload.langfuse as Record<string, unknown>;
  const langfusePublicKey = fields.langfuse_public_key.value.trim();
  if (langfusePublicKey) {
    langfusePayload.public_key = langfusePublicKey;
  } else if (fields.langfuse_clear_public_key?.checked) {
    langfusePayload.public_key = null;
  }
  const langfuseSecretKey = fields.langfuse_secret_key.value.trim();
  if (langfuseSecretKey) {
    langfusePayload.secret_key = langfuseSecretKey;
  } else if (fields.langfuse_clear_secret_key?.checked) {
    langfusePayload.secret_key = null;
  }

  const phoenixPayload = payload.phoenix as Record<string, unknown>;
  const phoenixApiKey = fields.phoenix_api_key.value.trim();
  if (phoenixApiKey) {
    phoenixPayload.api_key = phoenixApiKey;
  } else if (fields.phoenix_clear_api_key?.checked) {
    phoenixPayload.api_key = null;
  }

  return payload;
}

export function bindValidityReset(
  ...fields: Array<FormControlElement | null | undefined>
): void {
  fields.forEach((field) => {
    if (!field) {
      return;
    }
    const resetValidity = () => {
      field.setCustomValidity("");
    };
    field.addEventListener("input", resetValidity);
    field.addEventListener("change", resetValidity);
  });
}

export function validateRequiredCsvField(
  field: HTMLInputElement | null | undefined,
  message: string,
  options?: ValidationOptions,
): string {
  if (!field) {
    return "";
  }
  const error = parseCsv(field.value).length > 0 ? "" : message;
  field.setCustomValidity(error);
  if (error && options?.report) {
    field.reportValidity();
  }
  return error;
}

export function validatePositiveNumberField(
  field: HTMLInputElement | null | undefined,
  message: string,
  options?: ValidationOptions,
): string {
  if (!field) {
    return "";
  }
  const rawValue = field.value.trim();
  let error = "";
  if (rawValue) {
    const numeric = Number(rawValue);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      error = message;
    }
  }
  field.setCustomValidity(error);
  if (error && options?.report) {
    field.reportValidity();
  }
  return error;
}

export function validateJsonArrayField(
  field: HTMLTextAreaElement | null | undefined,
  value: unknown,
  {
    invalidMessage,
    nonArrayMessage,
    report,
  }: {
    invalidMessage: string;
    nonArrayMessage: string;
    report?: boolean;
  },
): string {
  if (!field) {
    return "";
  }
  const error =
    value === INVALID_JSON
      ? invalidMessage
      : !Array.isArray(value)
        ? nonArrayMessage
        : "";
  field.setCustomValidity(error);
  if (error && report) {
    field.reportValidity();
  }
  return error;
}

export function validateJsonObjectField(
  field: HTMLTextAreaElement | null | undefined,
  value: unknown,
  {
    invalidMessage,
    nonObjectMessage,
    report,
  }: {
    invalidMessage: string;
    nonObjectMessage: string;
    report?: boolean;
  },
): string {
  if (!field) {
    return "";
  }
  const error =
    value === INVALID_JSON
      ? invalidMessage
      : value !== null &&
          (!value || typeof value !== "object" || Array.isArray(value))
        ? nonObjectMessage
        : "";
  field.setCustomValidity(error);
  if (error && report) {
    field.reportValidity();
  }
  return error;
}

export function bindReplaceableFieldBehavior(
  options: ReplaceableFieldBindingOptions,
): () => SecretFieldState | null {
  const textarea = options.form.elements.namedItem(options.fieldName);
  const clearToggle = options.form.elements.namedItem(options.clearFieldName);
  if (!(textarea instanceof HTMLTextAreaElement) || !(clearToggle instanceof HTMLInputElement)) {
    return () => null;
  }

  const note = textarea.closest(".stack")?.querySelector<HTMLElement>(".field-note");
  const originalPlaceholder = textarea.placeholder;
  const preview = options.preview || "not configured";

  const sync = (): SecretFieldState => {
    const hasValue = textarea.value.trim().length > 0;
    if (hasValue) {
      clearToggle.checked = false;
      clearToggle.disabled = true;
      textarea.disabled = false;
      textarea.placeholder = originalPlaceholder;
      if (note) {
        note.textContent = `Stored: ${preview}. Save: ${options.noteReplace}`;
      }
      return {
        intent: "replace",
        message: options.messageReplace,
      };
    }

    clearToggle.disabled = false;
    if (clearToggle.checked) {
      textarea.disabled = true;
      textarea.placeholder = options.clearPlaceholder;
      if (note) {
        note.textContent = `Stored: ${preview}. Save: ${options.noteClear}`;
      }
      return {
        intent: "clear",
        message: options.messageClear,
      };
    }

    textarea.disabled = false;
    textarea.placeholder = originalPlaceholder;
    if (note) {
      note.textContent = `Stored: ${preview}. Save: ${options.noteKeep}`;
    }
    return {
      intent: "keep",
      message: options.messageKeep,
    };
  };

  textarea.addEventListener("input", sync);
  clearToggle.addEventListener("change", sync);
  return sync;
}

export function bindSecretFieldBehavior(
  options: SecretFieldBindingOptions,
): () => SecretFieldState | null {
  return bindReplaceableFieldBehavior({
    ...options,
    clearPlaceholder: "Uncheck clear to paste a replacement secret",
    noteReplace: "replace it.",
    noteClear: "clear it.",
    noteKeep: "keep it.",
    messageReplace: "A new secret is staged and will replace the stored value on save.",
    messageClear: "The stored secret will be removed when this section is saved.",
    messageKeep: "The stored secret remains unchanged unless you paste a replacement.",
  });
}

export async function withBusyState<T>({
  root,
  button,
  pendingLabel,
  action,
}: {
  root?: Element | DocumentFragment | null;
  button?: HTMLButtonElement | null;
  pendingLabel: string;
  action: () => Promise<T>;
}): Promise<T> {
  const controls = root
    ? Array.from(root.querySelectorAll<FormControlElement>(FORM_CONTROL_SELECTOR))
    : button
      ? [button]
      : [];
  const controlStates = controls.map((control) => ({
    control,
    disabled: control.disabled,
  }));
  const originalLabel = button?.textContent ?? "";
  const busyRoot = root instanceof HTMLElement ? root : null;

  controlStates.forEach(({ control }) => {
    control.disabled = true;
  });
  if (busyRoot) {
    busyRoot.setAttribute("data-busy", "true");
    busyRoot.setAttribute("aria-busy", "true");
  }
  if (button) {
    button.textContent = pendingLabel;
    button.setAttribute("aria-busy", "true");
  }

  try {
    return await action();
  } finally {
    controlStates.forEach(({ control, disabled }) => {
      control.disabled = disabled;
    });
    if (busyRoot) {
      busyRoot.removeAttribute("data-busy");
      busyRoot.removeAttribute("aria-busy");
    }
    if (button) {
      button.textContent = originalLabel;
      button.removeAttribute("aria-busy");
    }
  }
}

export function collectGigachatPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    model: HTMLInputElement;
    scope: HTMLInputElement;
    base_url: HTMLInputElement;
    auth_url: HTMLInputElement;
    ca_bundle_file: HTMLInputElement;
    credentials: HTMLTextAreaElement;
    access_token: HTMLTextAreaElement;
    clear_credentials?: HTMLInputElement;
    clear_access_token?: HTMLInputElement;
    verify_ssl_certs: HTMLSelectElement;
    timeout?: HTMLInputElement;
  };

  const payload: Record<string, unknown> = {
    model: fields.model.value.trim() || null,
    scope: fields.scope.value.trim() || null,
    base_url: fields.base_url.value.trim() || null,
    auth_url: fields.auth_url.value.trim() || null,
    ca_bundle_file: fields.ca_bundle_file.value.trim() || null,
    verify_ssl_certs: fields.verify_ssl_certs.value === "true",
    timeout: fields.timeout && fields.timeout.value ? Number(fields.timeout.value) : null,
  };

  const credentials = fields.credentials.value.trim();
  if (credentials) {
    payload.credentials = credentials;
  } else if (fields.clear_credentials?.checked) {
    payload.credentials = null;
  }

  const accessToken = fields.access_token.value.trim();
  if (accessToken) {
    payload.access_token = accessToken;
  } else if (fields.clear_access_token?.checked) {
    payload.access_token = null;
  }

  return payload;
}

export function planPendingApply(summary: PendingChangeSummary): PlannedApplyState {
  if (summary.restartFields.length === 0) {
    return {
      effectiveSummary: summary,
      blockedLiveFields: [],
    };
  }

  return {
    effectiveSummary: {
      ...summary,
      liveFields: [],
    },
    blockedLiveFields: [...summary.liveFields],
  };
}

export function describePendingRuntimeImpact(plan: PlannedApplyState): RuntimeImpactDescriptor {
  if (plan.effectiveSummary.changedFields.length === 0) {
    return {
      label: "Runtime matches persisted target",
      tone: "good",
      detail: "The current form matches the saved control-plane state.",
    };
  }
  if (plan.effectiveSummary.restartFields.length > 0) {
    return {
      label: "Runtime keeps current config until restart",
      tone: "warn",
      detail:
        "This save batch includes restart-sensitive fields, so the persisted target updates now but the running process keeps the previous runtime config until restart.",
    };
  }
  return {
    label: "Runtime updates immediately after save",
    tone: "good",
    detail: "This change set can be persisted and reloaded without restarting the process.",
  };
}

export function describePersistOutcome(
  sectionLabel: string,
  response: Record<string, unknown>,
): PersistOutcomeDescriptor {
  if (response.restart_required) {
    return {
      message: `${sectionLabel} saved. Persisted target updated, but the running process keeps the previous runtime config until restart.`,
      tone: "warn",
    };
  }
  if (response.applied_runtime) {
    return {
      message: `${sectionLabel} saved and applied to the running process.`,
      tone: "info",
    };
  }
  return {
    message: `${sectionLabel} saved.`,
    tone: "info",
  };
}

export function buildPendingDiffEntries(
  section: "application" | "gigachat" | "security",
  currentValues: Record<string, unknown>,
  payload: Record<string, unknown>,
): DiffEntry[] {
  return Object.entries(payload)
    .filter(([, value]) => value !== INVALID_JSON)
    .flatMap(([field, originalTarget]) => {
      let current = currentValues[field];
      let target = originalTarget;

      if (section === "gigachat" && field === "credentials") {
        current = currentValues.credentials_configured
          ? currentValues.credentials_preview || "configured"
          : "not configured";
        target = target ? "updated secret" : "clear secret";
      } else if (section === "gigachat" && field === "access_token") {
        current = currentValues.access_token_configured
          ? currentValues.access_token_preview || "configured"
          : "not configured";
        target = target ? "updated secret" : "clear secret";
      }

      if (
        JSON.stringify(normalizeComparableValue(current)) ===
        JSON.stringify(normalizeComparableValue(target))
      ) {
        return [];
      }

      return [{ field, current, target }];
    });
}

export function buildObservabilityDiffEntries(
  currentValues: Record<string, unknown>,
  payload: Record<string, unknown>,
): DiffEntry[] {
  const entries: DiffEntry[] = [];
  const otlpCurrent = asComparableRecord(currentValues.otlp);
  const langfuseCurrent = asComparableRecord(currentValues.langfuse);
  const phoenixCurrent = asComparableRecord(currentValues.phoenix);
  const otlpTarget = asComparableRecord(payload.otlp);
  const langfuseTarget = asComparableRecord(payload.langfuse);
  const phoenixTarget = asComparableRecord(payload.phoenix);

  pushDiffEntry(entries, "enable_telemetry", currentValues.enable_telemetry, payload.enable_telemetry);
  pushDiffEntry(entries, "active_sinks", currentValues.active_sinks, payload.active_sinks);
  pushDiffEntry(entries, "otlp_traces_endpoint", otlpCurrent.traces_endpoint, otlpTarget.traces_endpoint);
  pushDiffEntry(entries, "otlp_service_name", otlpCurrent.service_name, otlpTarget.service_name);
  pushDiffEntry(entries, "otlp_timeout_seconds", otlpCurrent.timeout_seconds, otlpTarget.timeout_seconds);
  pushDiffEntry(
    entries,
    "otlp_max_pending_requests",
    otlpCurrent.max_pending_requests,
    otlpTarget.max_pending_requests,
  );
  pushReplaceableDiffEntry(entries, {
    field: "otlp_headers",
    configured: Boolean(otlpCurrent.headers_configured),
    preview:
      Array.isArray(otlpCurrent.header_names) && otlpCurrent.header_names.length > 0
        ? `configured (${otlpCurrent.header_names.join(", ")})`
        : "configured",
    target: otlpTarget.headers,
    replaceLabel: buildHeaderTargetLabel(otlpTarget.headers),
  });

  pushDiffEntry(entries, "langfuse_base_url", langfuseCurrent.base_url, langfuseTarget.base_url);
  pushReplaceableDiffEntry(entries, {
    field: "langfuse_public_key",
    configured: Boolean(langfuseCurrent.public_key_configured),
    preview: langfuseCurrent.public_key_preview,
    target: langfuseTarget.public_key,
    replaceLabel: "updated secret",
  });
  pushReplaceableDiffEntry(entries, {
    field: "langfuse_secret_key",
    configured: Boolean(langfuseCurrent.secret_key_configured),
    preview: langfuseCurrent.secret_key_preview,
    target: langfuseTarget.secret_key,
    replaceLabel: "updated secret",
  });

  pushDiffEntry(entries, "phoenix_base_url", phoenixCurrent.base_url, phoenixTarget.base_url);
  pushDiffEntry(
    entries,
    "phoenix_project_name",
    phoenixCurrent.project_name,
    phoenixTarget.project_name,
  );
  pushReplaceableDiffEntry(entries, {
    field: "phoenix_api_key",
    configured: Boolean(phoenixCurrent.api_key_configured),
    preview: phoenixCurrent.api_key_preview,
    target: phoenixTarget.api_key,
    replaceLabel: "updated secret",
  });

  return entries;
}

export function summarizePendingChanges(entries: DiffEntry[]): PendingChangeSummary {
  const changedFields = entries.map((entry) => entry.field);
  return {
    changedFields,
    restartFields: changedFields.filter((field) => RESTART_SENSITIVE_FIELDS.has(field)),
    liveFields: changedFields.filter((field) => !RESTART_SENSITIVE_FIELDS.has(field)),
    secretFields: changedFields.filter((field) => SECRET_FIELDS.has(field)),
  };
}

function trimToNull(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

function parseOptionalNumber(value: string): number | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const numeric = Number(normalized);
  return Number.isFinite(numeric) ? numeric : null;
}

function parseOptionalJsonObject(
  value: string,
): Record<string, string> | typeof INVALID_JSON | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const parsed = safeJsonParse<unknown>(normalized, INVALID_JSON);
  if (!parsed || parsed === INVALID_JSON || typeof parsed !== "object" || Array.isArray(parsed)) {
    return parsed === INVALID_JSON ? INVALID_JSON : INVALID_JSON;
  }
  return Object.entries(parsed as Record<string, unknown>).reduce<Record<string, string>>(
    (result, [key, item]) => {
      result[key] = String(item);
      return result;
    },
    {},
  );
}

function asComparableRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function pushDiffEntry(
  entries: DiffEntry[],
  field: string,
  current: unknown,
  target: unknown,
): void {
  if (
    JSON.stringify(normalizeComparableValue(current)) ===
    JSON.stringify(normalizeComparableValue(target))
  ) {
    return;
  }
  entries.push({ field, current, target });
}

function pushReplaceableDiffEntry(
  entries: DiffEntry[],
  options: {
    field: string;
    configured: boolean;
    preview: unknown;
    target: unknown;
    replaceLabel: string;
  },
): void {
  if (options.target === undefined) {
    return;
  }
  entries.push({
    field: options.field,
    current: options.configured ? options.preview || "configured" : "not configured",
    target: options.target === null ? "clear value" : options.replaceLabel,
  });
}

function buildHeaderTargetLabel(headers: unknown): string {
  if (!headers || typeof headers !== "object" || Array.isArray(headers)) {
    return "updated headers";
  }
  const keys = Object.keys(headers as Record<string, unknown>);
  return keys.length ? `updated headers (${keys.join(", ")})` : "updated headers";
}
