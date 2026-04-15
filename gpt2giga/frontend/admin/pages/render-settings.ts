import type { AdminApp } from "../app.js";
import {
  bindValidityReset,
  bindSecretFieldBehavior,
  buildApplicationPayload,
  buildObservabilityDiffEntries,
  buildObservabilityPayload,
  buildPendingDiffEntries,
  buildSecurityPayload,
  bindReplaceableFieldBehavior,
  collectGigachatPayload,
  describePersistOutcome,
  validateJsonArrayField,
  validateJsonObjectField,
  validatePositiveNumberField,
  validateRequiredCsvField,
  withBusyState,
} from "../forms.js";
import {
  getSubmitterButton,
  persistControlPlaneSection,
  testGigachatConnection,
  type InlineStatus,
} from "./control-plane-actions.js";
import {
  bindGigachatSecretFields,
  renderApplicationSection,
  renderGigachatSection,
  renderObservabilitySection,
  renderSecuritySection,
} from "./control-plane-sections.js";
import {
  collectSecretFieldMessages,
  renderControlPlaneStatusNode,
  renderInlineBannerStatus,
} from "./control-plane-status.js";
import {
  banner,
  card,
  renderDiffSections,
} from "../templates.js";
import {
  asArray,
  asRecord,
  escapeHtml,
  formatTimestamp,
  toErrorMessage,
} from "../utils.js";

type SettingsSection =
  | "application"
  | "observability"
  | "gigachat"
  | "security"
  | "history";

const SETTINGS_SECTIONS: SettingsSection[] = [
  "application",
  "observability",
  "gigachat",
  "security",
  "history",
];

