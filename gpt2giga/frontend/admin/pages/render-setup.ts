import type { AdminApp } from "../app.js";
import {
  bindValidityReset,
  buildApplicationPayload,
  buildPendingDiffEntries,
  buildSecurityPayload,
  collectGigachatPayload,
  validatePositiveNumberField,
  validateRequiredCsvField,
  withBusyState,
} from "../forms.js";
import { subpagesFor } from "../routes.js";
import {
  banner,
  card,
  pill,
  renderSetupSteps,
  renderSubpageNav,
} from "../templates.js";
import {
  asArray,
  asRecord,
  escapeHtml,
} from "../utils.js";
import { getSubmitterButton } from "./control-plane-actions.js";
import {
  bindControlPlaneSectionForm,
  bindGigachatConnectionTestAction,
} from "./control-plane-form-bindings.js";
import {
  bindGigachatSecretFields,
  renderApplicationSection,
  renderGigachatSection,
  renderSetupObservabilityHandoff,
  renderSecuritySection,
} from "./control-plane-sections.js";
import { collectSecretFieldMessages } from "./control-plane-status.js";

type SetupPage =
  | "setup"
  | "setup-claim"
  | "setup-application"
  | "setup-gigachat"
  | "setup-security";

type SetupSection = "claim" | "application" | "gigachat" | "security";

type SetupApplicationFormElements = HTMLFormControlsCollection & {
  enabled_providers: HTMLInputElement;
};

type SetupGigachatFormElements = HTMLFormControlsCollection & {
  timeout?: HTMLInputElement;
};

export async function renderSetup(app: AdminApp, token: number): Promise<void> {
  await renderSetupPage(app, token, "setup");
}

export async function renderSetupClaim(app: AdminApp, token: number): Promise<void> {
  await renderSetupPage(app, token, "setup-claim");
}

export async function renderSetupApplication(
  app: AdminApp,
  token: number,
): Promise<void> {
  await renderSetupPage(app, token, "setup-application");
}

export async function renderSetupGigachat(
  app: AdminApp,
  token: number,
): Promise<void> {
  await renderSetupPage(app, token, "setup-gigachat");
}

export async function renderSetupSecurity(
  app: AdminApp,
  token: number,
): Promise<void> {
  await renderSetupPage(app, token, "setup-security");
}

