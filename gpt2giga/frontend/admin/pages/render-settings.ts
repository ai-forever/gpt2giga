import type { AdminApp } from "../app.js";
import {
  bindValidityReset,
  buildApplicationPayload,
  buildPendingDiffEntries,
  buildSecurityPayload,
  collectGigachatPayload,
  describePersistOutcome,
  summarizePendingChanges,
  validateJsonArrayField,
  validatePositiveNumberField,
  validateRequiredCsvField,
  withBusyState,
} from "../forms.js";
import {
  bindGigachatSecretFields,
  renderApplicationSection,
  renderGigachatSection,
} from "./control-plane-sections.js";
import {
  banner,
  card,
  pill,
  renderBooleanSelectOptions,
  renderControlPlaneSectionStatus,
  renderDiffSections,
} from "../templates.js";
import {
  asArray,
  asRecord,
  csv,
  escapeHtml,
  formatTimestamp,
  toErrorMessage,
} from "../utils.js";

type InlineStatus = {
  tone: "info" | "warn" | "danger";
  message: string;
};

type SettingsSection = "application" | "gigachat" | "security" | "history";

const SETTINGS_SECTIONS: SettingsSection[] = [
  "application",
  "gigachat",
  "security",
  "history",
];

export async function renderSettings(app: AdminApp, token: number): Promise<void> {
  const [application, gigachat, security, revisionsPayload] = await Promise.all([
    app.api.json<Record<string, unknown>>("/admin/api/settings/application"),
    app.api.json<Record<string, unknown>>("/admin/api/settings/gigachat"),
    app.api.json<Record<string, unknown>>("/admin/api/settings/security"),
    app.api.json<Record<string, unknown>>("/admin/api/settings/revisions?limit=6"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const applicationValues = asRecord(application.values);
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
      `
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
      `,
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
  const gigachatForm = app.pageContent.querySelector<HTMLFormElement>("#gigachat-form");
  const securityForm = app.pageContent.querySelector<HTMLFormElement>("#security-form");
  const applicationStatusNode = app.pageContent.querySelector<HTMLElement>(
    "#settings-application-status",
  );
  const gigachatStatusNode = app.pageContent.querySelector<HTMLElement>("#settings-gigachat-status");
  const securityStatusNode = app.pageContent.querySelector<HTMLElement>("#settings-security-status");
  const revisionsStatusNode = app.pageContent.querySelector<HTMLElement>("#settings-revisions-status");
  if (
    !applicationForm ||
    !gigachatForm ||
    !securityForm ||
    !applicationStatusNode ||
    !gigachatStatusNode ||
    !securityStatusNode ||
    !revisionsStatusNode
  ) {
    return;
  }

  const applicationFields = applicationForm.elements as typeof applicationForm.elements & {
    enabled_providers: HTMLInputElement;
  };
  const gigachatFields = gigachatForm.elements as typeof gigachatForm.elements & {
    timeout?: HTMLInputElement;
  };
  const securityFields = securityForm.elements as typeof securityForm.elements & {
    governance_limits: HTMLTextAreaElement;
  };
  bindValidityReset(
    applicationFields.enabled_providers,
    gigachatFields.timeout,
    securityFields.governance_limits,
  );

  const [syncCredentialsSecret, syncAccessTokenSecret] = bindGigachatSecretFields(
    gigachatForm,
    gigachatValues,
  );

  let applicationActionState: InlineStatus | null = null;
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

  const getSecurityValidationMessage = (
    payload: Record<string, unknown> & { governance_limits: unknown },
    report = false,
  ) =>
    validateJsonArrayField(securityFields.governance_limits, payload.governance_limits, {
      invalidMessage: "Governance limits must be valid JSON.",
      nonArrayMessage: "Governance limits must be a JSON array of rule descriptors.",
      report,
    });

  const refreshSectionStatus = () => {
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
    const securityPayload = buildSecurityPayload(securityForm);
    const securityEntries = buildPendingDiffEntries("security", securityValues, securityPayload);
    const applicationValidationMessage = getApplicationValidationMessage();
    const gigachatValidationMessage = getGigachatValidationMessage();
    const securityValidationMessage = getSecurityValidationMessage(securityPayload);
    const secretStates = [syncCredentialsSecret(), syncAccessTokenSecret()].flatMap((state) =>
      state ? [state] : [],
    );
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
      : banner(
          "Use history only when you need to restore a known-good persisted snapshot.",
        );
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
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : applicationForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    applicationActionState = {
      tone: "info",
      message:
        "Saving application settings. The persisted target updates first; runtime only reloads if this batch stays restart-safe.",
    };
    refreshSectionStatus();
    try {
      await withBusyState({
        root: applicationForm,
        button,
        pendingLabel: "Saving…",
        action: async () => {
          const response = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/application",
            {
              method: "PUT",
              json: buildApplicationPayload(applicationForm),
            },
          );
          const outcome = describePersistOutcome("Application settings", response);
          app.queueAlert(outcome.message, outcome.tone);
          await app.render("settings");
        },
      });
    } catch (error) {
      applicationActionState = {
        tone: "danger",
        message: `Application settings failed to save: ${toErrorMessage(error)}`,
      };
      refreshSectionStatus();
      app.pushAlert(applicationActionState.message, "danger");
    }
  });

  gigachatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (getGigachatValidationMessage(true)) {
      refreshSectionStatus();
      return;
    }
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : gigachatForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    gigachatActionState = {
      tone: "info",
      message:
        "Saving GigaChat settings. Secrets stay masked; the persisted target updates first and runtime reload only happens for restart-safe batches.",
    };
    refreshSectionStatus();
    try {
      await withBusyState({
        root: gigachatForm,
        button,
        pendingLabel: "Saving…",
        action: async () => {
          const response = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/gigachat",
            {
              method: "PUT",
              json: collectGigachatPayload(gigachatForm),
            },
          );
          const outcome = describePersistOutcome("GigaChat settings", response);
          app.queueAlert(outcome.message, outcome.tone);
          await app.render("settings");
        },
      });
    } catch (error) {
      gigachatActionState = {
        tone: "danger",
        message: `GigaChat settings failed to save: ${toErrorMessage(error)}`,
      };
      refreshSectionStatus();
      app.pushAlert(gigachatActionState.message, "danger");
    }
  });

  document.getElementById("gigachat-test")?.addEventListener("click", async (event) => {
    if (getGigachatValidationMessage(true)) {
      refreshSectionStatus();
      return;
    }
    const button = event.currentTarget instanceof HTMLButtonElement ? event.currentTarget : null;
    gigachatActionState = {
      tone: "info",
      message:
        "Testing candidate GigaChat settings only. Persisted control-plane values stay unchanged until you save.",
    };
    refreshSectionStatus();
    try {
      await withBusyState({
        root: gigachatForm,
        button,
        pendingLabel: "Testing…",
        action: async () => {
          const result = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/gigachat/test",
            {
              method: "POST",
              json: collectGigachatPayload(gigachatForm),
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
          refreshSectionStatus();
          app.pushAlert(gigachatActionState.message, gigachatActionState.tone);
        },
      });
    } catch (error) {
      gigachatActionState = {
        tone: "danger",
        message: `GigaChat connection test failed: ${toErrorMessage(error)}`,
      };
      refreshSectionStatus();
      app.pushAlert(gigachatActionState.message, "danger");
    }
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
    const submitter = (event as SubmitEvent).submitter;
    const button =
      submitter instanceof HTMLButtonElement
        ? submitter
        : securityForm.querySelector<HTMLButtonElement>('button[type="submit"]');
    securityActionState = {
      tone: "info",
      message:
        "Saving security settings. The persisted target updates first; runtime posture only changes immediately when the batch is restart-safe.",
    };
    refreshSectionStatus();
    try {
      await withBusyState({
        root: securityForm,
        button,
        pendingLabel: "Saving…",
        action: async () => {
          const response = await app.api.json<Record<string, unknown>>(
            "/admin/api/settings/security",
            {
              method: "PUT",
              json: payload,
            },
          );
          const outcome = describePersistOutcome("Security settings", response);
          app.queueAlert(outcome.message, outcome.tone);
          await app.render("settings");
        },
      });
    } catch (error) {
      securityActionState = {
        tone: "danger",
        message: `Security settings failed to save: ${toErrorMessage(error)}`,
      };
      refreshSectionStatus();
      app.pushAlert(securityActionState.message, "danger");
    }
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
