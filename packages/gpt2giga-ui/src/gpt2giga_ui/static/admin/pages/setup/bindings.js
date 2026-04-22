import { bindValidityReset, buildApplicationPayload, buildPendingDiffEntries, buildSecurityPayload, collectGigachatPayload, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../../forms.js";
import { asRecord } from "../../utils.js";
import { getSubmitterButton } from "../control-plane-actions.js";
import { bindControlPlaneSectionForm, bindGigachatConnectionTestAction, } from "../control-plane-form-bindings.js";
import { bindGigachatSecretFields } from "../control-plane-sections.js";
import { collectSecretFieldMessages } from "../control-plane-status.js";
export function bindSetupPage(app, state) {
    const claimForm = app.pageContent.querySelector("#setup-claim-form");
    const applicationForm = app.pageContent.querySelector("#setup-application-form");
    const gigachatForm = app.pageContent.querySelector("#setup-gigachat-form");
    const securityForm = app.pageContent.querySelector("#setup-security-form");
    const applicationStatusNode = app.pageContent.querySelector("#setup-application-status");
    const gigachatStatusNode = app.pageContent.querySelector("#setup-gigachat-status");
    const securityStatusNode = app.pageContent.querySelector("#setup-security-status");
    const applicationFields = applicationForm?.elements;
    const gigachatFields = gigachatForm?.elements;
    bindValidityReset(applicationFields?.enabled_providers, gigachatFields?.timeout);
    const [syncPasswordSecret, syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(gigachatForm ?? null, state.gigachatValues);
    claimForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const operatorLabel = form.elements.namedItem("operator_label").value.trim();
        const button = getSubmitterButton(event, form);
        await withBusyState({
            root: form,
            button,
            pendingLabel: "Claiming…",
            action: async () => {
                const response = await app.api.json("/admin/api/setup/claim", {
                    method: "POST",
                    json: {
                        operator_label: operatorLabel || null,
                    },
                });
                const nextClaim = asRecord(response.claim);
                app.queueAlert(nextClaim.operator_label
                    ? `Instance claimed by ${String(nextClaim.operator_label)}.`
                    : "Instance claim recorded.", "info");
                await app.render(state.currentPage);
            },
        });
    });
    if (applicationForm && applicationStatusNode) {
        bindControlPlaneSectionForm({
            app,
            form: applicationForm,
            statusNode: applicationStatusNode,
            persisted: state.persisted,
            updatedAt: state.persistedUpdatedAt,
            buildPayload: () => buildApplicationPayload(applicationForm),
            buildEntries: (payload) => buildPendingDiffEntries("application", state.applicationValues, payload),
            buildNote: () => "Restart-sensitive controls are flagged before save.",
            getValidationMessage: (_payload, report = false) => validateRequiredCsvField(applicationFields?.enabled_providers, "Provide at least one enabled provider.", { report }),
            endpoint: "/admin/api/settings/application",
            pendingMessage: "Saving the application bootstrap step. Restart-sensitive fields wait for restart.",
            outcomeLabel: "Application bootstrap step",
            failurePrefix: "Application bootstrap step failed to save",
            rerenderPage: state.currentPage,
        });
    }
    if (gigachatForm && gigachatStatusNode) {
        const getGigachatValidationMessage = (_payload, report = false) => validatePositiveNumberField(gigachatFields?.timeout, "Timeout must be a positive number of seconds.", { report });
        const gigachatBinding = bindControlPlaneSectionForm({
            app,
            form: gigachatForm,
            statusNode: gigachatStatusNode,
            persisted: state.persisted,
            updatedAt: state.persistedUpdatedAt,
            buildPayload: () => collectGigachatPayload(gigachatForm),
            buildEntries: (payload) => buildPendingDiffEntries("gigachat", state.gigachatValues, payload),
            buildNote: () => {
                const stagedSecretMessages = collectSecretFieldMessages([
                    syncPasswordSecret(),
                    syncCredentialsSecret(),
                    syncAccessTokenSecret(),
                ]);
                return stagedSecretMessages.length
                    ? `Connection test never saves. ${stagedSecretMessages.join(" ")}`
                    : "Connection test never saves. Review the pending state, then save.";
            },
            getValidationMessage: getGigachatValidationMessage,
            endpoint: "/admin/api/settings/gigachat",
            pendingMessage: "Saving the GigaChat bootstrap step. Secrets stay masked; restart-sensitive fields wait for restart.",
            outcomeLabel: "GigaChat bootstrap step",
            failurePrefix: "GigaChat bootstrap step failed to save",
            rerenderPage: state.currentPage,
        });
        bindGigachatConnectionTestAction({
            app,
            form: gigachatForm,
            button: document.getElementById("setup-gigachat-test"),
            buildPayload: () => collectGigachatPayload(gigachatForm),
            getValidationMessage: getGigachatValidationMessage,
            refreshStatus: gigachatBinding.refreshStatus,
            setActionState: (actionState) => {
                gigachatBinding.setActionState(actionState);
            },
            pendingMessage: "Testing candidate GigaChat settings only. Saved values stay unchanged.",
        });
    }
    if (securityForm && securityStatusNode) {
        bindControlPlaneSectionForm({
            app,
            form: securityForm,
            statusNode: securityStatusNode,
            persisted: state.persisted,
            updatedAt: state.persistedUpdatedAt,
            buildPayload: () => buildSecurityPayload(securityForm),
            buildEntries: (payload) => buildPendingDiffEntries("security", state.securityValues, payload),
            buildNote: () => "Gateway auth and CORS are the main restart-sensitive controls here.",
            endpoint: "/admin/api/settings/security",
            pendingMessage: "Saving the security bootstrap step. Restart-sensitive fields wait for restart.",
            outcomeLabel: "Security bootstrap step",
            failurePrefix: "Security bootstrap step failed to save",
            rerenderPage: state.currentPage,
        });
    }
    document.getElementById("setup-create-global-key")?.addEventListener("click", async (event) => {
        const input = document.getElementById("setup-global-key-value");
        const button = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
        await withBusyState({
            button,
            pendingLabel: "Creating…",
            action: async () => {
                const response = await app.api.json("/admin/api/keys/global/rotate", {
                    method: "POST",
                    json: { value: input?.value.trim() || null },
                });
                const nextGlobal = asRecord(response.global);
                app.saveAdminKey(String(nextGlobal.value ?? ""));
                app.saveGatewayKey(String(nextGlobal.value ?? ""));
                app.queueAlert(`Global gateway key created. New value: ${String(nextGlobal.value ?? "")}`, "warn");
                await app.render(state.currentPage);
            },
        });
    });
}
