import type { AdminApp } from "../app.js";
import { OPERATOR_GUIDE_LINKS } from "../docs-links.js";
import { pathForPage } from "../routes.js";
import {
  banner,
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderFormSection,
  renderGuideLinks,
  renderJson,
  renderTable,
  renderWorkflowCard,
} from "../templates.js";
import { asArray, asRecord, csv, escapeHtml, formatNumber, parseCsv } from "../utils.js";

type UsageRecord = Record<string, unknown>;
type ScopedKeyRow = Record<string, unknown>;

export async function renderKeys(app: AdminApp, token: number): Promise<void> {
  const keys = await app.api.json<Record<string, unknown>>("/admin/api/keys");
  if (!app.isCurrentRender(token)) {
    return;
  }

  const global = asRecord(keys.global);
  const globalUsage = asRecord(global.usage);
  const scoped = asArray<ScopedKeyRow>(keys.scoped);
  const scopedRequestCount = scoped.reduce(
    (total, item) => total + readUsageCount(asRecord(item.usage).request_count),
    0,
  );
  const scopedRestrictionCount = scoped.filter(hasScopedRestrictions).length;
  const totalRequestCount = readUsageCount(globalUsage.request_count) + scopedRequestCount;

  app.setHeroActions(`
    <button class="button" id="rotate-global-key" type="button">Rotate global key</button>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Open usage traffic</a>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("playground"))}">Smoke in playground</a>
  `);
  app.setContent(`
    ${kpi("Global key", global.configured ? "configured" : "missing")}
    ${kpi("Scoped keys", formatNumber(scoped.length))}
    ${kpi("Restricted scopes", formatNumber(scopedRestrictionCount))}
    ${kpi("Observed requests", formatNumber(totalRequestCount))}
    ${card(
      "Summary",
      `
        <div class="stack">
          ${renderKeysBanner(global, scoped)}
          ${renderDefinitionList(
            [
              {
                label: "Global gateway posture",
                value: global.configured ? "ready" : "missing",
                note: global.configured
                  ? `Preview ${String(global.key_preview ?? "hidden")} is the broad fallback key.`
                  : "Create a global key if you need one broad fallback.",
              },
              {
                label: "Scoped inventory",
                value: formatNumber(scoped.length),
                note: scoped.length
                  ? `${formatNumber(scopedRestrictionCount)} keys enforce provider, endpoint, or model limits.`
                  : "No scoped keys exist yet.",
              },
              {
                label: "Recent usage signal",
                value: `${formatNumber(totalRequestCount)} observed requests`,
                note: totalRequestCount
                  ? "Aggregated from Traffic > Usage counters."
                  : "No requests have been attributed yet.",
              },
              {
                label: "Fastest next handoff",
                value: global.configured || scoped.length ? "Playground or Traffic" : "Create a key first",
                note:
                  global.configured || scoped.length
                    ? "Smoke one request, then confirm attribution in Traffic > Usage."
                    : "Create one reusable key first.",
              },
            ],
            "Key posture is unavailable.",
          )}
        </div>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Key workflows",
      `
        <div class="stack">
          <div class="workflow-grid">
            ${renderWorkflowCard({
              workflow: "configure",
              compact: true,
              title: global.configured ? "Rotate the global fallback" : "Create the first global fallback",
              pills: [
                pill(`Global: ${global.configured ? "ready" : "missing"}`, global.configured ? "good" : "warn"),
                pill(`Scoped: ${formatNumber(scoped.length)}`),
                pill(`Observed requests: ${formatNumber(totalRequestCount)}`),
              ],
              actions: [
                { label: "Rotate global key", href: "#rotate-global-key", primary: true },
                { label: "Security settings", href: pathForPage("settings-security") },
              ],
            })}
            ${renderWorkflowCard({
              workflow: "start",
              compact: true,
              title: scoped.length ? "Issue a client-specific key" : "Create the first scoped key",
              pills: [
                pill(`Restricted scopes: ${formatNumber(scopedRestrictionCount)}`),
                pill(`Preview: ${String(global.key_preview ?? "none")}`),
                pill(`Traffic: ${totalRequestCount ? "warm" : "idle"}`, totalRequestCount ? "good" : "default"),
              ],
              actions: [
                { label: "Create scoped key", href: "#scoped-key-form", primary: true },
                { label: "Playground", href: pathForPage("playground") },
              ],
            })}
            ${renderWorkflowCard({
              workflow: "observe",
              compact: true,
              title: "Confirm attribution after one request",
              pills: [
                pill(`Global requests: ${formatNumber(readUsageCount(globalUsage.request_count))}`),
                pill(`Scoped requests: ${formatNumber(scopedRequestCount)}`),
                pill(`Keys with usage: ${formatNumber(countKeysWithUsage(global, scoped))}`),
              ],
              actions: [
                { label: "Traffic usage", href: pathForPage("traffic-usage"), primary: true },
                { label: "Logs", href: pathForPage("logs") },
              ],
            })}
          </div>
        </div>
      `,
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Create scoped key",
      `
        <form id="scoped-key-form" class="form-shell">
          <div class="form-shell__intro">
            <span class="eyebrow">Scoped handoff</span>
            <p class="muted">Create one narrow client key.</p>
          </div>
          ${renderFormSection({
            title: "Identity",
            body: `
              <label class="field">
                <span>Name</span>
                <input name="name" required placeholder="sdk-openai" />
              </label>
            `,
          })}
          ${renderFormSection({
            title: "Scope limits",
            body: `
              <div class="triple-grid">
                <label class="field">
                  <span>Providers</span>
                  <input name="providers" placeholder="openai, anthropic" />
                </label>
                <label class="field">
                  <span>Endpoints</span>
                  <input name="endpoints" placeholder="chat/completions, responses" />
                </label>
                <label class="field">
                  <span>Models</span>
                  <input name="models" placeholder="GigaChat-2-Max" />
                </label>
              </div>
            `,
          })}
          <div class="form-actions">
            <button class="button" type="submit">Create scoped key</button>
            <span class="muted">Full value is shown once.</span>
          </div>
        </form>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Current posture",
      `
        <div class="stack">
          ${renderDefinitionList(
            [
              {
                label: "Global preview",
                value: String(global.key_preview ?? "not configured"),
                note: global.configured
                  ? "Keep this for controlled broad access only."
                  : "No broad fallback is configured.",
              },
              {
                label: "Best smoke path",
                value: global.configured || scoped.length ? "Playground" : "Setup / Security",
                note:
                  global.configured || scoped.length
                    ? "Copy the target key into the rail before the next smoke run."
                    : "Finish bootstrap or key creation first.",
              },
              {
                label: "Usage confirmation",
                value: totalRequestCount ? "Traffic usage is warm" : "Traffic usage is idle",
                note: "Traffic > Usage stays the confirmation surface.",
              },
            ],
            "Current key posture is unavailable.",
          )}
          <div class="toolbar">
            <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-security"))}">Security settings</a>
            <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Usage traffic</a>
          </div>
        </div>
      `,
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Scoped key inventory",
      renderTable(
        [
          { label: "Name" },
          { label: "Scope posture" },
          { label: "Usage" },
          { label: "Preview" },
          { label: "Actions" },
        ],
        scoped.map((item) => {
          const name = String(item.name ?? "");
          return [
            `<strong>${escapeHtml(name)}</strong>`,
            `<span class="muted">${escapeHtml(describeScopePosture(item))}</span>`,
            `<span class="muted">${escapeHtml(describeUsage(asRecord(item.usage)))}</span>`,
            `<span class="muted">${escapeHtml(String(item.key_preview ?? ""))}</span>`,
            `
              <div class="toolbar">
                <button class="button button--secondary" data-rotate="${escapeHtml(name)}" type="button">Rotate</button>
                <button class="button button--danger" data-delete="${escapeHtml(name)}" type="button">Delete</button>
              </div>
            `,
          ];
        }),
        "No scoped keys yet. Create one above to establish a narrower handoff than the global key.",
      ),
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Guides",
      renderGuideLinks(
        [
          {
            label: "Overview workflow guide",
            href: OPERATOR_GUIDE_LINKS.overview,
            note: "Use the broader operator map when the question is where key management sits relative to Setup or diagnostics.",
          },
          {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Open the escalation map when key posture looks correct but failures still need a different surface.",
          },
          {
            label: "Provider surface diagnostics",
            href: OPERATOR_GUIDE_LINKS.providers,
            note: "Use provider diagnostics only after a key works but the mounted surface still behaves differently than expected.",
          },
        ],
        {
          compact: true,
          collapsibleSummary: "Operator guides",
        },
      ),
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Current key snapshot",
      `
        <details class="details-disclosure">
          <summary>Current key snapshot</summary>
          <p class="field-note">Open only if the summary or inventory rows are not enough.</p>
          ${renderJson(keys)}
        </details>
      `,
      "panel panel--span-12",
    )}
  `);

  const rotateButton = document.getElementById("rotate-global-key");
  rotateButton?.addEventListener("click", async () => {
    const response = await app.api.json<Record<string, unknown>>("/admin/api/keys/global/rotate", {
      method: "POST",
      json: {},
    });
    const nextGlobal = asRecord(response.global);
    app.saveAdminKey(String(nextGlobal.value ?? ""));
    app.saveGatewayKey(String(nextGlobal.value ?? ""));
    app.queueAlert(`Global key rotated. New value: ${String(nextGlobal.value ?? "")}`, "warn");
    await app.render("keys");
  });

  const scopedForm = app.pageContent.querySelector<HTMLFormElement>("#scoped-key-form");
  scopedForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget as HTMLFormElement;
    const fields = form.elements as typeof form.elements & {
      name: HTMLInputElement;
      providers: HTMLInputElement;
      endpoints: HTMLInputElement;
      models: HTMLInputElement;
    };
    const response = await app.api.json<Record<string, unknown>>("/admin/api/keys/scoped", {
      method: "POST",
      json: {
        name: fields.name.value.trim(),
        providers: parseCsv(fields.providers.value),
        endpoints: parseCsv(fields.endpoints.value),
        models: parseCsv(fields.models.value),
      },
    });
    const scopedKey = asRecord(response.scoped_key);
    app.queueAlert(`Scoped key created. Value: ${String(scopedKey.value ?? "")}`, "warn");
    await app.render("keys");
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-rotate]").forEach((button) => {
    button.addEventListener("click", async () => {
      const name = button.dataset.rotate;
      if (!name) {
        return;
      }
      const response = await app.api.json<Record<string, unknown>>(
        `/admin/api/keys/scoped/${encodeURIComponent(name)}/rotate`,
        {
          method: "POST",
          json: {},
        },
      );
      const scopedKey = asRecord(response.scoped_key);
      app.queueAlert(`Scoped key ${name} rotated. New value: ${String(scopedKey.value ?? "")}`, "warn");
      await app.render("keys");
    });
  });

  app.pageContent.querySelectorAll<HTMLElement>("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const name = button.dataset.delete;
      if (!name) {
        return;
      }
      await app.api.json(`/admin/api/keys/scoped/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      app.queueAlert(`Scoped key ${name} deleted.`, "info");
      await app.render("keys");
    });
  });
}

function renderKeysBanner(global: UsageRecord, scoped: ScopedKeyRow[]): string {
  if (!global.configured && scoped.length === 0) {
    return banner(
      "No reusable gateway keys yet. Create a global or scoped key before external access.",
      "warn",
    );
  }
  if (!global.configured) {
    return banner(
      "Only scoped keys exist. Fine for narrow clients, but recovery may still want a deliberate global fallback.",
      "info",
    );
  }
  if (scoped.length === 0) {
    return banner(
      "A global key exists, but no scoped keys do. Create one before wider distribution.",
      "warn",
    );
  }
  return banner(
    "Global fallback and scoped keys are present. Keep distribution narrow and confirm attribution in Traffic > Usage.",
    "info",
  );
}

function describeScopePosture(item: ScopedKeyRow): string {
  const parts = [
    csv(item.providers) ? `providers: ${csv(item.providers)}` : "",
    csv(item.endpoints) ? `endpoints: ${csv(item.endpoints)}` : "",
    csv(item.models) ? `models: ${csv(item.models)}` : "",
  ].filter(Boolean);
  return parts.join(" · ") || "full scoped access";
}

function describeUsage(usage: UsageRecord): string {
  const requests = readUsageCount(usage.request_count);
  const totalTokens = readUsageCount(usage.total_tokens);
  if (requests === 0 && totalTokens === 0) {
    return "No attributed usage yet";
  }
  return `${formatNumber(requests)} requests · ${formatNumber(totalTokens)} tokens`;
}

function hasScopedRestrictions(item: ScopedKeyRow): boolean {
  return Boolean(csv(item.providers) || csv(item.endpoints) || csv(item.models));
}

function countKeysWithUsage(global: UsageRecord, scoped: ScopedKeyRow[]): number {
  return [
    readUsageCount(asRecord(global.usage).request_count) > 0,
    ...scoped.map((item) => readUsageCount(asRecord(item.usage).request_count) > 0),
  ].filter(Boolean).length;
}

function readUsageCount(value: unknown): number {
  const normalized = Number(value ?? 0);
  return Number.isFinite(normalized) ? normalized : 0;
}
