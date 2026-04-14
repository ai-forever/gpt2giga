import { bindValidityReset, buildApplicationPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, describePersistOutcome, summarizePendingChanges, validateJsonArrayField, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../forms.js";
import { getSubmitterButton, persistControlPlaneSection, testGigachatConnection, } from "./control-plane-actions.js";
import { bindGigachatSecretFields, renderApplicationSection, renderGigachatSection, renderSecuritySection, } from "./control-plane-sections.js";
import { banner, card, pill, renderControlPlaneSectionStatus, renderDiffSections, } from "../templates.js";
import { asArray, asRecord, csv, escapeHtml, formatTimestamp, toErrorMessage, } from "../utils.js";
const SETTINGS_SECTIONS = [
    "application",
    "gigachat",
    "security",
    "history",
];
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
    const gigachatForm = app.pageContent.querySelector("#gigachat-form");
    const securityForm = app.pageContent.querySelector("#security-form");
    const applicationStatusNode = app.pageContent.querySelector("#settings-application-status");
    const gigachatStatusNode = app.pageContent.querySelector("#settings-gigachat-status");
    const securityStatusNode = app.pageContent.querySelector("#settings-security-status");
    const revisionsStatusNode = app.pageContent.querySelector("#settings-revisions-status");
    if (!applicationForm ||
        !gigachatForm ||
        !securityForm ||
        !applicationStatusNode ||
        !gigachatStatusNode ||
        !securityStatusNode ||
        !revisionsStatusNode) {
        return;
    }
    const applicationFields = applicationForm.elements;
    const gigachatFields = gigachatForm.elements;
    const securityFields = securityForm.elements;
    bindValidityReset(applicationFields.enabled_providers, gigachatFields.timeout, securityFields.governance_limits);
    const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(gigachatForm, gigachatValues);
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
    const refreshSectionStatus = () => {
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
            : banner("Use history only when you need to restore a known-good persisted snapshot.");
    };
    refreshSectionStatus();
    [applicationForm, gigachatForm, securityForm].forEach((form) => {
        form.addEventListener("input", refreshSectionStatus);
        form.addEventListener("change", refreshSectionStatus);
    });
    applicationForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (getApplicationValidationMessage(true)) {
            refreshSectionStatus();
            return;
        }
        await persistControlPlaneSection({
            app,
            form: applicationForm,
            button: getSubmitterButton(event, applicationForm),
            endpoint: "/admin/api/settings/application",
            payload: buildApplicationPayload(applicationForm),
            refreshStatus: refreshSectionStatus,
            setActionState: (state) => {
                applicationActionState = state;
            },
            pendingMessage: "Saving application settings. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
            outcomeLabel: "Application settings",
            failurePrefix: "Application settings failed to save",
            rerenderPage: "settings",
        });
    });
    gigachatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (getGigachatValidationMessage(true)) {
            refreshSectionStatus();
            return;
        }
        await persistControlPlaneSection({
            app,
            form: gigachatForm,
            button: getSubmitterButton(event, gigachatForm),
            endpoint: "/admin/api/settings/gigachat",
            payload: collectGigachatPayload(gigachatForm),
            refreshStatus: refreshSectionStatus,
            setActionState: (state) => {
                gigachatActionState = state;
            },
            pendingMessage: "Saving GigaChat settings. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
            outcomeLabel: "GigaChat settings",
            failurePrefix: "GigaChat settings failed to save",
            rerenderPage: "settings",
        });
    });
    document.getElementById("gigachat-test")?.addEventListener("click", async (event) => {
        if (getGigachatValidationMessage(true)) {
            refreshSectionStatus();
            return;
        }
        await testGigachatConnection({
            app,
            form: gigachatForm,
            button: event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null,
            payload: collectGigachatPayload(gigachatForm),
            refreshStatus: refreshSectionStatus,
            setActionState: (state) => {
                gigachatActionState = state;
            },
            pendingMessage: "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save.",
        });
    });
    securityForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = buildSecurityPayload(securityForm);
        const validationError = getSecurityValidationMessage(payload, true);
        if (validationError) {
            refreshSectionStatus();
            app.pushAlert(validationError, "danger");
            return;
        }
        await persistControlPlaneSection({
            app,
            form: securityForm,
            button: getSubmitterButton(event, securityForm),
            endpoint: "/admin/api/settings/security",
            payload,
            refreshStatus: refreshSectionStatus,
            setActionState: (state) => {
                securityActionState = state;
            },
            pendingMessage: "Saving security settings. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
            outcomeLabel: "Security settings",
            failurePrefix: "Security settings failed to save",
            rerenderPage: "settings",
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
            revisionsActionState = {
                tone: "warn",
                message: `Restoring revision ${revisionId}. The persisted target changes first; runtime only follows immediately if the rollback is restart-safe.`,
            };
            refreshSectionStatus();
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
                refreshSectionStatus();
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
