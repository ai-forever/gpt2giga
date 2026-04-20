import {
  bindReplaceableFieldBehavior,
  bindSecretFieldBehavior,
  type SecretFieldState,
} from "../forms.js";
import type { InlineStatus } from "./control-plane-actions.js";
import {
  banner,
  pill,
  renderBooleanSelectOptions,
  renderFormSection,
  renderSelectOption,
  renderSecretField,
  renderStaticSelectOptions,
} from "../templates.js";
import { pathForPage } from "../routes.js";
import {
  asArray,
  asRecord,
  csv,
  escapeHtml,
} from "../utils.js";

const LOG_LEVELS = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"];

type SectionValues = Record<string, unknown>;

interface ApplicationSectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  values: SectionValues;
  variant: "setup" | "settings";
}

interface GigachatSectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  testButtonId: string;
  testButtonLabel: string;
  values: SectionValues;
  variant: "setup" | "settings";
}

interface SecuritySectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  values: SectionValues;
  variant: "setup" | "settings";
}

interface ObservabilitySectionOptions {
  bannerMessage: string;
  formId: string;
  statusId: string;
  submitLabel: string;
  values: SectionValues;
}

interface ObservabilityFormFields extends HTMLFormControlsCollection {
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

interface ObservabilityPresetDescriptor {
  composeOverlay: string;
  description: string;
  id: string;
  label: string;
  note: string;
  pillLabels: string[];
  statusMessage: string;
  apply: (fields: ObservabilityFormFields) => void;
}

const OBSERVABILITY_PRESETS: ObservabilityPresetDescriptor[] = [
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

export function renderApplicationSection(
  options: ApplicationSectionOptions,
): string {
  return `
    <form id="${escapeHtml(options.formId)}" class="form-shell">
      <div class="form-shell__intro">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
      ${renderFormSection({
        title: "Gateway mode and compatibility",
        intro: "Set runtime posture here.",
        body: `
          <div class="dual-grid">
            <label class="field">
              <span>Mode</span>
              <select name="mode">
                ${renderStaticSelectOptions(String(options.values.mode ?? ""), ["DEV", "PROD"])}
              </select>
            </label>
            <label class="field">
              <span>GigaChat API mode</span>
              <select name="gigachat_api_mode">
                ${renderStaticSelectOptions(String(options.values.gigachat_api_mode ?? ""), ["v1", "v2"])}
              </select>
            </label>
            <label class="field">
              <span>Responses API mode</span>
              <select name="gigachat_responses_api_mode">
                ${renderSelectOption("", String(options.values.gigachat_responses_api_mode ?? ""), "inherit base mode")}
                ${renderStaticSelectOptions(String(options.values.gigachat_responses_api_mode ?? ""), ["v1", "v2"])}
              </select>
            </label>
          </div>
        `,
      })}
      ${renderFormSection({
        title:
          options.variant === "setup" ? "Bootstrap posture" : "Runtime posture details",
        intro:
          options.variant === "setup"
            ? "Keep only bootstrap-critical application fields here."
            : "Keep provider routing and runtime storage together.",
        body:
          options.variant === "setup"
            ? renderSetupApplicationFields(options.values)
            : renderSettingsApplicationFields(options.values),
      })}
      <div class="form-actions">
        <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
      </div>
    </form>
  `;
}

export function renderGigachatSection(options: GigachatSectionOptions): string {
  const timeoutField =
    options.variant === "setup"
      ? `
          <label class="field">
            <span>Timeout</span>
            <input name="timeout" type="number" min="1" step="1" value="${escapeHtml(options.values.timeout ?? "")}" />
          </label>
        `
      : `
          <label class="field"><span>Timeout</span><input name="timeout" type="number" min="1" step="1" value="${escapeHtml(options.values.timeout ?? "")}" /></label>
        `;

  return `
    <form id="${escapeHtml(options.formId)}" class="form-shell">
      <div class="form-shell__intro">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
      ${renderFormSection({
        title: "Provider routing and transport",
        intro: "Keep target and transport settings together.",
        body: `
          <div class="dual-grid">
            <label class="field"><span>Model</span><input name="model" value="${escapeHtml(options.values.model ?? "")}" /></label>
            <label class="field"><span>Scope</span><input name="scope" value="${escapeHtml(options.values.scope ?? "")}" /></label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Base URL</span><input name="base_url" value="${escapeHtml(options.values.base_url ?? "")}" /></label>
            <label class="field"><span>Auth URL</span><input name="auth_url" value="${escapeHtml(options.values.auth_url ?? "")}" /></label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>CA bundle file</span>
              <input name="ca_bundle_file" placeholder="/certs/company-root.pem" value="${escapeHtml(options.values.ca_bundle_file ?? "")}" />
            </label>
            <label class="field">
              <span>Verify SSL</span>
              <select name="verify_ssl_certs">
                ${renderBooleanSelectOptions(Boolean(options.values.verify_ssl_certs))}
              </select>
            </label>
          </div>
        `,
      })}
      ${renderFormSection({
        title: "Credentials and token staging",
        intro: "Blank keeps the stored secret.",
        body: `
          <div class="dual-grid">
            <label class="field">
              <span>User</span>
              <input name="user" value="${escapeHtml(options.values.user ?? "")}" />
            </label>
            ${renderSecretField({
              name: "password",
              label: "Password",
              placeholder: "Paste a new password to replace the stored secret",
              preview: String(
                options.values.password_preview ??
                  (options.values.password_configured ? "configured" : "not configured"),
              ),
              clearControlName: "clear_password",
              clearLabel: "Clear stored password on save",
            })}
          </div>
          <div class="dual-grid">
            ${renderSecretField({
              name: "credentials",
              label: "Credentials",
              placeholder: "Paste new GigaChat credentials to replace the stored secret",
              preview: String(options.values.credentials_preview ?? "not configured"),
              clearControlName: "clear_credentials",
              clearLabel: "Clear stored credentials on save",
            })}
            ${renderSecretField({
              name: "access_token",
              label: "Access token",
              placeholder: "Paste a new access token to replace the stored secret",
              preview: String(options.values.access_token_preview ?? "not configured"),
              clearControlName: "clear_access_token",
              clearLabel: "Clear stored access token on save",
            })}
          </div>
        `,
      })}
      ${renderFormSection({
        title: "Candidate connectivity check",
        intro: "Test candidate values before saving.",
        body: `
          <div class="${options.variant === "setup" ? "stack" : "dual-grid"}">
            ${timeoutField}
          </div>
        `,
      })}
      <div class="form-actions">
        <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
        <button class="button button--secondary" id="${escapeHtml(options.testButtonId)}" type="button">${escapeHtml(options.testButtonLabel)}</button>
      </div>
    </form>
  `;
}

export function renderSecuritySection(options: SecuritySectionOptions): string {
  const governanceField =
    options.variant === "settings"
      ? `<label class="field"><span>Governance limits (JSON array)</span><textarea name="governance_limits">${escapeHtml(JSON.stringify(options.values.governance_limits ?? [], null, 2))}</textarea></label>`
      : "";

  const authLabel =
    options.variant === "setup" ? "Enable gateway API key auth" : "Enable API key auth";

  return `
    <form id="${escapeHtml(options.formId)}" class="form-shell">
      <div class="form-shell__intro">
        <div id="${escapeHtml(options.statusId)}"></div>
        <div class="banner banner--warn">${escapeHtml(options.bannerMessage)}</div>
      </div>
      ${renderFormSection({
        title:
          options.variant === "setup"
            ? "Gateway access during bootstrap"
            : "Gateway access and operator guardrails",
        intro:
          options.variant === "setup"
            ? "Use the minimum auth posture needed to close bootstrap exposure."
            : "Keep API key auth, logs exposure, CORS, and governance together.",
        body: `
          <label class="field">
            <span>${escapeHtml(authLabel)}</span>
            <select name="enable_api_key_auth">
              ${renderBooleanSelectOptions(Boolean(options.values.enable_api_key_auth))}
            </select>
          </label>
          <label class="field"><span>Logs IP allowlist</span><input name="logs_ip_allowlist" value="${escapeHtml(csv(options.values.logs_ip_allowlist))}" /></label>
          <label class="field"><span>CORS origins</span><input name="cors_allow_origins" value="${escapeHtml(csv(options.values.cors_allow_origins))}" /></label>
          ${governanceField}
        `,
      })}
      <div class="form-actions">
        <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
      </div>
    </form>
  `;
}

export function renderObservabilitySection(
  options: ObservabilitySectionOptions,
): string {
  const sinkCards = asArray<Record<string, unknown>>(options.values.sinks);
  const sinkById = new Map(
    sinkCards
      .map((sink) => [String(sink.id ?? ""), sink] as const)
      .filter(([id]) => Boolean(id)),
  );
  const activeSinks = asArray<string>(options.values.active_sinks);
  const otlp = asRecord(options.values.otlp);
  const langfuse = asRecord(options.values.langfuse);
  const phoenix = asRecord(options.values.phoenix);

  return `
    <form id="${escapeHtml(options.formId)}" class="form-shell">
      <div class="form-shell__intro">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
      ${renderFormSection({
        title: "Telemetry gate and active sinks",
        intro: "Start with the pipeline switch and sink posture.",
        body: `
          <div class="dual-grid">
            <label class="field">
              <span>Telemetry pipeline</span>
              <select name="enable_telemetry">
                ${renderBooleanSelectOptions(Boolean(options.values.enable_telemetry))}
              </select>
            </label>
            <div class="stack">
              ${pill(`Active sinks: ${activeSinks.length || 0}`, activeSinks.length ? "good" : "warn")}
              ${pill(
                Boolean(options.values.metrics_enabled) ? "Metrics endpoint: live" : "Metrics endpoint: disabled",
                Boolean(options.values.metrics_enabled) ? "good" : "warn",
              )}
              <p class="muted">Telemetry gates all exports.</p>
            </div>
          </div>
        `,
      })}
      ${renderFormSection({
        title: "Repo-local presets",
        intro: "Use presets to stage local compose defaults.",
        body: `
          <div class="banner">Each preset stages one local sink without touching the others.</div>
          <div class="workflow-grid">
            ${OBSERVABILITY_PRESETS.map((preset) => renderObservabilityPresetCard(preset)).join("")}
          </div>
        `,
      })}
      ${renderFormSection({
        title: "Sink-specific configuration",
        intro: "Keep raw endpoints and credentials in the sink cards.",
        body: `
          <div class="stack">
            ${renderObservabilitySinkCard({
              sink: sinkById.get("prometheus"),
              title: "Prometheus",
              description: "Built-in metrics endpoints.",
              body: `
                <label class="checkbox-field">
                  <input name="sink_prometheus" type="checkbox" ${activeSinks.includes("prometheus") ? "checked" : ""} />
                  <span>Enable Prometheus metrics sink</span>
                </label>
                <div class="dual-grid">
                  <div class="stack">
                    ${pill("Gateway: /metrics")}
                    ${pill("Admin: /admin/api/metrics")}
                  </div>
                  <p class="muted">No extra credentials.</p>
                </div>
              `,
            })}
            ${renderObservabilitySinkCard({
              sink: sinkById.get("otlp"),
              title: "OTLP / HTTP",
              description: "Send traces to an OTLP/HTTP endpoint.",
              body: `
                <label class="checkbox-field">
                  <input name="sink_otlp" type="checkbox" ${activeSinks.includes("otlp") ? "checked" : ""} />
                  <span>Enable OTLP sink</span>
                </label>
                <div class="dual-grid">
                  <label class="field">
                    <span>Traces endpoint</span>
                    <input name="otlp_traces_endpoint" placeholder="http://otel-collector:4318/v1/traces" value="${escapeHtml(otlp.traces_endpoint ?? "")}" />
                  </label>
                  <label class="field">
                    <span>Service name</span>
                    <input name="otlp_service_name" placeholder="gpt2giga" value="${escapeHtml(otlp.service_name ?? "")}" />
                  </label>
                </div>
                <div class="dual-grid">
                  <label class="field">
                    <span>Timeout seconds</span>
                    <input name="otlp_timeout_seconds" type="number" min="1" step="0.5" value="${escapeHtml(otlp.timeout_seconds ?? "")}" />
                  </label>
                  <label class="field">
                    <span>Max pending requests</span>
                    <input name="otlp_max_pending_requests" type="number" min="1" step="1" value="${escapeHtml(otlp.max_pending_requests ?? "")}" />
                  </label>
                </div>
                <div class="stack">
                  <label class="field">
                    <span>Headers override (JSON object)</span>
                    <textarea name="otlp_headers" placeholder='{"x-tenant":"demo","authorization":"Bearer ..."}'></textarea>
                  </label>
                  <p class="field-note">Stored: <strong>${escapeHtml(renderHeaderPreview(otlp))}</strong>. Blank keeps it; paste JSON to replace.</p>
                  <label class="checkbox-field">
                    <input name="otlp_clear_headers" type="checkbox" />
                    <span>Clear stored OTLP headers on save</span>
                  </label>
                </div>
              `,
            })}
            ${renderObservabilitySinkCard({
              sink: sinkById.get("langfuse"),
              title: "Langfuse",
              description: "Forward traces to Langfuse.",
              body: `
                <label class="checkbox-field">
                  <input name="sink_langfuse" type="checkbox" ${activeSinks.includes("langfuse") ? "checked" : ""} />
                  <span>Enable Langfuse sink</span>
                </label>
                <label class="field">
                  <span>Base URL</span>
                  <input name="langfuse_base_url" placeholder="https://cloud.langfuse.com" value="${escapeHtml(langfuse.base_url ?? "")}" />
                </label>
                <div class="dual-grid">
                  ${renderSecretField({
                    name: "langfuse_public_key",
                    label: "Public key",
                    placeholder: "Paste a new Langfuse public key to replace the stored value",
                    preview: String(langfuse.public_key_preview ?? "not configured"),
                    clearControlName: "langfuse_clear_public_key",
                    clearLabel: "Clear stored public key on save",
                  })}
                  ${renderSecretField({
                    name: "langfuse_secret_key",
                    label: "Secret key",
                    placeholder: "Paste a new Langfuse secret key to replace the stored value",
                    preview: String(langfuse.secret_key_preview ?? "not configured"),
                    clearControlName: "langfuse_clear_secret_key",
                    clearLabel: "Clear stored secret key on save",
                  })}
                </div>
              `,
            })}
            ${renderObservabilitySinkCard({
              sink: sinkById.get("phoenix"),
              title: "Phoenix",
              description: "Push traces to Phoenix.",
              body: `
                <label class="checkbox-field">
                  <input name="sink_phoenix" type="checkbox" ${activeSinks.includes("phoenix") ? "checked" : ""} />
                  <span>Enable Phoenix sink</span>
                </label>
                <div class="dual-grid">
                  <label class="field">
                    <span>Base URL</span>
                    <input name="phoenix_base_url" placeholder="http://phoenix:6006" value="${escapeHtml(phoenix.base_url ?? "")}" />
                  </label>
                  <label class="field">
                    <span>Project name</span>
                    <input name="phoenix_project_name" placeholder="gpt2giga-local" value="${escapeHtml(phoenix.project_name ?? "")}" />
                  </label>
                </div>
                <div class="dual-grid">
                  ${renderSecretField({
                    name: "phoenix_api_key",
                    label: "API key",
                    placeholder: "Paste a new Phoenix API key to replace the stored value",
                    preview: String(phoenix.api_key_preview ?? "not configured"),
                    clearControlName: "phoenix_clear_api_key",
                    clearLabel: "Clear stored Phoenix API key on save",
                  })}
                </div>
              `,
            })}
          </div>
        `,
      })}
      <div class="form-actions">
        <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
      </div>
    </form>
  `;
}

export function bindGigachatSecretFields(
  form: HTMLFormElement | null,
  values: SectionValues,
): [
  () => SecretFieldState | null,
  () => SecretFieldState | null,
  () => SecretFieldState | null,
] {
  if (!form) {
    return [() => null, () => null, () => null];
  }

  return [
    bindSecretFieldBehavior({
      form,
      fieldName: "password",
      clearFieldName: "clear_password",
      preview: String(
        values.password_preview ??
          (values.password_configured ? "configured" : "not configured"),
      ),
    }),
    bindSecretFieldBehavior({
      form,
      fieldName: "credentials",
      clearFieldName: "clear_credentials",
      preview: String(values.credentials_preview ?? "not configured"),
    }),
    bindSecretFieldBehavior({
      form,
      fieldName: "access_token",
      clearFieldName: "clear_access_token",
      preview: String(values.access_token_preview ?? "not configured"),
    }),
  ];
}

export function bindObservabilitySecretFields(
  form: HTMLFormElement | null,
  values: SectionValues,
): {
  syncLangfusePublicKey: () => SecretFieldState | null;
  syncLangfuseSecretKey: () => SecretFieldState | null;
  syncOtlpHeadersField: () => SecretFieldState | null;
  syncPhoenixApiKey: () => SecretFieldState | null;
} {
  if (!form) {
    return {
      syncOtlpHeadersField: () => null,
      syncLangfusePublicKey: () => null,
      syncLangfuseSecretKey: () => null,
      syncPhoenixApiKey: () => null,
    };
  }

  return {
    syncOtlpHeadersField: bindReplaceableFieldBehavior({
      form,
      fieldName: "otlp_headers",
      clearFieldName: "otlp_clear_headers",
      preview: renderHeaderPreview(asRecord(values.otlp)),
      clearPlaceholder: "Uncheck clear to paste a replacement header object",
      noteReplace: "replace the stored OTLP headers on save.",
      noteClear: "clear the stored OTLP headers on save.",
      noteKeep:
        "keep the stored OTLP headers unless you paste a replacement JSON object.",
      messageReplace:
        "A new OTLP headers object is staged and will replace the stored value on save.",
      messageClear: "Stored OTLP headers will be removed when this section is saved.",
      messageKeep:
        "Stored OTLP headers remain unchanged unless you paste a replacement JSON object.",
    }),
    syncLangfusePublicKey: bindSecretFieldBehavior({
      form,
      fieldName: "langfuse_public_key",
      clearFieldName: "langfuse_clear_public_key",
      preview: String(asRecord(values.langfuse).public_key_preview ?? "not configured"),
    }),
    syncLangfuseSecretKey: bindSecretFieldBehavior({
      form,
      fieldName: "langfuse_secret_key",
      clearFieldName: "langfuse_clear_secret_key",
      preview: String(asRecord(values.langfuse).secret_key_preview ?? "not configured"),
    }),
    syncPhoenixApiKey: bindSecretFieldBehavior({
      form,
      fieldName: "phoenix_api_key",
      clearFieldName: "phoenix_clear_api_key",
      preview: String(asRecord(values.phoenix).api_key_preview ?? "not configured"),
    }),
  };
}

export function bindObservabilityPresetButtons(
  form: HTMLFormElement | null,
  options: {
    refreshStatus: () => void;
    setActionState: (state: InlineStatus | null) => void;
  },
): void {
  if (!form) {
    return;
  }

  const fields = form.elements as ObservabilityFormFields;
  const buttons = Array.from(
    form.querySelectorAll<HTMLButtonElement>("[data-observability-preset]"),
  );
  if (!buttons.length) {
    return;
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const preset = OBSERVABILITY_PRESETS.find(
        (item) => item.id === button.dataset.observabilityPreset,
      );
      if (!preset) {
        return;
      }
      preset.apply(fields);
      options.setActionState({
        tone: "info",
        message: `${preset.statusMessage} Review the diff, then save.`,
      });
      options.refreshStatus();
    });
  });
}

