import type { AdminApp } from "../app.js";
import {
  banner,
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderStatLines,
  renderTable,
} from "../templates.js";
import type { RuntimePayload, SetupPayload } from "../types.js";
import {
  asArray,
  asRecord,
  escapeHtml,
  formatNumber,
  formatTimestamp,
} from "../utils.js";

type UsageRow = Record<string, unknown>;
type ErrorEvent = Record<string, unknown>;

const MAX_SUMMARY_ROWS = 5;

export async function renderOverview(app: AdminApp, token: number): Promise<void> {
  const [runtime, setup, usageKeys, usageProviders, errors] = await Promise.all([
    app.api.json<RuntimePayload>("/admin/api/runtime"),
    app.api.json<SetupPayload>("/admin/api/setup"),
    app.api.json<Record<string, unknown>>("/admin/api/usage/keys"),
    app.api.json<Record<string, unknown>>("/admin/api/usage/providers"),
    app.api.json<Record<string, unknown>>("/admin/api/errors/recent?limit=5"),
  ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const runtimeRecord = asRecord(runtime);
  const setupRecord = asRecord(setup);
  const summary = asRecord(usageProviders.summary);
  const keyEntries = asArray<UsageRow>(usageKeys.entries).slice(0, MAX_SUMMARY_ROWS);
  const providerEntries = asArray<UsageRow>(usageProviders.entries).slice(0, MAX_SUMMARY_ROWS);
  const recentErrors = asArray<ErrorEvent>(errors.events)
    .slice(-MAX_SUMMARY_ROWS)
    .reverse();
  const enabledProviders = asArray<string>(runtimeRecord.enabled_providers);
  const requestCount = Number(summary.request_count ?? 0);
  const errorCount = Number(summary.error_count ?? 0);
  const totalTokens = Number(summary.total_tokens ?? 0);
  const topProvider = providerEntries[0] ?? null;
  const topKey = keyEntries[0] ?? null;
  const warnings = buildOverviewWarnings(setupRecord, runtimeRecord, errorCount);

  app.setHeroActions(
    setup.setup_complete
      ? `
          <a class="button" href="/admin/playground">Try playground</a>
          <a class="button button--secondary" href="/admin/logs">Open logs</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `
      : `
          <a class="button" href="/admin/setup">Open setup wizard</a>
          <a class="button button--secondary" href="/admin/keys">Open API keys</a>
          <a class="button button--secondary" href="/admin/settings">Open settings</a>
        `,
  );

  app.setContent(`
    ${kpi("Setup", setup.setup_complete ? "complete" : "needs action")}
    ${kpi("Requests", formatNumber(requestCount))}
    ${kpi("Error rate", formatPercent(errorCount, requestCount))}
    ${kpi("Providers", formatNumber(enabledProviders.length))}
    ${card(
      "Executive summary",
      `
        <div class="stack">
          ${warnings.length ? warnings.join("") : banner("No urgent operator blockers were detected.", "info")}
          ${renderDefinitionList(
            [
              {
                label: "Setup posture",
                value: setup.setup_complete ? "Ready for operator traffic" : "Bootstrap still open",
                note: setup.setup_complete
                  ? "Setup, security, and GigaChat bootstrap are complete."
                  : "Finish setup before treating this gateway as production-ready.",
              },
              {
                label: "Runtime mode",
                value: String(runtime.mode ?? "n/a"),
                note: runtimeRecord.docs_enabled
                  ? "Docs and OpenAPI are exposed in the current runtime."
                  : "Docs and OpenAPI are disabled in the current runtime.",
              },
              {
                label: "Provider mix",
                value: enabledProviders.join(", ") || "none",
                note: topProvider
                  ? `${String(topProvider.provider ?? "unknown")} currently carries the most visible traffic.`
                  : "No provider usage has been recorded yet.",
              },
              {
                label: "Traffic snapshot",
                value: `${formatNumber(requestCount)} requests / ${formatNumber(totalTokens)} tokens`,
                note:
                  errorCount > 0
                    ? `${formatNumber(errorCount)} recent errors require inspection.`
                    : "No recent errors are recorded in the provider usage rollup.",
              },
            ],
            "Overview summary is unavailable.",
          )}
        </div>
      `,
      "panel panel--span-5",
    )}
    ${card(
      "Immediate actions",
      `
        <div class="stack">
          <div class="toolbar">
            <a class="button" href="${escapeHtml(setup.setup_complete ? "/admin/playground" : "/admin/setup")}">
              ${escapeHtml(setup.setup_complete ? "Run smoke request" : "Finish setup")}
            </a>
            <a class="button button--secondary" href="/admin/traffic">Inspect traffic</a>
            <a class="button button--secondary" href="/admin/logs">Inspect logs</a>
          </div>
          ${renderDefinitionList(
            [
              {
                label: "Setup and secrets",
                value: setup.setup_complete ? "Stable" : "Needs review",
                note: "Use Setup for bootstrap flow and Settings for persisted runtime edits.",
              },
              {
                label: "Gateway keys",
                value: formatNumber(setup.scoped_api_keys_configured ?? 0),
                note: topKey
                  ? `${String(topKey.name ?? "Top key")} is currently the busiest key surface.`
                  : "No per-key traffic has been recorded yet.",
              },
              {
                label: "Operator drilldown",
                value: recentErrors.length ? "Start from recent errors" : "Start from playground",
                note: recentErrors.length
                  ? "Logs and Traffic both support request-id handoff from the error list below."
                  : "Use Playground to generate a first smoke request without leaving the console.",
              },
            ],
            "No action summary is available.",
          )}
        </div>
      `,
      "panel panel--span-3",
    )}
    ${card(
      "Readiness signals",
      renderStatLines(
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
            label: "Gateway auth",
            value: runtimeRecord.auth_required ? "required" : "open",
            tone: runtimeRecord.auth_required ? "good" : "warn",
          },
          {
            label: "Telemetry",
            value: runtime.telemetry_enabled ? "enabled" : "disabled",
            tone: runtime.telemetry_enabled ? "good" : "default",
          },
          {
            label: "Scoped API keys",
            value: formatNumber(setup.scoped_api_keys_configured ?? 0),
          },
        ],
        "No readiness metadata is available.",
      ),
      "panel panel--span-4",
    )}
    ${card(
      "Provider mix",
      renderTable(
        [
          { label: "Provider" },
          { label: "Traffic" },
          { label: "Tokens" },
          { label: "Coverage" },
        ],
        providerEntries.map((entry) => [
          `<strong>${escapeHtml(String(entry.provider ?? "unknown"))}</strong><br /><span class="muted">${escapeHtml(formatTimestamp(entry.last_seen_at))}</span>`,
          `${escapeHtml(formatNumber(entry.request_count ?? 0))} req<br /><span class="muted">${escapeHtml(formatNumber(entry.error_count ?? 0))} errors</span>`,
          `${escapeHtml(formatNumber(entry.total_tokens ?? 0))}<br /><span class="muted">${escapeHtml(formatNumber(entry.prompt_tokens ?? 0))} prompt / ${escapeHtml(formatNumber(entry.completion_tokens ?? 0))} completion</span>`,
          `<span class="muted">${escapeHtml(joinObjectKeys(entry.models))}</span><br /><span class="muted">${escapeHtml(joinObjectKeys(entry.api_keys))}</span>`,
        ]),
        "No provider usage has been recorded yet.",
      ),
      "panel panel--span-6",
    )}
    ${card(
      "Key pressure",
      renderTable(
        [
          { label: "API key" },
          { label: "Traffic" },
          { label: "Providers" },
          { label: "Models" },
        ],
        keyEntries.map((entry) => [
          `<strong>${escapeHtml(String(entry.name ?? "unnamed"))}</strong><br /><span class="muted">${escapeHtml(String(entry.source ?? "unknown"))}</span>`,
          `${escapeHtml(formatNumber(entry.request_count ?? 0))} req<br /><span class="muted">${escapeHtml(formatNumber(entry.error_count ?? 0))} errors</span>`,
          `<span class="muted">${escapeHtml(joinObjectKeys(entry.providers))}</span>`,
          `<span class="muted">${escapeHtml(joinObjectKeys(entry.models))}</span>`,
        ]),
        "No API-key usage has been recorded yet.",
      ),
      "panel panel--span-6",
    )}
    ${card(
      "Recent errors",
      recentErrors.length
        ? renderTable(
            [
              { label: "When" },
              { label: "Route" },
              { label: "Failure" },
              { label: "Context" },
              { label: "Handoff" },
            ],
            recentErrors.map((event) => {
              const requestId = String(event.request_id ?? "").trim();
              return [
                `<strong>${escapeHtml(formatTimestamp(event.created_at))}</strong><br /><span class="muted">${escapeHtml(requestId || "no request id")}</span>`,
                `${escapeHtml(String(event.provider ?? "unknown"))}<br /><span class="muted">${escapeHtml(String(event.method ?? "GET"))} ${escapeHtml(String(event.endpoint ?? event.path ?? "n/a"))}</span>`,
                `<strong>${escapeHtml(String(event.error_type ?? "HTTP error"))}</strong><br /><span class="muted">status ${escapeHtml(formatNumber(event.status_code ?? 0))}</span>`,
                `${escapeHtml(String(event.model ?? "n/a"))}<br /><span class="muted">${escapeHtml(String(event.api_key_name ?? event.api_key_source ?? "anonymous"))}</span>`,
                renderRecentErrorActions(requestId),
              ];
            }),
            "No recent errors recorded.",
          )
        : "<p>No recent errors recorded.</p>",
      "panel panel--span-12",
    )}
  `);
}

function buildOverviewWarnings(
  setup: Record<string, unknown>,
  runtime: Record<string, unknown>,
  errorCount: number,
): string[] {
  const warnings: string[] = [];
  if (!setup.persisted) {
    warnings.push(
      banner(
        "Control-plane config is not persisted yet. Zero-env restarts will fall back to defaults until Settings is saved.",
        "warn",
      ),
    );
  }
  if (!setup.gigachat_ready) {
    warnings.push(
      banner(
        "GigaChat credentials are still missing. Playground and live provider traffic will fail until setup is completed.",
        "warn",
      ),
    );
  }
  if (!setup.security_ready || !runtime.auth_required) {
    warnings.push(
      banner(
        "Gateway security posture is still open. Review API key bootstrap before exposing the proxy outside a trusted network.",
        "warn",
      ),
    );
  }
  if (errorCount > 0) {
    warnings.push(
      banner(
        `${formatNumber(errorCount)} recent errors were recorded. Start with the recent error table or jump into Logs/Traffic handoff.`,
        "warn",
      ),
    );
  }
  return warnings;
}

function joinObjectKeys(value: unknown): string {
  const entries = Object.keys(asRecord(value));
  return entries.length ? entries.join(", ") : "none";
}

function formatPercent(part: number, total: number): string {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) {
    return "0%";
  }
  return `${((part / total) * 100).toFixed(part === 0 ? 0 : 1)}%`;
}

function renderRecentErrorActions(requestId: string): string {
  if (!requestId) {
    return `<a class="button button--secondary" href="/admin/logs">Open logs</a>`;
  }
  return `
    <div class="toolbar">
      <a class="button button--secondary" href="${escapeHtml(buildLogsUrlForRequest(requestId))}">Logs</a>
      <a class="button button--secondary" href="${escapeHtml(buildTrafficUrlForRequest(requestId))}">Traffic</a>
    </div>
  `;
}

function buildLogsUrlForRequest(requestId: string): string {
  const params = new URLSearchParams();
  if (requestId.trim()) {
    params.set("request_id", requestId.trim());
  }
  const query = params.toString();
  return query ? `/admin/logs?${query}` : "/admin/logs";
}

function buildTrafficUrlForRequest(requestId: string): string {
  const params = new URLSearchParams();
  if (requestId.trim()) {
    params.set("request_id", requestId.trim());
  }
  const query = params.toString();
  return query ? `/admin/traffic?${query}` : "/admin/traffic";
}
