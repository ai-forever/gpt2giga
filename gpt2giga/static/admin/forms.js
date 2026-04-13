import { normalizeComparableValue, parseCsv, safeJsonParse } from "./utils.js";
export const INVALID_JSON = "__invalid__";
export function buildApplicationPayload(form) {
    const fields = form.elements;
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
export function buildSecurityPayload(form) {
    const fields = form.elements;
    return {
        enable_api_key_auth: fields.enable_api_key_auth.value === "true",
        logs_ip_allowlist: parseCsv(fields.logs_ip_allowlist.value),
        cors_allow_origins: parseCsv(fields.cors_allow_origins.value),
        governance_limits: safeJsonParse(fields.governance_limits.value || "[]", INVALID_JSON),
    };
}
export function collectGigachatPayload(form) {
    const fields = form.elements;
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
