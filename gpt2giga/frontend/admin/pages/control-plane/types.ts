export type SectionValues = Record<string, unknown>;

export interface ApplicationSectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  values: SectionValues;
  variant: "setup" | "settings";
}

export interface GigachatSectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  testButtonId: string;
  testButtonLabel: string;
  values: SectionValues;
  variant: "setup" | "settings";
}

export interface SecuritySectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  values: SectionValues;
  variant: "setup" | "settings";
}

export interface ObservabilitySectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  values: SectionValues;
}

export interface ObservabilityFormFields extends HTMLFormControlsCollection {
  enable_telemetry: HTMLSelectElement;
  sink_prometheus: HTMLInputElement;
  sink_otlp: HTMLInputElement;
  sink_langfuse: HTMLInputElement;
  sink_phoenix: HTMLInputElement;
  otlp_traces_endpoint: HTMLInputElement;
  otlp_service_name: HTMLInputElement;
  otlp_timeout_seconds: HTMLInputElement;
  otlp_max_pending_requests: HTMLInputElement;
  otlp_clear_headers?: HTMLInputElement;
  langfuse_base_url: HTMLInputElement;
  langfuse_clear_public_key?: HTMLInputElement;
  langfuse_clear_secret_key?: HTMLInputElement;
  phoenix_base_url: HTMLInputElement;
  phoenix_project_name: HTMLInputElement;
  phoenix_clear_api_key?: HTMLInputElement;
}

export interface ObservabilityPresetDescriptor {
  composeOverlay: string;
  description: string;
  id: string;
  label: string;
  note: string;
  pillLabels: string[];
  statusMessage: string;
  apply: (fields: ObservabilityFormFields) => void;
}

export const LOG_LEVELS = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"];

export const OBSERVABILITY_PRESETS: ObservabilityPresetDescriptor[] = [
  {
    id: "local-prometheus",
    label: "Local Prometheus",
    composeOverlay: "deploy/compose/observability-prometheus.yaml",
    description: "Stage the built-in metrics sink.",
    note: "Turns telemetry on and keeps the built-in metrics endpoints.",
    pillLabels: ["Sink: Prometheus", "Gateway: /metrics", "Admin: /admin/api/metrics"],
    statusMessage:
      "Local Prometheus preset staged. Telemetry is on and Prometheus metrics stay on the built-in endpoints until you save.",
    apply: (fields) => {
      fields.enable_telemetry.value = "true";
      fields.sink_prometheus.checked = true;
    },
  },
  {
    id: "local-otlp",
    label: "Local OTLP collector",
    composeOverlay: "deploy/compose/observability-otlp.yaml",
    description: "Stage the repo-local OTLP collector endpoint.",
    note: "Turns telemetry on, enables OTLP, and fills the local collector URL.",
    pillLabels: [
      "Sink: OTLP/HTTP",
      "Endpoint: http://otel-collector:4318/v1/traces",
      "Service: gpt2giga",
    ],
    statusMessage:
      "Local OTLP collector preset staged. The OTLP sink now points at http://otel-collector:4318/v1/traces with the default gpt2giga service name.",
    apply: (fields) => {
      fields.enable_telemetry.value = "true";
      fields.sink_otlp.checked = true;
      fields.otlp_traces_endpoint.value = "http://otel-collector:4318/v1/traces";
      fields.otlp_service_name.value = "gpt2giga";
      fields.otlp_timeout_seconds.value = "5";
      fields.otlp_max_pending_requests.value = "256";
      if (fields.otlp_clear_headers) {
        fields.otlp_clear_headers.checked = false;
      }
    },
  },
  {
    id: "local-langfuse",
    label: "Local Langfuse",
    composeOverlay: "deploy/compose/observability-langfuse.yaml",
    description: "Stage the local Langfuse base URL.",
    note: "Turns telemetry on, enables Langfuse, and leaves key fields ready for paste.",
    pillLabels: [
      "Sink: Langfuse",
      "Base URL: http://langfuse-web:3000",
      "Keys: required",
    ],
    statusMessage:
      "Local Langfuse preset staged. The sink now targets http://langfuse-web:3000; paste the Langfuse public and secret keys before saving.",
    apply: (fields) => {
      fields.enable_telemetry.value = "true";
      fields.sink_langfuse.checked = true;
      fields.langfuse_base_url.value = "http://langfuse-web:3000";
      if (fields.langfuse_clear_public_key) {
        fields.langfuse_clear_public_key.checked = false;
      }
      if (fields.langfuse_clear_secret_key) {
        fields.langfuse_clear_secret_key.checked = false;
      }
    },
  },
  {
    id: "local-phoenix",
    label: "Local Phoenix",
    composeOverlay: "deploy/compose/observability-phoenix.yaml",
    description: "Stage the local Phoenix endpoint and project.",
    note: "Turns telemetry on, enables Phoenix, and leaves the API key blank by default.",
    pillLabels: [
      "Sink: Phoenix",
      "Base URL: http://phoenix:6006",
      "Project: gpt2giga-local",
    ],
    statusMessage:
      "Local Phoenix preset staged. The Phoenix sink now targets http://phoenix:6006 with project gpt2giga-local; keep the API key empty unless Phoenix auth is enabled.",
    apply: (fields) => {
      fields.enable_telemetry.value = "true";
      fields.sink_phoenix.checked = true;
      fields.phoenix_base_url.value = "http://phoenix:6006";
      fields.phoenix_project_name.value = "gpt2giga-local";
      if (fields.phoenix_clear_api_key) {
        fields.phoenix_clear_api_key.checked = false;
      }
    },
  },
];
