import type { AdminApp } from "../app.js";
import { bindSetupPage } from "./setup/bindings.js";
import { buildSetupPageState } from "./setup/state.js";
import type { SetupPage } from "./setup/types.js";
import { renderSetupContent } from "./setup/view.js";

export async function renderSetup(app: AdminApp, token: number): Promise<void> {
  await renderSetupPage(app, token, "setup");
}

export async function renderSetupClaim(app: AdminApp, token: number): Promise<void> {
  await renderSetupPage(app, token, "setup-claim");
}

export async function renderSetupApplication(
  app: AdminApp,
  token: number,
): Promise<void> {
  await renderSetupPage(app, token, "setup-application");
}

export async function renderSetupGigachat(
  app: AdminApp,
  token: number,
): Promise<void> {
  await renderSetupPage(app, token, "setup-gigachat");
}

export async function renderSetupSecurity(
  app: AdminApp,
  token: number,
): Promise<void> {
  await renderSetupPage(app, token, "setup-security");
}

async function renderSetupPage(
  app: AdminApp,
  token: number,
  currentPage: SetupPage,
): Promise<void> {
  const [setup, runtime, application, observability, gigachat, security, keys] =
    await Promise.all([
      app.api.json<Record<string, unknown>>("/admin/api/setup"),
      app.api.json<Record<string, unknown>>("/admin/api/runtime"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/application"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/observability"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/gigachat"),
      app.api.json<Record<string, unknown>>("/admin/api/settings/security"),
      app.api.json<Record<string, unknown>>("/admin/api/keys"),
    ]);

  if (!app.isCurrentRender(token)) {
    return;
  }

  const state = buildSetupPageState(currentPage, {
    setup,
    runtime,
    application,
    observability,
    gigachat,
    security,
    keys,
  });

  app.setHeroActions(`
    <button class="button button--secondary" id="refresh-setup" type="button">Refresh setup state</button>
    <a class="button" href="${state.nextStep.href}">${state.nextStep.label}</a>
  `);

  app.setContent(renderSetupContent(state));

  document.getElementById("refresh-setup")?.addEventListener("click", () => {
    void app.render(currentPage);
  });

  bindSetupPage(app, state);
}
