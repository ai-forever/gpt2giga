import { subpagesFor } from "../../routes.js";
import {
  banner,
  card,
  pill,
  renderDiffSections,
  renderSubpageNav,
} from "../../templates.js";
import {
  asArray,
  asRecord,
  describeGigachatAuth,
  describePersistenceStatus,
  escapeHtml,
  formatTimestamp,
} from "../../utils.js";
import {
  renderApplicationSection,
  renderGigachatSection,
  renderObservabilitySection,
  renderSecuritySection,
} from "../control-plane-sections.js";
import type { SettingsPageState, } from "./state.js";
import { SETTINGS_LABELS } from "./types.js";

export function renderSettingsContent(state: SettingsPageState): string {
  return state.activeSection === null
    ? renderSettingsHub(state)
    : renderFocusedSettingsPage(state);
}

function renderSettingsHub(state: SettingsPageState): string {
  const activeSinks = asArray<string>(state.observabilityValues.active_sinks);
  const persistence = describePersistenceStatus(state.controlPlaneStatus);
  const gigachatAuth = describeGigachatAuth(state.controlPlaneStatus);

  return `
    ${card(
      "Configuration map",
      renderSubpageNav({
        currentPage: state.currentPage,
        title: "Settings pages",
        intro: "One concern per page.",
        items: subpagesFor(state.currentPage),
      }),
      "panel panel--span-12",
    )}
    ${card(
      "Persistence posture",
      `
        <div class="stack">
          <div class="toolbar">
            ${pill(persistence.pillLabel, persistence.tone)}
            ${pill(
              state.controlPlaneStatus.updated_at
                ? `Last update: ${formatTimestamp(state.controlPlaneStatus.updated_at)}`
                : state.controlPlaneStatus.persistence_enabled === false
                  ? "Persisted updates unavailable"
                  : "No persisted updates yet",
            )}
            ${pill(`Recent revisions: ${state.revisions.length}`)}
          </div>
          ${
            state.revisions.length
              ? banner(
                  `Latest revision: ${escapeHtml(asArray<string>(state.revisions[0]?.sections).join(", ") || "no field diff")}.`,
                )
              : banner("No persisted revisions yet. The first save will create history.", "warn")
          }
        </div>
      `,
      "panel panel--span-12",
    )}
    ${renderSettingsEntryCard({
      title: "Application",
      href: "/admin/settings-application",
      description: "Runtime mode, provider posture, and restart-sensitive controls.",
      pills: [
        pill(`Mode: ${String(state.applicationValues.mode ?? "n/a")}`),
        pill(
          `Providers: ${asArray<string>(state.applicationValues.enabled_providers).join(", ") || "none"}`,
        ),
        pill(`Store: ${String(state.applicationValues.runtime_store_backend ?? "n/a")}`),
      ],
    })}
    ${renderSettingsEntryCard({
      title: "Observability",
      href: "/admin/settings-observability",
      description: "Telemetry sinks, presets, and live-safe changes.",
      pills: [
        pill(
          `Telemetry: ${Boolean(state.observabilityValues.enable_telemetry) ? "on" : "off"}`,
          Boolean(state.observabilityValues.enable_telemetry) ? "good" : "warn",
        ),
        pill(`Sinks: ${activeSinks.join(", ") || "none"}`),
        pill(
          `Phoenix: ${asArray<Record<string, unknown>>(state.observabilityValues.sinks)
            .some((sink) => sink.id === "phoenix" && sink.enabled)
            ? "enabled"
            : "off"}`,
        ),
      ],
    })}
    ${renderSettingsEntryCard({
      title: "GigaChat",
      href: "/admin/settings-gigachat",
      description: "Credentials, transport, SSL posture, and connection tests.",
      pills: [
        pill(gigachatAuth.pillLabel, gigachatAuth.tone),
        pill(`Model: ${String(state.gigachatValues.model ?? "n/a")}`),
        pill(`Scope: ${String(state.gigachatValues.scope ?? "n/a")}`),
      ],
    })}
    ${renderSettingsEntryCard({
      title: "Security",
      href: "/admin/settings-security",
      description: "Gateway auth, logs access, CORS, and governance.",
      pills: [
        pill(
          `API key auth: ${Boolean(state.securityValues.enable_api_key_auth) ? "on" : "off"}`,
          Boolean(state.securityValues.enable_api_key_auth) ? "good" : "warn",
        ),
        pill(
          `Logs allowlist: ${asArray<string>(state.securityValues.logs_ip_allowlist).length || 0}`,
        ),
        pill(
          `CORS origins: ${asArray<string>(state.securityValues.cors_allow_origins).length || 0}`,
        ),
      ],
    })}
    ${card(
      "History",
      `
        <div class="stack">
          ${
            state.revisions.length
              ? `
                  <div class="stack">
                    ${state.revisions
                      .slice(0, 3)
                      .map(
                        (revision) => `
                          <div class="stat-line">
                            <strong>${escapeHtml(formatTimestamp(revision.updated_at))}</strong>
                            <span class="muted">${escapeHtml(asArray<string>(revision.sections).join(", ") || "no field diff")}</span>
                          </div>
                        `,
                      )
                      .join("")}
                  </div>
                `
              : `<p class="muted">No revisions recorded yet.</p>`
          }
          <div class="toolbar">
            <a class="button" href="/admin/settings-history">Open history</a>
          </div>
        </div>
      `,
      "panel panel--span-12",
    )}
  `;
}

