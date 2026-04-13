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
]);

type FormControlElement =
  | HTMLButtonElement
  | HTMLInputElement
  | HTMLSelectElement
  | HTMLTextAreaElement;

export function buildApplicationPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    mode: HTMLSelectElement;
    gigachat_api_mode: HTMLSelectElement;
    enabled_providers: HTMLInputElement;
    embeddings?: HTMLInputElement;
    enable_telemetry: HTMLSelectElement;
    pass_model: HTMLSelectElement;
    pass_token: HTMLSelectElement;
    enable_reasoning?: HTMLSelectElement;
    observability_sinks: HTMLInputElement;
    log_level?: HTMLSelectElement;
    runtime_store_backend?: HTMLSelectElement;
    runtime_store_namespace?: HTMLInputElement;
  };

  const payload: Record<string, unknown> = {
    mode: fields.mode.value,
    gigachat_api_mode: fields.gigachat_api_mode.value,
    enabled_providers: parseCsv(fields.enabled_providers.value),
    enable_telemetry: fields.enable_telemetry.value === "true",
    pass_model: fields.pass_model.value === "true",
    pass_token: fields.pass_token.value === "true",
    observability_sinks: parseCsv(fields.observability_sinks.value),
  };

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
): Record<string, unknown> & { governance_limits: unknown } {
  const fields = form.elements as typeof form.elements & {
    enable_api_key_auth: HTMLSelectElement;
    logs_ip_allowlist: HTMLInputElement;
    cors_allow_origins: HTMLInputElement;
    governance_limits: HTMLTextAreaElement;
  };

  return {
    enable_api_key_auth: fields.enable_api_key_auth.value === "true",
    logs_ip_allowlist: parseCsv(fields.logs_ip_allowlist.value),
    cors_allow_origins: parseCsv(fields.cors_allow_origins.value),
    governance_limits: safeJsonParse(fields.governance_limits.value || "[]", INVALID_JSON),
  };
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

  controlStates.forEach(({ control }) => {
    control.disabled = true;
  });
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

export function summarizePendingChanges(entries: DiffEntry[]): PendingChangeSummary {
  const changedFields = entries.map((entry) => entry.field);
  return {
    changedFields,
    restartFields: changedFields.filter((field) => RESTART_SENSITIVE_FIELDS.has(field)),
    secretFields: changedFields.filter((field) => SECRET_FIELDS.has(field)),
  };
}