export function renderSetupObservabilityHandoff(values: SectionValues): string {
  const activeSinks = asArray<string>(values.active_sinks);
  const sinkCards = asArray<Record<string, unknown>>(values.sinks);
  const enabledSinks = sinkCards.filter((sink) => Boolean(sink.enabled));

  const sinkSummaries = enabledSinks.length
    ? enabledSinks
        .map((sink) => {
          const label = String(sink.label ?? sink.id ?? "Sink");
          const missingFields = asArray<string>(sink.missing_fields);
          if (Boolean(sink.configured)) {
            return banner(`${label} is enabled and ready for live exports.`);
          }
          if (missingFields.length) {
            return banner(
              `${label} is enabled but still missing: ${missingFields.join(", ")}.`,
              "warn",
            );
          }
          return banner(`${label} is enabled but still incomplete.`, "warn");
        })
        .join("")
    : banner(
        "Observability is optional during bootstrap.",
      );

  return `
    <div class="stack">
      <div class="pill-row">
        ${pill(
          `Telemetry: ${Boolean(values.enable_telemetry) ? "enabled" : "disabled"}`,
          Boolean(values.enable_telemetry) ? "good" : "warn",
        )}
        ${pill(`Active sinks: ${activeSinks.length || 0}`, activeSinks.length ? "good" : "warn")}
        ${pill(
          Boolean(values.metrics_enabled) ? "Metrics endpoint: live" : "Metrics endpoint: disabled",
          Boolean(values.metrics_enabled) ? "good" : "warn",
        )}
      </div>
      ${sinkSummaries}
      <p class="muted">Use settings for sink tuning.</p>
      <div class="toolbar">
        <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-observability"))}">Open observability settings</a>
      </div>
    </div>
  `;
}

