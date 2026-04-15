import {
  bindSecretFieldBehavior,
  type SecretFieldState,
} from "../forms.js";
import {
  renderBooleanSelectOptions,
  renderSecretField,
  renderStaticSelectOptions,
} from "../templates.js";
import { csv, escapeHtml } from "../utils.js";

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
      <label class="field">
        <span>Reasoning</span>
        <select name="enable_reasoning">
          ${renderBooleanSelectOptions(Boolean(values.enable_reasoning))}
        </select>
      </label>
    </div>
    <div class="dual-grid">
      <label class="field"><span>Observability sinks</span><input name="observability_sinks" value="${escapeHtml(csv(values.observability_sinks))}" /></label>
      <label class="field">
        <span>Log level</span>
        <select name="log_level">
          ${renderStaticSelectOptions(String(values.log_level ?? ""), LOG_LEVELS)}
        </select>
      </label>
    </div>
  `;
}
