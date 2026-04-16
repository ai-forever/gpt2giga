import type { AdminApp } from "../app.js";
import { pathForPage } from "../routes.js";
import {
  banner,
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderSetupSteps,
  renderStatLines,
  renderWorkflowCard,
} from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber, humanizeField } from "../utils.js";

type RouteRow = Record<string, unknown>;
type RouteGroupKey = "admin" | "openai" | "anthropic" | "gemini" | "system";

interface RouteGroupSummary {
  key: RouteGroupKey;
  label: string;
  count: number;
  samples: string[];
}

export async function renderSystem(app: AdminApp, token: number): Promise<void> {
  const [runtime, config, routes, setup] = await Promise.all([
    app.api.json<Record<string, unknown>>("/admin/api/runtime"),
    app.api.json<Record<string, unknown>>("/admin/api/config"),
    app.api.json<Record<string, unknown>>("/admin/api/routes"),
    app.api.json<Record<string, unknown>>("/admin/api/setup"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const diagnostics = { runtime, config, routes, setup };
  const routeRows = asArray<RouteRow>(routes.routes);
  const routeSummaries = buildRouteSummaries(routeRows);
  const runtimeState = asRecord(runtime.state);
  const configSummary = asRecord(config.summary);
  const warnings = asArray<unknown>(setup.warnings).map(String);
  const setupSteps = asArray<Record<string, unknown>>(setup.wizard_steps).map((step) => ({
    id: String(step.id ?? ""),
    label: String(step.label ?? "Step"),
    description: String(step.description ?? ""),
    ready: Boolean(step.ready),
  }));
  const runtimeProviders = asArray<unknown>(runtime.enabled_providers).map(String);
  const serviceState = asRecord(runtimeState.services);
  const providerState = asRecord(runtimeState.providers);
  const storeState = asRecord(runtimeState.stores);
  const readyServiceCount = countTruthyEntries(serviceState);
  const readyProviderCount = countTruthyEntries(providerState);
  const systemWarnings = buildSystemWarnings(setup, runtime, warnings, readyServiceCount);
  const setupActionPath = setup.setup_complete ? pathForPage("settings") : pathForPage("setup");
  const setupActionLabel = setup.setup_complete ? "Review settings" : "Finish setup";

  app.setHeroActions(`
    <button class="button button--secondary" id="copy-diagnostics" type="button">Copy diagnostics JSON</button>
    <a class="button button--secondary" href="/admin/providers">Provider diagnostics</a>
    <a class="button button--secondary" href="/admin/traffic">Traffic summary</a>
    <a class="button button--secondary" href="/admin/settings">Open settings</a>
  `);
  app.setContent(`
    ${kpi("Setup", setup.setup_complete ? "complete" : "in progress")}
    ${kpi("Warnings", formatNumber(systemWarnings.length))}
    ${kpi("Ready services", formatNumber(readyServiceCount))}
    ${kpi("Mounted routes", formatNumber(routeRows.length))}
    ${card(
      "Executive summary",
      `
        <div class="stack">
          ${systemWarnings.length ? systemWarnings.join("") : banner("No high-signal runtime blockers are visible from the current system snapshot.", "info")}
          ${renderDefinitionList(
            [
              {
                label: "Version and mode",
                value: `${String(runtime.app_version ?? "n/a")} / ${String(runtime.mode ?? "n/a")}`,
                note: setup.setup_complete
                  ? "Setup is complete and the control-plane summary is stable."
                  : "Bootstrap and setup still need operator attention.",
              },
              {
                label: "Persisted config",
                value: setup.persisted ? "present" : "defaults only",
                note: setup.persisted
                  ? "Runtime has a persisted control-plane source of truth."
                  : "Save Settings if you need restart-safe config.",
              },
              {
                label: "Provider posture",
                value: runtimeProviders.join(", ") || "none",
                note: `${formatNumber(readyProviderCount)} provider-layer dependencies are currently wired.`,
              },
              {
                label: "Diagnostics reach",
                value: `${formatNumber(routeRows.length)} mounted routes`,
                note: runtime.docs_enabled
                  ? "Docs/OpenAPI are exposed in the current runtime."
                  : "Docs/OpenAPI are disabled in the current runtime.",
              },
            ],
            "System summary is unavailable.",
          )}
        </div>
      `,
      "panel panel--span-5",
    )}
    ${card(
      "Diagnostic workflows",
      `
        <div class="stack">
          <p class="muted">
            Start from the smallest workflow that resolves the question. Open detailed diagnostics only after the executive summary still feels inconsistent.
          </p>
          <div class="workflow-grid">
            ${renderWorkflowCard({
              workflow: "start",
              title: setup.setup_complete ? "Bootstrap is stable" : "Close bootstrap gaps first",
              note: setup.setup_complete
                ? "System already sees persisted bootstrap posture. Use Settings only for deliberate day-2 changes, not as the first reaction to every warning banner."
                : "Missing persisted config, credentials, or security posture should be resolved before you spend time on deeper runtime forensics.",
              pills: [
                pill(`Persisted: ${setup.persisted ? "ready" : "missing"}`, setup.persisted ? "good" : "warn"),
                pill(`GigaChat: ${setup.gigachat_ready ? "ready" : "missing"}`, setup.gigachat_ready ? "good" : "warn"),
                pill(`Security: ${setup.security_ready ? "ready" : "pending"}`, setup.security_ready ? "good" : "warn"),
              ],
              actions: [
                { label: setupActionLabel, href: setupActionPath, primary: true },
                { label: "API Keys", href: pathForPage("keys") },
              ],
            })}
            ${renderWorkflowCard({
              workflow: "observe",
              title: "Confirm live request behavior before deep forensics",
              note: "If the runtime posture looks healthy here but clients still fail, move to Traffic first and only then hand off one narrowed request into Logs.",
              pills: [
                pill(`Routes: ${formatNumber(routeRows.length)}`),
                pill(`Services: ${formatNumber(readyServiceCount)} ready`, readyServiceCount ? "good" : "warn"),
                pill(`Providers: ${formatNumber(readyProviderCount)} ready`, readyProviderCount ? "good" : "warn"),
              ],
              actions: [
                { label: "Traffic", href: pathForPage("traffic"), primary: true },
                { label: "Logs", href: pathForPage("logs") },
              ],
            })}
            ${renderWorkflowCard({
              workflow: "diagnose",
              title: "Use staged diagnostics when the summary is not enough",
              note: "Route coverage, effective config, and raw payload export stay secondary until the summary and workflow cards no longer explain the mismatch.",
              pills: [
                pill(`Warnings: ${formatNumber(systemWarnings.length)}`, systemWarnings.length ? "warn" : "good"),
                pill(`Docs: ${runtime.docs_enabled ? "exposed" : "disabled"}`),
                pill(`Mode: ${String(runtime.mode ?? "n/a")}`),
              ],
              actions: [
                { label: "Providers", href: pathForPage("providers"), primary: true },
                { label: "Detailed diagnostics", href: "#system-detailed-diagnostics" },
              ],
            })}
          </div>
        </div>
      `,
      "panel panel--span-7",
    )}
    ${card(
      "Route coverage",
      renderDefinitionList(
        routeSummaries.map((group) => ({
          label: group.label,
          value: formatNumber(group.count),
          note: group.samples.length ? group.samples.join(", ") : "No routes in this group.",
        })),
        "No mounted routes were reported by the admin API.",
      ),
      "panel panel--span-4",
    )}
    ${card(
      "Readiness",
      `
        <div class="stack">
          ${renderStatLines(
            [
              {
                label: "Persisted control-plane config",
                value: setup.persisted ? "ready" : "missing",
                tone: setup.persisted ? "good" : "warn",
              },
              {
                label: "GigaChat credentials",
                value: setup.gigachat_ready ? "ready" : "missing",
                tone: setup.gigachat_ready ? "good" : "warn",
              },
              {
                label: "Security bootstrap",
                value: setup.security_ready ? "ready" : "pending",
                tone: setup.security_ready ? "good" : "warn",
              },
              {
                label: "Service wiring",
                value: `${formatNumber(readyServiceCount)} ready`,
                tone: readyServiceCount ? "good" : "warn",
              },
              {
                label: "Provider wiring",
                value: `${formatNumber(readyProviderCount)} ready`,
                tone: readyProviderCount ? "good" : "warn",
              },
            ],
            "Readiness metadata is unavailable.",
          )}
          ${
            setupSteps.length
              ? `
                  <div class="stack">
                    <span class="eyebrow">Checklist</span>
                    ${renderSetupSteps(setupSteps)}
                  </div>
                `
              : ""
          }
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Runtime posture",
      renderDefinitionList(
        [
          {
            label: "Auth required",
            value: runtime.auth_required ? "yes" : "no",
          },
          {
            label: "Enabled providers",
            value: runtimeProviders.join(", ") || "none",
          },
          {
            label: "Docs / OpenAPI",
            value: runtime.docs_enabled ? "exposed" : "disabled",
          },
          {
            label: "Telemetry",
            value: runtime.telemetry_enabled ? "enabled" : "disabled",
          },
          {
            label: "Governance limits",
            value: formatNumber(runtime.governance_limits_configured ?? 0),
          },
          {
            label: "Logs allowlist",
            value: runtime.logs_ip_allowlist_enabled ? "configured" : "open",
          },
          {
            label: "Reasoning",
            value: runtime.enable_reasoning ? "enabled" : "disabled",
          },
          {
            label: "Images",
            value: runtime.enable_images ? "enabled" : "disabled",
          },
        ],
        "Runtime posture metadata is unavailable.",
      ),
      "panel panel--span-4",
    )}
    ${card(
      "Config highlights",
      renderDefinitionList(
        buildConfigHighlightItems(configSummary, runtime, setup, storeState),
        "No config highlights were reported.",
      ),
      "panel panel--span-4",
    )}
    ${card(
      "Detailed diagnostics",
      `
        <div class="stack">
          <p class="muted">
            Detailed diagnostics stay staged until the executive summary, workflow handoff, and route coverage still leave ambiguity.
          </p>
          <details class="surface details-disclosure" id="system-detailed-diagnostics">
            <summary>Runtime state detail</summary>
            <div class="dual-grid">
              <section class="surface stack">
                <div class="surface__header">
                  <h4>Services</h4>
                  ${pill(`${formatNumber(readyServiceCount)} ready`, readyServiceCount ? "good" : "warn")}
                </div>
                ${renderBooleanSection(serviceState)}
              </section>
              <section class="surface stack">
                <div class="surface__header">
                  <h4>Providers</h4>
                  ${pill(`${formatNumber(readyProviderCount)} ready`, readyProviderCount ? "good" : "warn")}
                </div>
                ${renderBooleanSection(providerState)}
              </section>
              <section class="surface stack">
                <div class="surface__header">
                  <h4>Stores</h4>
                  ${pill(String(storeState.backend ?? "n/a"))}
                </div>
                ${renderSummarySection(storeState)}
              </section>
            </div>
          </details>
          <details class="surface details-disclosure">
            <summary>Effective config summary</summary>
            <div class="dual-grid">
              ${Object.entries(configSummary)
                .map(([sectionName, sectionValue]) => {
                  const sectionRecord = asRecord(sectionValue);
                  return `
                    <section class="surface stack">
                      <div class="surface__header">
                        <h4>${escapeHtml(humanizeField(sectionName))}</h4>
                        ${pill(`${formatNumber(Object.keys(sectionRecord).length)} fields`)}
                      </div>
                      ${renderDefinitionList(
                        Object.entries(sectionRecord).map(([key, value]) => ({
                          label: humanizeField(key),
                          value: summarizeValue(value),
                        })),
                        "No summary entries were reported.",
                      )}
                    </section>
                  `;
                })
                .join("")}
            </div>
          </details>
          <details class="surface details-disclosure">
            <summary>Raw diagnostics JSON</summary>
            <p class="field-note">
              Copy the full runtime, config, setup, and route payload when you need a precise snapshot for debugging or for a support handoff.
            </p>
            <pre class="code-block code-block--tall" id="system-diagnostics">${escapeHtml(JSON.stringify(diagnostics, null, 2))}</pre>
          </details>
        </div>
      `,
      "panel panel--span-12",
    )}
  `);

  document.getElementById("copy-diagnostics")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2));
      app.pushAlert("Diagnostics copied to clipboard.", "info");
    } catch (error) {
      app.pushAlert(error instanceof Error ? error.message : String(error), "danger");
    }
  });
}

function buildRouteSummaries(routes: RouteRow[]): RouteGroupSummary[] {
  const groups: Record<RouteGroupKey, string[]> = {
    admin: [],
    openai: [],
    anthropic: [],
    gemini: [],
    system: [],
  };

  routes.forEach((route) => {
    const path = String(route.path ?? "");
    groups[classifyRoute(path)].push(path);
  });

  const descriptors: Array<Pick<RouteGroupSummary, "key" | "label">> = [
    { key: "admin", label: "Admin routes" },
    { key: "openai", label: "OpenAI routes" },
    { key: "anthropic", label: "Anthropic routes" },
    { key: "gemini", label: "Gemini routes" },
    { key: "system", label: "System routes" },
  ];

  return descriptors.map(({ key, label }) => ({
    key,
    label,
    count: groups[key].length,
    samples: [...new Set(groups[key])].slice(0, 3),
  }));
}

function buildSystemWarnings(
  setup: Record<string, unknown>,
  runtime: Record<string, unknown>,
  setupWarnings: string[],
  readyServiceCount: number,
): string[] {
  const warnings: string[] = setupWarnings.map((warning) => banner(warning, "warn"));
  if (!setup.persisted) {
    warnings.push(
      banner(
        "Control-plane state is not persisted. A restart can revert the operator posture back to defaults.",
        "warn",
      ),
    );
  }
  if (!runtime.auth_required) {
    warnings.push(
      banner(
        "Gateway auth is currently open. Review security posture before treating this runtime as externally reachable.",
        "warn",
      ),
    );
  }
  if (runtime.docs_enabled && runtime.mode === "DEV") {
    warnings.push(
      banner(
        "Docs and OpenAPI are exposed in DEV mode. Useful for operators, but this remains a softer system posture than hardened PROD.",
        "info",
      ),
    );
  }
  if (readyServiceCount === 0) {
    warnings.push(
      banner(
        "No feature services are wired in app state. Mounted routes may exist, but request handling will not be operational.",
        "warn",
      ),
    );
  }
  return warnings;
}

function buildConfigHighlightItems(
  configSummary: Record<string, unknown>,
  runtime: Record<string, unknown>,
  setup: Record<string, unknown>,
  storeState: Record<string, unknown>,
): Array<{ label: string; value: string; note?: string }> {
  const network = asRecord(configSummary.network);
  const providers = asRecord(configSummary.providers);
  const features = asRecord(configSummary.features);
  const logging = asRecord(configSummary.logging);
  const limits = asRecord(configSummary.limits);
  return [
    {
      label: "Bind and mode",
      value: String(network.bind ?? "n/a"),
      note: `Mode ${String(network.mode ?? runtime.mode ?? "n/a")} with ${runtime.docs_enabled ? "docs exposed" : "docs disabled"}.`,
    },
    {
      label: "Provider backends",
      value: `${String(providers.chat_backend_mode ?? providers.gigachat_api_mode ?? "n/a")} / ${String(providers.responses_backend_mode ?? "n/a")}`,
      note: `${asArray<unknown>(providers.enabled_providers).map(String).join(", ") || "No enabled providers"} using ${String(providers.runtime_store_backend ?? "n/a")} storage.`,
    },
    {
      label: "Security posture",
      value: setup.security_ready ? "ready" : "pending",
      note: `${formatNumber(network.scoped_api_keys_configured ?? 0)} scoped keys and ${formatNumber(network.governance_limits_configured ?? 0)} governance limits are configured.`,
    },
    {
      label: "Feature flags",
      value: renderEnabledList([
        features.pass_model ? "pass_model" : "",
        features.pass_token ? "pass_token" : "",
        features.enable_reasoning ? "reasoning" : "",
        features.enable_images ? "images" : "",
      ]),
      note: "These are the main protocol/runtime toggles changing operator-facing behavior.",
    },
    {
      label: "Logging",
      value: String(logging.log_level ?? "n/a"),
      note: logging.logs_ip_allowlist_enabled
        ? "Logs surface is allowlisted."
        : "Logs surface is open wherever admin access is allowed.",
    },
    {
      label: "Runtime stores",
      value: String(storeState.backend ?? "n/a"),
      note: `${formatNumber(storeState.recent_requests ?? 0)} recent requests and ${formatNumber(storeState.recent_errors ?? 0)} recent errors are retained.`,
    },
    {
      label: "Limits snapshot",
      value: formatNumber(limits.max_request_body_bytes ?? 0),
      note: `Recent request ring retains ${formatNumber(limits.recent_requests_max_items ?? 0)} items.`,
    },
  ];
}

function classifyRoute(path: string): RouteGroupKey {
  if (path.startsWith("/admin")) {
    return "admin";
  }
  if (path.startsWith("/messages")) {
    return "anthropic";
  }
  if (path.startsWith("/v1beta")) {
    return "gemini";
  }
  if (path === "/health" || path === "/ping" || path === "/metrics") {
    return "system";
  }
  return "openai";
}

function countTruthyEntries(section: Record<string, unknown>): number {
  return Object.values(section).filter(Boolean).length;
}

function renderBooleanSection(section: Record<string, unknown>): string {
  return renderStatLines(
    Object.entries(section).map(([key, value]) => ({
      label: key,
      value: value ? "ready" : "missing",
      tone: value ? "good" : "warn",
    })),
    "No state entries were reported.",
  );
}

function renderSummarySection(section: Record<string, unknown>): string {
  return renderStatLines(
    Object.entries(section).map(([key, value]) => ({
      label: key,
      value: summarizeValue(value),
      tone: typeof value === "boolean" && value ? "good" : "default",
    })),
    "No summary entries were reported.",
  );
}

function renderEnabledList(items: string[]): string {
  const filtered = items.filter(Boolean);
  return filtered.length ? filtered.join(", ") : "none";
}

function summarizeValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "empty";
  }
  if (typeof value === "boolean") {
    return value ? "enabled" : "disabled";
  }
  if (typeof value === "number") {
    return formatNumber(value);
  }
  if (Array.isArray(value)) {
    return value.length ? value.map(String).join(", ") : "none";
  }
  if (typeof value === "object") {
    return `${Object.keys(value as Record<string, unknown>).length} fields`;
  }
  return String(value);
}
