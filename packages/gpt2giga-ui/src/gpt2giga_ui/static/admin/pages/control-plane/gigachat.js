import { bindSecretFieldBehavior, } from "../../forms.js";
import { renderBooleanSelectOptions, renderFormSection, renderSecretField, } from "../../templates.js";
import { escapeHtml } from "../../utils.js";
import {} from "./types.js";
export function renderGigachatSection(options) {
    const timeoutField = options.variant === "setup"
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
            preview: String(options.values.password_preview ??
                (options.values.password_configured ? "configured" : "not configured")),
            clearControlName: "clear_password",
            clearLabel: "Clear stored password on save",
            masked: true,
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
            masked: true,
        })}
            ${renderSecretField({
            name: "access_token",
            label: "Access token",
            placeholder: "Paste a new access token to replace the stored secret",
            preview: String(options.values.access_token_preview ?? "not configured"),
            clearControlName: "clear_access_token",
            clearLabel: "Clear stored access token on save",
            masked: true,
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
export function bindGigachatSecretFields(form, values) {
    if (!form) {
        return [() => null, () => null, () => null];
    }
    return [
        bindSecretFieldBehavior({
            form,
            fieldName: "password",
            clearFieldName: "clear_password",
            preview: String(values.password_preview ??
                (values.password_configured ? "configured" : "not configured")),
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
