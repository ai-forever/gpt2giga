import { INVALID_JSON } from "./forms-types.js";
import { parseOptionalJsonObject, parseOptionalNumber, trimToNull, } from "./forms-normalization.js";
import { parseCsv, safeJsonParse } from "./utils.js";
export function buildApplicationPayload(form) {
    const fields = form.elements;
    const payload = {
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
export function buildObservabilityPayload(form) {
    const fields = form.elements;
    const payload = {
        enable_telemetry: fields.enable_telemetry.value === "true",
        active_sinks: [
            fields.sink_prometheus.checked ? "prometheus" : null,
            fields.sink_otlp.checked ? "otlp" : null,
            fields.sink_langfuse.checked ? "langfuse" : null,
            fields.sink_phoenix.checked ? "phoenix" : null,
        ].filter((value) => Boolean(value)),
        otlp: {
            traces_endpoint: trimToNull(fields.otlp_traces_endpoint.value),
            service_name: trimToNull(fields.otlp_service_name.value),
            timeout_seconds: parseOptionalNumber(fields.otlp_timeout_seconds.value),
            max_pending_requests: parseOptionalNumber(fields.otlp_max_pending_requests.value),
        },
        langfuse: {
            base_url: trimToNull(fields.langfuse_base_url.value),
        },
        phoenix: {
            base_url: trimToNull(fields.phoenix_base_url.value),
            project_name: trimToNull(fields.phoenix_project_name.value),
        },
    };
    const otlpPayload = payload.otlp;
    const otlpHeaders = parseOptionalJsonObject(fields.otlp_headers.value);
    if (otlpHeaders !== null) {
        otlpPayload.headers = otlpHeaders;
    }
    else if (fields.otlp_clear_headers?.checked) {
        otlpPayload.headers = null;
    }
    const langfusePayload = payload.langfuse;
    const langfusePublicKey = fields.langfuse_public_key.value.trim();
    if (langfusePublicKey) {
        langfusePayload.public_key = langfusePublicKey;
    }
    else if (fields.langfuse_clear_public_key?.checked) {
        langfusePayload.public_key = null;
    }
    const langfuseSecretKey = fields.langfuse_secret_key.value.trim();
    if (langfuseSecretKey) {
        langfusePayload.secret_key = langfuseSecretKey;
    }
    else if (fields.langfuse_clear_secret_key?.checked) {
        langfusePayload.secret_key = null;
    }
    const phoenixPayload = payload.phoenix;
    const phoenixApiKey = fields.phoenix_api_key.value.trim();
    if (phoenixApiKey) {
        phoenixPayload.api_key = phoenixApiKey;
    }
    else if (fields.phoenix_clear_api_key?.checked) {
        phoenixPayload.api_key = null;
    }
    return payload;
}
export function collectGigachatPayload(form) {
    const fields = form.elements;
    const payload = {
        model: fields.model.value.trim() || null,
        scope: fields.scope.value.trim() || null,
        user: fields.user.value.trim() || null,
        base_url: fields.base_url.value.trim() || null,
        auth_url: fields.auth_url.value.trim() || null,
        ca_bundle_file: fields.ca_bundle_file.value.trim() || null,
        verify_ssl_certs: fields.verify_ssl_certs.value === "true",
        timeout: fields.timeout && fields.timeout.value ? Number(fields.timeout.value) : null,
    };
    const password = fields.password.value.trim();
    if (password) {
        payload.password = password;
    }
    else if (fields.clear_password?.checked) {
        payload.password = null;
    }
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
