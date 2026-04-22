import {
  banner,
  pill,
  renderBooleanSelectOptions,
  renderFormSection,
  renderSelectOption,
  renderStaticSelectOptions,
} from "../../templates.js";
import { asArray, asRecord, csv, escapeHtml } from "../../utils.js";
import {
  LOG_LEVELS,
  type ApplicationSectionOptions,
  type SecuritySectionOptions,
  type SectionValues,
} from "./types.js";

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

function renderSetupApplicationFields(values: SectionValues): string {
  return `
    ${renderRuntimeStoreSection(values)}
    <div class="dual-grid">
      <label class="field">
        <span>Enabled providers</span>
        <input name="enabled_providers" value="${escapeHtml(csv(values.enabled_providers))}" />
      </label>
      <label class="field"><span>Mode handoff</span><input value="Use full settings for observability and advanced routing." disabled /></label>
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
    ${renderRuntimeStoreSection(values)}
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

interface RuntimeStoreCatalogEntry {
  active: boolean;
  configured: boolean;
  description: string;
  label: string;
  name: string;
  registered: boolean;
}

function renderRuntimeStoreSection(values: SectionValues): string {
  const configuredBackend = String(values.runtime_store_backend ?? "n/a");
  const activeBackend = String(values.runtime_store_active_backend ?? "n/a");
  const dsnConfigured = Boolean(values.runtime_store_dsn_configured);
  const catalog = getRuntimeStoreCatalog(values);
  const registeredNames = catalog
    .filter((item) => item.registered)
    .map((item) => item.name);

  return `
    <div class="stack">
      <div class="toolbar">
        ${pill(`Configured: ${configuredBackend}`)}
        ${pill(
          `Active: ${activeBackend}`,
          activeBackend !== "n/a" && activeBackend === configuredBackend ? "good" : "warn",
        )}
        ${pill(`Added: ${registeredNames.join(", ") || "none"}`)}
        ${pill(`DSN: ${dsnConfigured ? "configured" : "not configured"}`, dsnConfigured ? "good" : "warn")}
      </div>
      <div class="dual-grid">
        <label class="field">
          <span>Runtime store backend</span>
          <select name="runtime_store_backend">
            ${renderRuntimeStoreSelectOptions(catalog, configuredBackend)}
          </select>
        </label>
        <label class="field">
          <span>Runtime namespace</span>
          <input name="runtime_store_namespace" value="${escapeHtml(values.runtime_store_namespace ?? "")}" />
        </label>
      </div>
      <div class="stack">
        ${catalog
          .map(
            (item) => `
              <div class="stat-line">
                <strong>${escapeHtml(item.label)}</strong>
                <span class="muted">${escapeHtml(buildRuntimeStoreLine(item))}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function getRuntimeStoreCatalog(values: SectionValues): RuntimeStoreCatalogEntry[] {
  return asArray<unknown>(values.runtime_store_catalog)
    .map((item) => asRecord(item))
    .map((item) => ({
      active: Boolean(item.active),
      configured: Boolean(item.configured),
      description: String(item.description ?? ""),
      label: String(item.label ?? item.name ?? "unknown"),
      name: String(item.name ?? ""),
      registered: Boolean(item.registered),
    }))
    .filter((item) => item.name);
}

function renderRuntimeStoreSelectOptions(
  catalog: RuntimeStoreCatalogEntry[],
  selected: string,
): string {
  return catalog
    .map((item) => {
      const labelSuffix = item.registered
        ? item.active
          ? " (added, active)"
          : " (added)"
        : " (not added)";
      return `<option value="${escapeHtml(item.name)}" ${selected === item.name ? "selected" : ""} ${item.registered ? "" : "disabled"}>${escapeHtml(`${item.label}${labelSuffix}`)}</option>`;
    })
    .join("");
}

function buildRuntimeStoreLine(item: RuntimeStoreCatalogEntry): string {
  const statusParts = [
    item.registered ? "added" : "not added",
    item.configured ? "configured" : null,
    item.active ? "active" : null,
  ].filter(Boolean);
  return `${statusParts.join(", ")}. ${item.description}`;
}