function renderSetupApplicationFields(values: SectionValues): string {
  return `
    <div class="dual-grid">
      <label class="field">
        <span>Enabled providers</span>
        <input name="enabled_providers" value="${escapeHtml(csv(values.enabled_providers))}" />
      </label>
      <label class="field"><span>Mode handoff</span><input value="Use full settings for observability and advanced routing." disabled /></label>
    </div>
    <div class="dual-grid">
      <label class="field">
        <span>Runtime store backend</span>
        <select name="runtime_store_backend">
          ${renderStaticSelectOptions(String(values.runtime_store_backend ?? ""), ["memory", "sqlite"])}
        </select>
      </label>
      <label class="field">
        <span>Runtime namespace</span>
        <input name="runtime_store_namespace" value="${escapeHtml(values.runtime_store_namespace ?? "")}" />
      </label>
    </div>
    <div class="triple-grid">
      <label class="field">
        <span>Pass model</span>
        <select name="pass_model">
          ${renderBooleanSelectOptions(Boolean(values.pass_model))}
        </select>
      </label>
      <label class="field">
        <span>Pass token</span>
        <select name="pass_token">
          ${renderBooleanSelectOptions(Boolean(values.pass_token))}
        </select>
      </label>
    </div>
  `;
}

function renderSettingsApplicationFields(values: SectionValues): string {
  return `
    <div class="dual-grid">
      <label class="field"><span>Enabled providers</span><input name="enabled_providers" value="${escapeHtml(csv(values.enabled_providers))}" /></label>
      <label class="field"><span>Embeddings model</span><input name="embeddings" value="${escapeHtml(values.embeddings ?? "")}" /></label>
    </div>
    <div class="quad-grid">
      <label class="field">
        <span>Pass model</span>
        <select name="pass_model">
          ${renderBooleanSelectOptions(Boolean(values.pass_model))}
        </select>
      </label>
      <label class="field">
        <span>Pass token</span>
        <select name="pass_token">
          ${renderBooleanSelectOptions(Boolean(values.pass_token))}
        </select>
      </label>
      <label class="field">
        <span>Reasoning</span>
        <select name="enable_reasoning">
          ${renderBooleanSelectOptions(Boolean(values.enable_reasoning))}
        </select>
      </label>
    </div>
    <div class="dual-grid">
      <label class="field">
        <span>Log level</span>
        <select name="log_level">
          ${renderStaticSelectOptions(String(values.log_level ?? ""), LOG_LEVELS)}
        </select>
      </label>
    </div>
  `;
}

