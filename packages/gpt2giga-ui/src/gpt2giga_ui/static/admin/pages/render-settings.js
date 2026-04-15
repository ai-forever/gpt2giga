import { bindValidityReset, buildApplicationPayload, buildObservabilityDiffEntries, buildObservabilityPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, describePersistOutcome, validateJsonArrayField, validateJsonObjectField, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../forms.js";
import {} from "./control-plane-actions.js";
import { bindControlPlaneSectionForm, bindGigachatConnectionTestAction, } from "./control-plane-form-bindings.js";
import { bindGigachatSecretFields, bindObservabilitySecretFields, renderApplicationSection, renderGigachatSection, renderObservabilitySection, renderSecuritySection, } from "./control-plane-sections.js";
import { collectSecretFieldMessages, renderInlineBannerStatus, } from "./control-plane-status.js";
import { banner, card, renderDiffSections, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatTimestamp, toErrorMessage, } from "../utils.js";
const SETTINGS_SECTIONS = [
    "application",
    "observability",
    "gigachat",
    "security",
    "history",
];
export async function renderSettings(app, token) {
    const [application, observability, gigachat, security, revisionsPayload] = await Promise.all([
        app.api.json("/admin/api/settings/application"),
        app.api.json("/admin/api/settings/observability"),
        app.api.json("/admin/api/settings/gigachat"),
        app.api.json("/admin/api/settings/security"),
        app.api.json("/admin/api/settings/revisions?limit=6"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const applicationValues = asRecord(application.values);
    const observabilityValues = asRecord(observability.values);
    const gigachatValues = asRecord(gigachat.values);
    const securityValues = asRecord(security.values);
    const controlPlaneStatus = asRecord(application.control_plane);
    const revisions = asArray(revisionsPayload.revisions);
    const selectedSection = getSelectedSettingsSection();
    app.setHeroActions(`<button class="button button--secondary" id="reload-settings" type="button">Reload values</button>`);
    app.setContent(`
    ${card("Settings", `
        <div class="stack">
          <p class="muted">Settings are split into focused sections. One group is visible at a time.</p>
          <div class="settings-switcher" id="settings-switcher">
            ${SETTINGS_SECTIONS.map((section) => renderSectionButton(section, selectedSection)).join("")}
          </div>
        </div>
      `, "panel panel--span-12")}
    ${card("Application", renderApplicationSection({
        bannerMessage: "Saving always updates the persisted control-plane target. Runtime only reloads immediately when this batch contains no restart-sensitive fields.",
        formId: "application-form",
        statusId: "settings-application-status",
        submitLabel: "Save application settings",
        values: applicationValues,
        variant: "settings",
    }), sectionPanelClass(selectedSection === "application", "panel panel--span-12"))}
    ${card("Observability", renderObservabilitySection({
        bannerMessage: "Observability now has its own control-plane slice. Sink toggles, endpoints, and masked auth values save independently from the general application posture.",
        formId: "observability-form",
        statusId: "settings-observability-status",
        submitLabel: "Save observability settings",
        values: observabilityValues,
    }), sectionPanelClass(selectedSection === "observability", "panel panel--span-12"))}
    ${card("GigaChat", renderGigachatSection({
        bannerMessage: "Connection tests use the candidate values without persisting them. Saving updates the persisted target first, then reloads runtime only when no restart-sensitive fields are present.",
        formId: "gigachat-form",
        statusId: "settings-gigachat-status",
        submitLabel: "Save GigaChat settings",
        testButtonId: "gigachat-test",
        testButtonLabel: "Test connection",
        values: gigachatValues,
        variant: "settings",
    }), sectionPanelClass(selectedSection === "gigachat", "panel panel--span-12"))}
    ${card("Security", renderSecuritySection({
        bannerMessage: "Auth and CORS always save to the control plane first. If this batch includes restart-sensitive fields, the running process keeps the previous posture until restart.",
        formId: "security-form",
        statusId: "settings-security-status",
        submitLabel: "Save security settings",
        values: securityValues,
        variant: "settings",
    }), sectionPanelClass(selectedSection === "security", "panel panel--span-12"))}
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
        : `<p>No persisted revisions yet. Save a settings change to start revision history.</p>`, sectionPanelClass(selectedSection === "history", "panel panel--span-8"))}
    ${card("Persistence", `
        <div class="stack">
          <div id="settings-revisions-status"></div>
          <div class="stat-line"><strong>Persisted target</strong><span class="muted">${Boolean(controlPlaneStatus.persisted) ? "saved" : "not saved yet"}</span></div>
          <div class="stat-line"><strong>Last update</strong><span class="muted">${escapeHtml(controlPlaneStatus.updated_at ? formatTimestamp(controlPlaneStatus.updated_at) : "n/a")}</span></div>
          <p class="muted">Rollback restores the persisted target first. Runtime follows immediately only when the restored change set is restart-safe.</p>
        </div>
      `, sectionPanelClass(selectedSection === "history", "panel panel--span-4"))}
  `);
    document.getElementById("reload-settings")?.addEventListener("click", () => {
        void app.render("settings");
    });
    app.pageContent.querySelectorAll("[data-settings-section]").forEach((button) => {
        button.addEventListener("click", () => {
            const section = button.dataset.settingsSection;
            if (!section) {
                return;
            }
            const url = new URL(window.location.href);
            url.searchParams.set("section", section);
            window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
            void app.render("settings");
        });
    });
    const applicationForm = app.pageContent.querySelector("#application-form");
    const observabilityForm = app.pageContent.querySelector("#observability-form");
    const gigachatForm = app.pageContent.querySelector("#gigachat-form");
    const securityForm = app.pageContent.querySelector("#security-form");
    const applicationStatusNode = app.pageContent.querySelector("#settings-application-status");
    const observabilityStatusNode = app.pageContent.querySelector("#settings-observability-status");
    const gigachatStatusNode = app.pageContent.querySelector("#settings-gigachat-status");
    const securityStatusNode = app.pageContent.querySelector("#settings-security-status");
    const revisionsStatusNode = app.pageContent.querySelector("#settings-revisions-status");
    if (!applicationForm ||
        !observabilityForm ||
        !gigachatForm ||
        !securityForm ||
        !applicationStatusNode ||
        !observabilityStatusNode ||
        !gigachatStatusNode ||
        !securityStatusNode ||
        !revisionsStatusNode) {
        return;
    }
    const applicationFields = applicationForm.elements;
    const observabilityFields = observabilityForm.elements;
    const gigachatFields = gigachatForm.elements;
    const securityFields = securityForm.elements;
    bindValidityReset(applicationFields.enabled_providers, observabilityFields.otlp_headers, gigachatFields.timeout, securityFields.governance_limits);
    const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(gigachatForm, gigachatValues);
    const { syncOtlpHeadersField, syncLangfusePublicKey, syncLangfuseSecretKey, syncPhoenixApiKey, } = bindObservabilitySecretFields(observabilityForm, observabilityValues);
    let revisionsActionState = null;
    const getApplicationValidationMessage = (_payload, report = false) => validateRequiredCsvField(applicationFields.enabled_providers, "Provide at least one enabled provider.", { report });
    const getGigachatValidationMessage = (_payload, report = false) => validatePositiveNumberField(gigachatFields.timeout, "Timeout must be a positive number of seconds.", { report });
    const getObservabilityValidationMessage = (payload, report = false) => validateJsonObjectField(observabilityFields.otlp_headers, (payload.otlp?.headers ?? null), {
        invalidMessage: "OTLP headers must be valid JSON.",
        nonObjectMessage: "OTLP headers must be a JSON object of header names to values.",
        report,
    });
    const getSecurityValidationMessage = (payload, report = false) => validateJsonArrayField(securityFields.governance_limits, payload.governance_limits, {
        invalidMessage: "Governance limits must be valid JSON.",
        nonArrayMessage: "Governance limits must be a JSON array of rule descriptors.",
        report,
    });
    const refreshRevisionsStatus = () => {
        renderInlineBannerStatus(revisionsStatusNode, revisionsActionState, "Use history only when you need to restore a known-good persisted snapshot.");
    };
    bindControlPlaneSectionForm({
        app,
        form: applicationForm,
        statusNode: applicationStatusNode,
        persisted: Boolean(controlPlaneStatus.persisted),
        updatedAt: controlPlaneStatus.updated_at,
        buildPayload: () => buildApplicationPayload(applicationForm),
        buildEntries: (payload) => buildPendingDiffEntries("application", applicationValues, payload),
        buildNote: () => "Mode, provider routing, runtime-store backend and auth-adjacent controls are the main restart-sensitive levers here.",
        getValidationMessage: getApplicationValidationMessage,
        endpoint: "/admin/api/settings/application",
        pendingMessage: "Saving application settings. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
        outcomeLabel: "Application settings",
        failurePrefix: "Application settings failed to save",
        rerenderPage: "settings",
    });
    bindControlPlaneSectionForm({
        app,
        form: observabilityForm,
        statusNode: observabilityStatusNode,
        persisted: Boolean(controlPlaneStatus.persisted),
        updatedAt: controlPlaneStatus.updated_at,
        buildPayload: () => buildObservabilityPayload(observabilityForm),
        buildEntries: (payload) => buildObservabilityDiffEntries(observabilityValues, payload),
        buildNote: () => {
            const observabilityFieldMessages = collectSecretFieldMessages([
                syncOtlpHeadersField(),
                syncLangfusePublicKey(),
                syncLangfuseSecretKey(),
                syncPhoenixApiKey(),
            ]);
            return observabilityFieldMessages.length
                ? `Sink changes apply live when telemetry stays enabled. ${observabilityFieldMessages.join(" ")}`
                : "Sink changes apply live and stay restart-safe unless a later backend slice marks them otherwise.";
        },
        getValidationMessage: getObservabilityValidationMessage,
        endpoint: "/admin/api/settings/observability",
        pendingMessage: "Saving observability settings. The persisted target updates first, then live sinks reload without a restart.",
        outcomeLabel: "Observability settings",
        failurePrefix: "Observability settings failed to save",
        rerenderPage: "settings",
    });
    const gigachatBinding = bindControlPlaneSectionForm({
        app,
        form: gigachatForm,
        statusNode: gigachatStatusNode,
        persisted: Boolean(controlPlaneStatus.persisted),
        updatedAt: controlPlaneStatus.updated_at,
        buildPayload: () => collectGigachatPayload(gigachatForm),
        buildEntries: (payload) => buildPendingDiffEntries("gigachat", gigachatValues, payload),
        buildNote: () => {
            const stagedSecretMessages = collectSecretFieldMessages([
                syncCredentialsSecret(),
                syncAccessTokenSecret(),
            ]);
            return stagedSecretMessages.length
                ? `Connection tests never persist the form. ${stagedSecretMessages.join(" ")}`
                : "Connection tests never persist the form. Secret values stay masked after save.";
        },
        getValidationMessage: getGigachatValidationMessage,
        endpoint: "/admin/api/settings/gigachat",
        pendingMessage: "Saving GigaChat settings. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
        outcomeLabel: "GigaChat settings",
        failurePrefix: "GigaChat settings failed to save",
        rerenderPage: "settings",
    });
    bindGigachatConnectionTestAction({
        app,
        form: gigachatForm,
        button: document.getElementById("gigachat-test"),
        buildPayload: () => collectGigachatPayload(gigachatForm),
        getValidationMessage: getGigachatValidationMessage,
        refreshStatus: gigachatBinding.refreshStatus,
        setActionState: (state) => {
            gigachatBinding.setActionState(state);
        },
        pendingMessage: "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save.",
    });
    bindControlPlaneSectionForm({
        app,
        form: securityForm,
        statusNode: securityStatusNode,
        persisted: Boolean(controlPlaneStatus.persisted),
        updatedAt: controlPlaneStatus.updated_at,
        buildPayload: () => buildSecurityPayload(securityForm),
        buildEntries: (payload) => buildPendingDiffEntries("security", securityValues, payload),
        buildNote: () => "Saved security changes always update the persisted target first. Runtime posture only changes immediately when the whole batch is restart-safe.",
        getValidationMessage: (payload, report = false) => getSecurityValidationMessage(payload, report),
        onValidationError: (message) => {
            app.pushAlert(message, "danger");
        },
        endpoint: "/admin/api/settings/security",
        pendingMessage: "Saving security settings. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
        outcomeLabel: "Security settings",
        failurePrefix: "Security settings failed to save",
        rerenderPage: "settings",
    });
    refreshRevisionsStatus();
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
            refreshRevisionsStatus();
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
                refreshRevisionsStatus();
                app.pushAlert(revisionsActionState.message, "danger");
            }
        });
    });
}
function getSelectedSettingsSection() {
    const value = new URLSearchParams(window.location.search).get("section");
    return SETTINGS_SECTIONS.includes(value)
        ? value
        : "application";
}
function renderSectionButton(section, selectedSection) {
    const labels = {
        application: "Basics",
        observability: "Observability",
        gigachat: "GigaChat",
        security: "Security",
        history: "History",
    };
    return `
    <button
      class="section-tab ${section === selectedSection ? "section-tab--active" : ""}"
      data-settings-section="${escapeHtml(section)}"
      type="button"
    >
      ${escapeHtml(labels[section])}
    </button>
  `;
}
function sectionPanelClass(isVisible, baseClass) {
    return isVisible ? baseClass : `${baseClass} is-hidden`;
}
