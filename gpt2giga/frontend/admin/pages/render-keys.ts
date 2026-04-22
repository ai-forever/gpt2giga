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
  renderPageFrame,
  renderPageSection,
  renderStatLines,
  renderTable,
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
  const keyRows = buildKeyInventoryRows(global, scoped);

  app.setHeroActions(`
    <a class="button" href="#scoped-key-form">Create scoped key</a>
    <button class="button button--secondary" id="rotate-global-key" type="button">Rotate global key</button>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-security"))}">Security settings</a>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("playground"))}">Smoke in playground</a>
  `);
  app.setContent(
    renderPageFrame({
      toolbar: `
        <div class="toolbar">
          <a class="button" href="#scoped-key-form">Create scoped key</a>
          <button class="button button--secondary" id="rotate-global-key-toolbar" type="button">Rotate global key</button>
          <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Open usage traffic</a>
          <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-security"))}">Security settings</a>
        </div>
        <div class="pill-row">
          ${pill(`Global ${global.configured ? "ready" : "missing"}`, global.configured ? "good" : "warn")}
          ${pill(`Scoped ${formatNumber(scoped.length)}`)}
          ${pill(`Restricted ${formatNumber(scopedRestrictionCount)}`)}
          ${pill(`Observed requests ${formatNumber(totalRequestCount)}`, totalRequestCount ? "good" : "default")}
        </div>
      `,
      stats: [
        kpi("Global key", global.configured ? "configured" : "missing"),
        kpi("Scoped keys", formatNumber(scoped.length)),
        kpi("Restricted scopes", formatNumber(scopedRestrictionCount)),
        kpi("Observed requests", formatNumber(totalRequestCount)),
      ],
      sections: [
        renderPageSection({
          eyebrow: "Inventory",
          title: "Key inventory and live usage",
          description:
            "Scan current key posture from one table, then rotate or issue without leaving the page.",
          actions: `
            <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Usage traffic</a>
            <a class="button button--secondary" href="${escapeHtml(pathForPage("playground"))}">Playground</a>
          `,
          bodyClassName: "page-grid",
          body: `
            ${card(
              "Key inventory",
              `
                <div class="stack">
                  ${renderKeysBanner(global, scoped)}
                  ${renderTable(
                    [
                      { label: "Type" },
                      { label: "Name" },
                      { label: "Scope posture" },
                      { label: "Requests" },
                      { label: "Tokens" },
                      { label: "Preview" },
                      { label: "Actions" },
                    ],
                    keyRows,
                    "Key inventory is unavailable.",
                  )}
                  <p class="field-note">Full key values are shown only once on create or rotate. Use Traffic > Usage to confirm which key actually received requests.</p>
                </div>
              `,
              "panel panel--span-8 panel--measure",
            )}
            ${card(
              "Operational summary",
              renderStatLines(
                [
                  {
                    label: "Global fallback",
                    value: global.configured ? "ready" : "missing",
                    tone: global.configured ? "good" : "warn",
                  },
                  {
                    label: "Restricted scoped keys",
                    value: formatNumber(scopedRestrictionCount),
                  },
                  {
                    label: "Keys with observed usage",
                    value: formatNumber(countKeysWithUsage(global, scoped)),
                    tone: totalRequestCount ? "good" : "default",
                  },
                  {
                    label: "Next move",
                    value: describeNextKeyAction(global, scoped, totalRequestCount),
                  },
                ],
                "Operational summary is unavailable.",
              ),
              "panel panel--span-4 panel--aside",
            )}
          `,
        }),
        renderPageSection({
          eyebrow: "Provision",
          title: "Rotate the fallback and issue scoped keys",
          description:
            "Keep broad fallback changes and narrow client issuance on the same work surface.",
          actions: `
            <button class="button button--secondary" id="rotate-global-key-section" type="button">Rotate global key</button>
          `,
          bodyClassName: "page-grid",
          body: `
            ${card(
              "Global fallback",
              `
                <div class="stack">
                  ${renderDefinitionList(
                    [
                      {
                        label: "Current preview",
                        value: String(global.key_preview ?? "not configured"),
                        note: global.configured
                          ? "Keep this key for deliberate broad fallback access only."
                          : "Rotate once to mint the first reusable broad fallback key.",
                      },
                      {
                        label: "Observed requests",
                        value: formatNumber(readUsageCount(globalUsage.request_count)),
                        note: "Broad fallback usage should stay the exception, not the default distribution path.",
                      },
                      {
                        label: "Preferred distribution model",
                        value: scoped.length ? "Scoped-first" : "Broad fallback only",
                        note: scoped.length
                          ? "Issue narrow keys for real clients and keep the fallback as recovery capacity."
                          : "Create at least one scoped key before wider rollout.",
                      },
                    ],
                    "Global fallback posture is unavailable.",
                  )}
                  <div class="toolbar">
                    <button class="button button--secondary" data-rotate-global type="button">Rotate global key</button>
                    <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-security"))}">Security settings</a>
                    <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic-usage"))}">Usage traffic</a>
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
          `,
        }),
        renderPageSection({
          eyebrow: "Diagnostics",
          title: "Scope posture and raw snapshot",
          description:
            "Use concise guardrails next to the page before falling back to raw payload inspection.",
          bodyClassName: "page-grid",
          body: `
            ${card(
              "Restriction diagnostics",
              renderDefinitionList(
                [
                  {
                    label: "Restricted inventory",
                    value: formatNumber(scopedRestrictionCount),
                    note: scopedRestrictionCount
                      ? "These keys constrain provider, endpoint, or model scope."
                      : "Every scoped key currently has full scoped access.",
                  },
                  {
                    label: "Unrestricted scoped keys",
                    value: formatNumber(scoped.length - scopedRestrictionCount),
                    note: scoped.length
                      ? "Narrow these further if they are client-specific handoffs."
                      : "Create a scoped key above before tuning restrictions.",
                  },
                  {
                    label: "Busiest path",
                    value:
                      scopedRequestCount >= readUsageCount(globalUsage.request_count)
                        ? "Scoped keys"
                        : "Global fallback",
                    note: totalRequestCount
                      ? "Use Traffic > Usage to confirm whether the current distribution still matches policy."
                      : "No attributed usage yet.",
                  },
                ],
                "Restriction diagnostics are unavailable.",
              ),
              "panel panel--span-4 panel--aside",
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
                    label: "Traffic workflow guide",
                    href: OPERATOR_GUIDE_LINKS.traffic,
                    note: "Use Traffic > Usage to verify which key actually received requests after distribution.",
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
                  collapsibleSummary: "Canonical docs",
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
          `,
        }),
      ],
    }),
  );

  const rotateGlobalKey = async (): Promise<void> => {
    const response = await app.api.json<Record<string, unknown>>("/admin/api/keys/global/rotate", {
      method: "POST",
      json: {},
    });
    const nextGlobal = asRecord(response.global);
    app.saveAdminKey(String(nextGlobal.value ?? ""));
    app.saveGatewayKey(String(nextGlobal.value ?? ""));
    app.queueAlert(`Global key rotated. New value: ${String(nextGlobal.value ?? "")}`, "warn");
    await app.render("keys");
  };

  document
    .querySelectorAll<HTMLElement>("#rotate-global-key, #rotate-global-key-toolbar, #rotate-global-key-section, [data-rotate-global]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        void rotateGlobalKey();
      });
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

function buildKeyInventoryRows(global: UsageRecord, scoped: ScopedKeyRow[]): string[][] {
  const globalUsage = asRecord(global.usage);
  const rows: string[][] = [
    [
      pill("Global", global.configured ? "good" : "warn"),
      `
        <strong>Fallback key</strong>
        <div class="field-note">Broad recovery path</div>
      `,
      `<span class="muted">${escapeHtml(global.configured ? "Broad fallback access" : "Not configured yet")}</span>`,
      `<span class="muted">${escapeHtml(formatNumber(readUsageCount(globalUsage.request_count)))}</span>`,
      `<span class="muted">${escapeHtml(formatNumber(readUsageCount(globalUsage.total_tokens)))}</span>`,
      `<span class="muted">${escapeHtml(String(global.key_preview ?? "not configured"))}</span>`,
      `
        <div class="toolbar">
          <button class="button button--secondary" data-rotate-global type="button">Rotate</button>
          <a class="button button--secondary" href="${escapeHtml(pathForPage("settings-security"))}">Security</a>
        </div>
      `,
    ],
  ];

  scoped.forEach((item) => {
    const name = String(item.name ?? "");
    const usage = asRecord(item.usage);
    rows.push([
      pill("Scoped", hasScopedRestrictions(item) ? "good" : "default"),
      `
        <strong>${escapeHtml(name)}</strong>
        <div class="field-note">${escapeHtml(describeRestrictionSummary(item))}</div>
      `,
      `<span class="muted">${escapeHtml(describeScopePosture(item))}</span>`,
      `<span class="muted">${escapeHtml(formatNumber(readUsageCount(usage.request_count)))}</span>`,
      `<span class="muted">${escapeHtml(formatNumber(readUsageCount(usage.total_tokens)))}</span>`,
      `<span class="muted">${escapeHtml(String(item.key_preview ?? ""))}</span>`,
      `
        <div class="toolbar">
          <button class="button button--secondary" data-rotate="${escapeHtml(name)}" type="button">Rotate</button>
          <button class="button button--danger" data-delete="${escapeHtml(name)}" type="button">Delete</button>
        </div>
      `,
    ]);
  });

  return rows;
}

function describeScopePosture(item: ScopedKeyRow): string {
  const parts = [
    csv(item.providers) ? `providers: ${csv(item.providers)}` : "",
    csv(item.endpoints) ? `endpoints: ${csv(item.endpoints)}` : "",
    csv(item.models) ? `models: ${csv(item.models)}` : "",
  ].filter(Boolean);
  return parts.join(" · ") || "full scoped access";
}

function describeRestrictionSummary(item: ScopedKeyRow): string {
  const restrictedDimensions = [
    csv(item.providers) ? "providers" : "",
    csv(item.endpoints) ? "endpoints" : "",
    csv(item.models) ? "models" : "",
  ].filter(Boolean);
  return restrictedDimensions.length
    ? `Restricted by ${restrictedDimensions.join(", ")}`
    : "No explicit provider, endpoint, or model restrictions";
}

function describeNextKeyAction(
  global: UsageRecord,
  scoped: ScopedKeyRow[],
  totalRequestCount: number,
): string {
  if (!global.configured && scoped.length === 0) {
    return "Create first key";
  }
  if (global.configured && scoped.length === 0) {
    return "Issue first scoped key";
  }
  if (!global.configured && scoped.length > 0) {
    return "Consider fallback rotation";
  }
  return totalRequestCount ? "Review usage attribution" : "Smoke one request";
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
