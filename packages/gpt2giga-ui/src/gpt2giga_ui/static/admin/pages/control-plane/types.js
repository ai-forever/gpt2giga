export const LOG_LEVELS = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"];
export const OBSERVABILITY_PRESETS = [
    {
        id: "local-prometheus",
        label: "Local Prometheus",
        composeOverlay: "deploy/compose/observability-prometheus.yaml",
        description: "Stage the built-in metrics sink.",
        note: "Turns telemetry on and keeps the built-in metrics endpoints.",
        pillLabels: ["Sink: Prometheus", "Gateway: /metrics", "Admin: /admin/api/metrics"],
        statusMessage: "Local Prometheus preset staged. Telemetry is on and Prometheus metrics stay on the built-in endpoints until you save.",
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
        statusMessage: "Local OTLP collector preset staged. The OTLP sink now points at http://otel-collector:4318/v1/traces with the default gpt2giga service name.",
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
        statusMessage: "Local Langfuse preset staged. The sink now targets http://langfuse-web:3000; paste the Langfuse public and secret keys before saving.",
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
        statusMessage: "Local Phoenix preset staged. The Phoenix sink now targets http://phoenix:6006 with project gpt2giga-local; keep the API key empty unless Phoenix auth is enabled.",
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
