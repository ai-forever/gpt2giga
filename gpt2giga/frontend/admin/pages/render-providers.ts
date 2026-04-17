import type { AdminApp } from "../app.js";
import { OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import {
  banner,
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderGuideLinks,
  renderStatLines,
  renderTable,
  renderWorkflowCard,
} from "../templates.js";
import { asArray, asRecord, escapeHtml, formatNumber } from "../utils.js";

type ProviderRow = Record<string, unknown>;
type RouteRow = Record<string, unknown>;
type RouteFamilyKey = "admin" | "openai" | "anthropic" | "gemini" | "system";

interface RouteFamilySummary {
  key: RouteFamilyKey;
  label: string;
  count: number;
  samples: string[];
  owner: string;
}

interface CapabilitySummaryRow {
  label: string;
  enabledSurfaces: string;
  standbySurfaces: string;
  routeSample: string;
}

export async function renderProviders(app: AdminApp, token: number): Promise<void> {
  const [capabilities, routes, runtime] = await Promise.all([
    app.api.json<Record<string, unknown>>("/admin/api/capabilities"),
    app.api.json<Record<string, unknown>>("/admin/api/routes"),
    app.api.json<Record<string, unknown>>("/admin/api/runtime"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const capabilityMatrix = asRecord(capabilities.matrix);
  const providerRows = asArray<ProviderRow>(capabilityMatrix.rows);
  const routeRows = asArray<RouteRow>(routes.routes);
  const backend = asRecord(capabilities.backend);
  const surfaceRows = providerRows.filter((row) => row.surface === "provider");
  const enabledProviderRows = surfaceRows.filter((row) => Boolean(row.enabled));
  const enabledProviders = asArray<string>(runtime.enabled_providers);
  const adminRouteCount = asArray<unknown>(asRecord(capabilities.admin).routes).length;
  const routeFamilyRows = buildRouteFamilySummaries(routeRows);
  const capabilityRows = buildCapabilityCoverageRows(surfaceRows);
  const leadProvider = [...enabledProviderRows].sort(
    (left, right) => Number(right.route_count ?? 0) - Number(left.route_count ?? 0),
  )[0];
  const leadProviderName = String(leadProvider?.name ?? "");
  const warnings = buildProviderWarnings(enabledProviderRows.length, backend);
  const smokeHref = pathForPage("playground");
  const trafficHref = buildTrafficUrlForProvider(leadProviderName);
  const logsHref = buildLogsUrlForProvider(leadProviderName);

  app.setHeroActions(`
    <a class="button" href="${escapeHtml(smokeHref)}">Smoke in playground</a>
    <a class="button button--secondary" href="${escapeHtml(trafficHref)}">Provider traffic</a>
    <a class="button button--secondary" href="/admin/settings">Open settings</a>
    <a class="button button--secondary" href="/admin/system">Open system</a>
  `);

  app.setContent(`
    ${kpi("Enabled providers", formatNumber(enabledProviders.length))}
    ${kpi("Mounted routes", formatNumber(routeRows.length))}
    ${kpi("Capability groups", formatNumber(capabilityRows.length))}
    ${kpi("Metrics", backend.telemetry_enabled ? "on" : "off")}
    ${card(
      "Executive summary",
      `
        <div class="stack">
          ${warnings.length ? warnings.join("") : banner("Provider posture is readable and no urgent backend blockers were detected.", "info")}
          ${renderDefinitionList(
            [
              {
                label: "Enabled provider mix",
                value: enabledProviders.join(", ") || "none",
                note: leadProvider
                  ? `${displayName(leadProvider)} currently owns the widest mounted provider surface.`
                  : "No provider surface is enabled yet.",
              },
              {
                label: "Backend modes",
                value: `${String(backend.gigachat_api_mode ?? "n/a")} / ${String(backend.chat_backend_mode ?? "n/a")}`,
                note: `Responses mode: ${String(backend.responses_backend_mode ?? "n/a")}.`,
              },
              {
                label: "Operator surfaces",
                value: `${formatNumber(adminRouteCount)} admin routes / ${formatNumber(routeRows.length)} total`,
                note: "System and Admin surfaces stay mounted even when provider families are reduced.",
              },
              {
                label: "Runtime store",
                value: String(backend.runtime_store_backend ?? "n/a"),
                note:
                  asArray<string>(backend.observability_sinks).join(", ") || "No observability sinks are configured.",
              },
            ],
            "Provider summary is unavailable.",
          )}
        </div>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Provider workflows",
      `
        <div class="stack">
          <div class="workflow-grid">
            ${renderWorkflowCard({
              workflow: "configure",
              compact: true,
              title: enabledProviderRows.length ? "Adjust provider posture" : "Enable a provider family first",
              note: enabledProviderRows.length
                ? "Settings owns toggles and auth posture."
                : "Use Setup or Settings to restore a usable provider path.",
              pills: [
                pill(`Enabled: ${formatNumber(enabledProviderRows.length)}`, enabledProviderRows.length ? "good" : "warn"),
                pill(`Telemetry: ${backend.telemetry_enabled ? "on" : "off"}`, backend.telemetry_enabled ? "good" : "warn"),
                pill(`Governance: ${backend.governance_enabled ? "on" : "off"}`),
              ],
              actions: [
                { label: "Settings", href: pathForPage("settings"), primary: true },
                { label: "Setup", href: pathForPage("setup") },
              ],
            })}
            ${renderWorkflowCard({
              workflow: "start",
              compact: true,
              title: "Smoke the mounted provider surface",
              note: leadProvider
                ? `${displayName(leadProvider)} currently exposes the widest surface.`
                : "Use Playground after the first provider is enabled.",
              pills: [
                pill(`Lead provider: ${leadProvider ? displayName(leadProvider) : "n/a"}`),
                pill(`Routes: ${formatNumber(routeRows.length)}`),
                pill(`Capabilities: ${formatNumber(capabilityRows.length)}`),
              ],
              actions: [
                { label: "Playground", href: smokeHref, primary: true },
                { label: "System", href: pathForPage("system") },
              ],
            })}
            ${renderWorkflowCard({
              workflow: "observe",
              compact: true,
              title: "Confirm the live request path",
              note: leadProvider
                ? "Traffic opens scoped to the current lead provider."
                : "Traffic and Logs stay secondary until a provider is enabled.",
              pills: [
                pill(`Lead route owner: ${leadProvider ? displayName(leadProvider) : "none"}`),
                pill(`Admin routes: ${formatNumber(adminRouteCount)}`),
                pill(`Store: ${String(backend.runtime_store_backend ?? "n/a")}`),
              ],
              actions: [
                { label: "Traffic", href: trafficHref, primary: true },
                { label: "Logs", href: logsHref },
              ],
            })}
          </div>
        </div>
      `,
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Capability coverage",
      `
        <div class="stack">
          ${renderTable(
            [
              { label: "Capability" },
              { label: "Enabled surfaces" },
              { label: "Standby surfaces" },
              { label: "Route sample" },
            ],
            capabilityRows.map((row) => [
              `<strong>${escapeHtml(row.label)}</strong>`,
              `<span class="muted">${escapeHtml(row.enabledSurfaces)}</span>`,
              `<span class="muted">${escapeHtml(row.standbySurfaces)}</span>`,
              `<span class="muted">${escapeHtml(row.routeSample)}</span>`,
            ]),
            "No capability coverage rows were reported by the admin API.",
          )}
        </div>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Guide and troubleshooting",
      renderGuideLinks(
        [
          {
            label: "Provider surface diagnostics",
            href: OPERATOR_GUIDE_LINKS.providers,
            note: "Use the operator playbook for capability coverage, mounted route checks, and the expected page-to-page handoff from Settings to Playground to Traffic.",
          },
          {
            label: "Rollout backend v2",
            href: OPERATOR_GUIDE_LINKS.rolloutV2,
            note: "Open the rollout notes when the mismatch is really about backend mode selection rather than a missing route or disabled provider family.",
          },
          {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Use the escalation map when provider posture looks wrong but the next operator surface is still ambiguous.",
          },
        ],
        {
          compact: true,
          collapsibleSummary: "Operator guides",
          intro: "Open docs only after coverage, smoke, or live traffic still leave the mismatch unresolved.",
        },
      ),
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Provider briefs",
      `
        <div class="step-grid">
          ${surfaceRows
            .map((row) => {
              const capabilitiesList = readStringList(row.capabilities);
              const routesList = readStringList(row.routes);
              const enabled = Boolean(row.enabled);
              const providerName = String(row.name ?? "");
              return `
                <article class="step-card ${enabled ? "step-card--ready" : ""}">
                  ${pill(enabled ? "enabled" : "disabled", enabled ? "good" : "warn")}
                  <h4>${escapeHtml(displayName(row))}</h4>
                  ${renderDefinitionList(
                    [
                      {
                        label: "Capabilities",
                        value: formatNumber(capabilitiesList.length),
                        note: capabilitiesList.slice(0, 4).join(", ") || "No capabilities declared.",
                      },
                      {
                        label: "Declared routes",
                        value: formatNumber(row.route_count ?? routesList.length),
                        note: routesList.slice(0, 3).join(", ") || "No routes declared.",
                      },
                      {
                        label: "Best next step",
                        value: enabled ? "Smoke in playground" : "Check Settings",
                        note: enabled
                          ? "Use Playground or Traffic to validate the enabled compatibility surface."
                          : "Enable this provider family from Settings before expecting mounted routes.",
                      },
                    ],
                    "No provider details were reported.",
                  )}
                  <div class="toolbar">
                    <a class="button button--secondary" href="/admin/playground">Playground</a>
                    <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForProvider(providerName))}">Traffic</a>
                  </div>
                </article>
              `;
            })
            .join("")}
        </div>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Backend posture",
      renderStatLines(
        [
          { label: "GigaChat API mode", value: String(backend.gigachat_api_mode ?? "n/a") },
          { label: "Chat backend mode", value: String(backend.chat_backend_mode ?? "n/a") },
          {
            label: "Responses backend mode",
            value: String(backend.responses_backend_mode ?? "n/a"),
          },
          {
            label: "Runtime store backend",
            value: String(backend.runtime_store_backend ?? "n/a"),
          },
          {
            label: "Telemetry",
            value: backend.telemetry_enabled ? "enabled" : "disabled",
            tone: backend.telemetry_enabled ? "good" : "default",
          },
          {
            label: "Governance",
            value: backend.governance_enabled
              ? `${formatNumber(backend.governance_limits_configured ?? 0)} limits`
              : "disabled",
            tone: backend.governance_enabled ? "good" : "default",
          },
        ],
        "Backend capability metadata is unavailable.",
      ),
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Staged route diagnostics",
      `
        <div class="stack">
          <p class="muted">Open these disclosures only when the summary still leaves a route-family mismatch unresolved.</p>
          <details class="surface details-disclosure" id="providers-route-detail">
            <summary>Current route-family snapshot</summary>
            ${renderTable(
              [
                { label: "Family" },
                { label: "Mounted routes" },
                { label: "Examples" },
                { label: "Owner" },
              ],
              routeFamilyRows.map((group) => [
                `<strong>${escapeHtml(group.label)}</strong>`,
                `${escapeHtml(formatNumber(group.count))}<br /><span class="muted">${escapeHtml(group.count ? "mounted" : "idle")}</span>`,
                `<span class="muted">${escapeHtml(group.samples.join(", ") || "No routes in this family.")}</span>`,
                `<span class="muted">${escapeHtml(group.owner)}</span>`,
              ]),
              "No mounted routes were reported by the admin API.",
            )}
          </details>
          <details class="surface details-disclosure">
            <summary>Full provider surface matrix</summary>
            ${renderTable(
              [
                { label: "Surface" },
                { label: "Mode" },
                { label: "Capabilities" },
                { label: "Routes" },
              ],
              providerRows.map((row) => {
                const capabilitiesList = readStringList(row.capabilities);
                const routesList = readStringList(row.routes);
                return [
                  `<strong>${escapeHtml(displayName(row))}</strong><br /><span class="muted">${escapeHtml(String(row.surface ?? "surface"))}</span>`,
                  row.enabled
                    ? `<strong>enabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`
                    : `<strong>disabled</strong><br /><span class="muted">${escapeHtml(String(row.name ?? ""))}</span>`,
                  `${escapeHtml(formatNumber(capabilitiesList.length))}<br /><span class="muted">${escapeHtml(capabilitiesList.slice(0, 3).join(", ") || "none")}</span>`,
                  `${escapeHtml(formatNumber(row.route_count ?? routesList.length))}<br /><span class="muted">${escapeHtml(routesList.slice(0, 2).join(", ") || "none")}</span>`,
                ];
              }),
              "No capability rows were reported by the admin API.",
            )}
          </details>
        </div>
      `,
      "panel panel--span-12",
    )}
  `);
}

function buildProviderWarnings(
  enabledProviderCount: number,
  backend: Record<string, unknown>,
): string[] {
  const warnings: string[] = [];
  if (enabledProviderCount === 0) {
    warnings.push(
      banner(
        "No provider compatibility surface is enabled. The gateway can mount Admin/System, but client traffic will not have a usable provider family.",
        "warn",
      ),
    );
  }
  if (!backend.telemetry_enabled) {
    warnings.push(
      banner(
        "Telemetry is disabled, so provider posture will stay configuration-only until you inspect raw logs or targeted traffic tables.",
        "warn",
      ),
    );
  }
  if (!backend.governance_enabled) {
    warnings.push(
      banner(
        "Governance limits are disabled. Throughput posture is visible here, but request shaping is not being constrained by configured limits.",
        "info",
      ),
    );
  }
  return warnings;
}

function buildCapabilityCoverageRows(rows: ProviderRow[]): CapabilitySummaryRow[] {
  const definitions: Array<{ label: string; capabilities: string[] }> = [
    {
      label: "Chat requests",
      capabilities: ["chat_completions", "messages", "generate_content", "stream_generate_content"],
    },
    {
      label: "Responses API",
      capabilities: ["responses"],
    },
    {
      label: "Embeddings",
      capabilities: ["embeddings", "batch_embed_contents"],
    },
    {
      label: "Files",
      capabilities: ["files"],
    },
    {
      label: "Batches",
      capabilities: ["batches", "message_batches"],
    },
    {
      label: "Model discovery",
      capabilities: ["models", "litellm_model_info"],
    },
    {
      label: "Token counting",
      capabilities: ["count_tokens"],
    },
  ];

  return definitions.map((definition) => {
    const matchingRows = rows.filter((row) =>
      readStringList(row.capabilities).some((capability) =>
        definition.capabilities.includes(capability),
      ),
    );
    const enabled = matchingRows.filter((row) => Boolean(row.enabled)).map(displayName);
    const standby = matchingRows.filter((row) => !row.enabled).map(displayName);
    const sampleRoutes = matchingRows.flatMap((row) => readStringList(row.routes)).slice(0, 3);
    return {
      label: definition.label,
      enabledSurfaces: enabled.join(", ") || "none",
      standbySurfaces: standby.join(", ") || "none",
      routeSample: sampleRoutes.join(", ") || "No route sample",
    };
  });
}

function buildRouteFamilySummaries(routes: RouteRow[]): RouteFamilySummary[] {
  const groups: Record<RouteFamilyKey, string[]> = {
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

  const descriptors: Array<Pick<RouteFamilySummary, "key" | "label" | "owner">> = [
    { key: "admin", label: "Admin", owner: "Console and admin APIs" },
    { key: "openai", label: "OpenAI", owner: "OpenAI compatibility + LiteLLM" },
    { key: "anthropic", label: "Anthropic", owner: "Anthropic compatibility" },
    { key: "gemini", label: "Gemini", owner: "Gemini compatibility" },
    { key: "system", label: "System", owner: "Health, ping, and metrics" },
  ];

  return descriptors.map(({ key, label, owner }) => ({
    key,
    label,
    owner,
    count: groups[key].length,
    samples: [...new Set(groups[key])].slice(0, 3),
  }));
}

function classifyRoute(path: string): RouteFamilyKey {
  if (path.startsWith("/admin")) {
    return "admin";
  }
  if (path.startsWith("/messages")) {
    return "anthropic";
  }
  if (path.startsWith("/v1beta") || path.startsWith("/upload/v1beta")) {
    return "gemini";
  }
  if (path === "/health" || path === "/ping" || path === "/metrics") {
    return "system";
  }
  return "openai";
}

function readStringList(value: unknown): string[] {
  return asArray<unknown>(value).map(String);
}

function displayName(row: ProviderRow): string {
  return String(row.display_name ?? row.name ?? "unknown");
}

function buildTrafficUrlForProvider(providerName: string): string {
  const params = new URLSearchParams();
  if (providerName.trim()) {
    params.set("provider", providerName.trim());
  }
  const query = params.toString();
  return query ? `/admin/traffic?${query}` : "/admin/traffic";
}

function buildLogsUrlForProvider(providerName: string): string {
  const params = new URLSearchParams();
  if (providerName.trim()) {
    params.set("provider", providerName.trim());
  }
  const query = params.toString();
  return query ? `/admin/logs?${query}` : "/admin/logs";
}
