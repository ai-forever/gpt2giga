import { bindValidityReset, buildApplicationPayload, buildSecurityPayload, buildPendingDiffEntries, collectGigachatPayload, validatePositiveNumberField, validateRequiredCsvField, withBusyState, } from "../forms.js";
import { getSubmitterButton } from "./control-plane-actions.js";
import { bindControlPlaneSectionForm, bindGigachatConnectionTestAction, } from "./control-plane-form-bindings.js";
import { bindGigachatSecretFields, renderApplicationSection, renderGigachatSection, renderSetupObservabilityHandoff, renderSecuritySection, } from "./control-plane-sections.js";
import { collectSecretFieldMessages, } from "./control-plane-status.js";
import { card, pill, banner, renderSetupSteps, } from "../templates.js";
import { asArray, asRecord, escapeHtml, } from "../utils.js";
export async function renderSetup(app, token) {
    const [setup, runtime, application, observability, gigachat, security, keys] = await Promise.all([
        app.api.json("/admin/api/setup"),
        app.api.json("/admin/api/runtime"),
        app.api.json("/admin/api/settings/application"),
        app.api.json("/admin/api/settings/observability"),
        app.api.json("/admin/api/settings/gigachat"),
        app.api.json("/admin/api/settings/security"),
        app.api.json("/admin/api/keys"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const claim = asRecord(setup.claim);
    const bootstrap = asRecord(setup.bootstrap);
    const applicationValues = asRecord(application.values);
    const observabilityValues = asRecord(observability.values);
    const gigachatValues = asRecord(gigachat.values);
    const securityValues = asRecord(security.values);
    const globalKey = asRecord(asRecord(keys.global));
    const scopedKeys = asArray(keys.scoped);
    const warnings = asArray(setup.warnings);
    const persisted = Boolean(setup.persisted);
    const persistedUpdatedAt = setup.updated_at;
    app.setHeroActions(`
    <button class="button button--secondary" id="refresh-setup" type="button">Refresh setup state</button>
    <a class="button" href="/admin/settings">Open full settings</a>
  `);
    app.setContent(`
    ${card("Setup progress", `
        <div class="stack">
          ${renderSetupSteps(asArray(setup.wizard_steps))}
          ${bootstrap.required
        ? banner(`Bootstrap gate is active. Admin setup is currently limited to localhost or the bootstrap token stored at ${String(bootstrap.token_path ?? "the control-plane volume")}.`, "warn")
        : banner("Bootstrap gate is closed. Normal operator access now relies on the configured admin/global API key path.")}
          <div class="dual-grid">
            <div class="stack">
              <div class="stat-line"><strong>Claim status</strong><span class="muted">${claim.claimed ? "claimed" : claim.required ? "pending" : "not required"}</span></div>
              <div class="stat-line"><strong>Control-plane file</strong><span class="muted">${escapeHtml(setup.path ?? "n/a")}</span></div>
              <div class="stat-line"><strong>Encryption key file</strong><span class="muted">${escapeHtml(setup.key_path ?? "n/a")}</span></div>
              <div class="stat-line"><strong>Runtime mode</strong><span class="muted">${escapeHtml(runtime.mode ?? "n/a")}</span></div>
              <div class="stat-line"><strong>Store backend</strong><span class="muted">${escapeHtml(runtime.runtime_store_backend ?? "n/a")}</span></div>
            </div>
            <div class="stack">
              ${claim.claimed ? `<span class="pill">Claimed at: ${escapeHtml(claim.claimed_at ?? "n/a")}</span>` : ""}
              ${claim.claimed ? `<span class="pill">Operator: ${escapeHtml(claim.operator_label ?? "not recorded")}</span>` : ""}
              ${bootstrap.required ? `<span class="pill">Bootstrap localhost access: ${bootstrap.allow_localhost ? "on" : "off"}</span>` : ""}
              ${bootstrap.required ? `<span class="pill">Bootstrap token access: ${bootstrap.allow_token ? "on" : "off"}</span>` : ""}
              ${warnings.length
        ? warnings.map((warning) => banner(String(warning), "warn")).join("")
        : banner("Setup checks look healthy. You can move on to playground and traffic pages.")}
            </div>
          </div>
        </div>
      `, "panel panel--span-12")}
    ${card("Step 1 · Claim instance", `
        <div class="stack">
          ${banner(claim.required
        ? claim.claimed
            ? `This bootstrap session is already claimed${claim.operator_label ? ` by ${String(claim.operator_label)}` : ""}.`
            : "First-run PROD bootstrap is active. Claim the instance before continuing with operator setup."
        : "Claiming is not required in the current runtime mode.", claim.claimed ? "info" : "warn")}
          ${claim.claimed
        ? `
                  <div class="dual-grid">
                    <div class="stack">
                      ${pill(`Claimed at: ${String(claim.claimed_at ?? "n/a")}`)}
                      ${pill(`Claimed via: ${String(claim.claimed_via ?? "n/a")}`)}
                    </div>
                    <div class="stack">
                      ${pill(`Operator label: ${String(claim.operator_label ?? "not recorded")}`)}
                      ${pill(`Source IP: ${String(claim.claimed_from ?? "unknown")}`)}
                    </div>
                  </div>
                `
        : claim.required
            ? `
                    <form id="setup-claim-form" class="stack">
                      <label class="field">
                        <span>Operator label (optional)</span>
                        <input name="operator_label" placeholder="Primary operator" />
                      </label>
                      <div class="toolbar">
                        <button class="button" type="submit">Claim this instance</button>
                      </div>
                    </form>
                  `
            : ""}
        </div>
      `, "panel panel--span-4")}
    ${card("Step 2 · Application posture", renderApplicationSection({
        bannerMessage: "Saving always updates the persisted control-plane target. Runtime only reloads immediately when this bootstrap step stays restart-safe.",
        formId: "setup-application-form",
        statusId: "setup-application-status",
        submitLabel: "Save application step",
        values: applicationValues,
        variant: "setup",
    }), "panel panel--span-4")}
    ${card("Step 3 · GigaChat auth", renderGigachatSection({
        bannerMessage: "Connection tests use the candidate values without persisting them. Saving updates the persisted target first, then reloads runtime only when the batch is restart-safe.",
        formId: "setup-gigachat-form",
        statusId: "setup-gigachat-status",
        submitLabel: "Save GigaChat step",
        testButtonId: "setup-gigachat-test",
        testButtonLabel: "Test connection",
        values: gigachatValues,
        variant: "setup",
    }), "panel panel--span-4")}
    ${card("Step 4 · Security bootstrap", `
        <div class="stack">
          ${renderSecuritySection({
        bannerMessage: "Security bootstrap saves to the control plane first. If this step includes restart-sensitive changes, the running process keeps the previous posture until restart.",
        formId: "setup-security-form",
        statusId: "setup-security-status",
        submitLabel: "Save security step",
        values: securityValues,
        variant: "setup",
    })}
          <div class="dual-grid">
            <div class="stack">
              ${pill(`Global key: ${globalKey.configured ? "configured" : "missing"}`)}
              ${pill(`Scoped keys: ${scopedKeys.length}`)}
              ${pill(`Preview: ${String(globalKey.key_preview ?? "not configured")}`)}
            </div>
            <div class="stack">
              <label class="field">
                <span>Custom global key (optional)</span>
                <input id="setup-global-key-value" placeholder="Leave blank to auto-generate" />
              </label>
              <div class="toolbar">
                <button class="button" id="setup-create-global-key" type="button">Create or rotate global key</button>
                <a class="button button--secondary" href="/admin/keys">Open API keys page</a>
              </div>
            </div>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Optional · Observability", renderSetupObservabilityHandoff(observabilityValues), "panel panel--span-4")}
    ${card("Step 5 · Finish", `
        <div class="stack">
          ${pill(`Claimed instance: ${claim.claimed ? "yes" : claim.required ? "pending" : "not required"}`)}
          ${pill(`Persisted config: ${setup.persisted ? "yes" : "no"}`)}
          ${pill(`GigaChat ready: ${setup.gigachat_ready ? "yes" : "no"}`)}
          ${pill(`Security ready: ${setup.security_ready ? "yes" : "no"}`)}
          ${pill(`Observability sinks: ${asArray(observabilityValues.active_sinks).join(", ") || "none"}`)}
          ${setup.setup_complete
        ? banner("Bootstrap path is complete. The operator console can now be used as the main control plane.")
        : banner("Bootstrap is not complete yet. Finish the missing steps above before relying on zero-env restarts or exposing the gateway.", "warn")}
          <div class="toolbar">
            <a class="button button--secondary" href="/admin">Back to overview</a>
            <a class="button" href="/admin/playground">Open playground</a>
          </div>
        </div>
      `, "panel panel--span-12")}
  `);
    document.getElementById("refresh-setup")?.addEventListener("click", () => {
        void app.render("setup");
    });
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
    const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(gigachatForm ?? null, gigachatValues);
    const getApplicationValidationMessage = (_payload, report = false) => validateRequiredCsvField(applicationFields?.enabled_providers, "Provide at least one enabled provider.", { report });
    const getGigachatValidationMessage = (_payload, report = false) => validatePositiveNumberField(gigachatFields?.timeout, "Timeout must be a positive number of seconds.", { report });
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
                await app.render("setup");
            },
        });
    });
    if (applicationForm && applicationStatusNode && gigachatForm && gigachatStatusNode && securityForm && securityStatusNode) {
        bindControlPlaneSectionForm({
            app,
            form: applicationForm,
            statusNode: applicationStatusNode,
            persisted,
            updatedAt: persistedUpdatedAt,
            buildPayload: () => buildApplicationPayload(applicationForm),
            buildEntries: (payload) => buildPendingDiffEntries("application", applicationValues, payload),
            buildNote: () => "Use this step for runtime posture and provider routing. Restart-sensitive controls are called out before you save.",
            getValidationMessage: getApplicationValidationMessage,
            endpoint: "/admin/api/settings/application",
            pendingMessage: "Saving the application bootstrap step. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
            outcomeLabel: "Application bootstrap step",
            failurePrefix: "Application bootstrap step failed to save",
            rerenderPage: "setup",
        });
        const gigachatBinding = bindControlPlaneSectionForm({
            app,
            form: gigachatForm,
            statusNode: gigachatStatusNode,
            persisted,
            updatedAt: persistedUpdatedAt,
            buildPayload: () => collectGigachatPayload(gigachatForm),
            buildEntries: (payload) => buildPendingDiffEntries("gigachat", gigachatValues, payload),
            buildNote: () => {
                const stagedSecretMessages = collectSecretFieldMessages([
                    syncCredentialsSecret(),
                    syncAccessTokenSecret(),
                ]);
                return stagedSecretMessages.length
                    ? `Testing the connection here does not persist the form. ${stagedSecretMessages.join(" ")}`
                    : "Testing the connection here does not persist the form; save only after the pending state looks correct.";
            },
            getValidationMessage: getGigachatValidationMessage,
            endpoint: "/admin/api/settings/gigachat",
            pendingMessage: "Saving the GigaChat bootstrap step. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
            outcomeLabel: "GigaChat bootstrap step",
            failurePrefix: "GigaChat bootstrap step failed to save",
            rerenderPage: "setup",
        });
        bindGigachatConnectionTestAction({
            app,
            form: gigachatForm,
            button: document.getElementById("setup-gigachat-test"),
            buildPayload: () => collectGigachatPayload(gigachatForm),
            getValidationMessage: getGigachatValidationMessage,
            refreshStatus: gigachatBinding.refreshStatus,
            setActionState: (state) => {
                gigachatBinding.setActionState(state);
            },
            pendingMessage: "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save this step.",
        });
        bindControlPlaneSectionForm({
            app,
            form: securityForm,
            statusNode: securityStatusNode,
            persisted,
            updatedAt: persistedUpdatedAt,
            buildPayload: () => buildSecurityPayload(securityForm),
            buildEntries: (payload) => buildPendingDiffEntries("security", securityValues, payload),
            buildNote: () => "Gateway auth posture and CORS are the main restart-sensitive controls in this step.",
            endpoint: "/admin/api/settings/security",
            pendingMessage: "Saving the security bootstrap step. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
            outcomeLabel: "Security bootstrap step",
            failurePrefix: "Security bootstrap step failed to save",
            rerenderPage: "setup",
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
                await app.render("setup");
            },
        });
    });
}