async function renderSetupPage(
  app: AdminApp,
  token: number,
  currentPage: SetupPage,
): Promise<void> {
  const [setup, runtime, application, observability, gigachat, security, keys] =
    await Promise.all([
      app.api.json<Record<string, unknown>>("/admin/api/setup"),
      app.api.json<Record<string, unknown>>("/admin/api/runtime"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/application"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/observability"),
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
  const observabilityValues = asRecord(observability.values);
  const gigachatValues = asRecord(gigachat.values);
  const securityValues = asRecord(security.values);
  const globalKey = asRecord(asRecord(keys.global));
  const scopedKeys = asArray<Record<string, unknown>>(keys.scoped);
  const warnings = asArray<string>(setup.warnings);
  const persisted = Boolean(setup.persisted);
  const persistedUpdatedAt = setup.updated_at;
  const activeSection = sectionForPage(currentPage);
  const nextStep = getNextRecommendedSetupPage(setup);

  app.setHeroActions(`
    <button class="button button--secondary" id="refresh-setup" type="button">Refresh setup state</button>
    <a class="button" href="${escapeHtml(nextStep.href)}">${escapeHtml(nextStep.label)}</a>
  `);

  app.setContent(
    activeSection === null
      ? renderSetupHub({
          currentPage,
          setup,
          runtime,
          claim,
          bootstrap,
          warnings,
          observabilityValues,
          nextStep,
        })
      : renderFocusedSetupPage({
          currentPage,
          activeSection,
          setup,
          runtime,
          claim,
          bootstrap,
          warnings,
          applicationValues,
          observabilityValues,
          gigachatValues,
          securityValues,
          globalKey,
          scopedKeys,
        }),
  );

  document.getElementById("refresh-setup")?.addEventListener("click", () => {
    void app.render(currentPage);
  });

  bindSetupInteractions({
    app,
    currentPage,
    claim,
    persisted,
    persistedUpdatedAt,
    applicationValues,
    gigachatValues,
    securityValues,
  });
}

function renderSetupHub(options: {
  currentPage: SetupPage;
  setup: Record<string, unknown>;
  runtime: Record<string, unknown>;
  claim: Record<string, unknown>;
  bootstrap: Record<string, unknown>;
  warnings: string[];
  observabilityValues: Record<string, unknown>;
  nextStep: {
    href: string;
    label: string;
    note: string;
  };
}): string {
  return `
    ${card(
      "Setup map",
      renderSubpageNav({
        currentPage: options.currentPage,
        title: "Setup pages",
        intro:
          "Use the hub for progress and warnings, then open one focused setup step per page.",
        items: subpagesFor(options.currentPage),
      }),
      "panel panel--span-12",
    )}
    ${card(
      "Setup progress",
      `
        <div class="stack">
          ${renderSetupSteps(asArray(options.setup.wizard_steps))}
          ${
            options.bootstrap.required
              ? banner(
                  `Bootstrap gate is active. Admin setup is currently limited to localhost or the bootstrap token stored at ${String(options.bootstrap.token_path ?? "the control-plane volume")}.`,
                  "warn",
                )
              : banner(
                  "Bootstrap gate is closed. Normal operator access now relies on the configured admin or global API key path.",
                )
          }
          <div class="toolbar">
            ${pill(`Claim: ${options.claim.claimed ? "done" : options.claim.required ? "pending" : "not required"}`, options.claim.claimed ? "good" : "warn")}
            ${pill(`Persisted config: ${options.setup.persisted ? "yes" : "no"}`, options.setup.persisted ? "good" : "warn")}
            ${pill(`GigaChat: ${options.setup.gigachat_ready ? "ready" : "pending"}`, options.setup.gigachat_ready ? "good" : "warn")}
            ${pill(`Security: ${options.setup.security_ready ? "ready" : "pending"}`, options.setup.security_ready ? "good" : "warn")}
          </div>
          <div class="toolbar">
            <a class="button" href="${escapeHtml(options.nextStep.href)}">${escapeHtml(options.nextStep.label)}</a>
            <a class="button button--secondary" href="/admin/playground">Open playground</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Readiness and warnings",
      `
        <div class="stack">
          <div class="stat-line"><strong>Runtime mode</strong><span class="muted">${escapeHtml(options.runtime.mode ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Store backend</strong><span class="muted">${escapeHtml(options.runtime.runtime_store_backend ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Control-plane file</strong><span class="muted">${escapeHtml(options.setup.path ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Encryption key file</strong><span class="muted">${escapeHtml(options.setup.key_path ?? "n/a")}</span></div>
          ${
            options.warnings.length
              ? options.warnings.map((warning) => banner(String(warning), "warn")).join("")
              : banner("Setup checks look healthy. You can continue with playground and traffic.")
          }
        </div>
      `,
      "panel panel--span-6",
    )}
    ${card(
      "Next recommended step",
      `
        <div class="stack">
          <p class="muted">${escapeHtml(options.nextStep.note)}</p>
          <div class="toolbar">
            <a class="button" href="${escapeHtml(options.nextStep.href)}">${escapeHtml(options.nextStep.label)}</a>
            <a class="button button--secondary" href="/admin/settings-observability">Observability settings</a>
          </div>
          <div class="toolbar">
            ${pill(`Observability sinks: ${asArray<string>(options.observabilityValues.active_sinks).join(", ") || "none"}`)}
            ${pill(`Setup complete: ${options.setup.setup_complete ? "yes" : "no"}`, options.setup.setup_complete ? "good" : "warn")}
          </div>
        </div>
      `,
      "panel panel--span-6",
    )}
    ${renderSetupStepCard({
      title: "Claim",
      href: "/admin/setup-claim",
      description: options.claim.required
        ? options.claim.claimed
          ? "Bootstrap claim is already recorded. Reopen the page to inspect claim details."
          : "Record the first operator before continuing with bootstrap-critical changes."
        : "Claiming is not required in the current runtime mode.",
      pills: [
        pill(`Required: ${options.claim.required ? "yes" : "no"}`),
        pill(`Claimed: ${options.claim.claimed ? "yes" : "no"}`, options.claim.claimed ? "good" : "warn"),
      ],
    })}
    ${renderSetupStepCard({
      title: "Application",
      href: "/admin/setup-application",
      description:
        "Persist runtime mode and provider posture without mixing it with GigaChat or security changes.",
      pills: [
        pill(`Persisted config: ${options.setup.persisted ? "yes" : "no"}`, options.setup.persisted ? "good" : "warn"),
        pill(`Mode: ${String(options.runtime.mode ?? "n/a")}`),
      ],
    })}
    ${renderSetupStepCard({
      title: "GigaChat",
      href: "/admin/setup-gigachat",
      description:
        "Configure provider credentials and run connection testing on a dedicated page.",
      pills: [
        pill(`Ready: ${options.setup.gigachat_ready ? "yes" : "no"}`, options.setup.gigachat_ready ? "good" : "warn"),
        pill(`Backend: ${String(options.runtime.gigachat_api_mode ?? "n/a")}`),
      ],
    })}
    ${renderSetupStepCard({
      title: "Security",
      href: "/admin/setup-security",
      description:
        "Close bootstrap access, stage gateway auth, and rotate the global key without setup overload.",
      pills: [
        pill(`Ready: ${options.setup.security_ready ? "yes" : "no"}`, options.setup.security_ready ? "good" : "warn"),
        pill(`Bootstrap gate: ${options.bootstrap.required ? "open" : "closed"}`, options.bootstrap.required ? "warn" : "good"),
      ],
    })}
  `;
}

function renderFocusedSetupPage(options: {
  currentPage: SetupPage;
  activeSection: SetupSection;
  setup: Record<string, unknown>;
  runtime: Record<string, unknown>;
  claim: Record<string, unknown>;
  bootstrap: Record<string, unknown>;
  warnings: string[];
  applicationValues: Record<string, unknown>;
  observabilityValues: Record<string, unknown>;
  gigachatValues: Record<string, unknown>;
  securityValues: Record<string, unknown>;
  globalKey: Record<string, unknown>;
  scopedKeys: Record<string, unknown>[];
}): string {
  return `
    ${card(
      "Setup navigation",
      renderSubpageNav({
        currentPage: options.currentPage,
        title: "Setup pages",
        intro:
          "Each setup page carries one primary task. Use the hub only for progress and next-step decisions.",
        items: subpagesFor(options.currentPage),
      }),
      "panel panel--span-12",
    )}
    ${renderSetupMainCard(options)}
    ${renderSetupSidebar(options)}
  `;
}

function renderSetupMainCard(options: {
  activeSection: SetupSection;
  claim: Record<string, unknown>;
  applicationValues: Record<string, unknown>;
  gigachatValues: Record<string, unknown>;
  securityValues: Record<string, unknown>;
}): string {
  if (options.activeSection === "claim") {
    return card(
      "Claim instance",
      `
        <div class="stack">
          ${banner(
            options.claim.required
              ? options.claim.claimed
                ? `This bootstrap session is already claimed${options.claim.operator_label ? ` by ${String(options.claim.operator_label)}` : ""}.`
                : "First-run PROD bootstrap is active. Claim the instance before continuing with operator setup."
              : "Claiming is not required in the current runtime mode.",
            options.claim.claimed ? "info" : "warn",
          )}
          ${
            options.claim.claimed
              ? `
                  <div class="dual-grid">
                    <div class="stack">
                      ${pill(`Claimed at: ${String(options.claim.claimed_at ?? "n/a")}`)}
                      ${pill(`Claimed via: ${String(options.claim.claimed_via ?? "n/a")}`)}
                    </div>
                    <div class="stack">
                      ${pill(`Operator label: ${String(options.claim.operator_label ?? "not recorded")}`)}
                      ${pill(`Source IP: ${String(options.claim.claimed_from ?? "unknown")}`)}
                    </div>
                  </div>
                `
              : options.claim.required
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
                : `<p class="muted">This environment does not require an explicit bootstrap claim.</p>`
          }
        </div>
      `,
      "panel panel--span-8 panel--measure",
    );
  }

  if (options.activeSection === "application") {
    return card(
      "Application posture",
      renderApplicationSection({
        bannerMessage:
          "Saving always updates the persisted control-plane target. Runtime only reloads immediately when this bootstrap step stays restart-safe.",
        formId: "setup-application-form",
        statusId: "setup-application-status",
        submitLabel: "Save application step",
        values: options.applicationValues,
        variant: "setup",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  if (options.activeSection === "gigachat") {
    return card(
      "GigaChat auth",
      renderGigachatSection({
        bannerMessage:
          "Connection tests use candidate values without persisting them. Saving updates the persisted target first, then reloads runtime only when the batch is restart-safe.",
        formId: "setup-gigachat-form",
        statusId: "setup-gigachat-status",
        submitLabel: "Save GigaChat step",
        testButtonId: "setup-gigachat-test",
        testButtonLabel: "Test connection",
        values: options.gigachatValues,
        variant: "setup",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  return card(
    "Security bootstrap",
    renderSecuritySection({
      bannerMessage:
        "Security bootstrap saves to the control plane first. If this step includes restart-sensitive changes, the running process keeps the previous posture until restart.",
      formId: "setup-security-form",
      statusId: "setup-security-status",
      submitLabel: "Save security step",
      values: options.securityValues,
      variant: "setup",
    }),
    "panel panel--span-8 panel--measure",
  );
}

function renderSetupSidebar(options: {
  activeSection: SetupSection;
  setup: Record<string, unknown>;
  runtime: Record<string, unknown>;
  claim: Record<string, unknown>;
  bootstrap: Record<string, unknown>;
  warnings: string[];
  observabilityValues: Record<string, unknown>;
  globalKey: Record<string, unknown>;
  scopedKeys: Record<string, unknown>[];
}): string {
  const nextStep = getNextRecommendedSetupPage(options.setup);

  if (options.activeSection === "security") {
    return `
      ${card(
        "Security posture",
        `
          <div class="stack">
            <div class="toolbar">
              ${pill(`Bootstrap gate: ${options.bootstrap.required ? "open" : "closed"}`, options.bootstrap.required ? "warn" : "good")}
              ${pill(`Global key: ${options.globalKey.configured ? "configured" : "missing"}`, options.globalKey.configured ? "good" : "warn")}
              ${pill(`Scoped keys: ${options.scopedKeys.length}`)}
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
            ${banner(
              "Use the dedicated keys page for scoped key inventory. This page only keeps the bootstrap-critical global-key action nearby.",
            )}
          </div>
        `,
        "panel panel--span-4 panel--aside",
      )}
      ${card(
        "Observability handoff",
        renderSetupObservabilityHandoff(options.observabilityValues),
        "panel panel--span-4 panel--aside",
      )}
      ${renderSetupStatusCard({
        setup: options.setup,
        runtime: options.runtime,
        claim: options.claim,
        warnings: options.warnings,
        nextStep,
      })}
    `;
  }

  return renderSetupStatusCard({
    setup: options.setup,
    runtime: options.runtime,
    claim: options.claim,
    warnings: options.warnings,
    nextStep,
  });
}

function renderSetupStatusCard(options: {
  setup: Record<string, unknown>;
  runtime: Record<string, unknown>;
  claim: Record<string, unknown>;
  warnings: string[];
  nextStep: {
    href: string;
    label: string;
    note: string;
  };
}): string {
  return card(
    "Setup status",
    `
      <div class="stack">
        <div class="toolbar">
          ${pill(`Runtime mode: ${String(options.runtime.mode ?? "n/a")}`)}
          ${pill(`Backend: ${String(options.runtime.gigachat_api_mode ?? "n/a")}`)}
          ${pill(`Setup complete: ${options.setup.setup_complete ? "yes" : "no"}`, options.setup.setup_complete ? "good" : "warn")}
        </div>
        <div class="stat-line"><strong>Claim</strong><span class="muted">${options.claim.claimed ? "claimed" : options.claim.required ? "pending" : "not required"}</span></div>
        <div class="stat-line"><strong>Persisted config</strong><span class="muted">${options.setup.persisted ? "yes" : "no"}</span></div>
        <div class="stat-line"><strong>GigaChat ready</strong><span class="muted">${options.setup.gigachat_ready ? "yes" : "no"}</span></div>
        <div class="stat-line"><strong>Security ready</strong><span class="muted">${options.setup.security_ready ? "yes" : "no"}</span></div>
        ${
          options.warnings.length
            ? options.warnings.slice(0, 2).map((warning) => banner(String(warning), "warn")).join("")
            : banner("Setup warnings are clear right now.")
        }
        <div class="toolbar">
          <a class="button button--secondary" href="/admin/setup">Back to setup hub</a>
          <a class="button" href="${escapeHtml(options.nextStep.href)}">${escapeHtml(options.nextStep.label)}</a>
        </div>
        <p class="muted">${escapeHtml(options.nextStep.note)}</p>
      </div>
    `,
    "panel panel--span-4 panel--aside",
  );
}

function renderSetupStepCard(options: {
  title: string;
  href: string;
  description: string;
  pills: string[];
}): string {
  return card(
    options.title,
    `
      <div class="stack">
        <p class="muted">${escapeHtml(options.description)}</p>
        <div class="toolbar">
          ${options.pills.join("")}
        </div>
        <div class="toolbar">
          <a class="button" href="${escapeHtml(options.href)}">Open ${escapeHtml(options.title)}</a>
        </div>
      </div>
    `,
    "panel panel--span-6",
  );
}

function bindSetupInteractions(options: {
  app: AdminApp;
  currentPage: SetupPage;
  claim: Record<string, unknown>;
  persisted: boolean;
  persistedUpdatedAt: unknown;
  applicationValues: Record<string, unknown>;
  gigachatValues: Record<string, unknown>;
  securityValues: Record<string, unknown>;
}): void {
  const claimForm = options.app.pageContent.querySelector<HTMLFormElement>("#setup-claim-form");
  const applicationForm = options.app.pageContent.querySelector<HTMLFormElement>(
    "#setup-application-form",
  );
  const gigachatForm = options.app.pageContent.querySelector<HTMLFormElement>(
    "#setup-gigachat-form",
  );
  const securityForm = options.app.pageContent.querySelector<HTMLFormElement>(
    "#setup-security-form",
  );
  const applicationStatusNode = options.app.pageContent.querySelector<HTMLElement>(
    "#setup-application-status",
  );
  const gigachatStatusNode = options.app.pageContent.querySelector<HTMLElement>(
    "#setup-gigachat-status",
  );
  const securityStatusNode = options.app.pageContent.querySelector<HTMLElement>(
    "#setup-security-status",
  );
  const applicationFields = applicationForm?.elements as SetupApplicationFormElements | undefined;
  const gigachatFields = gigachatForm?.elements as SetupGigachatFormElements | undefined;

  bindValidityReset(applicationFields?.enabled_providers, gigachatFields?.timeout);

  const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(
    gigachatForm ?? null,
    options.gigachatValues,
  );

  claimForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const operatorLabel = (
      form.elements.namedItem("operator_label") as HTMLInputElement
    ).value.trim();
    const button = getSubmitterButton(event as SubmitEvent, form);
    await withBusyState({
      root: form,
      button,
      pendingLabel: "Claiming…",
      action: async () => {
        const response = await options.app.api.json<Record<string, unknown>>(
          "/admin/api/setup/claim",
          {
            method: "POST",
            json: {
              operator_label: operatorLabel || null,
            },
          },
        );
        const nextClaim = asRecord(response.claim);
        options.app.queueAlert(
          nextClaim.operator_label
            ? `Instance claimed by ${String(nextClaim.operator_label)}.`
            : "Instance claim recorded.",
          "info",
        );
        await options.app.render(options.currentPage);
      },
    });
  });

  if (applicationForm && applicationStatusNode) {
    bindControlPlaneSectionForm({
      app: options.app,
      form: applicationForm,
      statusNode: applicationStatusNode,
      persisted: options.persisted,
      updatedAt: options.persistedUpdatedAt,
      buildPayload: () => buildApplicationPayload(applicationForm),
      buildEntries: (payload) =>
        buildPendingDiffEntries("application", options.applicationValues, payload),
      buildNote: () =>
        "Use this step for runtime posture and provider routing. Restart-sensitive controls are called out before you save.",
      getValidationMessage: (_payload, report = false) =>
        validateRequiredCsvField(
          applicationFields?.enabled_providers,
          "Provide at least one enabled provider.",
          { report },
        ),
      endpoint: "/admin/api/settings/application",
      pendingMessage:
        "Saving the application bootstrap step. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
      outcomeLabel: "Application bootstrap step",
      failurePrefix: "Application bootstrap step failed to save",
      rerenderPage: options.currentPage,
    });
  }

  if (gigachatForm && gigachatStatusNode) {
    const getGigachatValidationMessage = (_payload: Record<string, unknown>, report = false) =>
      validatePositiveNumberField(
        gigachatFields?.timeout,
        "Timeout must be a positive number of seconds.",
        { report },
      );

    const gigachatBinding = bindControlPlaneSectionForm({
      app: options.app,
      form: gigachatForm,
      statusNode: gigachatStatusNode,
      persisted: options.persisted,
      updatedAt: options.persistedUpdatedAt,
      buildPayload: () => collectGigachatPayload(gigachatForm),
      buildEntries: (payload) =>
        buildPendingDiffEntries("gigachat", options.gigachatValues, payload),
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
      pendingMessage:
        "Saving the GigaChat bootstrap step. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
      outcomeLabel: "GigaChat bootstrap step",
      failurePrefix: "GigaChat bootstrap step failed to save",
      rerenderPage: options.currentPage,
    });

    bindGigachatConnectionTestAction({
      app: options.app,
      form: gigachatForm,
      button: document.getElementById("setup-gigachat-test") as HTMLButtonElement | null,
      buildPayload: () => collectGigachatPayload(gigachatForm),
      getValidationMessage: getGigachatValidationMessage,
      refreshStatus: gigachatBinding.refreshStatus,
      setActionState: (state) => {
        gigachatBinding.setActionState(state);
      },
      pendingMessage:
        "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save this step.",
    });
  }

  if (securityForm && securityStatusNode) {
    bindControlPlaneSectionForm({
      app: options.app,
      form: securityForm,
      statusNode: securityStatusNode,
      persisted: options.persisted,
      updatedAt: options.persistedUpdatedAt,
      buildPayload: () => buildSecurityPayload(securityForm),
      buildEntries: (payload) =>
        buildPendingDiffEntries("security", options.securityValues, payload),
      buildNote: () =>
        "Gateway auth posture and CORS are the main restart-sensitive controls in this step.",
      endpoint: "/admin/api/settings/security",
      pendingMessage:
        "Saving the security bootstrap step. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
      outcomeLabel: "Security bootstrap step",
      failurePrefix: "Security bootstrap step failed to save",
      rerenderPage: options.currentPage,
    });
  }

  document.getElementById("setup-create-global-key")?.addEventListener("click", async (event) => {
    const input = document.getElementById("setup-global-key-value") as HTMLInputElement | null;
    const button =
      event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
    await withBusyState({
      button,
      pendingLabel: "Creating…",
      action: async () => {
        const response = await options.app.api.json<Record<string, unknown>>(
          "/admin/api/keys/global/rotate",
          {
            method: "POST",
            json: { value: input?.value.trim() || null },
          },
        );
        const nextGlobal = asRecord(response.global);
        options.app.saveAdminKey(String(nextGlobal.value ?? ""));
        options.app.saveGatewayKey(String(nextGlobal.value ?? ""));
        options.app.queueAlert(
          `Global gateway key created. New value: ${String(nextGlobal.value ?? "")}`,
          "warn",
        );
        await options.app.render(options.currentPage);
      },
    });
  });
}

function sectionForPage(page: SetupPage): SetupSection | null {
  switch (page) {
    case "setup-claim":
      return "claim";
    case "setup-application":
      return "application";
    case "setup-gigachat":
      return "gigachat";
    case "setup-security":
      return "security";
    default:
      return null;
  }
}

function getNextRecommendedSetupPage(setup: Record<string, unknown>): {
  href: string;
  label: string;
  note: string;
} {
  const claim = asRecord(setup.claim);
  if (claim.required && !claim.claimed) {
    return {
      href: "/admin/setup-claim",
      label: "Open claim step",
      note: "Claim the bootstrap session before relying on the rest of the setup flow.",
    };
  }
  if (!setup.persisted) {
    return {
      href: "/admin/setup-application",
      label: "Open application step",
      note: "Persist baseline runtime posture before moving deeper into provider and security steps.",
    };
  }
  if (!setup.gigachat_ready) {
    return {
      href: "/admin/setup-gigachat",
      label: "Open GigaChat step",
      note: "Provider credentials are still incomplete, so playground calls will fail until this step is ready.",
    };
  }
  if (!setup.security_ready) {
    return {
      href: "/admin/setup-security",
      label: "Open security step",
      note: "Close bootstrap exposure and stage gateway auth before treating the gateway as production-ready.",
    };
  }
  return {
    href: "/admin/playground",
    label: "Open playground",
    note: "Bootstrap-critical setup is complete. The next move is a smoke request against the mounted surfaces.",
  };
}
