import {
  bindSecretFieldBehavior,
  type SecretFieldState,
} from "../forms.js";
import {
  banner,
  pill,
  renderBooleanSelectOptions,
  renderSecretField,
  renderStaticSelectOptions,
} from "../templates.js";
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

export function renderApplicationSection(
  options: ApplicationSectionOptions,
): string {
  return `
    <form id="${escapeHtml(options.formId)}" class="stack">
      <div class="stack">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
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
      </div>
      ${
        options.variant === "setup"
          ? renderSetupApplicationFields(options.values)
          : renderSettingsApplicationFields(options.values)
      }
      <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
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
    <form id="${escapeHtml(options.formId)}" class="stack">
      <div class="stack">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
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
      <div class="${options.variant === "setup" ? "stack" : "dual-grid"}">
        ${timeoutField}
      </div>
      <div class="toolbar">
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
    <form id="${escapeHtml(options.formId)}" class="stack">
      <div id="${escapeHtml(options.statusId)}"></div>
      <label class="field">
        <span>${escapeHtml(authLabel)}</span>
        <select name="enable_api_key_auth">
          ${renderBooleanSelectOptions(Boolean(options.values.enable_api_key_auth))}
        </select>
      </label>
      <label class="field"><span>Logs IP allowlist</span><input name="logs_ip_allowlist" value="${escapeHtml(csv(options.values.logs_ip_allowlist))}" /></label>
      <label class="field"><span>CORS origins</span><input name="cors_allow_origins" value="${escapeHtml(csv(options.values.cors_allow_origins))}" /></label>
      ${governanceField}
      <div class="banner banner--warn">${escapeHtml(options.bannerMessage)}</div>
      <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
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
    <form id="${escapeHtml(options.formId)}" class="stack">
      <div class="stack">
        <div class="banner">${escapeHtml(options.bannerMessage)}</div>
        <div id="${escapeHtml(options.statusId)}"></div>
      </div>
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
          <p class="muted">Each sink keeps its own settings. Enabling telemetry gates all exports, while sink toggles decide which integrations receive data.</p>
        </div>
      </div>
      <div class="stack">
        ${renderObservabilitySinkCard({
          sink: sinkById.get("prometheus"),
          title: "Prometheus",
          description:
            "Local metrics stay inside the gateway and can be scraped from the built-in endpoints.",
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
              <p class="muted">No extra credentials are required. Prometheus follows telemetry changes live without restart.</p>
            </div>
          `,
        })}
        ${renderObservabilitySinkCard({
          sink: sinkById.get("otlp"),
          title: "OTLP / HTTP",
          description:
            "Send traces to an OpenTelemetry collector or compatible OTLP/HTTP endpoint.",
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
              <p class="field-note">Stored preview: <strong>${escapeHtml(renderHeaderPreview(otlp))}</strong>. Leave blank to keep the current headers; paste a JSON object to replace them.</p>
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
          description:
            "Forward traces to Langfuse with base URL, public key, and secret key managed from the control plane.",
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
          description:
            "Push traces to Phoenix with an optional API key and project-level routing.",
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
      <button class="button" type="submit">${escapeHtml(options.submitLabel)}</button>
    </form>
  `;
}

export function bindGigachatSecretFields(
  form: HTMLFormElement | null,
  values: SectionValues,
): [() => SecretFieldState | null, () => SecretFieldState | null] {
  if (!form) {
    return [() => null, () => null];
  }

  return [
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

function renderSetupApplicationFields(values: SectionValues): string {
  return `
    <div class="dual-grid">
      <label class="field">
        <span>Enabled providers</span>
        <input name="enabled_providers" value="${escapeHtml(csv(values.enabled_providers))}" />
      </label>
      <label class="field">
        <span>Observability sinks</span>
        <input name="observability_sinks" value="${escapeHtml(csv(values.observability_sinks))}" />
      </label>
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
        <span>Telemetry</span>
        <select name="enable_telemetry">
          ${renderBooleanSelectOptions(Boolean(values.enable_telemetry))}
        </select>
      </label>
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
        ? `Enabled, but still missing: ${missingFields.join(", ")}.`
        : "Enabled, but still incomplete."
    : "Disabled. Stored values remain available until you remove them.";

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

function renderHeaderPreview(otlp: SectionValues): string {
  if (Array.isArray(otlp.header_names) && otlp.header_names.length > 0) {
    return `configured (${otlp.header_names.join(", ")})`;
  }
  return Boolean(otlp.headers_configured) ? "configured" : "not configured";
}
