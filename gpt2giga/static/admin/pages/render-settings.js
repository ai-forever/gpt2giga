import { INVALID_JSON, bindValidityReset, buildApplicationPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, withBusyState, } from "../forms.js";
import { banner, card, renderDiffSections, renderJson, renderSecretField } from "../templates.js";
import { asArray, asRecord, csv, escapeHtml, formatTimestamp, parseCsv } from "../utils.js";
const LOG_LEVELS = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"];
export async function renderSettings(app, token) {
    const [application, gigachat, security, revisionsPayload] = await Promise.all([
        app.api.json("/admin/api/settings/application"),
        app.api.json("/admin/api/settings/gigachat"),
        app.api.json("/admin/api/settings/security"),
        app.api.json("/admin/api/settings/revisions?limit=6"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const applicationValues = asRecord(application.values);
    const gigachatValues = asRecord(gigachat.values);
    const securityValues = asRecord(security.values);
    const revisions = asArray(revisionsPayload.revisions);
    app.setHeroActions(`<button class="button button--secondary" id="reload-settings" type="button">Reload values</button>`);
    app.setContent(`
    ${card("Application", `
        <form id="application-form" class="stack">
          ${banner("Keep at least one provider enabled. Mode, runtime backend, auth and CORS-adjacent changes may require a restart.")}
          <div class="dual-grid">
            <label class="field">
              <span>Mode</span>
              <select name="mode">
                <option value="DEV" ${applicationValues.mode === "DEV" ? "selected" : ""}>DEV</option>
                <option value="PROD" ${applicationValues.mode === "PROD" ? "selected" : ""}>PROD</option>
              </select>
            </label>
            <label class="field">
              <span>GigaChat API mode</span>
              <select name="gigachat_api_mode">
                <option value="v1" ${applicationValues.gigachat_api_mode === "v1" ? "selected" : ""}>v1</option>
                <option value="v2" ${applicationValues.gigachat_api_mode === "v2" ? "selected" : ""}>v2</option>
              </select>
            </label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Enabled providers</span><input name="enabled_providers" value="${escapeHtml(csv(applicationValues.enabled_providers))}" /></label>
            <label class="field"><span>Embeddings model</span><input name="embeddings" value="${escapeHtml(applicationValues.embeddings ?? "")}" /></label>
          </div>
          <div class="quad-grid">
            <label class="field">
              <span>Telemetry</span>
              <select name="enable_telemetry">
                <option value="true" ${applicationValues.enable_telemetry ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.enable_telemetry ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field">
              <span>Pass model</span>
              <select name="pass_model">
                <option value="true" ${applicationValues.pass_model ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.pass_model ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field">
              <span>Pass token</span>
              <select name="pass_token">
                <option value="true" ${applicationValues.pass_token ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.pass_token ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field">
              <span>Reasoning</span>
              <select name="enable_reasoning">
                <option value="true" ${applicationValues.enable_reasoning ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.enable_reasoning ? "selected" : ""}>off</option>
              </select>
            </label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Observability sinks</span><input name="observability_sinks" value="${escapeHtml(csv(applicationValues.observability_sinks))}" /></label>
            <label class="field">
              <span>Log level</span>
              <select name="log_level">
                ${LOG_LEVELS.map((level) => `<option value="${level}" ${applicationValues.log_level === level ? "selected" : ""}>${level}</option>`).join("")}
              </select>
            </label>
          </div>
          <button class="button" type="submit">Save application settings</button>
        </form>
      `, "panel panel--span-6")}
    ${card("GigaChat", `
        <form id="gigachat-form" class="stack">
          ${banner("Secrets stay masked after save. Leave secret fields blank to preserve the stored value; use the clear toggle only when you want to remove it.")}
          <div class="dual-grid">
            <label class="field"><span>Model</span><input name="model" value="${escapeHtml(gigachatValues.model ?? "")}" /></label>
            <label class="field"><span>Scope</span><input name="scope" value="${escapeHtml(gigachatValues.scope ?? "")}" /></label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Base URL</span><input name="base_url" value="${escapeHtml(gigachatValues.base_url ?? "")}" /></label>
            <label class="field"><span>Auth URL</span><input name="auth_url" value="${escapeHtml(gigachatValues.auth_url ?? "")}" /></label>
          </div>
          <div class="dual-grid">
            ${renderSecretField({
        name: "credentials",
        label: "Credentials",
        placeholder: "Paste new GigaChat credentials to replace the stored secret",
        preview: String(gigachatValues.credentials_preview ?? "not configured"),
        clearControlName: "clear_credentials",
        clearLabel: "Clear stored credentials on save",
    })}
            ${renderSecretField({
        name: "access_token",
        label: "Access token",
        placeholder: "Paste a new access token to replace the stored secret",
        preview: String(gigachatValues.access_token_preview ?? "not configured"),
        clearControlName: "clear_access_token",
        clearLabel: "Clear stored access token on save",
    })}
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Verify SSL</span>
              <select name="verify_ssl_certs">
                <option value="true" ${gigachatValues.verify_ssl_certs ? "selected" : ""}>on</option>
                <option value="false" ${!gigachatValues.verify_ssl_certs ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field"><span>Timeout</span><input name="timeout" type="number" min="1" step="1" value="${escapeHtml(gigachatValues.timeout ?? "")}" /></label>
          </div>
          <div class="toolbar">
            <button class="button" type="submit">Save GigaChat settings</button>
            <button class="button button--secondary" id="gigachat-test" type="button">Test connection</button>
          </div>
        </form>
      `, "panel panel--span-6")}
    ${card("Security", `
        <form id="security-form" class="stack">
          <label class="field">
            <span>Enable API key auth</span>
            <select name="enable_api_key_auth">
              <option value="true" ${securityValues.enable_api_key_auth ? "selected" : ""}>on</option>
              <option value="false" ${!securityValues.enable_api_key_auth ? "selected" : ""}>off</option>
            </select>
          </label>
          <label class="field"><span>Logs IP allowlist</span><input name="logs_ip_allowlist" value="${escapeHtml(csv(securityValues.logs_ip_allowlist))}" /></label>
          <label class="field"><span>CORS origins</span><input name="cors_allow_origins" value="${escapeHtml(csv(securityValues.cors_allow_origins))}" /></label>
          <label class="field"><span>Governance limits (JSON array)</span><textarea name="governance_limits">${escapeHtml(JSON.stringify(securityValues.governance_limits ?? [], null, 2))}</textarea></label>
          ${banner("Changes to auth and CORS are persisted immediately but require a restart before the mounted routes fully reflect them.", "warn")}
          <button class="button" type="submit">Save security settings</button>
        </form>
      `, "panel panel--span-4")}
    ${card("Pending diff before apply", `<div id="settings-pending-diff" class="stack"></div>`, "panel panel--span-4")}
    ${card("Recent revisions", revisions.length
        ? `
            <div class="stack">
              ${revisions
            .map((revision) => {
            const revisionId = String(revision.revision_id ?? "");
            return `
                    <article class="step-card">
                      <div class="stack">
                        <div class="toolbar">
                          <span class="pill">${escapeHtml(formatTimestamp(revision.updated_at))}</span>
                          <span class="pill">${escapeHtml(asArray(revision.sections).join(", ") || "no field diff")}</span>
                          <button class="button button--secondary" data-rollback-revision="${escapeHtml(revisionId)}" type="button">Rollback</button>
                        </div>
                        ${revision.restored_from_revision_id ? banner(`Rollback snapshot from revision ${String(revision.restored_from_revision_id)}.`) : ""}
                        ${renderDiffSections(asRecord(revision.diff), "Revision matches the current runtime config.")}
                      </div>
                    </article>
                  `;
        })
            .join("")}
            </div>
          `
        : `<p>No persisted revisions yet. Save a settings change to start revision history.</p>`, "panel panel--span-4")}
    ${card("Control-plane status", renderJson(application.control_plane ?? {}), "panel panel--span-12")}
  `);
    document.getElementById("reload-settings")?.addEventListener("click", () => {
        void app.render("settings");
    });
    const applicationForm = app.pageContent.querySelector("#application-form");
    const gigachatForm = app.pageContent.querySelector("#gigachat-form");
    const securityForm = app.pageContent.querySelector("#security-form");
    const pendingDiffNode = app.pageContent.querySelector("#settings-pending-diff");
    if (!applicationForm || !gigachatForm || !securityForm || !pendingDiffNode) {
        return;
    }
    const applicationFields = applicationForm.elements;
    const gigachatFields = gigachatForm.elements;
    const securityFields = securityForm.elements;
    bindValidityReset(applicationFields.enabled_providers, gigachatFields.timeout, securityFields.governance_limits);
    const validateEnabledProviders = () => {
        if (parseCsv(applicationFields.enabled_providers.value).length > 0) {
            applicationFields.enabled_providers.setCustomValidity("");
            return true;
        }
        applicationFields.enabled_providers.setCustomValidity("Provide at least one enabled provider.");
        applicationFields.enabled_providers.reportValidity();
        return false;
    };
    const validateGigachatTimeout = () => {
        const timeoutField = gigachatFields.timeout;
        if (!timeoutField) {
            return true;
        }
        const rawValue = timeoutField.value.trim();
        if (!rawValue) {
            timeoutField.setCustomValidity("");
            return true;
        }
        const numeric = Number(rawValue);
        if (Number.isFinite(numeric) && numeric > 0) {
            timeoutField.setCustomValidity("");
            return true;
        }
        timeoutField.setCustomValidity("Timeout must be a positive number of seconds.");
        timeoutField.reportValidity();
        return false;
    };
    const validateSecurityPayload = (payload) => {
        if (payload.governance_limits === INVALID_JSON) {
            securityFields.governance_limits.setCustomValidity("Governance limits must be valid JSON.");
            securityFields.governance_limits.reportValidity();
            return "Governance limits JSON is invalid.";
        }
        if (!Array.isArray(payload.governance_limits)) {
            securityFields.governance_limits.setCustomValidity("Governance limits must be a JSON array of rule descriptors.");
            securityFields.governance_limits.reportValidity();
            return "Governance limits must be a JSON array.";
        }
        securityFields.governance_limits.setCustomValidity("");
        return "";
    };
    const refreshPendingDiff = () => {
        const applicationEntries = buildPendingDiffEntries("application", applicationValues, buildApplicationPayload(applicationForm));
        const gigachatEntries = buildPendingDiffEntries("gigachat", gigachatValues, collectGigachatPayload(gigachatForm));
        const securityPayload = buildSecurityPayload(securityForm);
        const securityValidationError = securityPayload.governance_limits === INVALID_JSON
            ? "Governance limits JSON is invalid. Fix it before saving the security section."
            : !Array.isArray(securityPayload.governance_limits)
                ? "Governance limits must stay a JSON array."
                : "";
        pendingDiffNode.innerHTML = `
      ${securityValidationError ? banner(securityValidationError, "danger") : ""}
      ${renderDiffSections({
            application: applicationEntries,
            gigachat: gigachatEntries,
            security: buildPendingDiffEntries("security", securityValues, securityPayload),
        }, "Forms currently match the persisted runtime values.")}
    `;
    };
    refreshPendingDiff();
    [applicationForm, gigachatForm, securityForm].forEach((form) => {
        form.addEventListener("input", refreshPendingDiff);
        form.addEventListener("change", refreshPendingDiff);
    });
    applicationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!validateEnabledProviders()) {
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : applicationForm.querySelector('button[type="submit"]');
        await withBusyState({
            root: applicationForm,
            button,
            pendingLabel: "Saving…",
            action: async () => {
                const response = await app.api.json("/admin/api/settings/application", {
                    method: "PUT",
                    json: buildApplicationPayload(applicationForm),
                });
                app.queueAlert(response.restart_required
                    ? "Application settings saved. Restart required for part of the change set."
                    : "Application settings saved and applied.", response.restart_required ? "warn" : "info");
                await app.render("settings");
            },
        });
    });
    gigachatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!validateGigachatTimeout()) {
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : gigachatForm.querySelector('button[type="submit"]');
        await withBusyState({
            root: gigachatForm,
            button,
            pendingLabel: "Saving…",
            action: async () => {
                const response = await app.api.json("/admin/api/settings/gigachat", {
                    method: "PUT",
                    json: collectGigachatPayload(gigachatForm),
                });
                app.queueAlert(response.restart_required
                    ? "GigaChat settings saved. Restart required."
                    : "GigaChat settings saved and runtime reloaded.", response.restart_required ? "warn" : "info");
                await app.render("settings");
            },
        });
    });
    document.getElementById("gigachat-test")?.addEventListener("click", async (event) => {
        if (!validateGigachatTimeout()) {
            return;
        }
        const button = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
        await withBusyState({
            root: gigachatForm,
            button,
            pendingLabel: "Testing…",
            action: async () => {
                const result = await app.api.json("/admin/api/settings/gigachat/test", {
                    method: "POST",
                    json: collectGigachatPayload(gigachatForm),
                });
                app.pushAlert(result.ok
                    ? `GigaChat connection ok. Models visible: ${String(result.model_count ?? 0)}.`
                    : `GigaChat connection failed: ${String(result.error_type ?? "Error")}: ${String(result.error ?? "unknown error")}`, result.ok ? "info" : "danger");
            },
        });
    });
    securityForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = buildSecurityPayload(securityForm);
        const validationError = validateSecurityPayload(payload);
        if (validationError) {
            app.pushAlert(validationError, "danger");
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : securityForm.querySelector('button[type="submit"]');
        await withBusyState({
            root: securityForm,
            button,
            pendingLabel: "Saving…",
            action: async () => {
                const response = await app.api.json("/admin/api/settings/security", {
                    method: "PUT",
                    json: payload,
                });
                app.queueAlert(response.restart_required
                    ? "Security settings saved. Restart required."
                    : "Security settings saved and applied.", response.restart_required ? "warn" : "info");
                await app.render("settings");
            },
        });
    });
    app.pageContent.querySelectorAll("[data-rollback-revision]").forEach((button) => {
        button.addEventListener("click", async () => {
            const revisionId = button.dataset.rollbackRevision;
            if (!revisionId) {
                return;
            }
            if (!window.confirm(`Rollback settings to revision ${revisionId}?`)) {
                return;
            }
            const actionButton = button instanceof HTMLButtonElement ? button : null;
            await withBusyState({
                button: actionButton,
                pendingLabel: "Rolling back…",
                action: async () => {
                    const response = await app.api.json(`/admin/api/settings/revisions/${revisionId}/rollback`, { method: "POST" });
                    app.queueAlert(response.restart_required
                        ? `Revision ${revisionId} restored. Restart required for part of the rollback.`
                        : `Revision ${revisionId} restored and applied.`, response.restart_required ? "warn" : "info");
                    await app.render("settings");
                },
            });
        });
    });
}
