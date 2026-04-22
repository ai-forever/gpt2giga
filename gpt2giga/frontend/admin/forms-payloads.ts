import { INVALID_JSON } from "./forms-types.js";
import {
  parseOptionalJsonObject,
  parseOptionalNumber,
  trimToNull,
} from "./forms-normalization.js";
import { parseCsv, safeJsonParse } from "./utils.js";

type ReplaceableFieldElement = HTMLInputElement | HTMLTextAreaElement;

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

export function collectGigachatPayload(form: HTMLFormElement): Record<string, unknown> {
  const fields = form.elements as typeof form.elements & {
    model: HTMLInputElement;
    scope: HTMLInputElement;
    user: HTMLInputElement;
    base_url: HTMLInputElement;
    auth_url: HTMLInputElement;
    ca_bundle_file: HTMLInputElement;
    password: ReplaceableFieldElement;
    credentials: ReplaceableFieldElement;
    access_token: ReplaceableFieldElement;
    clear_password?: HTMLInputElement;
    clear_credentials?: HTMLInputElement;
    clear_access_token?: HTMLInputElement;
    verify_ssl_certs: HTMLSelectElement;
    timeout?: HTMLInputElement;
  };

  const payload: Record<string, unknown> = {
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
  } else if (fields.clear_password?.checked) {
    payload.password = null;
  }

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
