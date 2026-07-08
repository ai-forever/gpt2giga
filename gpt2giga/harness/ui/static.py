"""Inline static assets for the no-build Unified Harness UI."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga Unified Harness</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      line-height: 1.4;
      --bg: #f5f6f8;
      --panel: #ffffff;
      --panel-soft: #f9fafb;
      --border: #d7dce5;
      --text: #172033;
      --muted: #657085;
      --accent: #0f766e;
      --accent-strong: #0b5f59;
      --blue: #1d4ed8;
      --yellow: #a16207;
      --red: #b42318;
      --green: #067647;
      --mono: #101828;
      --mono-text: #f8fafc;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
    }
    button,
    input,
    select,
    textarea {
      font: inherit;
    }
    button {
      min-height: 34px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: #ffffff;
      padding: 7px 12px;
      font-weight: 650;
      cursor: pointer;
    }
    button:hover:not(:disabled) {
      background: var(--accent-strong);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.52;
    }
    button.secondary {
      background: #ffffff;
      color: var(--accent);
    }
    button.secondary:hover:not(:disabled),
    button.tab.active {
      background: #ecfdf3;
      color: var(--accent-strong);
    }
    button.tab {
      border-color: var(--border);
      background: #ffffff;
      color: var(--text);
      font-weight: 600;
    }
    label {
      display: grid;
      gap: 5px;
      margin: 0;
      color: var(--text);
      font-size: 13px;
      font-weight: 650;
    }
    input,
    select,
    textarea {
      width: 100%;
      border: 1px solid #c8cfdb;
      border-radius: 6px;
      background: #ffffff;
      color: #111827;
      padding: 8px 10px;
    }
    input:disabled,
    select:disabled,
    textarea:disabled {
      background: #eef1f5;
      color: #687386;
    }
    textarea {
      min-height: 154px;
      resize: vertical;
    }
    pre,
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
        "Liberation Mono", monospace;
    }
    pre {
      margin: 0;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .page {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr auto;
    }
    .topbar {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 22px 12px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }
    .title-block {
      display: grid;
      gap: 4px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.15;
      letter-spacing: 0;
    }
    .subtitle,
    .hint,
    .status-line {
      color: var(--muted);
      font-size: 13px;
    }
    .status-strip {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      max-width: 720px;
    }
    .shell {
      display: grid;
      grid-template-columns: minmax(280px, 330px) minmax(0, 1fr);
      gap: 14px;
      width: min(1480px, 100%);
      margin: 0 auto;
      padding: 14px 18px;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
    }
    .sidebar {
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 580px;
    }
    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 13px 14px;
      border-bottom: 1px solid var(--border);
    }
    .panel-header h2 {
      margin: 0;
      font-size: 15px;
      letter-spacing: 0;
    }
    .harness-list {
      display: grid;
      align-content: start;
      gap: 9px;
      padding: 12px;
      overflow: auto;
    }
    .harness-card {
      width: 100%;
      display: grid;
      gap: 6px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-soft);
      color: var(--text);
      padding: 10px;
      text-align: left;
    }
    .harness-card.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.14);
    }
    .harness-title-row,
    .row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .harness-title {
      font-weight: 750;
    }
    .harness-desc {
      color: var(--muted);
      font-size: 12px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      border: 1px solid #cdd5df;
      border-radius: 999px;
      background: #ffffff;
      color: #344054;
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 650;
    }
    .badge.ok {
      border-color: #abefc6;
      background: #ecfdf3;
      color: var(--green);
    }
    .badge.warn {
      border-color: #fedf89;
      background: #fffaeb;
      color: var(--yellow);
    }
    .badge.error {
      border-color: #fecdca;
      background: #fef3f2;
      color: var(--red);
    }
    .badge.info {
      border-color: #bfdbfe;
      background: #eff6ff;
      color: var(--blue);
    }
    .main {
      display: grid;
      grid-template-rows: auto minmax(320px, 1fr);
      gap: 14px;
      min-width: 0;
    }
    .config-panel {
      padding: 14px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      gap: 12px;
      align-items: end;
    }
    .span-2 {
      grid-column: 1 / -1;
    }
    .radio-row,
    .check-row,
    .actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .choice {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 34px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel-soft);
      padding: 6px 10px;
      color: var(--text);
      font-size: 13px;
      font-weight: 650;
    }
    .choice input {
      width: auto;
      margin: 0;
    }
    .warning {
      display: none;
      border: 1px solid #fedf89;
      border-radius: 8px;
      background: #fffaeb;
      color: #7a4b00;
      padding: 9px 10px;
      font-size: 13px;
    }
    .warning.visible {
      display: block;
    }
    .details {
      display: grid;
      gap: 7px;
      min-height: 76px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .tabs-panel {
      min-width: 0;
      overflow: hidden;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 10px;
      border-bottom: 1px solid var(--border);
      background: var(--panel-soft);
    }
    .tab-body {
      min-height: 330px;
      padding: 12px;
      background: var(--panel);
    }
    .tab-panel {
      min-height: 306px;
      border-radius: 8px;
      background: var(--mono);
      color: var(--mono-text);
      padding: 13px;
      font-size: 13px;
    }
    .tab-panel[hidden] {
      display: none;
    }
    .event-list {
      display: grid;
      align-content: start;
      gap: 9px;
      overflow: auto;
    }
    .event-row {
      display: grid;
      gap: 5px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.12);
      padding-bottom: 9px;
    }
    .event-row:last-child {
      border-bottom: 0;
    }
    .event-message {
      color: #e5e7eb;
    }
    .event-payload {
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.08);
      color: #d1d5db;
      padding: 8px;
      font-size: 12px;
    }
    .footer {
      padding: 0 22px 14px;
      color: var(--muted);
      font-size: 12px;
    }
    @media (max-width: 880px) {
      .shell {
        grid-template-columns: 1fr;
        padding: 12px;
      }
      .form-grid {
        grid-template-columns: 1fr;
      }
      .span-2 {
        grid-column: auto;
      }
      .status-strip {
        justify-content: flex-start;
      }
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #111827;
        --panel: #172033;
        --panel-soft: #1f2937;
        --border: #344054;
        --text: #f8fafc;
        --muted: #c5cedb;
      }
      button.secondary,
      button.tab,
      input,
      select,
      textarea,
      .badge {
        background: #111827;
        color: var(--text);
      }
      input:disabled,
      select:disabled,
      textarea:disabled {
        background: #202b3d;
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="topbar">
      <div class="title-block">
        <h1>gpt2giga Unified Harness</h1>
        <div class="subtitle">
          127.0.0.1 local control panel · v1 -&gt; /v1/chat/completions · v2 -&gt; /v2/chat/completions
        </div>
        <div id="model-status" class="status-line">Loading model suggestions...</div>
      </div>
      <div class="status-strip">
        <span id="proxy-status" class="badge warn">Proxy: checking</span>
        <button id="refresh-health-button" class="secondary" type="button">Refresh proxy</button>
        <button id="refresh-models-button" class="secondary" type="button">Refresh models</button>
      </div>
    </header>

    <main class="shell">
      <aside class="panel sidebar" aria-label="Harnesses">
        <div class="panel-header">
          <h2>Harnesses</h2>
          <span id="harness-count" class="badge info">0</span>
        </div>
        <div id="harness-list" class="harness-list"></div>
      </aside>

      <section class="main" aria-label="Run configuration and output">
        <div class="panel config-panel">
          <div class="form-grid">
            <label>Harness
              <select id="harness-select"></select>
            </label>
            <label>Model
              <input id="model-input" list="model-list" placeholder="GigaChat-2-Max" autocomplete="off">
              <datalist id="model-list"></datalist>
            </label>

            <fieldset class="radio-row" aria-label="API mode">
              <legend class="hint">API mode</legend>
              <label class="choice" for="api-mode-v2">
                <input id="api-mode-v2" name="api-mode" type="radio" value="v2" checked>
                v2
              </label>
              <label class="choice" for="api-mode-v1">
                <input id="api-mode-v1" name="api-mode" type="radio" value="v1">
                v1
              </label>
              <span id="route-note" class="hint">Current route: /v2/chat/completions</span>
            </fieldset>

            <label>Capability
              <select id="capability-select"></select>
            </label>

            <label>Mode
              <select id="mode-select">
                <option value="plan">plan</option>
                <option value="read">read</option>
                <option value="edit">edit</option>
              </select>
            </label>

            <label>Workspace
              <input id="workspace-input" placeholder="." autocomplete="off">
            </label>

            <div class="check-row span-2">
              <label class="choice" for="dry-run-checkbox">
                <input id="dry-run-checkbox" type="checkbox">
                dry run
              </label>
              <label class="choice" for="stream-checkbox">
                <input id="stream-checkbox" type="checkbox">
                stream
              </label>
              <span class="hint">Run mode defaults to plan. Edit mode must be selected explicitly.</span>
            </div>

            <label class="span-2">Prompt
              <textarea id="prompt-input" spellcheck="true" placeholder="Type a smoke prompt or agent task"></textarea>
            </label>

            <div id="harness-warning" class="warning span-2"></div>
            <div id="harness-details" class="details span-2"></div>

            <div class="actions span-2">
              <button id="run-button" type="button">Run</button>
              <button id="copy-cli-button" class="secondary" type="button">Copy CLI</button>
              <button id="copy-curl-button" class="secondary" type="button">Copy curl</button>
              <button id="reset-button" class="secondary" type="button">Reset</button>
            </div>
          </div>
        </div>

        <div class="panel tabs-panel">
          <div class="tabs" role="tablist">
            <button class="tab active" type="button" data-tab="output">Output</button>
            <button class="tab" type="button" data-tab="events">Events</button>
            <button class="tab" type="button" data-tab="raw-request">Raw request</button>
            <button class="tab" type="button" data-tab="raw-response">Raw response</button>
            <button class="tab" type="button" data-tab="command">Command</button>
            <button class="tab" type="button" data-tab="diff">Diff</button>
          </div>
          <div class="tab-body">
            <pre id="output-panel" class="tab-panel">Ready.</pre>
            <div id="events-panel" class="tab-panel event-list" hidden></div>
            <pre id="raw-request-panel" class="tab-panel" hidden>{}</pre>
            <pre id="raw-response-panel" class="tab-panel" hidden>{}</pre>
            <pre id="command-panel" class="tab-panel" hidden>No command has been generated yet.</pre>
            <pre id="diff-panel" class="tab-panel" hidden>No diff or file-change data was returned by this harness run.</pre>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      The browser UI does not store or display API keys. Curl previews use placeholder auth only.
    </footer>
  </div>

  <script>
    const state = {
      defaults: {
        proxy_url: "http://127.0.0.1:8090",
        default_model: "GigaChat-2-Max",
        default_api_mode: "v2"
      },
      harnesses: [],
      selectedHarness: null,
      lastPayload: null,
      lastResponse: null,
      events: []
    };

    const knownEvents = new Set([
      "run_started",
      "proxy_sidecar",
      "message_delta",
      "tool_call_started",
      "tool_call_finished",
      "file_changed",
      "approval_requested",
      "raw_request",
      "raw_response",
      "run_finished",
      "error"
    ]);

    const byId = (id) => document.getElementById(id);

    function setText(id, text) {
      byId(id).textContent = String(text ?? "");
    }

    function pretty(value) {
      return JSON.stringify(value ?? {}, null, 2);
    }

    function selectedApiMode() {
      return byId("api-mode-v1").checked ? "v1" : "v2";
    }

    function setApiMode(value) {
      const mode = value === "v1" ? "v1" : "v2";
      byId("api-mode-v1").checked = mode === "v1";
      byId("api-mode-v2").checked = mode === "v2";
      updateRouteNote();
    }

    function updateRouteNote() {
      setText("route-note", `Current route: /${selectedApiMode()}/chat/completions`);
    }

    function statusClass(status) {
      if (status === "available" || status === true) return "badge ok";
      if (status === "missing") return "badge warn";
      if (status === "error" || status === false) return "badge error";
      return "badge info";
    }

    function readPrefs() {
      try {
        return JSON.parse(localStorage.getItem("gpt2giga.harness.ui") || "{}");
      } catch {
        return {};
      }
    }

    function writePrefs() {
      const prefs = {
        harness_id: byId("harness-select").value,
        api_mode: selectedApiMode(),
        mode: byId("mode-select").value,
        model: byId("model-input").value
      };
      localStorage.setItem("gpt2giga.harness.ui", JSON.stringify(prefs));
    }

    async function getJson(url, options) {
      try {
        const response = await fetch(url, options);
        const text = await response.text();
        let data = {};
        if (text) {
          try {
            data = JSON.parse(text);
          } catch {
            data = { detail: text };
          }
        }
        return { ok: response.ok, status: response.status, data };
      } catch (error) {
        return { ok: false, status: 0, data: { detail: String(error) } };
      }
    }

    async function loadDefaults() {
      const result = await getJson("/api/defaults");
      if (!result.ok) {
        setText("model-status", "Defaults unavailable; using local fallback values.");
        return;
      }
      state.defaults = { ...state.defaults, ...result.data };
      const prefs = readPrefs();
      setApiMode(prefs.api_mode || state.defaults.default_api_mode || "v2");
      byId("mode-select").value = prefs.mode || "plan";
      byId("model-input").value = prefs.model || state.defaults.default_model || "";
      if (result.data.note) {
        setText("model-status", result.data.note);
      }
    }

    async function loadHealth() {
      const result = await getJson("/api/health");
      const node = byId("proxy-status");
      node.className = statusClass(result.ok && result.data.ok);
      if (result.ok && result.data.ok) {
        node.textContent = `Proxy: OK ${result.data.path || ""}`.trim();
      } else {
        const error = result.data.error || result.data.detail || "unreachable";
        node.textContent = `Proxy: Error (${error})`;
      }
    }

    async function loadHarnesses() {
      const result = await getJson("/api/harnesses");
      if (!result.ok) {
        setText("harness-list", "Failed to load harness registry.");
        setText("harness-details", result.data.detail || "Harness registry failed.");
        return;
      }
      state.harnesses = Array.isArray(result.data.harnesses) ? result.data.harnesses : [];
      renderHarnessSelect();
      renderHarnessCards();
      const errors = Array.isArray(result.data.discovery_errors)
        ? result.data.discovery_errors
        : [];
      if (errors.length) {
        setWarning(`Harness discovery warnings: ${errors.join("; ")}`);
      }
      chooseInitialHarness();
    }

    async function loadModels() {
      const mode = selectedApiMode();
      updateRouteNote();
      const result = await getJson(`/api/models?api_mode=${encodeURIComponent(mode)}`);
      const list = byId("model-list");
      list.textContent = "";
      const models = Array.isArray(result.data.models) ? result.data.models : [];
      for (const model of models) {
        const option = document.createElement("option");
        option.value = model;
        list.appendChild(option);
      }
      if (!byId("model-input").value && models.length) {
        byId("model-input").value = models[0];
      }
      const note = result.data.note ? ` ${result.data.note}` : "";
      if (result.ok && result.data.ok) {
        setText("model-status", `Models loaded from ${result.data.source}.${note}`);
      } else {
        const error = result.data.error || result.data.detail || "model discovery failed";
        setText("model-status", `Model discovery fallback: ${error}.${note}`);
      }
      writePrefs();
    }

    function renderHarnessSelect() {
      const select = byId("harness-select");
      select.textContent = "";
      for (const item of state.harnesses) {
        const spec = item.spec || {};
        const availability = item.availability || {};
        const option = document.createElement("option");
        option.value = spec.id || "";
        option.textContent = `${spec.id || "unknown"} (${availability.status || "unknown"})`;
        select.appendChild(option);
      }
      setText("harness-count", String(state.harnesses.length));
    }

    function renderHarnessCards() {
      const list = byId("harness-list");
      list.textContent = "";
      if (!state.harnesses.length) {
        list.textContent = "No harnesses registered.";
        return;
      }
      for (const item of state.harnesses) {
        const spec = item.spec || {};
        const availability = item.availability || {};
        const card = document.createElement("button");
        card.type = "button";
        card.className = "harness-card";
        card.dataset.harnessId = spec.id || "";

        const titleRow = document.createElement("div");
        titleRow.className = "harness-title-row";
        const title = document.createElement("span");
        title.className = "harness-title";
        title.textContent = spec.id || "unknown";
        const status = document.createElement("span");
        status.className = statusClass(availability.status);
        status.textContent = availability.status || "unknown";
        titleRow.append(title, status);

        const desc = document.createElement("div");
        desc.className = "harness-desc";
        desc.textContent = spec.description || "";

        const tags = document.createElement("div");
        tags.className = "row";
        const kind = document.createElement("span");
        kind.className = "badge info";
        kind.textContent = spec.kind || "unknown";
        tags.appendChild(kind);
        for (const capability of spec.capabilities || []) {
          const cap = document.createElement("span");
          cap.className = "badge";
          cap.textContent = capability;
          tags.appendChild(cap);
        }

        card.append(titleRow, desc, tags);
        card.addEventListener("click", () => selectHarness(spec.id));
        list.appendChild(card);
      }
    }

    function chooseInitialHarness() {
      const prefs = readPrefs();
      const ids = state.harnesses.map((item) => item.spec && item.spec.id).filter(Boolean);
      const preferred = [prefs.harness_id, "echo", "direct-chat", ids[0]].find(
        (id) => id && ids.includes(id)
      );
      if (preferred) {
        selectHarness(preferred);
      }
    }

    function selectHarness(harnessId) {
      const item = state.harnesses.find((entry) => entry.spec && entry.spec.id === harnessId);
      if (!item) return;
      state.selectedHarness = item;
      byId("harness-select").value = harnessId;
      for (const card of document.querySelectorAll(".harness-card")) {
        card.classList.toggle("selected", card.dataset.harnessId === harnessId);
      }
      updateHarnessDrivenControls();
      writePrefs();
    }

    function updateHarnessDrivenControls() {
      const item = state.selectedHarness;
      if (!item) return;
      const spec = item.spec || {};
      const availability = item.availability || {};
      const capabilities = Array.isArray(spec.capabilities) ? spec.capabilities : [];

      const capabilitySelect = byId("capability-select");
      capabilitySelect.textContent = "";
      for (const capability of capabilities.length ? capabilities : ["chat_completions"]) {
        const option = document.createElement("option");
        option.value = capability;
        option.textContent = capability;
        capabilitySelect.appendChild(option);
      }

      byId("model-input").disabled = spec.supports_model_selection === false;
      const apiModeDisabled = spec.supports_api_mode_selection === false;
      byId("api-mode-v1").disabled = apiModeDisabled;
      byId("api-mode-v2").disabled = apiModeDisabled;
      byId("workspace-input").disabled = spec.supports_workspace !== true;
      byId("stream-checkbox").disabled = spec.supports_streaming !== true;
      byId("copy-curl-button").disabled = spec.id !== "direct-chat";

      const detailLines = [
        `${spec.title || spec.id || "Harness"} - ${spec.description || ""}`,
        `kind: ${spec.kind || "unknown"}`,
        `availability: ${availability.status || "unknown"} - ${availability.reason || ""}`,
        `capabilities: ${capabilities.join(", ") || "none"}`
      ];
      if (availability.detail) detailLines.push(`detail: ${availability.detail}`);
      setText("harness-details", detailLines.join("\\n"));

      if (availability.status === "missing" || availability.status === "error") {
        setWarning(
          `${spec.id} is ${availability.status}. Real runs are blocked; dry run can still preview commands.`
        );
      } else if (spec.kind === "agent-cli") {
        setWarning("External agent harness. Use plan/read by default; edit must be explicit.");
      } else {
        setWarning("");
      }
    }

    function setWarning(message) {
      const warning = byId("harness-warning");
      warning.textContent = message;
      warning.classList.toggle("visible", Boolean(message));
    }

    function buildPayload() {
      const item = state.selectedHarness || {};
      const spec = item.spec || {};
      return {
        harness_id: byId("harness-select").value || "echo",
        prompt: byId("prompt-input").value,
        model: byId("model-input").disabled ? "" : byId("model-input").value,
        api_mode: selectedApiMode(),
        capability: byId("capability-select").value || "chat_completions",
        mode: byId("mode-select").value || "plan",
        workspace: spec.supports_workspace ? byId("workspace-input").value : "",
        stream: byId("stream-checkbox").checked && !byId("stream-checkbox").disabled,
        dry_run: byId("dry-run-checkbox").checked,
        extra: {}
      };
    }

    function canRunPayload(payload) {
      const item = state.selectedHarness;
      if (!item) {
        return { ok: false, message: "No harness is selected." };
      }
      const status = item.availability && item.availability.status;
      if ((status === "missing" || status === "error") && !payload.dry_run) {
        return {
          ok: false,
          message: "This harness is not available. Enable dry run to preview it safely."
        };
      }
      return { ok: true, message: "" };
    }

    async function runHarness() {
      const payload = buildPayload();
      state.lastPayload = payload;
      state.lastResponse = null;
      state.events = [
        {
          type: "run_started",
          message: `Run started for ${payload.harness_id}`,
          payload: {
            harness_id: payload.harness_id,
            api_mode: payload.api_mode,
            mode: payload.mode,
            dry_run: payload.dry_run
          }
        },
        { type: "raw_request", message: "Normalized UI request", payload }
      ];
      renderEvents();
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      setText("diff-panel", "No diff or file-change data was returned by this harness run.");
      showTab("events");
      writePrefs();

      const allowed = canRunPayload(payload);
      if (!allowed.ok) {
        const body = { ok: false, detail: allowed.message };
        state.lastResponse = body;
        state.events.push({ type: "error", message: allowed.message, payload: {} });
        renderEvents();
        setText("output-panel", allowed.message);
        setText("raw-response-panel", pretty(body));
        showTab("output");
        return;
      }

      byId("run-button").disabled = true;
      byId("run-button").textContent = "Running...";
      setText("output-panel", "Running...");
      try {
        const result = await getJson("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const body = result.data || {};
        state.lastResponse = body;
        setText("raw-response-panel", pretty(body));
        if (result.ok && body.ok) {
          setText("output-panel", body.text || "");
          state.events.push(...normalizeEvents(body.events));
          state.events.push({ type: "run_finished", message: "Run finished.", payload: {} });
        } else {
          const message = body.error || body.detail || `Request failed with HTTP ${result.status}`;
          setText("output-panel", message);
          state.events.push(...normalizeEvents(body.events));
          state.events.push({ type: "error", message, payload: body });
        }
        renderEvents();
        setText("command-panel", commandPreview(payload, body));
        renderDiff(body);
        showTab("output");
      } finally {
        byId("run-button").disabled = false;
        byId("run-button").textContent = "Run";
      }
    }

    function normalizeEvents(events) {
      if (!Array.isArray(events)) return [];
      return events.map((event) => ({
        type: String(event.type || "event"),
        message: String(event.message || ""),
        payload: event.payload && typeof event.payload === "object" ? event.payload : {}
      }));
    }

    function renderEvents() {
      const panel = byId("events-panel");
      panel.textContent = "";
      if (!state.events.length) {
        panel.textContent = "No events yet.";
        return;
      }
      for (const event of state.events) {
        const row = document.createElement("div");
        row.className = "event-row";
        const header = document.createElement("div");
        header.className = "row";
        const badge = document.createElement("span");
        badge.className = knownEvents.has(event.type) ? "badge info" : "badge";
        badge.textContent = event.type;
        const message = document.createElement("span");
        message.className = "event-message";
        message.textContent = event.message || "";
        header.append(badge, message);
        row.appendChild(header);
        if (event.payload && Object.keys(event.payload).length) {
          const payload = document.createElement("pre");
          payload.className = "event-payload";
          payload.textContent = pretty(event.payload);
          row.appendChild(payload);
        }
        panel.appendChild(row);
      }
    }

    function renderDiff(body) {
      const chunks = [];
      const raw = body && body.raw && typeof body.raw === "object" ? body.raw : {};
      if (typeof raw.diff === "string" && raw.diff) chunks.push(raw.diff);
      if (typeof raw.git_diff === "string" && raw.git_diff) chunks.push(raw.git_diff);
      if (Array.isArray(raw.changed_files) && raw.changed_files.length) {
        chunks.push(`changed_files:\\n${pretty(raw.changed_files)}`);
      }
      const fileEvents = state.events.filter((event) => {
        if (event.type === "file_changed") return true;
        return event.payload && typeof event.payload.path === "string";
      });
      if (fileEvents.length) {
        chunks.push(`file events:\\n${pretty(fileEvents)}`);
      }
      setText(
        "diff-panel",
        chunks.length
          ? chunks.join("\\n\\n")
          : "No diff or file-change data was returned by this harness run."
      );
    }

    function commandPreview(payload, responseBody) {
      const sections = [];
      if (
        payloadMatchesLastRun(payload) &&
        responseBody &&
        Array.isArray(responseBody.command) &&
        responseBody.command.length
      ) {
        sections.push(`Backend command array:\\n${pretty(responseBody.command)}`);
        sections.push(`Backend shell command:\\n${responseBody.command.map(shellQuote).join(" ")}`);
      }
      sections.push(`Equivalent CLI:\\n${buildCliCommand(payload).map(shellQuote).join(" ")}`);
      const curl = buildCurlCommand(payload);
      if (curl) {
        sections.push(`Direct-chat curl:\\n${curl.map(shellQuote).join(" ")}`);
      } else {
        sections.push("Direct-chat curl:\\ncurl is only available for direct-chat.");
      }
      return sections.join("\\n\\n");
    }

    function payloadMatchesLastRun(payload) {
      if (!state.lastPayload) return false;
      return JSON.stringify(state.lastPayload) === JSON.stringify(payload);
    }

    function buildCliCommand(payload) {
      const model = payload.model || state.defaults.default_model || "GigaChat-2-Max";
      if (payload.harness_id === "direct-chat") {
        const command = ["giga", "chat", "--api-mode", payload.api_mode, "--model", model];
        if (payload.dry_run) command.push("--dry-run");
        command.push(payload.prompt || "");
        return command;
      }
      const command = [
        "giga",
        "harness",
        "run",
        payload.harness_id,
        "--api-mode",
        payload.api_mode,
        "--model",
        model,
        "--capability",
        payload.capability,
        "--mode",
        payload.mode
      ];
      if (payload.workspace) command.push("--workspace", payload.workspace);
      if (payload.dry_run) command.push("--dry-run");
      command.push("--prompt", payload.prompt || "");
      return command;
    }

    function buildCurlCommand(payload) {
      if (payload.harness_id !== "direct-chat") return null;
      const proxyUrl = (state.defaults.proxy_url || "http://127.0.0.1:8090").replace(/\\/$/, "");
      const model = payload.model || state.defaults.default_model || "GigaChat-2-Max";
      const body = {
        model,
        messages: [{ role: "user", content: payload.prompt || "" }],
        stream: Boolean(payload.stream)
      };
      return [
        "curl",
        "-sS",
        `${proxyUrl}/${payload.api_mode}/chat/completions`,
        "-H",
        "Content-Type: application/json",
        "-H",
        "Authorization: Bearer <GPT2GIGA_API_KEY>",
        "-d",
        JSON.stringify(body)
      ];
    }

    function shellQuote(value) {
      const text = String(value ?? "");
      if (/^[A-Za-z0-9_./:=@+-]+$/.test(text)) return text;
      return "'" + text.replaceAll("'", "'\\''") + "'";
    }

    async function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      const node = document.createElement("textarea");
      node.value = text;
      node.setAttribute("readonly", "readonly");
      node.style.position = "fixed";
      node.style.left = "-9999px";
      document.body.appendChild(node);
      node.select();
      document.execCommand("copy");
      node.remove();
    }

    async function copyCli() {
      const payload = buildPayload();
      await copyText(buildCliCommand(payload).map(shellQuote).join(" "));
      setText("model-status", "Copied CLI command.");
      setText("command-panel", commandPreview(payload, state.lastResponse));
      showTab("command");
    }

    async function copyCurl() {
      const payload = buildPayload();
      const command = buildCurlCommand(payload);
      if (!command) {
        setText("model-status", "curl is only available for direct-chat.");
        return;
      }
      await copyText(command.map(shellQuote).join(" "));
      setText("model-status", "Copied direct-chat curl command.");
      setText("command-panel", commandPreview(payload, state.lastResponse));
      showTab("command");
    }

    function resetUi() {
      const prefs = readPrefs();
      byId("prompt-input").value = "";
      byId("workspace-input").value = "";
      byId("dry-run-checkbox").checked = false;
      byId("stream-checkbox").checked = false;
      byId("mode-select").value = prefs.mode || "plan";
      setApiMode(prefs.api_mode || state.defaults.default_api_mode || "v2");
      byId("model-input").value = prefs.model || state.defaults.default_model || "";
      chooseInitialHarness();
      state.lastPayload = null;
      state.lastResponse = null;
      state.events = [];
      setText("output-panel", "Ready.");
      setText("raw-request-panel", "{}");
      setText("raw-response-panel", "{}");
      setText("command-panel", "No command has been generated yet.");
      setText("diff-panel", "No diff or file-change data was returned by this harness run.");
      renderEvents();
      showTab("output");
    }

    function showTab(name) {
      const map = {
        output: "output-panel",
        events: "events-panel",
        "raw-request": "raw-request-panel",
        "raw-response": "raw-response-panel",
        command: "command-panel",
        diff: "diff-panel"
      };
      for (const [tab, panelId] of Object.entries(map)) {
        byId(panelId).hidden = tab !== name;
      }
      for (const button of document.querySelectorAll("[data-tab]")) {
        button.classList.toggle("active", button.dataset.tab === name);
      }
    }

    function wireEvents() {
      byId("harness-select").addEventListener("change", (event) => {
        selectHarness(event.target.value);
      });
      byId("api-mode-v1").addEventListener("change", loadModels);
      byId("api-mode-v2").addEventListener("change", loadModels);
      byId("mode-select").addEventListener("change", writePrefs);
      byId("model-input").addEventListener("change", writePrefs);
      byId("dry-run-checkbox").addEventListener("change", updateHarnessDrivenControls);
      byId("run-button").addEventListener("click", runHarness);
      byId("copy-cli-button").addEventListener("click", copyCli);
      byId("copy-curl-button").addEventListener("click", copyCurl);
      byId("reset-button").addEventListener("click", resetUi);
      byId("refresh-health-button").addEventListener("click", loadHealth);
      byId("refresh-models-button").addEventListener("click", loadModels);
      for (const button of document.querySelectorAll("[data-tab]")) {
        button.addEventListener("click", () => showTab(button.dataset.tab));
      }
    }

    async function init() {
      wireEvents();
      renderEvents();
      await loadDefaults();
      await loadHealth();
      await loadHarnesses();
      await loadModels();
      updateRouteNote();
    }

    init().catch((error) => {
      setText("output-panel", String(error));
      state.events.push({ type: "error", message: String(error), payload: {} });
      renderEvents();
    });
  </script>
</body>
</html>
"""
