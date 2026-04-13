import type { DiffEntry } from "./types.js";
import { normalizeComparableValue, parseCsv, safeJsonParse } from "./utils.js";

export const INVALID_JSON = "__invalid__";

export function buildApplicationPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    mode: HTMLSelectElement;
    gigachat_api_mode: HTMLSelectElement;
    enabled_providers: HTMLInputElement;
    embeddings: HTMLInputElement;
    enable_telemetry: HTMLSelectElement;
    pass_model: HTMLSelectElement;
    pass_token: HTMLSelectElement;
    enable_reasoning: HTMLSelectElement;
    observability_sinks: HTMLInputElement;
    log_level: HTMLSelectElement;
  };

  return {
    mode: fields.mode.value,
    gigachat_api_mode: fields.gigachat_api_mode.value,
    enabled_providers: parseCsv(fields.enabled_providers.value),
    embeddings: fields.embeddings.value.trim(),
    enable_telemetry: fields.enable_telemetry.value === "true",
    pass_model: fields.pass_model.value === "true",
    pass_token: fields.pass_token.value === "true",
    enable_reasoning: fields.enable_reasoning.value === "true",
    observability_sinks: parseCsv(fields.observability_sinks.value),
    log_level: fields.log_level.value,
  };
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

export function collectGigachatPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    model: HTMLInputElement;
    scope: HTMLInputElement;
    base_url: HTMLInputElement;
    auth_url: HTMLInputElement;
    credentials: HTMLTextAreaElement;
    access_token: HTMLTextAreaElement;
    verify_ssl_certs: HTMLSelectElement;
    timeout?: HTMLInputElement;
  };

  return {
    model: fields.model.value.trim() || null,
    scope: fields.scope.value.trim() || null,
    base_url: fields.base_url.value.trim() || null,
    auth_url: fields.auth_url.value.trim() || null,
    credentials: fields.credentials.value.trim() || null,
    access_token: fields.access_token.value.trim() || null,
    verify_ssl_certs: fields.verify_ssl_certs.value === "true",
    timeout: fields.timeout && fields.timeout.value ? Number(fields.timeout.value) : null,
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