function renderFocusedSettingsPage(state: SettingsPageState): string {
  const activeSection = state.activeSection;
  if (activeSection === null) {
    return renderSettingsHub(state);
  }
  const mainContent = renderSettingsMainCard(state);
  const sidebar = renderSettingsSidebar(state);

  if (activeSection === "history") {
    return `
      ${card(
        "Configuration map",
        renderSubpageNav({
          currentPage: state.currentPage,
          title: "Settings pages",
          intro: "History stays separate from editing.",
          items: subpagesFor(state.currentPage),
        }),
        "panel panel--span-12",
      )}
      ${mainContent}
      ${sidebar}
    `;
  }

  return `
    ${card(
      `${SETTINGS_LABELS[activeSection]} navigation`,
      renderSubpageNav({
        currentPage: state.currentPage,
        title: "Settings pages",
        intro: "One task per page.",
        items: subpagesFor(state.currentPage),
      }),
      "panel panel--span-12",
    )}
    ${mainContent}
    ${sidebar}
  `;
}

function renderSettingsMainCard(state: SettingsPageState): string {
  if (state.activeSection === "application") {
    return card(
      "Application",
      renderApplicationSection({
        bannerMessage: "Saves target config. Restart-sensitive fields wait for restart.",
        formId: "application-form",
        statusId: "settings-application-status",
        submitLabel: "Save application settings",
        values: state.applicationValues,
        variant: "settings",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  if (state.activeSection === "observability") {
    return card(
      "Observability",
      renderObservabilitySection({
        bannerMessage: "Observability saves independently and applies live.",
        formId: "observability-form",
        statusId: "settings-observability-status",
        submitLabel: "Save observability settings",
        values: state.observabilityValues,
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  if (state.activeSection === "gigachat") {
    return card(
      "GigaChat",
      renderGigachatSection({
        bannerMessage: "Connection test is dry-run. Restart-sensitive fields wait for restart.",
        formId: "gigachat-form",
        statusId: "settings-gigachat-status",
        submitLabel: "Save GigaChat settings",
        testButtonId: "gigachat-test",
        testButtonLabel: "Test connection",
        values: state.gigachatValues,
        variant: "settings",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  if (state.activeSection === "security") {
    return card(
      "Security",
      renderSecuritySection({
        bannerMessage: "Saves target config first. Restart-sensitive fields wait for restart.",
        formId: "security-form",
        statusId: "settings-security-status",
        submitLabel: "Save security settings",
        values: state.securityValues,
        variant: "settings",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  return card(
    "Recent revisions",
    state.revisions.length
      ? `
          <div class="stack">
            ${state.revisions
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
                      ${
                        revision.restored_from_revision_id
                          ? banner(
                              `Rollback snapshot from revision ${String(revision.restored_from_revision_id)}.`,
                            )
                          : ""
                      }
                      ${renderDiffSections(
                        asRecord(revision.diff) as Record<string, never[]>,
                        "Revision matches the current runtime config.",
                      )}
                    </div>
                  </article>
                `;
              })
              .join("")}
          </div>
        `
      : `<p>No persisted revisions yet. Save a settings change to start revision history.</p>`,
    "panel panel--span-8 panel--measure",
  );
}

function renderSettingsSidebar(state: SettingsPageState): string {
  const persistence = describePersistenceStatus(state.controlPlaneStatus);
  const gigachatAuth = describeGigachatAuth(state.controlPlaneStatus);
  const detailPills = (() => {
    if (state.activeSection === "application") {
      return [
        pill(`Mode: ${String(state.applicationValues.mode ?? "n/a")}`),
        pill(
          `Providers: ${asArray<string>(state.applicationValues.enabled_providers).join(", ") || "none"}`,
        ),
        pill(`Responses mode: ${String(state.applicationValues.gigachat_responses_api_mode ?? "inherit")}`),
      ];
    }
    if (state.activeSection === "observability") {
      return [
        pill(
          `Telemetry: ${Boolean(state.observabilityValues.enable_telemetry) ? "on" : "off"}`,
          Boolean(state.observabilityValues.enable_telemetry) ? "good" : "warn",
        ),
        pill(`Sinks: ${asArray<string>(state.observabilityValues.active_sinks).join(", ") || "none"}`),
        pill(`Phoenix project: ${String(state.observabilityValues.phoenix_project_name ?? "n/a")}`),
      ];
    }
    if (state.activeSection === "gigachat") {
      return [
        pill(gigachatAuth.pillLabel, gigachatAuth.tone),
        pill(`Model: ${String(state.gigachatValues.model ?? "n/a")}`),
        pill(`Verify SSL: ${Boolean(state.gigachatValues.verify_ssl_certs) ? "on" : "off"}`),
      ];
    }
    if (state.activeSection === "security") {
      return [
        pill(
          `API key auth: ${Boolean(state.securityValues.enable_api_key_auth) ? "on" : "off"}`,
          Boolean(state.securityValues.enable_api_key_auth) ? "good" : "warn",
        ),
        pill(
          `Logs allowlist: ${asArray<string>(state.securityValues.logs_ip_allowlist).length || 0}`,
        ),
        pill(
          `Governance rules: ${asArray<Record<string, unknown>>(state.securityValues.governance_limits).length || 0}`,
        ),
      ];
    }
    return [
      pill(`Revisions: ${state.revisions.length}`),
      pill(
        state.controlPlaneStatus.updated_at
          ? `Last update: ${formatTimestamp(state.controlPlaneStatus.updated_at)}`
          : state.controlPlaneStatus.persistence_enabled === false
            ? "Persisted updates unavailable"
            : "No persisted update yet",
      ),
      pill(persistence.pillLabel, persistence.tone),
    ];
  })();

  return card(
    state.activeSection === "history" ? "Rollback posture" : "Section posture",
    `
      <div class="stack">
        <div class="stack">
          <div id="settings-revisions-status"></div>
          <div class="toolbar">
            ${detailPills.join("")}
          </div>
          <div class="stat-line"><strong>Persistence</strong><span class="muted">${escapeHtml(persistence.value)}</span></div>
          <div class="stat-line"><strong>Last update</strong><span class="muted">${escapeHtml(state.controlPlaneStatus.updated_at ? formatTimestamp(state.controlPlaneStatus.updated_at) : "n/a")}</span></div>
        </div>
        ${
          state.activeSection === "history"
            ? banner(
                "Rollback restores the persisted target first. Runtime follows only for restart-safe changes.",
                "warn",
              )
            : banner("Use history only when you need a known-good snapshot.")
        }
        <div class="toolbar">
          <a class="button button--secondary" href="/admin/settings">Back to settings hub</a>
          ${
            state.activeSection === "history"
              ? `<a class="button" href="/admin/settings-application">Open application settings</a>`
              : `<a class="button" href="/admin/settings-history">Open history</a>`
          }
        </div>
      </div>
    `,
    "panel panel--span-4 panel--aside",
  );
}

function renderSettingsEntryCard(options: {
  description: string;
  href: string;
  pills: string[];
  title: string;
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
