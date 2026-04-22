import type { DiffEntry, PendingChangeSummary } from "./types.js";
import {
  INVALID_JSON,
  type PendingDiffSection,
  type PersistOutcomeDescriptor,
  type PlannedApplyState,
  type RuntimeImpactDescriptor,
} from "./forms-types.js";
import { asComparableRecord } from "./forms-normalization.js";
import { normalizeComparableValue } from "./utils.js";

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
  section: PendingDiffSection,
  currentValues: Record<string, unknown>,
  payload: Record<string, unknown>,
): DiffEntry[] {
  return Object.entries(payload)
    .filter(([, value]) => value !== INVALID_JSON)
    .flatMap(([field, originalTarget]) => {
      let current = currentValues[field];
      let target = originalTarget;

      if (section === "gigachat" && field === "password") {
        current = currentValues.password_configured
          ? currentValues.password_preview || "configured"
          : "not configured";
        target = target ? "updated secret" : "clear secret";
      } else if (section === "gigachat" && field === "credentials") {
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

      if (valuesEqual(current, target)) {
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

function valuesEqual(current: unknown, target: unknown): boolean {
  return (
    JSON.stringify(normalizeComparableValue(current)) ===
    JSON.stringify(normalizeComparableValue(target))
  );
}

function pushDiffEntry(
  entries: DiffEntry[],
  field: string,
  current: unknown,
  target: unknown,
): void {
  if (valuesEqual(current, target)) {
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