function renderObservabilitySinkCard(options: {
  sink: Record<string, unknown> | undefined;
  title: string;
  description: string;
  body: string;
}): string {
  const sink = options.sink ?? {};
  const enabled = Boolean(sink.enabled);
  const configured = Boolean(sink.configured);
  const missingFields = asArray<string>(sink.missing_fields);
  const liveApply = Boolean(sink.live_apply);
  const restartRequired = Boolean(sink.restart_required);
  const summary = enabled
      ? configured
        ? "Enabled and configured."
        : missingFields.length
        ? `Enabled, missing: ${missingFields.join(", ")}.`
        : "Enabled, incomplete."
    : "Disabled. Stored values remain until removed.";

  return `
    <article class="step-card ${enabled ? "step-card--ready" : ""}">
      <div class="stack">
        <div class="toolbar">
          <div class="stack">
            <h4>${escapeHtml(options.title)}</h4>
            <p class="muted">${escapeHtml(options.description)}</p>
          </div>
          <div class="stack">
            ${pill(enabled ? "enabled" : "disabled", enabled ? "good" : "warn")}
            ${pill(configured ? "configured" : "needs fields", configured ? "good" : "warn")}
          </div>
        </div>
        ${banner(summary, enabled && !configured ? "warn" : "info")}
        <div class="pill-row">
          ${pill(liveApply ? "Live apply" : "Requires restart", liveApply ? "good" : "warn")}
          ${restartRequired ? pill("Restart-sensitive", "warn") : pill("Restart-safe", "good")}
          ${missingFields.length ? pill(`Missing: ${missingFields.join(", ")}`, "warn") : pill("Required fields satisfied", "good")}
        </div>
        ${options.body}
      </div>
    </article>
  `;
}

function renderObservabilityPresetCard(
  preset: ObservabilityPresetDescriptor,
): string {
  return `
    <article class="workflow-card">
      <div class="workflow-card__header">
        <span class="eyebrow">Local preset</span>
        <h4>${escapeHtml(preset.label)}</h4>
        <p>${escapeHtml(preset.description)}</p>
      </div>
      <div class="pill-row">
        ${preset.pillLabels.map((label) => pill(label)).join("")}
      </div>
      <p class="muted">Overlay: <strong>${escapeHtml(preset.composeOverlay)}</strong>. ${escapeHtml(preset.note)}</p>
      <div class="workflow-card__actions">
        <button
          class="button button--secondary"
          type="button"
          data-observability-preset="${escapeHtml(preset.id)}"
        >
          Apply preset
        </button>
      </div>
    </article>
  `;
}

function renderHeaderPreview(otlp: SectionValues): string {
  if (Array.isArray(otlp.header_names) && otlp.header_names.length > 0) {
    return `configured (${otlp.header_names.join(", ")})`;
  }
  return Boolean(otlp.headers_configured) ? "configured" : "not configured";
}
