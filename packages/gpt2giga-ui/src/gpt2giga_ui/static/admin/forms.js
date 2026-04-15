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
export function buildApplicationPayload(form) {
    const fields = form.elements;
    const payload = {
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
export function buildSecurityPayload(form) {
    const fields = form.elements;
    const payload = {
        enable_api_key_auth: fields.enable_api_key_auth.value === "true",
        logs_ip_allowlist: parseCsv(fields.logs_ip_allowlist.value),
        cors_allow_origins: parseCsv(fields.cors_allow_origins.value),
    };
    if (fields.governance_limits) {
        payload.governance_limits = safeJsonParse(fields.governance_limits.value || "[]", INVALID_JSON);
    }
    return payload;
}
export function bindValidityReset(...fields) {
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
export function validateRequiredCsvField(field, message, options) {
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
export function validatePositiveNumberField(field, message, options) {
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
export function validateJsonArrayField(field, value, { invalidMessage, nonArrayMessage, report, }) {
    if (!field) {
        return "";
    }
    const error = value === INVALID_JSON
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
export function bindSecretFieldBehavior(options) {
    const textarea = options.form.elements.namedItem(options.fieldName);
    const clearToggle = options.form.elements.namedItem(options.clearFieldName);
    if (!(textarea instanceof HTMLTextAreaElement) || !(clearToggle instanceof HTMLInputElement)) {
        return () => null;
    }
    const note = textarea.closest(".stack")?.querySelector(".field-note");
    const originalPlaceholder = textarea.placeholder;
    const preview = options.preview || "not configured";
    const sync = () => {
        const hasValue = textarea.value.trim().length > 0;
        if (hasValue) {
            clearToggle.checked = false;
            clearToggle.disabled = true;
            textarea.disabled = false;
            textarea.placeholder = originalPlaceholder;
            if (note) {
                note.textContent = `Stored preview: ${preview}. Pending action: replace the stored secret on save.`;
            }
            return {
                intent: "replace",
                message: "A new secret is staged and will replace the stored value on save.",
            };
        }
        clearToggle.disabled = false;
        if (clearToggle.checked) {
            textarea.disabled = true;
            textarea.placeholder = "Uncheck clear to paste a replacement secret";
            if (note) {
                note.textContent = `Stored preview: ${preview}. Pending action: clear the stored secret on save.`;
            }
            return {
                intent: "clear",
                message: "The stored secret will be removed when this section is saved.",
            };
        }
        textarea.disabled = false;
        textarea.placeholder = originalPlaceholder;
        if (note) {
            note.textContent = `Stored preview: ${preview}. Pending action: keep the stored secret unless you paste a replacement.`;
        }
        return {
            intent: "keep",
            message: "The stored secret remains unchanged unless you paste a replacement.",
        };
    };
    textarea.addEventListener("input", sync);
    clearToggle.addEventListener("change", sync);
    return sync;
}
export async function withBusyState({ root, button, pendingLabel, action, }) {
    const controls = root
        ? Array.from(root.querySelectorAll(FORM_CONTROL_SELECTOR))
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
    }
    finally {
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
export function collectGigachatPayload(form) {
    const fields = form.elements;
    const payload = {
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
    }
    else if (fields.clear_credentials?.checked) {
        payload.credentials = null;
    }
    const accessToken = fields.access_token.value.trim();
    if (accessToken) {
        payload.access_token = accessToken;
    }
    else if (fields.clear_access_token?.checked) {
        payload.access_token = null;
    }
    return payload;
}
export function planPendingApply(summary) {
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
export function describePendingRuntimeImpact(plan) {
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
            detail: "This save batch includes restart-sensitive fields, so the persisted target updates now but the running process keeps the previous runtime config until restart.",
        };
    }
    return {
        label: "Runtime updates immediately after save",
        tone: "good",
        detail: "This change set can be persisted and reloaded without restarting the process.",
    };
}
export function describePersistOutcome(sectionLabel, response) {
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
export function buildPendingDiffEntries(section, currentValues, payload) {
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
        }
        else if (section === "gigachat" && field === "access_token") {
            current = currentValues.access_token_configured
                ? currentValues.access_token_preview || "configured"
                : "not configured";
            target = target ? "updated secret" : "clear secret";
        }
        if (JSON.stringify(normalizeComparableValue(current)) ===
            JSON.stringify(normalizeComparableValue(target))) {
            return [];
        }
        return [{ field, current, target }];
    });
}
export function summarizePendingChanges(entries) {
    const changedFields = entries.map((entry) => entry.field);
    return {
        changedFields,
        restartFields: changedFields.filter((field) => RESTART_SENSITIVE_FIELDS.has(field)),
        liveFields: changedFields.filter((field) => !RESTART_SENSITIVE_FIELDS.has(field)),
        secretFields: changedFields.filter((field) => SECRET_FIELDS.has(field)),
    };
}
