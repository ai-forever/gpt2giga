import { bindValidityReset, buildApplicationPayload, buildObservabilityDiffEntries, buildObservabilityPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, describePersistOutcome, validateJsonArrayField, validateJsonObjectField, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../../forms.js";
import { toErrorMessage } from "../../utils.js";
import { bindControlPlaneSectionForm, bindGigachatConnectionTestAction, } from "../control-plane-form-bindings.js";
import { bindGigachatSecretFields, bindObservabilityPresetButtons, bindObservabilitySecretFields, } from "../control-plane-sections.js";
import { collectSecretFieldMessages, renderInlineBannerStatus, } from "../control-plane-status.js";
export function bindSettingsPage(app, state) {
    bindSettingsForms({ app, state });
    bindSettingsHistory({ app, state });
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
    const [syncPasswordSecret, syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(gigachatForm ?? null, options.state.gigachatValues);
    const { syncOtlpHeadersField, syncLangfusePublicKey, syncLangfuseSecretKey, syncPhoenixApiKey, } = bindObservabilitySecretFields(observabilityForm, options.state.observabilityValues);
    if (applicationForm && applicationStatusNode) {
        bindControlPlaneSectionForm({
            app: options.app,
            form: applicationForm,
            statusNode: applicationStatusNode,
            persisted: Boolean(options.state.controlPlaneStatus.persisted),
            updatedAt: options.state.controlPlaneStatus.updated_at,
            buildPayload: () => buildApplicationPayload(applicationForm),
            buildEntries: (payload) => buildPendingDiffEntries("application", options.state.applicationValues, payload),
            buildNote: () => "Restart-sensitive controls are flagged before save.",
            getValidationMessage: (_payload, report = false) => validateRequiredCsvField(applicationFields?.enabled_providers, "Provide at least one enabled provider.", { report }),
            endpoint: "/admin/api/settings/application",
            pendingMessage: "Saving application settings. Restart-sensitive fields wait for restart.",
            outcomeLabel: "Application settings",
            failurePrefix: "Application settings failed to save",
            rerenderPage: options.state.currentPage,
        });
    }
    if (observabilityForm && observabilityStatusNode) {
        const observabilityBinding = bindControlPlaneSectionForm({
            app: options.app,
            form: observabilityForm,
            statusNode: observabilityStatusNode,
            persisted: Boolean(options.state.controlPlaneStatus.persisted),
            updatedAt: options.state.controlPlaneStatus.updated_at,
            buildPayload: () => buildObservabilityPayload(observabilityForm),
            buildEntries: (payload) => buildObservabilityDiffEntries(options.state.observabilityValues, payload),
            buildNote: () => {
                const observabilityFieldMessages = collectSecretFieldMessages([
                    syncOtlpHeadersField(),
                    syncLangfusePublicKey(),
                    syncLangfuseSecretKey(),
                    syncPhoenixApiKey(),
                ]);
                return observabilityFieldMessages.length
                    ? `Sink changes apply live. ${observabilityFieldMessages.join(" ")}`
                    : "Sink changes apply live.";
            },
            getValidationMessage: (payload, report = false) => validateJsonObjectField(observabilityFields?.otlp_headers, (payload.otlp?.headers ?? null), {
                invalidMessage: "OTLP headers must be valid JSON.",
                nonObjectMessage: "OTLP headers must be a JSON object of header names to values.",
                report,
            }),
            endpoint: "/admin/api/settings/observability",
            pendingMessage: "Saving observability settings. Live sinks reload without restart.",
            outcomeLabel: "Observability settings",
            failurePrefix: "Observability settings failed to save",
            rerenderPage: options.state.currentPage,
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
            persisted: Boolean(options.state.controlPlaneStatus.persisted),
            updatedAt: options.state.controlPlaneStatus.updated_at,
            buildPayload: () => collectGigachatPayload(gigachatForm),
            buildEntries: (payload) => buildPendingDiffEntries("gigachat", options.state.gigachatValues, payload),
            buildNote: () => {
                const stagedSecretMessages = collectSecretFieldMessages([
                    syncPasswordSecret(),
                    syncCredentialsSecret(),
                    syncAccessTokenSecret(),
                ]);
                return stagedSecretMessages.length
                    ? `Connection test never saves. ${stagedSecretMessages.join(" ")}`
                    : "Connection test never saves. Secret values stay masked after save.";
            },
            getValidationMessage: getGigachatValidationMessage,
            endpoint: "/admin/api/settings/gigachat",
            pendingMessage: "Saving GigaChat settings. Secrets stay masked; restart-sensitive fields wait for restart.",
            outcomeLabel: "GigaChat settings",
            failurePrefix: "GigaChat settings failed to save",
            rerenderPage: options.state.currentPage,
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
            pendingMessage: "Testing candidate GigaChat settings only. Saved values stay unchanged.",
        });
    }
    if (securityForm && securityStatusNode) {
        bindControlPlaneSectionForm({
            app: options.app,
            form: securityForm,
            statusNode: securityStatusNode,
            persisted: Boolean(options.state.controlPlaneStatus.persisted),
            updatedAt: options.state.controlPlaneStatus.updated_at,
            buildPayload: () => buildSecurityPayload(securityForm),
            buildEntries: (payload) => buildPendingDiffEntries("security", options.state.securityValues, payload),
            buildNote: () => "Restart-sensitive controls are flagged before save.",
            getValidationMessage: (payload, report = false) => validateJsonArrayField(securityFields?.governance_limits, payload.governance_limits, {
                invalidMessage: "Governance limits must be valid JSON.",
                nonArrayMessage: "Governance limits must be a JSON array of rule descriptors.",
                report,
            }),
            onValidationError: (message) => {
                options.app.pushAlert(message, "danger");
            },
            endpoint: "/admin/api/settings/security",
            pendingMessage: "Saving security settings. Restart-sensitive fields wait for restart.",
            outcomeLabel: "Security settings",
            failurePrefix: "Security settings failed to save",
            rerenderPage: options.state.currentPage,
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
        renderInlineBannerStatus(revisionsStatusNode, revisionsActionState, "Use history only when you need a known-good snapshot.");
    };
    refreshRevisionsStatus();
    if (!options.state.revisions.length) {
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
                        await options.app.render(options.state.currentPage);
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
