import { INVALID_JSON, bindValidityReset, bindSecretFieldBehavior, buildApplicationPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, describePersistOutcome, summarizePendingChanges, validateJsonArrayField, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../forms.js";
import { banner, card, renderBooleanSelectOptions, renderControlPlaneSectionStatus, renderDiffSections, renderJson, renderSecretField, pill, renderStaticSelectOptions, } from "../templates.js";
import { asArray, asRecord, csv, escapeHtml, formatTimestamp, toErrorMessage, } from "../utils.js";
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
    const controlPlaneStatus = asRecord(application.control_plane);
    const revisions = asArray(revisionsPayload.revisions);
    app.setHeroActions(`<button class="button button--secondary" id="reload-settings" type="button">Reload values</button>`);
    app.setContent(`
    ${card("Application", `
        <form id="application-form" class="stack">
          ${banner("Saving always updates the persisted control-plane target. Runtime only reloads immediately when this batch contains no restart-sensitive fields.")}
          <div id="settings-application-status"></div>
          <div class="dual-grid">
            <label class="field">
              <span>Mode</span>
              <select name="mode">
                ${renderStaticSelectOptions(String(applicationValues.mode ?? ""), ["DEV", "PROD"])}
              </select>
            </label>
            <label class="field">
              <span>GigaChat API mode</span>
              <select name="gigachat_api_mode">
                ${renderStaticSelectOptions(String(applicationValues.gigachat_api_mode ?? ""), ["v1", "v2"])}
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
                ${renderBooleanSelectOptions(Boolean(applicationValues.enable_telemetry))}
              </select>
            </label>
            <label class="field">
              <span>Pass model</span>
              <select name="pass_model">
                ${renderBooleanSelectOptions(Boolean(applicationValues.pass_model))}
              </select>
            </label>
            <label class="field">
              <span>Pass token</span>
              <select name="pass_token">
                ${renderBooleanSelectOptions(Boolean(applicationValues.pass_token))}
              </select>
            </label>
            <label class="field">
              <span>Reasoning</span>
              <select name="enable_reasoning">
                ${renderBooleanSelectOptions(Boolean(applicationValues.enable_reasoning))}
              </select>
            </label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Observability sinks</span><input name="observability_sinks" value="${escapeHtml(csv(applicationValues.observability_sinks))}" /></label>
            <label class="field">
              <span>Log level</span>
              <select name="log_level">
                ${renderStaticSelectOptions(String(applicationValues.log_level ?? ""), LOG_LEVELS)}
              </select>
            </label>
          </div>
          <button class="button" type="submit">Save application settings</button>
        </form>
      `, "panel panel--span-6")}
    ${card("GigaChat", `
        <form id="gigachat-form" class="stack">
          ${banner("Connection tests use the candidate values without persisting them. Saving updates the persisted target first, then reloads runtime only when no restart-sensitive fields are present.")}
          <div id="settings-gigachat-status"></div>
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
                ${renderBooleanSelectOptions(Boolean(gigachatValues.verify_ssl_certs))}
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
          <div id="settings-security-status"></div>
          <label class="field">
            <span>Enable API key auth</span>
            <select name="enable_api_key_auth">
              ${renderBooleanSelectOptions(Boolean(securityValues.enable_api_key_auth))}
            </select>
          </label>
          <label class="field"><span>Logs IP allowlist</span><input name="logs_ip_allowlist" value="${escapeHtml(csv(securityValues.logs_ip_allowlist))}" /></label>
          <label class="field"><span>CORS origins</span><input name="cors_allow_origins" value="${escapeHtml(csv(securityValues.cors_allow_origins))}" /></label>
          <label class="field"><span>Governance limits (JSON array)</span><textarea name="governance_limits">${escapeHtml(JSON.stringify(securityValues.governance_limits ?? [], null, 2))}</textarea></label>
          ${banner("Auth and CORS always save to the control plane first. If this batch includes restart-sensitive fields, the running process keeps the previous posture until restart.", "warn")}
          <button class="button" type="submit">Save security settings</button>
        </form>
      `, "panel panel--span-4")}
    ${card("Pending diff before apply", `<div id="settings-pending-diff" class="stack"></div>`, "panel panel--span-4")}
    ${card("Recent revisions", revisions.length
        ? `
            <div class="stack">
              <div id="settings-revisions-status"></div>
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
    const applicationStatusNode = app.pageContent.querySelector("#settings-application-status");
    const gigachatStatusNode = app.pageContent.querySelector("#settings-gigachat-status");
    const securityStatusNode = app.pageContent.querySelector("#settings-security-status");
    const pendingDiffNode = app.pageContent.querySelector("#settings-pending-diff");
    const revisionsStatusNode = app.pageContent.querySelector("#settings-revisions-status");
    if (!applicationForm ||
        !gigachatForm ||
        !securityForm ||
        !applicationStatusNode ||
        !gigachatStatusNode ||
        !securityStatusNode ||
        !pendingDiffNode ||
        !revisionsStatusNode) {
        return;
    }
    const applicationFields = applicationForm.elements;
    const gigachatFields = gigachatForm.elements;
    const securityFields = securityForm.elements;
    bindValidityReset(applicationFields.enabled_providers, gigachatFields.timeout, securityFields.governance_limits);
    const syncCredentialsSecret = bindSecretFieldBehavior({
        form: gigachatForm,
        fieldName: "credentials",
        clearFieldName: "clear_credentials",
        preview: String(gigachatValues.credentials_preview ?? "not configured"),
    });
    const syncAccessTokenSecret = bindSecretFieldBehavior({
        form: gigachatForm,
        fieldName: "access_token",
        clearFieldName: "clear_access_token",
        preview: String(gigachatValues.access_token_preview ?? "not configured"),
    });
    let applicationActionState = null;
    let gigachatActionState = null;
    let securityActionState = null;
    let revisionsActionState = null;
    const getApplicationValidationMessage = (report = false) => validateRequiredCsvField(applicationFields.enabled_providers, "Provide at least one enabled provider.", { report });
    const getGigachatValidationMessage = (report = false) => validatePositiveNumberField(gigachatFields.timeout, "Timeout must be a positive number of seconds.", { report });
    const getSecurityValidationMessage = (payload, report = false) => validateJsonArrayField(securityFields.governance_limits, payload.governance_limits, {
        invalidMessage: "Governance limits must be valid JSON.",
        nonArrayMessage: "Governance limits must be a JSON array of rule descriptors.",
        report,
    });
    const refreshPendingDiff = () => {
        const applicationEntries = buildPendingDiffEntries("application", applicationValues, buildApplicationPayload(applicationForm));
        const gigachatEntries = buildPendingDiffEntries("gigachat", gigachatValues, collectGigachatPayload(gigachatForm));
        const securityPayload = buildSecurityPayload(securityForm);
        const securityEntries = buildPendingDiffEntries("security", securityValues, securityPayload);
        const applicationValidationMessage = getApplicationValidationMessage();
        const gigachatValidationMessage = getGigachatValidationMessage();
        const securityValidationMessage = getSecurityValidationMessage(securityPayload);
        const secretStates = [syncCredentialsSecret(), syncAccessTokenSecret()].flatMap((state) => state ? [state] : []);
        const stagedSecretMessages = secretStates
            .filter((state) => state.intent !== "keep")
            .map((state) => state.message);
        applicationStatusNode.innerHTML = renderControlPlaneSectionStatus({
            summary: summarizePendingChanges(applicationEntries),
            persisted: Boolean(controlPlaneStatus.persisted),
            updatedAt: controlPlaneStatus.updated_at,
            note: "Mode, provider routing, runtime-store backend and auth-adjacent controls are the main restart-sensitive levers here.",
            validationMessage: applicationValidationMessage || undefined,
            actionState: applicationActionState,
        });
        gigachatStatusNode.innerHTML = renderControlPlaneSectionStatus({
            summary: summarizePendingChanges(gigachatEntries),
            persisted: Boolean(controlPlaneStatus.persisted),
            updatedAt: controlPlaneStatus.updated_at,
            note: stagedSecretMessages.length
                ? `Connection tests never persist the form. ${stagedSecretMessages.join(" ")}`
                : "Connection tests never persist the form. Secret values stay masked after save.",
            validationMessage: gigachatValidationMessage || undefined,
            actionState: gigachatActionState,
        });
        securityStatusNode.innerHTML = renderControlPlaneSectionStatus({
            summary: summarizePendingChanges(securityEntries),
            persisted: Boolean(controlPlaneStatus.persisted),
            updatedAt: controlPlaneStatus.updated_at,
            note: "Saved security changes always update the persisted target first. Runtime posture only changes immediately when the whole batch is restart-safe.",
            validationMessage: securityValidationMessage || undefined,
            actionState: securityActionState,
        });
        revisionsStatusNode.innerHTML = revisionsActionState
            ? banner(revisionsActionState.message, revisionsActionState.tone)
            : banner("Rollback restores the persisted target from history first. Runtime only follows immediately when the restored diff is restart-safe.");
        const validationMessages = [
            applicationValidationMessage,
            gigachatValidationMessage,
            securityValidationMessage
                ? (securityPayload.governance_limits === INVALID_JSON
                    ? "Governance limits JSON is invalid. Fix it before saving the security section."
                    : "Governance limits must stay a JSON array.")
                : "",
        ].filter(Boolean);
        pendingDiffNode.innerHTML = `
      ${validationMessages.map((message) => banner(message, "danger")).join("")}
      ${renderDiffSections({
            application: applicationEntries,
            gigachat: gigachatEntries,
            security: securityEntries,
        }, "Forms currently match the persisted control-plane target.")}
    `;
    };
    refreshPendingDiff();
    [applicationForm, gigachatForm, securityForm].forEach((form) => {
        form.addEventListener("input", refreshPendingDiff);
        form.addEventListener("change", refreshPendingDiff);
    });
    applicationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (getApplicationValidationMessage(true)) {
            refreshPendingDiff();
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : applicationForm.querySelector('button[type="submit"]');
        applicationActionState = {
            tone: "info",
            message: "Saving application settings. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
        };
        refreshPendingDiff();
        try {
            await withBusyState({
                root: applicationForm,
                button,
                pendingLabel: "Saving…",
                action: async () => {
                    const response = await app.api.json("/admin/api/settings/application", {
                        method: "PUT",
                        json: buildApplicationPayload(applicationForm),
                    });
                    const outcome = describePersistOutcome("Application settings", response);
                    app.queueAlert(outcome.message, outcome.tone);
                    await app.render("settings");
                },
            });
        }
        catch (error) {
            applicationActionState = {
                tone: "danger",
                message: `Application settings failed to save: ${toErrorMessage(error)}`,
            };
            refreshPendingDiff();
            app.pushAlert(applicationActionState.message, "danger");
        }
    });
    gigachatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (getGigachatValidationMessage(true)) {
            refreshPendingDiff();
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : gigachatForm.querySelector('button[type="submit"]');
        gigachatActionState = {
            tone: "info",
            message: "Saving GigaChat settings. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
        };
        refreshPendingDiff();
        try {
            await withBusyState({
                root: gigachatForm,
                button,
                pendingLabel: "Saving…",
                action: async () => {
                    const response = await app.api.json("/admin/api/settings/gigachat", {
                        method: "PUT",
                        json: collectGigachatPayload(gigachatForm),
                    });
                    const outcome = describePersistOutcome("GigaChat settings", response);
                    app.queueAlert(outcome.message, outcome.tone);
                    await app.render("settings");
                },
            });
        }
        catch (error) {
            gigachatActionState = {
                tone: "danger",
                message: `GigaChat settings failed to save: ${toErrorMessage(error)}`,
            };
            refreshPendingDiff();
            app.pushAlert(gigachatActionState.message, "danger");
        }
    });
    document.getElementById("gigachat-test")?.addEventListener("click", async (event) => {
        if (getGigachatValidationMessage(true)) {
            refreshPendingDiff();
            return;
        }
        const button = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
        gigachatActionState = {
            tone: "info",
            message: "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save.",
        };
        refreshPendingDiff();
        try {
            await withBusyState({
                root: gigachatForm,
                button,
                pendingLabel: "Testing…",
                action: async () => {
                    const result = await app.api.json("/admin/api/settings/gigachat/test", {
                        method: "POST",
                        json: collectGigachatPayload(gigachatForm),
                    });
                    gigachatActionState = result.ok
                        ? {
                            tone: "info",
                            message: `Connection ok. Models visible: ${String(result.model_count ?? 0)}. Candidate values were tested but not persisted.`,
                        }
                        : {
                            tone: "danger",
                            message: `Connection failed: ${String(result.error_type ?? "Error")}: ${String(result.error ?? "unknown error")}. Persisted values remain unchanged.`,
                        };
                    refreshPendingDiff();
                    app.pushAlert(gigachatActionState.message, gigachatActionState.tone);
                },
            });
        }
        catch (error) {
            gigachatActionState = {
                tone: "danger",
                message: `GigaChat connection test failed: ${toErrorMessage(error)}`,
            };
            refreshPendingDiff();
            app.pushAlert(gigachatActionState.message, "danger");
        }
    });
    securityForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = buildSecurityPayload(securityForm);
        const validationError = getSecurityValidationMessage(payload, true);
        if (validationError) {
            refreshPendingDiff();
            app.pushAlert(validationError, "danger");
            return;
        }
        const submitter = event.submitter;
        const button = submitter instanceof HTMLButtonElement
            ? submitter
            : securityForm.querySelector('button[type="submit"]');
        securityActionState = {
            tone: "info",
            message: "Saving security settings. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
        };
        refreshPendingDiff();
        try {
            await withBusyState({
                root: securityForm,
                button,
                pendingLabel: "Saving…",
                action: async () => {
                    const response = await app.api.json("/admin/api/settings/security", {
                        method: "PUT",
                        json: payload,
                    });
                    const outcome = describePersistOutcome("Security settings", response);
                    app.queueAlert(outcome.message, outcome.tone);
                    await app.render("settings");
                },
            });
        }
        catch (error) {
            securityActionState = {
                tone: "danger",
                message: `Security settings failed to save: ${toErrorMessage(error)}`,
            };
            refreshPendingDiff();
            app.pushAlert(securityActionState.message, "danger");
        }
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
            revisionsActionState = {
                tone: "warn",
                message: `Restoring revision ${revisionId}. The persisted target changes first; runtime only follows immediately if the rollback is restart-safe.`,
            };
            refreshPendingDiff();
            try {
                await withBusyState({
                    button: actionButton,
                    pendingLabel: "Rolling back…",
                    action: async () => {
                        const response = await app.api.json(`/admin/api/settings/revisions/${revisionId}/rollback`, { method: "POST" });
                        const outcome = describePersistOutcome(`Revision ${revisionId}`, response);
                        app.queueAlert(outcome.message, outcome.tone);
                        await app.render("settings");
                    },
                });
            }
            catch (error) {
                revisionsActionState = {
                    tone: "danger",
                    message: `Rollback for revision ${revisionId} failed: ${toErrorMessage(error)}`,
                };
                refreshPendingDiff();
                app.pushAlert(revisionsActionState.message, "danger");
            }
        });
    });
}
