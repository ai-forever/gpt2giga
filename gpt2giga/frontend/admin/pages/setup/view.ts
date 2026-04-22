import { subpagesFor } from "../../routes.js";
import {
  banner,
  card,
  pill,
  renderSetupSteps,
  renderSubpageNav,
} from "../../templates.js";
import {
  asArray,
  describeGigachatAuth,
  describePersistenceStatus,
  escapeHtml,
} from "../../utils.js";
import {
  renderApplicationSection,
  renderGigachatSection,
  renderSecuritySection,
  renderSetupObservabilityHandoff,
} from "../control-plane-sections.js";
import type { SetupPageState } from "./state.js";

export function renderSetupContent(state: SetupPageState): string {
  return state.activeSection === null
    ? renderSetupHub(state)
    : renderFocusedSetupPage(state);
}

function renderSetupHub(state: SetupPageState): string {
  const persistence = describePersistenceStatus(state.setup);
  const gigachatAuth = describeGigachatAuth(state.setup);
  return `
    ${card(
      "Setup map",
      renderSubpageNav({
        currentPage: state.currentPage,
        title: "Setup pages",
        intro: "Use the hub for progress.",
        items: subpagesFor(state.currentPage),
      }),
      "panel panel--span-12",
    )}
    ${card(
      "Setup progress",
      `
        <div class="stack">
          ${renderSetupSteps(asArray(state.setup.wizard_steps))}
          ${
            state.bootstrap.required
              ? banner(
                  `Bootstrap gate is open. Setup is limited to localhost or the token at ${String(state.bootstrap.token_path ?? "the control-plane volume")}.`,
                  "warn",
                )
              : banner(
                  "Bootstrap gate is closed. Admin or global API key access is active.",
                )
          }
          <div class="toolbar">
            ${pill(`Claim: ${state.claim.claimed ? "done" : state.claim.required ? "pending" : "not required"}`, state.claim.claimed ? "good" : "warn")}
            ${pill(persistence.pillLabel, persistence.tone)}
            ${pill(gigachatAuth.pillLabel, gigachatAuth.tone)}
            ${pill(`Security: ${state.setup.security_ready ? "ready" : "pending"}`, state.setup.security_ready ? "good" : "warn")}
          </div>
          <div class="toolbar">
            <a class="button" href="${escapeHtml(state.nextStep.href)}">${escapeHtml(state.nextStep.label)}</a>
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
          <div class="stat-line"><strong>Runtime mode</strong><span class="muted">${escapeHtml(state.runtime.mode ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Store backend</strong><span class="muted">${escapeHtml(state.runtime.runtime_store_backend ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Active store</strong><span class="muted">${escapeHtml(state.applicationValues.runtime_store_active_backend ?? state.runtime.runtime_store_backend ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Control-plane file</strong><span class="muted">${escapeHtml(state.setup.path ?? "n/a")}</span></div>
          <div class="stat-line"><strong>Encryption key file</strong><span class="muted">${escapeHtml(state.setup.key_path ?? "n/a")}</span></div>
          ${
            state.warnings.length
              ? state.warnings.map((warning) => banner(String(warning), "warn")).join("")
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
          ${banner(state.nextStep.note)}
          <div class="toolbar">
            <a class="button" href="${escapeHtml(state.nextStep.href)}">${escapeHtml(state.nextStep.label)}</a>
            <a class="button button--secondary" href="/admin/settings-observability">Observability settings</a>
          </div>
          <div class="toolbar">
            ${pill(`Observability sinks: ${asArray<string>(state.observabilityValues.active_sinks).join(", ") || "none"}`)}
            ${pill(`Setup complete: ${state.setup.setup_complete ? "yes" : "no"}`, state.setup.setup_complete ? "good" : "warn")}
          </div>
        </div>
      `,
      "panel panel--span-6",
    )}
    ${renderSetupStepCard({
      title: "Claim",
      href: "/admin/setup-claim",
      description: state.claim.required
        ? state.claim.claimed
          ? "Bootstrap claim is already recorded."
          : "Record the first operator."
        : "Claiming is not required.",
      pills: [
        pill(`Required: ${state.claim.required ? "yes" : "no"}`),
        pill(`Claimed: ${state.claim.claimed ? "yes" : "no"}`, state.claim.claimed ? "good" : "warn"),
      ],
    })}
    ${renderSetupStepCard({
      title: "Application",
      href: "/admin/setup-application",
      description: "Persist runtime mode and provider posture.",
      pills: [
        pill(persistence.pillLabel, persistence.tone),
        pill(`Mode: ${String(state.runtime.mode ?? "n/a")}`),
      ],
    })}
    ${renderSetupStepCard({
      title: "GigaChat",
      href: "/admin/setup-gigachat",
      description: "Configure credentials and test the connection.",
      pills: [
        pill(gigachatAuth.pillLabel, gigachatAuth.tone),
        pill(`Backend: ${String(state.runtime.gigachat_api_mode ?? "n/a")}`),
      ],
    })}
    ${renderSetupStepCard({
      title: "Security",
      href: "/admin/setup-security",
      description: "Close bootstrap access and stage gateway auth.",
      pills: [
        pill(`Ready: ${state.setup.security_ready ? "yes" : "no"}`, state.setup.security_ready ? "good" : "warn"),
        pill(`Bootstrap gate: ${state.bootstrap.required ? "open" : "closed"}`, state.bootstrap.required ? "warn" : "good"),
      ],
    })}
  `;
}

function renderFocusedSetupPage(state: SetupPageState): string {
  return `
    ${card(
      "Setup navigation",
      renderSubpageNav({
        currentPage: state.currentPage,
        title: "Setup pages",
        intro: "One task per page.",
        items: subpagesFor(state.currentPage),
      }),
      "panel panel--span-12",
    )}
    ${renderSetupMainCard(state)}
    ${renderSetupSidebar(state)}
  `;
}

function renderSetupMainCard(state: SetupPageState): string {
  if (state.activeSection === "claim") {
    return card(
      "Claim instance",
      `
        <div class="stack">
          ${banner(
            state.claim.required
              ? state.claim.claimed
                ? `This bootstrap session is already claimed${state.claim.operator_label ? ` by ${String(state.claim.operator_label)}` : ""}.`
                : "First-run PROD bootstrap is active. Claim the instance before continuing."
              : "Claiming is not required.",
            state.claim.claimed ? "info" : "warn",
          )}
          ${
            state.claim.claimed
              ? `
                  <div class="dual-grid">
                    <div class="stack">
                      ${pill(`Claimed at: ${String(state.claim.claimed_at ?? "n/a")}`)}
                      ${pill(`Claimed via: ${String(state.claim.claimed_via ?? "n/a")}`)}
                    </div>
                    <div class="stack">
                      ${pill(`Operator label: ${String(state.claim.operator_label ?? "not recorded")}`)}
                      ${pill(`Source IP: ${String(state.claim.claimed_from ?? "unknown")}`)}
                    </div>
                  </div>
                `
              : state.claim.required
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
                : `<p class="muted">No bootstrap claim is required in this runtime.</p>`
          }
        </div>
      `,
      "panel panel--span-8 panel--measure",
    );
  }

  if (state.activeSection === "application") {
    return card(
      "Application posture",
      renderApplicationSection({
        bannerMessage: "Saves the target config. Restart-sensitive fields wait for restart.",
        formId: "setup-application-form",
        statusId: "setup-application-status",
        submitLabel: "Save application step",
        values: state.applicationValues,
        variant: "setup",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  if (state.activeSection === "gigachat") {
    return card(
      "GigaChat auth",
      renderGigachatSection({
        bannerMessage: "Connection test is dry-run. Restart-sensitive fields wait for restart.",
        formId: "setup-gigachat-form",
        statusId: "setup-gigachat-status",
        submitLabel: "Save GigaChat step",
        testButtonId: "setup-gigachat-test",
        testButtonLabel: "Test connection",
        values: state.gigachatValues,
        variant: "setup",
      }),
      "panel panel--span-8 panel--measure",
    );
  }

  return card(
    "Security bootstrap",
    renderSecuritySection({
      bannerMessage: "Saves the target config first. Restart-sensitive fields wait for restart.",
      formId: "setup-security-form",
      statusId: "setup-security-status",
      submitLabel: "Save security step",
      values: state.securityValues,
      variant: "setup",
    }),
    "panel panel--span-8 panel--measure",
  );
}

function renderSetupSidebar(state: SetupPageState): string {
  if (state.activeSection === "security") {
    return `
      ${card(
        "Security posture",
        `
          <div class="stack">
            <div class="toolbar">
              ${pill(`Bootstrap gate: ${state.bootstrap.required ? "open" : "closed"}`, state.bootstrap.required ? "warn" : "good")}
              ${pill(`Global key: ${state.globalKey.configured ? "configured" : "missing"}`, state.globalKey.configured ? "good" : "warn")}
              ${pill(`Scoped keys: ${state.scopedKeys.length}`)}
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
              "Use the keys page for scoped inventory. This page keeps only the bootstrap global-key action nearby.",
            )}
          </div>
        `,
        "panel panel--span-4 panel--aside",
      )}
      ${card(
        "Observability handoff",
        renderSetupObservabilityHandoff(state.observabilityValues),
        "panel panel--span-4 panel--aside",
      )}
      ${renderSetupStatusCard(state)}
    `;
  }

  return renderSetupStatusCard(state);
}

function renderSetupStatusCard(state: SetupPageState): string {
  const persistence = describePersistenceStatus(state.setup);
  const gigachatAuth = describeGigachatAuth(state.setup);
  return card(
    "Setup status",
    `
      <div class="stack">
        <div class="toolbar">
          ${pill(`Runtime mode: ${String(state.runtime.mode ?? "n/a")}`)}
          ${pill(`Backend: ${String(state.runtime.gigachat_api_mode ?? "n/a")}`)}
          ${pill(`Setup complete: ${state.setup.setup_complete ? "yes" : "no"}`, state.setup.setup_complete ? "good" : "warn")}
        </div>
        <div class="stat-line"><strong>Claim</strong><span class="muted">${state.claim.claimed ? "claimed" : state.claim.required ? "pending" : "not required"}</span></div>
        <div class="stat-line"><strong>Persistence</strong><span class="muted">${escapeHtml(persistence.value)}</span></div>
        <div class="stat-line"><strong>GigaChat auth</strong><span class="muted">${escapeHtml(gigachatAuth.value)}</span></div>
        <div class="stat-line"><strong>Security ready</strong><span class="muted">${state.setup.security_ready ? "yes" : "no"}</span></div>
        ${
          state.warnings.length
            ? state.warnings.slice(0, 2).map((warning) => banner(String(warning), "warn")).join("")
            : banner("No setup warnings right now.")
        }
        <div class="toolbar">
          <a class="button button--secondary" href="/admin/setup">Back to setup hub</a>
          <a class="button" href="${escapeHtml(state.nextStep.href)}">${escapeHtml(state.nextStep.label)}</a>
        </div>
      </div>
    `,
    "panel panel--span-4 panel--aside",
  );
}

function renderSetupStepCard(options: {
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
