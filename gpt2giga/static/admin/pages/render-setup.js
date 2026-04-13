import { collectGigachatPayload } from "../forms";
import { banner, card, pill, renderSetupSteps } from "../templates";
import { asArray, asRecord, csv, escapeHtml, parseCsv } from "../utils";
export async function renderSetup(app, token) {
    const [setup, runtime, application, gigachat, security, keys] = await Promise.all([
        app.api.json("/admin/api/setup"),
        app.api.json("/admin/api/runtime"),
        app.api.json("/admin/api/settings/application"),
        app.api.json("/admin/api/settings/gigachat"),
        app.api.json("/admin/api/settings/security"),
        app.api.json("/admin/api/keys"),
    ]);
    if (!app.isCurrentRender(token)) {
        return;
    }
    const claim = asRecord(setup.claim);
    const bootstrap = asRecord(setup.bootstrap);
    const applicationValues = asRecord(application.values);
    const gigachatValues = asRecord(gigachat.values);
    const securityValues = asRecord(security.values);
    const globalKey = asRecord(asRecord(keys.global));
    const scopedKeys = asArray(keys.scoped);
    const warnings = asArray(setup.warnings);
    app.setHeroActions(`
    <button class="button button--secondary" id="refresh-setup" type="button">Refresh setup state</button>
    <a class="button" href="/admin/settings">Open full settings</a>
  `);
    app.setContent(`
    ${card("Setup progress", `
        <div class="stack">
          ${renderSetupSteps(asArray(setup.wizard_steps))}
          ${bootstrap.required
        ? banner(`Bootstrap gate is active. Admin setup is currently limited to localhost or the bootstrap token stored at ${String(bootstrap.token_path ?? "the control-plane volume")}.`, "warn")
        : banner("Bootstrap gate is closed. Normal operator access now relies on the configured admin/global API key path.")}
          <div class="dual-grid">
            <div class="stack">
              <div class="stat-line"><strong>Claim status</strong><span class="muted">${claim.claimed ? "claimed" : claim.required ? "pending" : "not required"}</span></div>
              <div class="stat-line"><strong>Control-plane file</strong><span class="muted">${escapeHtml(setup.path ?? "n/a")}</span></div>
              <div class="stat-line"><strong>Encryption key file</strong><span class="muted">${escapeHtml(setup.key_path ?? "n/a")}</span></div>
              <div class="stat-line"><strong>Runtime mode</strong><span class="muted">${escapeHtml(runtime.mode ?? "n/a")}</span></div>
              <div class="stat-line"><strong>Store backend</strong><span class="muted">${escapeHtml(runtime.runtime_store_backend ?? "n/a")}</span></div>
            </div>
            <div class="stack">
              ${claim.claimed ? `<span class="pill">Claimed at: ${escapeHtml(claim.claimed_at ?? "n/a")}</span>` : ""}
              ${claim.claimed ? `<span class="pill">Operator: ${escapeHtml(claim.operator_label ?? "not recorded")}</span>` : ""}
              ${bootstrap.required ? `<span class="pill">Bootstrap localhost access: ${bootstrap.allow_localhost ? "on" : "off"}</span>` : ""}
              ${bootstrap.required ? `<span class="pill">Bootstrap token access: ${bootstrap.allow_token ? "on" : "off"}</span>` : ""}
              ${warnings.length
        ? warnings.map((warning) => banner(String(warning), "warn")).join("")
        : banner("Setup checks look healthy. You can move on to playground and traffic pages.")}
            </div>
          </div>
        </div>
      `, "panel panel--span-12")}
    ${card("Step 1 · Claim instance", `
        <div class="stack">
          ${banner(claim.required
        ? claim.claimed
            ? `This bootstrap session is already claimed${claim.operator_label ? ` by ${String(claim.operator_label)}` : ""}.`
            : "First-run PROD bootstrap is active. Claim the instance before continuing with operator setup."
        : "Claiming is not required in the current runtime mode.", claim.claimed ? "info" : "warn")}
          ${claim.claimed
        ? `
                  <div class="dual-grid">
                    <div class="stack">
                      ${pill(`Claimed at: ${String(claim.claimed_at ?? "n/a")}`)}
                      ${pill(`Claimed via: ${String(claim.claimed_via ?? "n/a")}`)}
                    </div>
                    <div class="stack">
                      ${pill(`Operator label: ${String(claim.operator_label ?? "not recorded")}`)}
                      ${pill(`Source IP: ${String(claim.claimed_from ?? "unknown")}`)}
                    </div>
                  </div>
                `
        : claim.required
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
            : ""}
        </div>
      `, "panel panel--span-4")}
    ${card("Step 2 · Application posture", `
        <form id="setup-application-form" class="stack">
          <div class="dual-grid">
            <label class="field">
              <span>Mode</span>
              <select name="mode">
                <option value="DEV" ${applicationValues.mode === "DEV" ? "selected" : ""}>DEV</option>
                <option value="PROD" ${applicationValues.mode === "PROD" ? "selected" : ""}>PROD</option>
              </select>
            </label>
            <label class="field">
              <span>GigaChat API mode</span>
              <select name="gigachat_api_mode">
                <option value="v1" ${applicationValues.gigachat_api_mode === "v1" ? "selected" : ""}>v1</option>
                <option value="v2" ${applicationValues.gigachat_api_mode === "v2" ? "selected" : ""}>v2</option>
              </select>
            </label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Enabled providers</span>
              <input name="enabled_providers" value="${escapeHtml(csv(applicationValues.enabled_providers))}" />
            </label>
            <label class="field">
              <span>Observability sinks</span>
              <input name="observability_sinks" value="${escapeHtml(csv(applicationValues.observability_sinks))}" />
            </label>
          </div>
          <div class="dual-grid">
            <label class="field">
              <span>Runtime store backend</span>
              <select name="runtime_store_backend">
                <option value="memory" ${applicationValues.runtime_store_backend === "memory" ? "selected" : ""}>memory</option>
                <option value="sqlite" ${applicationValues.runtime_store_backend === "sqlite" ? "selected" : ""}>sqlite</option>
              </select>
            </label>
            <label class="field">
              <span>Runtime namespace</span>
              <input name="runtime_store_namespace" value="${escapeHtml(applicationValues.runtime_store_namespace ?? "")}" />
            </label>
          </div>
          <div class="triple-grid">
            <label class="field">
              <span>Telemetry</span>
              <select name="enable_telemetry">
                <option value="true" ${applicationValues.enable_telemetry ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.enable_telemetry ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field">
              <span>Pass model</span>
              <select name="pass_model">
                <option value="true" ${applicationValues.pass_model ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.pass_model ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field">
              <span>Pass token</span>
              <select name="pass_token">
                <option value="true" ${applicationValues.pass_token ? "selected" : ""}>on</option>
                <option value="false" ${!applicationValues.pass_token ? "selected" : ""}>off</option>
              </select>
            </label>
          </div>
          <button class="button" type="submit">Save application step</button>
        </form>
      `, "panel panel--span-4")}
    ${card("Step 3 · GigaChat auth", `
        <form id="setup-gigachat-form" class="stack">
          <div class="dual-grid">
            <label class="field"><span>Model</span><input name="model" value="${escapeHtml(gigachatValues.model ?? "")}" /></label>
            <label class="field"><span>Scope</span><input name="scope" value="${escapeHtml(gigachatValues.scope ?? "")}" /></label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Base URL</span><input name="base_url" value="${escapeHtml(gigachatValues.base_url ?? "")}" /></label>
            <label class="field"><span>Auth URL</span><input name="auth_url" value="${escapeHtml(gigachatValues.auth_url ?? "")}" /></label>
          </div>
          <div class="dual-grid">
            <label class="field"><span>Credentials</span><textarea name="credentials" placeholder="Paste GigaChat credentials"></textarea></label>
            <label class="field"><span>Access token</span><textarea name="access_token" placeholder="Optional access token"></textarea></label>
          </div>
          <label class="field">
            <span>Verify SSL</span>
            <select name="verify_ssl_certs">
              <option value="true" ${gigachatValues.verify_ssl_certs ? "selected" : ""}>on</option>
              <option value="false" ${!gigachatValues.verify_ssl_certs ? "selected" : ""}>off</option>
            </select>
          </label>
          ${banner(`Current credentials preview: ${String(gigachatValues.credentials_preview ?? "not configured")}.`)}
          <div class="toolbar">
            <button class="button" type="submit">Save GigaChat step</button>
            <button class="button button--secondary" id="setup-gigachat-test" type="button">Test connection</button>
          </div>
        </form>
      `, "panel panel--span-4")}
    ${card("Step 4 · Security bootstrap", `
        <div class="stack">
          <form id="setup-security-form" class="stack">
            <label class="field">
              <span>Enable gateway API key auth</span>
              <select name="enable_api_key_auth">
                <option value="true" ${securityValues.enable_api_key_auth ? "selected" : ""}>on</option>
                <option value="false" ${!securityValues.enable_api_key_auth ? "selected" : ""}>off</option>
              </select>
            </label>
            <label class="field">
              <span>CORS origins</span>
              <input name="cors_allow_origins" value="${escapeHtml(csv(securityValues.cors_allow_origins))}" />
            </label>
            <label class="field">
              <span>Logs IP allowlist</span>
              <input name="logs_ip_allowlist" value="${escapeHtml(csv(securityValues.logs_ip_allowlist))}" />
            </label>
            <button class="button" type="submit">Save security step</button>
          </form>
          <div class="dual-grid">
            <div class="stack">
              ${pill(`Global key: ${globalKey.configured ? "configured" : "missing"}`)}
              ${pill(`Scoped keys: ${scopedKeys.length}`)}
              ${pill(`Preview: ${String(globalKey.key_preview ?? "not configured")}`)}
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
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Step 5 · Finish", `
        <div class="stack">
          ${pill(`Claimed instance: ${claim.claimed ? "yes" : claim.required ? "pending" : "not required"}`)}
          ${pill(`Persisted config: ${setup.persisted ? "yes" : "no"}`)}
          ${pill(`GigaChat ready: ${setup.gigachat_ready ? "yes" : "no"}`)}
          ${pill(`Security ready: ${setup.security_ready ? "yes" : "no"}`)}
          ${setup.setup_complete
        ? banner("Bootstrap path is complete. The operator console can now be used as the main control plane.")
        : banner("Bootstrap is not complete yet. Finish the missing steps above before relying on zero-env restarts or exposing the gateway.", "warn")}
          <div class="toolbar">
            <a class="button button--secondary" href="/admin">Back to overview</a>
            <a class="button" href="/admin/playground">Open playground</a>
          </div>
        </div>
      `, "panel panel--span-12")}
  `);
    document.getElementById("refresh-setup")?.addEventListener("click", () => {
        void app.render("setup");
    });
    const claimForm = app.pageContent.querySelector("#setup-claim-form");
    claimForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const operatorLabel = form.elements.namedItem("operator_label").value.trim();
        const response = await app.api.json("/admin/api/setup/claim", {
            method: "POST",
            json: {
                operator_label: operatorLabel || null,
            },
        });
        const nextClaim = asRecord(response.claim);
        app.queueAlert(nextClaim.operator_label
            ? `Instance claimed by ${String(nextClaim.operator_label)}.`
            : "Instance claim recorded.", "info");
        await app.render("setup");
    });
    app.pageContent
        .querySelector("#setup-application-form")
        ?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const response = await app.api.json("/admin/api/settings/application", {
            method: "PUT",
            json: {
                mode: fields.mode.value,
                gigachat_api_mode: fields.gigachat_api_mode.value,
                enabled_providers: parseCsv(fields.enabled_providers.value),
                observability_sinks: parseCsv(fields.observability_sinks.value),
                runtime_store_backend: fields.runtime_store_backend.value,
                runtime_store_namespace: fields.runtime_store_namespace.value.trim(),
                enable_telemetry: fields.enable_telemetry.value === "true",
                pass_model: fields.pass_model.value === "true",
                pass_token: fields.pass_token.value === "true",
            },
        });
        app.queueAlert(response.restart_required
            ? "Application bootstrap step saved. Restart required for part of the change set."
            : "Application bootstrap step saved and applied.", response.restart_required ? "warn" : "info");
        await app.render("setup");
    });
    app.pageContent
        .querySelector("#setup-gigachat-form")
        ?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const response = await app.api.json("/admin/api/settings/gigachat", {
            method: "PUT",
            json: collectGigachatPayload(form),
        });
        app.queueAlert(response.restart_required
            ? "GigaChat bootstrap step saved. Restart required."
            : "GigaChat bootstrap step saved and runtime reloaded.", response.restart_required ? "warn" : "info");
        await app.render("setup");
    });
    document.getElementById("setup-gigachat-test")?.addEventListener("click", async () => {
        const form = app.pageContent.querySelector("#setup-gigachat-form");
        if (!form) {
            return;
        }
        const result = await app.api.json("/admin/api/settings/gigachat/test", {
            method: "POST",
            json: collectGigachatPayload(form),
        });
        app.pushAlert(result.ok
            ? `GigaChat connection ok. Models visible: ${String(result.model_count ?? 0)}.`
            : `GigaChat connection failed: ${String(result.error_type ?? "Error")}: ${String(result.error ?? "unknown error")}`, result.ok ? "info" : "danger");
    });
    app.pageContent
        .querySelector("#setup-security-form")
        ?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = form.elements;
        const response = await app.api.json("/admin/api/settings/security", {
            method: "PUT",
            json: {
                enable_api_key_auth: fields.enable_api_key_auth.value === "true",
                cors_allow_origins: parseCsv(fields.cors_allow_origins.value),
                logs_ip_allowlist: parseCsv(fields.logs_ip_allowlist.value),
            },
        });
        app.queueAlert(response.restart_required
            ? "Security bootstrap step saved. Restart required."
            : "Security bootstrap step saved and applied.", response.restart_required ? "warn" : "info");
        await app.render("setup");
    });
    document.getElementById("setup-create-global-key")?.addEventListener("click", async () => {
        const input = document.getElementById("setup-global-key-value");
        const response = await app.api.json("/admin/api/keys/global/rotate", {
            method: "POST",
            json: { value: input?.value.trim() || null },
        });
        const nextGlobal = asRecord(response.global);
        app.saveGatewayKey(String(nextGlobal.value ?? ""));
        app.queueAlert(`Global gateway key created. New value: ${String(nextGlobal.value ?? "")}`, "warn");
        await app.render("setup");
    });
}