export async function renderSettings(app: AdminApp, token: number): Promise<void> {
  const [application, observability, gigachat, security, revisionsPayload] =
    await Promise.all([
      app.api.json<Record<string, unknown>>("/admin/api/settings/application"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/observability"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/gigachat"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/security"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/revisions?limit=6"),
    ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const applicationValues = asRecord(application.values);
  const observabilityValues = asRecord(observability.values);
  const gigachatValues = asRecord(gigachat.values);
  const securityValues = asRecord(security.values);
  const controlPlaneStatus = asRecord(application.control_plane);
  const revisions = asArray<Record<string, unknown>>(revisionsPayload.revisions);
  const selectedSection = getSelectedSettingsSection();

  app.setHeroActions(
    `<button class="button button--secondary" id="reload-settings" type="button">Reload values</button>`,
  );

  app.setContent(`
    ${card(
      "Settings",
      `
        <div class="stack">
          <p class="muted">Settings are split into focused sections. One group is visible at a time.</p>
          <div class="settings-switcher" id="settings-switcher">
            ${SETTINGS_SECTIONS.map((section) => renderSectionButton(section, selectedSection)).join("")}
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
    ${card(
      "Application",
      renderApplicationSection({
        bannerMessage:
          "Saving always updates the persisted control-plane target. Runtime only reloads immediately when this batch contains no restart-sensitive fields.",
        formId: "application-form",
        statusId: "settings-application-status",
        submitLabel: "Save application settings",
        values: applicationValues,
        variant: "settings",
      }),
      sectionPanelClass(selectedSection === "application", "panel panel--span-12"),
    )}
    ${card(
      "Observability",
      renderObservabilitySection({
        bannerMessage:
          "Observability now has its own control-plane slice. Sink toggles, endpoints, and masked auth values save independently from the general application posture.",
        formId: "observability-form",
        statusId: "settings-observability-status",
        submitLabel: "Save observability settings",
        values: observabilityValues,
      }),
      sectionPanelClass(selectedSection === "observability", "panel panel--span-12"),
    )}
    ${card(
      "GigaChat",
      renderGigachatSection({
        bannerMessage:
          "Connection tests use the candidate values without persisting them. Saving updates the persisted target first, then reloads runtime only when no restart-sensitive fields are present.",
        formId: "gigachat-form",
        statusId: "settings-gigachat-status",
        submitLabel: "Save GigaChat settings",
        testButtonId: "gigachat-test",
        testButtonLabel: "Test connection",
        values: gigachatValues,
        variant: "settings",
      }),
      sectionPanelClass(selectedSection === "gigachat", "panel panel--span-12"),
    )}
    ${card(
      "Security",
      renderSecuritySection({
        bannerMessage:
          "Auth and CORS always save to the control plane first. If this batch includes restart-sensitive fields, the running process keeps the previous posture until restart.",
        formId: "security-form",
        statusId: "settings-security-status",
        submitLabel: "Save security settings",
        values: securityValues,
        variant: "settings",
      }),
      sectionPanelClass(selectedSection === "security", "panel panel--span-12"),
    )}
    ${card(
      "Recent revisions",
      revisions.length
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
                          <span class="pill">${escapeHtml(asArray<string>(revision.sections).join(", ") || "no field diff")}</span>
                          <button class="button button--secondary" data-rollback-revision="${escapeHtml(revisionId)}" type="button">Rollback</button>
                        </div>
                        ${revision.restored_from_revision_id ? banner(`Rollback snapshot from revision ${String(revision.restored_from_revision_id)}.`) : ""}
                        ${renderDiffSections(asRecord(revision.diff) as Record<string, never[]>, "Revision matches the current runtime config.")}
                      </div>
                    </article>
                  `;
                })
                .join("")}
            </div>
          `
        : `<p>No persisted revisions yet. Save a settings change to start revision history.</p>`,
      sectionPanelClass(selectedSection === "history", "panel panel--span-8"),
    )}
    ${card(
      "Persistence",
      `
        <div class="stack">
          <div id="settings-revisions-status"></div>
          <div class="stat-line"><strong>Persisted target</strong><span class="muted">${Boolean(controlPlaneStatus.persisted) ? "saved" : "not saved yet"}</span></div>
          <div class="stat-line"><strong>Last update</strong><span class="muted">${escapeHtml(controlPlaneStatus.updated_at ? formatTimestamp(controlPlaneStatus.updated_at) : "n/a")}</span></div>
          <p class="muted">Rollback restores the persisted target first. Runtime follows immediately only when the restored change set is restart-safe.</p>
        </div>
      `,
      sectionPanelClass(selectedSection === "history", "panel panel--span-4"),
    )}
  `);

  document.getElementById("reload-settings")?.addEventListener("click", () => {
    void app.render("settings");
  });

  app.pageContent.querySelectorAll<HTMLButtonElement>("[data-settings-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = button.dataset.settingsSection as SettingsSection | undefined;
      if (!section) {
        return;
      }
      const url = new URL(window.location.href);
      url.searchParams.set("section", section);
      window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
      void app.render("settings");
    });
  });

  const applicationForm = app.pageContent.querySelector<HTMLFormElement>("#application-form");
  const observabilityForm =
    app.pageContent.querySelector<HTMLFormElement>("#observability-form");
  const gigachatForm = app.pageContent.querySelector<HTMLFormElement>("#gigachat-form");
  const securityForm = app.pageContent.querySelector<HTMLFormElement>("#security-form");
  const applicationStatusNode = app.pageContent.querySelector<HTMLElement>(
    "#settings-application-status",
  );
  const observabilityStatusNode = app.pageContent.querySelector<HTMLElement>(
    "#settings-observability-status",
  );
  const gigachatStatusNode = app.pageContent.querySelector<HTMLElement>("#settings-gigachat-status");
  const securityStatusNode = app.pageContent.querySelector<HTMLElement>("#settings-security-status");
  const revisionsStatusNode = app.pageContent.querySelector<HTMLElement>("#settings-revisions-status");
  if (
    !applicationForm ||
    !observabilityForm ||
    !gigachatForm ||
    !securityForm ||
    !applicationStatusNode ||
    !observabilityStatusNode ||
    !gigachatStatusNode ||
    !securityStatusNode ||
    !revisionsStatusNode
  ) {
    return;
  }

  const applicationFields = applicationForm.elements as typeof applicationForm.elements & {
    enabled_providers: HTMLInputElement;
  };
  const observabilityFields = observabilityForm.elements as typeof observabilityForm.elements & {
    otlp_headers: HTMLTextAreaElement;
  };
  const gigachatFields = gigachatForm.elements as typeof gigachatForm.elements & {
    timeout?: HTMLInputElement;
  };
  const securityFields = securityForm.elements as typeof securityForm.elements & {
    governance_limits: HTMLTextAreaElement;
  };
  bindValidityReset(
    applicationFields.enabled_providers,
    observabilityFields.otlp_headers,
    gigachatFields.timeout,
    securityFields.governance_limits,
  );

  const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(
    gigachatForm,
    gigachatValues,
  );

  let applicationActionState: InlineStatus | null = null;
  let observabilityActionState: InlineStatus | null = null;
  let gigachatActionState: InlineStatus | null = null;
  let securityActionState: InlineStatus | null = null;
  let revisionsActionState: InlineStatus | null = null;

  const getApplicationValidationMessage = (report = false) =>
    validateRequiredCsvField(
      applicationFields.enabled_providers,
      "Provide at least one enabled provider.",
      { report },
    );

  const getGigachatValidationMessage = (report = false) =>
    validatePositiveNumberField(
      gigachatFields.timeout,
      "Timeout must be a positive number of seconds.",
      { report },
    );

  const getObservabilityValidationMessage = (report = false) =>
    validateJsonObjectField(
      observabilityFields.otlp_headers,
      (
        (
          buildObservabilityPayload(observabilityForm).otlp as Record<
            string,
            unknown
          >
        )?.headers ?? null
      ) as unknown,
      {
        invalidMessage: "OTLP headers must be valid JSON.",
        nonObjectMessage: "OTLP headers must be a JSON object of header names to values.",
        report,
      },
    );

  const getSecurityValidationMessage = (
    payload: Record<string, unknown> & { governance_limits?: unknown },
    report = false,
  ) =>
    validateJsonArrayField(securityFields.governance_limits, payload.governance_limits, {
      invalidMessage: "Governance limits must be valid JSON.",
      nonArrayMessage: "Governance limits must be a JSON array of rule descriptors.",
      report,
    });

  const refreshSectionStatus = () => {
    const observabilityPayload = buildObservabilityPayload(observabilityForm);
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
    const observabilityEntries = buildObservabilityDiffEntries(
      observabilityValues,
      observabilityPayload,
    );
    const securityPayload = buildSecurityPayload(securityForm);
    const securityEntries = buildPendingDiffEntries("security", securityValues, securityPayload);
    const applicationValidationMessage = getApplicationValidationMessage();
    const observabilityValidationMessage = getObservabilityValidationMessage();
    const gigachatValidationMessage = getGigachatValidationMessage();
    const securityValidationMessage = getSecurityValidationMessage(securityPayload);
    const stagedSecretMessages = collectSecretFieldMessages([
      syncCredentialsSecret(),
      syncAccessTokenSecret(),
    ]);
    const observabilityFieldMessages = collectSecretFieldMessages([
      syncOtlpHeadersField(),
      syncLangfusePublicKey(),
      syncLangfuseSecretKey(),
      syncPhoenixApiKey(),
    ]);

    renderControlPlaneStatusNode(applicationStatusNode, {
      entries: applicationEntries,
      persisted: Boolean(controlPlaneStatus.persisted),
      updatedAt: controlPlaneStatus.updated_at,
      note: "Mode, provider routing, runtime-store backend and auth-adjacent controls are the main restart-sensitive levers here.",
      validationMessage: applicationValidationMessage || undefined,
      actionState: applicationActionState,
    });
    renderControlPlaneStatusNode(observabilityStatusNode, {
      entries: observabilityEntries,
      persisted: Boolean(controlPlaneStatus.persisted),
      updatedAt: controlPlaneStatus.updated_at,
      note: observabilityFieldMessages.length
        ? `Sink changes apply live when telemetry stays enabled. ${observabilityFieldMessages.join(" ")}`
        : "Sink changes apply live and stay restart-safe unless a later backend slice marks them otherwise.",
      validationMessage: observabilityValidationMessage || undefined,
      actionState: observabilityActionState,
    });
    renderControlPlaneStatusNode(gigachatStatusNode, {
      entries: gigachatEntries,
      persisted: Boolean(controlPlaneStatus.persisted),
      updatedAt: controlPlaneStatus.updated_at,
      note: stagedSecretMessages.length
        ? `Connection tests never persist the form. ${stagedSecretMessages.join(" ")}`
        : "Connection tests never persist the form. Secret values stay masked after save.",
      validationMessage: gigachatValidationMessage || undefined,
      actionState: gigachatActionState,
    });
    renderControlPlaneStatusNode(securityStatusNode, {
      entries: securityEntries,
      persisted: Boolean(controlPlaneStatus.persisted),
      updatedAt: controlPlaneStatus.updated_at,
      note: "Saved security changes always update the persisted target first. Runtime posture only changes immediately when the whole batch is restart-safe.",
      validationMessage: securityValidationMessage || undefined,
      actionState: securityActionState,
    });
    renderInlineBannerStatus(
      revisionsStatusNode,
      revisionsActionState,
      "Use history only when you need to restore a known-good persisted snapshot.",
    );
  };

  applicationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (getApplicationValidationMessage(true)) {
      refreshSectionStatus();
      return;
    }
    await persistControlPlaneSection({
      app,
      form: applicationForm,
      button: getSubmitterButton(event as SubmitEvent, applicationForm),
      endpoint: "/admin/api/settings/application",
      payload: buildApplicationPayload(applicationForm),
      refreshStatus: refreshSectionStatus,
      setActionState: (state) => {
        applicationActionState = state;
      },
      pendingMessage:
        "Saving application settings. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
      outcomeLabel: "Application settings",
      failurePrefix: "Application settings failed to save",
      rerenderPage: "settings",
    });
  });

  const syncOtlpHeadersField = bindReplaceableFieldBehavior({
    form: observabilityForm,
    fieldName: "otlp_headers",
    clearFieldName: "otlp_clear_headers",
    preview: renderConfiguredPreview(
      asRecord(observabilityValues.otlp),
      "header_names",
      "headers_configured",
    ),
    clearPlaceholder: "Uncheck clear to paste a replacement header object",
    noteReplace: "replace the stored OTLP headers on save.",
    noteClear: "clear the stored OTLP headers on save.",
    noteKeep: "keep the stored OTLP headers unless you paste a replacement JSON object.",
    messageReplace: "A new OTLP headers object is staged and will replace the stored value on save.",
    messageClear: "Stored OTLP headers will be removed when this section is saved.",
    messageKeep: "Stored OTLP headers remain unchanged unless you paste a replacement JSON object.",
  });
  const syncLangfusePublicKey = bindSecretFieldBehavior({
    form: observabilityForm,
    fieldName: "langfuse_public_key",
    clearFieldName: "langfuse_clear_public_key",
    preview: String(asRecord(observabilityValues.langfuse).public_key_preview ?? "not configured"),
  });
  const syncLangfuseSecretKey = bindSecretFieldBehavior({
    form: observabilityForm,
    fieldName: "langfuse_secret_key",
    clearFieldName: "langfuse_clear_secret_key",
    preview: String(asRecord(observabilityValues.langfuse).secret_key_preview ?? "not configured"),
  });
  const syncPhoenixApiKey = bindSecretFieldBehavior({
    form: observabilityForm,
    fieldName: "phoenix_api_key",
    clearFieldName: "phoenix_clear_api_key",
    preview: String(asRecord(observabilityValues.phoenix).api_key_preview ?? "not configured"),
  });

  refreshSectionStatus();
  [applicationForm, observabilityForm, gigachatForm, securityForm].forEach((form) => {
    form.addEventListener("input", refreshSectionStatus);
    form.addEventListener("change", refreshSectionStatus);
  });

  observabilityForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (getObservabilityValidationMessage(true)) {
      refreshSectionStatus();
      return;
    }
    await persistControlPlaneSection({
      app,
      form: observabilityForm,
      button: getSubmitterButton(event as SubmitEvent, observabilityForm),
      endpoint: "/admin/api/settings/observability",
      payload: buildObservabilityPayload(observabilityForm),
      refreshStatus: refreshSectionStatus,
      setActionState: (state) => {
        observabilityActionState = state;
      },
      pendingMessage:
        "Saving observability settings. The persisted target updates first, then live sinks reload without a restart.",
      outcomeLabel: "Observability settings",
      failurePrefix: "Observability settings failed to save",
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
      button: getSubmitterButton(event as SubmitEvent, gigachatForm),
      endpoint: "/admin/api/settings/gigachat",
      payload: collectGigachatPayload(gigachatForm),
      refreshStatus: refreshSectionStatus,
      setActionState: (state) => {
        gigachatActionState = state;
      },
      pendingMessage:
        "Saving GigaChat settings. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
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
      pendingMessage:
        "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save.",
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
      button: getSubmitterButton(event as SubmitEvent, securityForm),
      endpoint: "/admin/api/settings/security",
      payload,
      refreshStatus: refreshSectionStatus,
      setActionState: (state) => {
        securityActionState = state;
      },
      pendingMessage:
        "Saving security settings. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
      outcomeLabel: "Security settings",
      failurePrefix: "Security settings failed to save",
      rerenderPage: "settings",
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-rollback-revision]").forEach((button) => {
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
            const response = await app.api.json<Record<string, unknown>>(
              `/admin/api/settings/revisions/${revisionId}/rollback`,
              { method: "POST" },
            );
            const outcome = describePersistOutcome(`Revision ${revisionId}`, response);
            app.queueAlert(outcome.message, outcome.tone);
            await app.render("settings");
          },
        });
      } catch (error) {
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

function getSelectedSettingsSection(): SettingsSection {
  const value = new URLSearchParams(window.location.search).get("section");
  return SETTINGS_SECTIONS.includes(value as SettingsSection)
    ? (value as SettingsSection)
    : "application";
}

function renderSectionButton(section: SettingsSection, selectedSection: SettingsSection): string {
  const labels: Record<SettingsSection, string> = {
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

function sectionPanelClass(isVisible: boolean, baseClass: string): string {
  return isVisible ? baseClass : `${baseClass} is-hidden`;
}

function renderConfiguredPreview(
  values: Record<string, unknown>,
  namesField: string,
  configuredField: string,
): string {
  const names = asArray<string>(values[namesField]);
  if (names.length) {
    return `configured (${names.join(", ")})`;
  }
  return Boolean(values[configuredField]) ? "configured" : "not configured";
}
