import type { AdminApp } from "../app.js";
import {
  bindValidityReset,
  bindSecretFieldBehavior,
  buildApplicationPayload,
  buildPendingDiffEntries,
  collectGigachatPayload,
  describePersistOutcome,
  summarizePendingChanges,
  validatePositiveNumberField,
  validateRequiredCsvField,
  withBusyState,
} from "../forms.js";
import {
  banner,
  card,
  pill,
  renderBooleanSelectOptions,
  renderControlPlaneSectionStatus,
  renderSecretField,
  renderStaticSelectOptions,
  renderSetupSteps,
} from "../templates.js";
import {
  asArray,
  asRecord,
  csv,
  escapeHtml,
  parseCsv,
  toErrorMessage,
} from "../utils.js";

type SetupApplicationFormElements = HTMLFormControlsCollection & {
  enabled_providers: HTMLInputElement;
};

type SetupGigachatFormElements = HTMLFormControlsCollection & {
  timeout?: HTMLInputElement;
};

type InlineStatus = {
  tone: "info" | "warn" | "danger";
  message: string;
};

export async function renderSetup(app: AdminApp, token: number): Promise<void> {
  const [setup, runtime, application, gigachat, security, keys] = await Promise.all([
    app.api.json<Record<string, unknown>>("/admin/api/setup"),
    app.api.json<Record<string, unknown>>("/admin/api/runtime"),
    app.api.json<Record<string, unknown>>("/admin/api/settings/application"),
    app.api.json<Record<string, unknown>>("/admin/api/settings/gigachat"),
    app.api.json<Record<string, unknown>>("/admin/api/settings/security"),
    app.api.json<Record<string, unknown>>("/admin/api/keys"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const claim = asRecord(setup.claim);
  const bootstrap = asRecord(setup.bootstrap);
  const applicationValues = asRecord(application.values);
  const gigachatValues = asRecord(gigachat.values);
  const securityValues = asRecord(security.values);
  const globalKey = asRecord(asRecord(keys.global));
  const scopedKeys = asArray<Record<string, unknown>>(keys.scoped);
  const warnings = asArray<string>(setup.warnings);
  const persisted = Boolean(setup.persisted);
  const persistedUpdatedAt = setup.updated_at;

  app.setHeroActions(`
    <button class="button button--secondary" id="refresh-setup" type="button">Refresh setup state</button>
    <a class="button" href="/admin/settings">Open full settings</a>
  `);

  app.setContent(`
    ${card(
      "Setup progress",
      `
        <div class="stack">
          ${renderSetupSteps(asArray(setup.wizard_steps))}
          ${
            bootstrap.required
              ? banner(
                  `Bootstrap gate is active. Admin setup is currently limited to localhost or the bootstrap token stored at ${String(bootstrap.token_path ?? "the control-plane volume")}.`,
                  "warn",
                )
              : banner(
                  "Bootstrap gate is closed. Normal operator access now relies on the configured admin/global API key path.",
                )
          }
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
              ${
                warnings.length
                  ? warnings.map((warning) => banner(String(warning), "warn")).join("")
                  : banner("Setup checks look healthy. You can move on to playground and traffic pages.")
              }
            </div>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Step 1 · Claim instance",
      `
        <div class="stack">
          ${banner(
            claim.required
              ? claim.claimed
                ? `This bootstrap session is already claimed${claim.operator_label ? ` by ${String(claim.operator_label)}` : ""}.`
                : "First-run PROD bootstrap is active. Claim the instance before continuing with operator setup."
              : "Claiming is not required in the current runtime mode.",
            claim.claimed ? "info" : "warn",
          )}
          ${
            claim.claimed
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
                : ""
          }
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Step 2 · Application posture",
      `
        <form id="setup-application-form" class="stack">
          ${banner("Saving always updates the persisted control-plane target. Runtime only reloads immediately when this bootstrap step stays restart-safe.")}
          <div id="setup-application-status"></div>
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
            <label class="field">
              <span>Enabled providers</span>
              <input name="enabled_providers" value="${escapeHtml(csv(applicationValues.enabled_providers))}" />
            </label>
            <label class="field">
              <span>Observability sinks</span>
              <input name="observability_sinks" value="${escapeHtml(csv(applicationValues.observability_sinks))}" />
            </label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Runtime store backend</span>
              <select name="runtime_store_backend">
                ${renderStaticSelectOptions(String(applicationValues.runtime_store_backend ?? ""), ["memory", "sqlite"])}
              </select>
            </label>
            <label class="field">
              <span>Runtime namespace</span>
              <input name="runtime_store_namespace" value="${escapeHtml(applicationValues.runtime_store_namespace ?? "")}" />
            </label>
          </div>
          <div class="triple-grid">
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
          </div>
          <button class="button" type="submit">Save application step</button>
        </form>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Step 3 · GigaChat auth",
      `
        <form id="setup-gigachat-form" class="stack">
          ${banner("Connection tests use the candidate values without persisting them. Saving updates the persisted target first, then reloads runtime only when the batch is restart-safe.")}
          <div id="setup-gigachat-status"></div>
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
          <label class="field">
            <span>Verify SSL</span>
            <select name="verify_ssl_certs">
              ${renderBooleanSelectOptions(Boolean(gigachatValues.verify_ssl_certs))}
            </select>
          </label>
          <label class="field">
            <span>Timeout</span>
            <input name="timeout" type="number" min="1" step="1" value="${escapeHtml(gigachatValues.timeout ?? "")}" />
          </label>
          <div class="toolbar">
            <button class="button" type="submit">Save GigaChat step</button>
            <button class="button button--secondary" id="setup-gigachat-test" type="button">Test connection</button>
          </div>
        </form>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Step 4 · Security bootstrap",
      `
        <div class="stack">
          <form id="setup-security-form" class="stack">
            ${banner("Security bootstrap saves to the control plane first. If this step includes restart-sensitive changes, the running process keeps the previous posture until restart.", "warn")}
            <div id="setup-security-status"></div>
            <label class="field">
              <span>Enable gateway API key auth</span>
              <select name="enable_api_key_auth">
                ${renderBooleanSelectOptions(Boolean(securityValues.enable_api_key_auth))}
              </select>
            </label>
            <label class="field">
              <span>CORS origins</span>
              <input name="cors_allow_origins" value="${escapeHtml(csv(securityValues.cors_allow_origins))}" />
            </label>
            <label class="field">
              <span>Logs IP allowlist</span>
              <input name="logs_ip_allowlist" value="${escapeHtml(csv(securityValues.logs_ip_allowlist))}" />
            </label>
            <button class="button" type="submit">Save security step</button>
          </form>
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
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Step 5 · Finish",
      `
        <div class="stack">
          ${pill(`Claimed instance: ${claim.claimed ? "yes" : claim.required ? "pending" : "not required"}`)}
          ${pill(`Persisted config: ${setup.persisted ? "yes" : "no"}`)}
          ${pill(`GigaChat ready: ${setup.gigachat_ready ? "yes" : "no"}`)}
          ${pill(`Security ready: ${setup.security_ready ? "yes" : "no"}`)}
          ${
            setup.setup_complete
              ? banner("Bootstrap path is complete. The operator console can now be used as the main control plane.")
              : banner(
                  "Bootstrap is not complete yet. Finish the missing steps above before relying on zero-env restarts or exposing the gateway.",
                  "warn",
                )
          }
          <div class="toolbar">
            <a class="button button--secondary" href="/admin">Back to overview</a>
            <a class="button" href="/admin/playground">Open playground</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
  `);

  document.getElementById("refresh-setup")?.addEventListener("click", () => {
    void app.render("setup");
  });

  const claimForm = app.pageContent.querySelector<HTMLFormElement>("#setup-claim-form");
  const applicationForm = app.pageContent.querySelector<HTMLFormElement>("#setup-application-form");
  const gigachatForm = app.pageContent.querySelector<HTMLFormElement>("#setup-gigachat-form");
  const securityForm = app.pageContent.querySelector<HTMLFormElement>("#setup-security-form");
  const applicationStatusNode = app.pageContent.querySelector<HTMLElement>("#setup-application-status");
  const gigachatStatusNode = app.pageContent.querySelector<HTMLElement>("#setup-gigachat-status");
  const securityStatusNode = app.pageContent.querySelector<HTMLElement>("#setup-security-status");
  const applicationFields = applicationForm?.elements as SetupApplicationFormElements | undefined;
  const gigachatFields = gigachatForm?.elements as SetupGigachatFormElements | undefined;
  bindValidityReset(applicationFields?.enabled_providers, gigachatFields?.timeout);

  const syncCredentialsSecret = gigachatForm
    ? bindSecretFieldBehavior({
        form: gigachatForm,
        fieldName: "credentials",
        clearFieldName: "clear_credentials",
        preview: String(gigachatValues.credentials_preview ?? "not configured"),
      })
    : () => null;
  const syncAccessTokenSecret = gigachatForm
    ? bindSecretFieldBehavior({
        form: gigachatForm,
        fieldName: "access_token",
        clearFieldName: "clear_access_token",
        preview: String(gigachatValues.access_token_preview ?? "not configured"),
      })
    : () => null;

  let applicationActionState: InlineStatus | null = null;
  let gigachatActionState: InlineStatus | null = null;
  let securityActionState: InlineStatus | null = null;

  const getApplicationValidationMessage = (report = false) =>
    validateRequiredCsvField(
      applicationFields?.enabled_providers,
      "Provide at least one enabled provider.",
      { report },
    );

  const getGigachatValidationMessage = (report = false) =>
    validatePositiveNumberField(
      gigachatFields?.timeout,
      "Timeout must be a positive number of seconds.",
      { report },
    );

  const buildSecurityStepPayload = (form: HTMLFormElement) => {
    const fields = form.elements as typeof form.elements & {
      enable_api_key_auth: HTMLSelectElement;
      cors_allow_origins: HTMLInputElement;
      logs_ip_allowlist: HTMLInputElement;
    };
    return {
      enable_api_key_auth: fields.enable_api_key_auth.value === "true",
      cors_allow_origins: parseCsv(fields.cors_allow_origins.value),
      logs_ip_allowlist: parseCsv(fields.logs_ip_allowlist.value),
    };
  };

  const refreshStepStatuses = () => {
    if (!applicationForm || !gigachatForm || !securityForm) {
      return;
    }

    applicationStatusNode?.replaceChildren();
    gigachatStatusNode?.replaceChildren();
    securityStatusNode?.replaceChildren();

    const applicationEntries = buildPendingDiffEntries(
      "application",
      applicationValues,
      buildApplicationPayload(applicationForm),
    );
    const gigachatEntries = buildPendingDiffEntries(
      "gigachat",
      gigachatValues,
      collectGigachatPayload(gigachatForm),
    );
    const securityEntries = buildPendingDiffEntries(
      "security",
      securityValues,
      buildSecurityStepPayload(securityForm),
    );
    const applicationValidationMessage = getApplicationValidationMessage();
    const gigachatValidationMessage = getGigachatValidationMessage();
    const secretStates = [syncCredentialsSecret(), syncAccessTokenSecret()].flatMap((state) =>
      state ? [state] : [],
    );
    const stagedSecretMessages = secretStates
      .filter((state) => state.intent !== "keep")
      .map((state) => state.message);

    if (applicationStatusNode) {
      applicationStatusNode.innerHTML = renderControlPlaneSectionStatus({
        summary: summarizePendingChanges(applicationEntries),
        persisted,
        updatedAt: persistedUpdatedAt,
        note: "Use this step for runtime posture and provider routing. Restart-sensitive controls are called out before you save.",
        validationMessage: applicationValidationMessage || undefined,
        actionState: applicationActionState,
      });
    }
    if (gigachatStatusNode) {
      gigachatStatusNode.innerHTML = renderControlPlaneSectionStatus({
        summary: summarizePendingChanges(gigachatEntries),
        persisted,
        updatedAt: persistedUpdatedAt,
        note: stagedSecretMessages.length
          ? `Testing the connection here does not persist the form. ${stagedSecretMessages.join(" ")}`
          : "Testing the connection here does not persist the form; save only after the pending state looks correct.",
        validationMessage: gigachatValidationMessage || undefined,
        actionState: gigachatActionState,
      });
    }
    if (securityStatusNode) {
      securityStatusNode.innerHTML = renderControlPlaneSectionStatus({
        summary: summarizePendingChanges(securityEntries),
        persisted,
        updatedAt: persistedUpdatedAt,
        note: "Gateway auth posture and CORS are the main restart-sensitive controls in this step.",
        actionState: securityActionState,
      });
    }
  };

  refreshStepStatuses();
  [applicationForm, gigachatForm, securityForm].forEach((form) => {
    form?.addEventListener("input", refreshStepStatuses);
    form?.addEventListener("change", refreshStepStatuses);
  });

  claimForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const operatorLabel = (form.elements.namedItem("operator_label") as HTMLInputElement).value.trim();
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');
    await withBusyState({
      root: form,
      button,
      pendingLabel: "Claiming…",
      action: async () => {
        const response = await app.api.json<Record<string, unknown>>("/admin/api/setup/claim", {
          method: "POST",
          json: {
            operator_label: operatorLabel || null,
          },
        });
        const nextClaim = asRecord(response.claim);
        app.queueAlert(
          nextClaim.operator_label
            ? `Instance claimed by ${String(nextClaim.operator_label)}.`
            : "Instance claim recorded.",
          "info",
        );
        await app.render("setup");
      },
    });
  });

  applicationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (getApplicationValidationMessage(true)) {
      refreshStepStatuses();
      return;
    }
    const form = event.currentTarget as HTMLFormElement;
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');
    applicationActionState = {
      tone: "info",
      message:
        "Saving the application bootstrap step. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
    };
    refreshStepStatuses();
    try {
      await withBusyState({
        root: form,
        button,
        pendingLabel: "Saving…",
        action: async () => {
          const response = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/application",
            {
              method: "PUT",
              json: buildApplicationPayload(form),
            },
          );
          const outcome = describePersistOutcome("Application bootstrap step", response);
          app.queueAlert(outcome.message, outcome.tone);
          await app.render("setup");
        },
      });
    } catch (error) {
      applicationActionState = {
        tone: "danger",
        message: `Application bootstrap step failed to save: ${toErrorMessage(error)}`,
      };
      refreshStepStatuses();
      app.pushAlert(applicationActionState.message, "danger");
    }
  });

  gigachatForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (getGigachatValidationMessage(true)) {
      refreshStepStatuses();
      return;
    }
    const form = event.currentTarget as HTMLFormElement;
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');
    gigachatActionState = {
      tone: "info",
      message:
        "Saving the GigaChat bootstrap step. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
    };
    refreshStepStatuses();
    try {
      await withBusyState({
        root: form,
        button,
        pendingLabel: "Saving…",
        action: async () => {
          const response = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/gigachat",
            {
              method: "PUT",
              json: collectGigachatPayload(form),
            },
          );
          const outcome = describePersistOutcome("GigaChat bootstrap step", response);
          app.queueAlert(outcome.message, outcome.tone);
          await app.render("setup");
        },
      });
    } catch (error) {
      gigachatActionState = {
        tone: "danger",
        message: `GigaChat bootstrap step failed to save: ${toErrorMessage(error)}`,
      };
      refreshStepStatuses();
      app.pushAlert(gigachatActionState.message, "danger");
    }
  });

  document.getElementById("setup-gigachat-test")?.addEventListener("click", async (event) => {
    const form = gigachatForm;
    if (!form) {
      return;
    }
    if (getGigachatValidationMessage(true)) {
      refreshStepStatuses();
      return;
    }
    const button = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
    gigachatActionState = {
      tone: "info",
      message:
        "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save this step.",
    };
    refreshStepStatuses();
    try {
      await withBusyState({
        root: form,
        button,
        pendingLabel: "Testing…",
        action: async () => {
          const result = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/gigachat/test",
            {
              method: "POST",
              json: collectGigachatPayload(form),
            },
          );
          gigachatActionState = result.ok
            ? {
                tone: "info",
                message: `Connection ok. Models visible: ${String(result.model_count ?? 0)}. Candidate values were tested but not persisted.`,
              }
            : {
                tone: "danger",
                message: `Connection failed: ${String(result.error_type ?? "Error")}: ${String(result.error ?? "unknown error")}. Persisted values remain unchanged.`,
              };
          refreshStepStatuses();
          app.pushAlert(gigachatActionState.message, gigachatActionState.tone);
        },
      });
    } catch (error) {
      gigachatActionState = {
        tone: "danger",
        message: `GigaChat connection test failed: ${toErrorMessage(error)}`,
      };
      refreshStepStatuses();
      app.pushAlert(gigachatActionState.message, "danger");
    }
  });

  securityForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');
    securityActionState = {
      tone: "info",
      message:
        "Saving the security bootstrap step. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
    };
    refreshStepStatuses();
    try {
      await withBusyState({
        root: form,
        button,
        pendingLabel: "Saving…",
        action: async () => {
          const response = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/security",
            {
              method: "PUT",
              json: buildSecurityStepPayload(form),
            },
          );
          const outcome = describePersistOutcome("Security bootstrap step", response);
          app.queueAlert(outcome.message, outcome.tone);
          await app.render("setup");
        },
      });
    } catch (error) {
      securityActionState = {
        tone: "danger",
        message: `Security bootstrap step failed to save: ${toErrorMessage(error)}`,
      };
      refreshStepStatuses();
      app.pushAlert(securityActionState.message, "danger");
    }
  });

  document.getElementById("setup-create-global-key")?.addEventListener("click", async (event) => {
    const input = document.getElementById("setup-global-key-value") as HTMLInputElement | null;
    const button = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
    await withBusyState({
      button,
      pendingLabel: "Creating…",
      action: async () => {
        const response = await app.api.json<Record<string, unknown>>("/admin/api/keys/global/rotate", {
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
