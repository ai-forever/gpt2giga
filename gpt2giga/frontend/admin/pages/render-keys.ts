import type { AdminApp } from "../app.js";
import { card, renderJson } from "../templates.js";
import { asArray, asRecord, csv, escapeHtml, parseCsv } from "../utils.js";

export async function renderKeys(app: AdminApp, token: number): Promise<void> {
  const keys = await app.api.json<Record<string, unknown>>("/admin/api/keys");
  if (!app.isCurrentRender(token)) {
    return;
  }

  const global = asRecord(keys.global);
  const scoped = asArray<Record<string, unknown>>(keys.scoped);

  app.setHeroActions(`<button class="button" id="rotate-global-key" type="button">Rotate global key</button>`);
  app.setContent(`
    ${card(
      "Global key",
      `
        <div class="stack">
          <div class="pill-row">
            <span class="pill">Configured: ${global.configured ? "yes" : "no"}</span>
            <span class="pill">Preview: ${escapeHtml(global.key_preview ?? "not configured")}</span>
          </div>
          ${renderJson(global.usage ?? {})}
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Create scoped key",
      `
        <form id="scoped-key-form" class="stack">
          <label class="field">Name <input name="name" required /></label>
          <label class="field">Providers <input name="providers" placeholder="openai, anthropic" /></label>
          <label class="field">Endpoints <input name="endpoints" placeholder="chat/completions, responses" /></label>
          <label class="field">Models <input name="models" placeholder="GigaChat-2-Max" /></label>
          <button class="button" type="submit">Create scoped key</button>
        </form>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Scoped keys",
      scoped.length
        ? `
            <div class="table-wrap">
              <table>
                <thead>
                  <tr><th>Name</th><th>Scopes</th><th>Preview</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  ${scoped
                    .map((item) => {
                      const name = String(item.name ?? "");
                      const scopes =
                        [csv(item.providers), csv(item.endpoints), csv(item.models)]
                          .filter(Boolean)
                          .join(" | ") || "full scoped access";
                      return `
                        <tr>
                          <td>${escapeHtml(name)}</td>
                          <td>${escapeHtml(scopes)}</td>
                          <td>${escapeHtml(item.key_preview ?? "")}</td>
                          <td>
                            <div class="toolbar">
                              <button class="button button--secondary" data-rotate="${escapeHtml(name)}" type="button">Rotate</button>
                              <button class="button button--danger" data-delete="${escapeHtml(name)}" type="button">Delete</button>
                            </div>
                          </td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            </div>
          `
        : "<p>No scoped keys yet.</p>",
      "panel panel--span-4",
    )}
    ${card("Raw usage", renderJson(keys), "panel panel--span-12")}
  `);

  const rotateButton = document.getElementById("rotate-global-key");
  rotateButton?.addEventListener("click", async () => {
    const response = await app.api.json<Record<string, unknown>>("/admin/api/keys/global/rotate", {
      method: "POST",
      json: {},
    });
    const nextGlobal = asRecord(response.global);
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
