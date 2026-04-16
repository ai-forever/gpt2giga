import { bindValidityReset, buildApplicationPayload, buildObservabilityDiffEntries, buildObservabilityPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, describePersistOutcome, validateJsonArrayField, validateJsonObjectField, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../forms.js";
import { subpagesFor } from "../routes.js";
import { banner, card, pill, renderDiffSections, renderSubpageNav, } from "../templates.js";
import { asArray, asRecord, escapeHtml, formatTimestamp, toErrorMessage, } from "../utils.js";
import {} from "./control-plane-actions.js";
import { bindControlPlaneSectionForm, bindGigachatConnectionTestAction, } from "./control-plane-form-bindings.js";
import { bindGigachatSecretFields, bindObservabilityPresetButtons, bindObservabilitySecretFields, renderApplicationSection, renderGigachatSection, renderObservabilitySection, renderSecuritySection, } from "./control-plane-sections.js";
import { collectSecretFieldMessages, renderInlineBannerStatus, } from "./control-plane-status.js";
const SETTINGS_LABELS = {
    application: "Application",
    observability: "Observability",
    gigachat: "GigaChat",
    security: "Security",
    history: "History",
};
export async function renderSettings(app, token) {
    await renderSettingsPage(app, token, "settings");
}
export async function renderSettingsApplication(app, token) {
    await renderSettingsPage(app, token, "settings-application");
}
export async function renderSettingsObservability(app, token) {
    await renderSettingsPage(app, token, "settings-observability");
}
export async function renderSettingsGigachat(app, token) {
    await renderSettingsPage(app, token, "settings-gigachat");
}
export async function renderSettingsSecurity(app, token) {
    await renderSettingsPage(app, token, "settings-security");
}
export async function renderSettingsHistory(app, token) {
    await renderSettingsPage(app, token, "settings-history");
}
async function renderSettingsPage(app, token, currentPage) {
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
    const activeSection = sectionForPage(currentPage);
    app.setHeroActions(`<button class="button button--secondary" id="reload-settings" type="button">Reload values</button>`);
    app.setContent(activeSection === null
        ? renderSettingsHub({
            currentPage,
            applicationValues,
            observabilityValues,
            gigachatValues,
            securityValues,
            controlPlaneStatus,
            revisions,
        })
        : renderFocusedSettingsPage({
            currentPage,
            activeSection,
            applicationValues,
            observabilityValues,
            gigachatValues,
            securityValues,
            controlPlaneStatus,
            revisions,
        }));
    document.getElementById("reload-settings")?.addEventListener("click", () => {
        void app.render(currentPage);
    });
    bindSettingsForms({
        app,
        currentPage,
        applicationValues,
        observabilityValues,
        gigachatValues,
        securityValues,
        controlPlaneStatus,
    });
    bindSettingsHistory({ app, currentPage, revisions });
}
function renderSettingsHub(options) {
    const activeSinks = asArray(options.observabilityValues.active_sinks);
    return `
    ${card("Configuration map", renderSubpageNav({
        currentPage: options.currentPage,
        title: "Settings pages",
        intro: "Keep one configuration concern per page. Open a focused section instead of working through a single long settings screen.",
        items: subpagesFor(options.currentPage),
    }), "panel panel--span-12")}
    ${card("Persistence posture", `
        <div class="stack">
          <div class="toolbar">
            ${pill(Boolean(options.controlPlaneStatus.persisted) ? "Persisted target saved" : "Persisted target pending", Boolean(options.controlPlaneStatus.persisted) ? "good" : "warn")}
            ${pill(options.controlPlaneStatus.updated_at
        ? `Last update: ${formatTimestamp(options.controlPlaneStatus.updated_at)}`
        : "No persisted updates yet")}
            ${pill(`Recent revisions: ${options.revisions.length}`)}
          </div>
          <p class="muted">
            The hub stays summary-first. Open a child page when one settings area needs actual edits, testing, or rollback.
          </p>
          ${options.revisions.length
        ? banner(`Latest persisted revision covers ${escapeHtml(asArray(options.revisions[0]?.sections).join(", ") || "no field diff")}.`)
        : banner("No persisted revisions yet. The first save will create history.", "warn")}
        </div>
      `, "panel panel--span-12")}
    ${renderSettingsEntryCard({
        title: "Application",
        href: "/admin/settings-application",
        description: "Runtime mode, provider posture, and restart-sensitive controls that shape the gateway baseline.",
        pills: [
            pill(`Mode: ${String(options.applicationValues.mode ?? "n/a")}`),
            pill(`Providers: ${asArray(options.applicationValues.enabled_providers).join(", ") || "none"}`),
            pill(`Store: ${String(options.applicationValues.runtime_store_backend ?? "n/a")}`),
        ],
    })}
    ${renderSettingsEntryCard({
        title: "Observability",
        href: "/admin/settings-observability",
        description: "Telemetry sink posture, preset staging, and runtime-safe observability changes.",
        pills: [
            pill(`Telemetry: ${Boolean(options.observabilityValues.enable_telemetry) ? "on" : "off"}`, Boolean(options.observabilityValues.enable_telemetry) ? "good" : "warn"),
            pill(`Sinks: ${activeSinks.join(", ") || "none"}`),
            pill(`Phoenix: ${asArray(options.observabilityValues.sinks)
                .some((sink) => sink.id === "phoenix" && sink.enabled)
                ? "enabled"
                : "off"}`),
        ],
    })}
    ${renderSettingsEntryCard({
        title: "GigaChat",
        href: "/admin/settings-gigachat",
        description: "Credentials, transport details, SSL posture, and connection testing for the provider surface.",
        pills: [
            pill(`Credentials: ${options.gigachatValues.credentials_configured ? "configured" : "missing"}`, options.gigachatValues.credentials_configured ? "good" : "warn"),
            pill(`Model: ${String(options.gigachatValues.model ?? "n/a")}`),
            pill(`Scope: ${String(options.gigachatValues.scope ?? "n/a")}`),
        ],
    })}
    ${renderSettingsEntryCard({
        title: "Security",
        href: "/admin/settings-security",
        description: "Gateway auth, logs access, CORS, and governance controls that affect operator exposure.",
        pills: [
            pill(`API key auth: ${Boolean(options.securityValues.enable_api_key_auth) ? "on" : "off"}`, Boolean(options.securityValues.enable_api_key_auth) ? "good" : "warn"),
            pill(`Logs allowlist: ${asArray(options.securityValues.logs_ip_allowlist).length || 0}`),
            pill(`CORS origins: ${asArray(options.securityValues.cors_allow_origins).length || 0}`),
        ],
    })}
    ${card("History", `
        <div class="stack">
          <p class="muted">
            Rollback and revision review now live on their own page so they do not compete with the forms.
          </p>
          ${options.revisions.length
        ? `
                  <div class="stack">
                    ${options.revisions
            .slice(0, 3)
            .map((revision) => `
                          <div class="stat-line">
                            <strong>${escapeHtml(formatTimestamp(revision.updated_at))}</strong>
                            <span class="muted">${escapeHtml(asArray(revision.sections).join(", ") || "no field diff")}</span>
                          </div>
                        `)
            .join("")}
                  </div>
                `
        : `<p class="muted">No revisions recorded yet.</p>`}
          <div class="toolbar">
            <a class="button" href="/admin/settings-history">Open history</a>
          </div>
        </div>
      `, "panel panel--span-12")}
  `;
}
function renderFocusedSettingsPage(options) {
    const mainContent = renderSettingsMainCard(options);
    const sidebar = renderSettingsSidebar(options);
    if (options.activeSection === "history") {
        return `
      ${card("Configuration map", renderSubpageNav({
            currentPage: options.currentPage,
            title: "Settings pages",
            intro: "History has its own page so rollback and diff review stay separate from form editing.",
            items: subpagesFor(options.currentPage),
        }), "panel panel--span-12")}
      ${mainContent}
      ${sidebar}
    `;
    }
    return `
    ${card(`${SETTINGS_LABELS[options.activeSection]} navigation`, renderSubpageNav({
        currentPage: options.currentPage,
        title: "Settings pages",
        intro: "Each child page keeps a single primary task on screen and leaves the rest available by URL.",
        items: subpagesFor(options.currentPage),
    }), "panel panel--span-12")}
    ${mainContent}
    ${sidebar}
  `;
}
function renderSettingsMainCard(options) {
    if (options.activeSection === "application") {
        return card("Application", renderApplicationSection({
            bannerMessage: "Saving always updates the persisted control-plane target. Runtime only reloads immediately when this batch contains no restart-sensitive fields.",
            formId: "application-form",
            statusId: "settings-application-status",
            submitLabel: "Save application settings",
            values: options.applicationValues,
            variant: "settings",
        }), "panel panel--span-8");
    }
    if (options.activeSection === "observability") {
        return card("Observability", renderObservabilitySection({
            bannerMessage: "Observability has its own control-plane slice. Sink toggles, endpoints, and masked auth values save independently from the general application posture.",
            formId: "observability-form",
            statusId: "settings-observability-status",
            submitLabel: "Save observability settings",
            values: options.observabilityValues,
        }), "panel panel--span-8");
    }
    if (options.activeSection === "gigachat") {
        return card("GigaChat", renderGigachatSection({
            bannerMessage: "Connection tests use candidate values without persisting them. Saving updates the persisted target first and only reloads runtime for restart-safe batches.",
            formId: "gigachat-form",
            statusId: "settings-gigachat-status",
            submitLabel: "Save GigaChat settings",
            testButtonId: "gigachat-test",
            testButtonLabel: "Test connection",
            values: options.gigachatValues,
            variant: "settings",
        }), "panel panel--span-8");
    }
    if (options.activeSection === "security") {
        return card("Security", renderSecuritySection({
            bannerMessage: "Auth and CORS save to the control plane first. If this batch includes restart-sensitive fields, the running process keeps the previous posture until restart.",
            formId: "security-form",
            statusId: "settings-security-status",
            submitLabel: "Save security settings",
            values: options.securityValues,
            variant: "settings",
        }), "panel panel--span-8");
    }
    return card("Recent revisions", options.revisions.length
        ? `
          <div class="stack">
            ${options.revisions
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
                      ${revision.restored_from_revision_id
                ? banner(`Rollback snapshot from revision ${String(revision.restored_from_revision_id)}.`)
                : ""}
                      ${renderDiffSections(asRecord(revision.diff), "Revision matches the current runtime config.")}
                    </div>
                  </article>
                `;
        })
            .join("")}
          </div>
        `
        : `<p>No persisted revisions yet. Save a settings change to start revision history.</p>`, "panel panel--span-8");
}
function renderSettingsSidebar(options) {
    const intro = (() => {
        if (options.activeSection === "application") {
            return "Keep this page focused on runtime posture. Observability, GigaChat, security, and rollback stay on their own URLs.";
        }
        if (options.activeSection === "observability") {
            return "Use presets only to stage sink values quickly. The rest of the settings surface stays off this page.";
        }
        if (options.activeSection === "gigachat") {
            return "Connection testing is intentionally local to this page so secrets and transport checks stay together.";
        }
        if (options.activeSection === "security") {
            return "This page owns auth-adjacent operator posture. Key inventory remains on the dedicated API Keys page.";
        }
        return "Review diffs and rollback here without sharing space with editable forms.";
    })();
    const detailPills = (() => {
        if (options.activeSection === "application") {
            return [
                pill(`Mode: ${String(options.applicationValues.mode ?? "n/a")}`),
                pill(`Providers: ${asArray(options.applicationValues.enabled_providers).join(", ") || "none"}`),
                pill(`Responses mode: ${String(options.applicationValues.gigachat_responses_api_mode ?? "inherit")}`),
            ];
        }
        if (options.activeSection === "observability") {
            return [
                pill(`Telemetry: ${Boolean(options.observabilityValues.enable_telemetry) ? "on" : "off"}`, Boolean(options.observabilityValues.enable_telemetry) ? "good" : "warn"),
                pill(`Sinks: ${asArray(options.observabilityValues.active_sinks).join(", ") || "none"}`),
                pill(`Phoenix project: ${String(options.observabilityValues.phoenix_project_name ?? "n/a")}`),
            ];
        }
        if (options.activeSection === "gigachat") {
            return [
                pill(`Credentials: ${options.gigachatValues.credentials_configured ? "configured" : "missing"}`, options.gigachatValues.credentials_configured ? "good" : "warn"),
                pill(`Model: ${String(options.gigachatValues.model ?? "n/a")}`),
                pill(`Verify SSL: ${Boolean(options.gigachatValues.verify_ssl_certs) ? "on" : "off"}`),
            ];
        }
        if (options.activeSection === "security") {
            return [
                pill(`API key auth: ${Boolean(options.securityValues.enable_api_key_auth) ? "on" : "off"}`, Boolean(options.securityValues.enable_api_key_auth) ? "good" : "warn"),
                pill(`Logs allowlist: ${asArray(options.securityValues.logs_ip_allowlist).length || 0}`),
                pill(`Governance rules: ${asArray(options.securityValues.governance_limits).length || 0}`),
            ];
        }
        return [
            pill(`Revisions: ${options.revisions.length}`),
            pill(options.controlPlaneStatus.updated_at
                ? `Last update: ${formatTimestamp(options.controlPlaneStatus.updated_at)}`
                : "No persisted update yet"),
            pill(Boolean(options.controlPlaneStatus.persisted) ? "Persisted target saved" : "Persisted target pending"),
        ];
    })();
    return card(options.activeSection === "history" ? "Rollback posture" : "Section posture", `
      <div class="stack">
        <p class="muted">${escapeHtml(intro)}</p>
        <div class="stack">
          <div id="settings-revisions-status"></div>
          <div class="toolbar">
            ${detailPills.join("")}
          </div>
          <div class="stat-line"><strong>Persisted target</strong><span class="muted">${Boolean(options.controlPlaneStatus.persisted) ? "saved" : "not saved yet"}</span></div>
          <div class="stat-line"><strong>Last update</strong><span class="muted">${escapeHtml(options.controlPlaneStatus.updated_at ? formatTimestamp(options.controlPlaneStatus.updated_at) : "n/a")}</span></div>
        </div>
        ${options.activeSection === "history"
        ? banner("Rollback restores the persisted target first. Runtime follows immediately only when the restored change set is restart-safe.", "warn")
        : banner("Use history only when you need to restore a known-good persisted snapshot.")}
        <div class="toolbar">
          <a class="button button--secondary" href="/admin/settings">Back to settings hub</a>
          ${options.activeSection === "history"
        ? `<a class="button" href="/admin/settings-application">Open application settings</a>`
        : `<a class="button" href="/admin/settings-history">Open history</a>`}
        </div>
      </div>
    `, "panel panel--span-4");
}
function renderSettingsEntryCard(options) {
    return card(options.title, `
      <div class="stack">
        <p class="muted">${escapeHtml(options.description)}</p>
        <div class="toolbar">
          ${options.pills.join("")}
        </div>
        <div class="toolbar">
          <a class="button" href="${escapeHtml(options.href)}">Open ${escapeHtml(options.title)}</a>
        </div>
      </div>
    `, "panel panel--span-6");
}
function bindSettingsForms(options) {
    const applicationForm = options.app.pageContent.querySelector("#application-form");
    const observabilityForm = options.app.pageContent.querySelector("#observability-form");
    const gigachatForm = options.app.pageContent.querySelector("#gigachat-form");
    const securityForm = options.app.pageContent.querySelector("#security-form");
    const applicationStatusNode = options.app.pageContent.querySelector("#settings-application-status");
    const observabilityStatusNode = options.app.pageContent.querySelector("#settings-observability-status");
    const gigachatStatusNode = options.app.pageContent.querySelector("#settings-gigachat-status");
    const securityStatusNode = options.app.pageContent.querySelector("#settings-security-status");
    const applicationFields = applicationForm?.elements;
    const observabilityFields = observabilityForm?.elements;
    const gigachatFields = gigachatForm?.elements;
    const securityFields = securityForm?.elements;
    bindValidityReset(applicationFields?.enabled_providers, observabilityFields?.otlp_headers, gigachatFields?.timeout, securityFields?.governance_limits);
    const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(gigachatForm ?? null, options.gigachatValues);
    const { syncOtlpHeadersField, syncLangfusePublicKey, syncLangfuseSecretKey, syncPhoenixApiKey, } = bindObservabilitySecretFields(observabilityForm, options.observabilityValues);
    if (applicationForm && applicationStatusNode) {
        bindControlPlaneSectionForm({
            app: options.app,
            form: applicationForm,
            statusNode: applicationStatusNode,
            persisted: Boolean(options.controlPlaneStatus.persisted),
            updatedAt: options.controlPlaneStatus.updated_at,
            buildPayload: () => buildApplicationPayload(applicationForm),
            buildEntries: (payload) => buildPendingDiffEntries("application", options.applicationValues, payload),
            buildNote: () => "Mode, provider routing, runtime-store backend and auth-adjacent controls are the main restart-sensitive levers here.",
            getValidationMessage: (_payload, report = false) => validateRequiredCsvField(applicationFields?.enabled_providers, "Provide at least one enabled provider.", { report }),
            endpoint: "/admin/api/settings/application",
            pendingMessage: "Saving application settings. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
            outcomeLabel: "Application settings",
            failurePrefix: "Application settings failed to save",
            rerenderPage: options.currentPage,
        });
    }
    if (observabilityForm && observabilityStatusNode) {
        const observabilityBinding = bindControlPlaneSectionForm({
            app: options.app,
            form: observabilityForm,
            statusNode: observabilityStatusNode,
            persisted: Boolean(options.controlPlaneStatus.persisted),
            updatedAt: options.controlPlaneStatus.updated_at,
            buildPayload: () => buildObservabilityPayload(observabilityForm),
            buildEntries: (payload) => buildObservabilityDiffEntries(options.observabilityValues, payload),
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
            getValidationMessage: (payload, report = false) => validateJsonObjectField(observabilityFields?.otlp_headers, (payload.otlp?.headers ?? null), {
                invalidMessage: "OTLP headers must be valid JSON.",
                nonObjectMessage: "OTLP headers must be a JSON object of header names to values.",
                report,
            }),
            endpoint: "/admin/api/settings/observability",
            pendingMessage: "Saving observability settings. The persisted target updates first, then live sinks reload without a restart.",
            outcomeLabel: "Observability settings",
            failurePrefix: "Observability settings failed to save",
            rerenderPage: options.currentPage,
        });
        bindObservabilityPresetButtons(observabilityForm, {
            refreshStatus: observabilityBinding.refreshStatus,
            setActionState: observabilityBinding.setActionState,
        });
    }
    if (gigachatForm && gigachatStatusNode) {
        const getGigachatValidationMessage = (_payload, report = false) => validatePositiveNumberField(gigachatFields?.timeout, "Timeout must be a positive number of seconds.", { report });
        const gigachatBinding = bindControlPlaneSectionForm({
            app: options.app,
            form: gigachatForm,
            statusNode: gigachatStatusNode,
            persisted: Boolean(options.controlPlaneStatus.persisted),
            updatedAt: options.controlPlaneStatus.updated_at,
            buildPayload: () => collectGigachatPayload(gigachatForm),
            buildEntries: (payload) => buildPendingDiffEntries("gigachat", options.gigachatValues, payload),
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
            rerenderPage: options.currentPage,
        });
        bindGigachatConnectionTestAction({
            app: options.app,
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
    }
    if (securityForm && securityStatusNode) {
        bindControlPlaneSectionForm({
            app: options.app,
            form: securityForm,
            statusNode: securityStatusNode,
            persisted: Boolean(options.controlPlaneStatus.persisted),
            updatedAt: options.controlPlaneStatus.updated_at,
            buildPayload: () => buildSecurityPayload(securityForm),
            buildEntries: (payload) => buildPendingDiffEntries("security", options.securityValues, payload),
            buildNote: () => "Saved security changes always update the persisted target first. Runtime posture only changes immediately when the whole batch is restart-safe.",
            getValidationMessage: (payload, report = false) => validateJsonArrayField(securityFields?.governance_limits, payload.governance_limits, {
                invalidMessage: "Governance limits must be valid JSON.",
                nonArrayMessage: "Governance limits must be a JSON array of rule descriptors.",
                report,
            }),
            onValidationError: (message) => {
                options.app.pushAlert(message, "danger");
            },
            endpoint: "/admin/api/settings/security",
            pendingMessage: "Saving security settings. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
            outcomeLabel: "Security settings",
            failurePrefix: "Security settings failed to save",
            rerenderPage: options.currentPage,
        });
    }
}
function bindSettingsHistory(options) {
    const revisionsStatusNode = options.app.pageContent.querySelector("#settings-revisions-status");
    if (!revisionsStatusNode) {
        return;
    }
    let revisionsActionState = null;
    const refreshRevisionsStatus = () => {
        renderInlineBannerStatus(revisionsStatusNode, revisionsActionState, "Use history only when you need to restore a known-good persisted snapshot.");
    };
    refreshRevisionsStatus();
    if (!options.revisions.length) {
        return;
    }
    options.app.pageContent.querySelectorAll("[data-rollback-revision]").forEach((button) => {
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
                        const response = await options.app.api.json(`/admin/api/settings/revisions/${revisionId}/rollback`, { method: "POST" });
                        const outcome = describePersistOutcome(`Revision ${revisionId}`, response);
                        options.app.queueAlert(outcome.message, outcome.tone);
                        await options.app.render(options.currentPage);
                    },
                });
            }
            catch (error) {
                revisionsActionState = {
                    tone: "danger",
                    message: `Rollback for revision ${revisionId} failed: ${toErrorMessage(error)}`,
                };
                refreshRevisionsStatus();
                options.app.pushAlert(revisionsActionState.message, "danger");
            }
        });
    });
}
function sectionForPage(page) {
    switch (page) {
        case "settings-application":
            return "application";
        case "settings-observability":
            return "observability";
        case "settings-gigachat":
            return "gigachat";
        case "settings-security":
            return "security";
        case "settings-history":
            return "history";
        default:
            return null;
    }
}
