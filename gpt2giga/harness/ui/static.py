"""Inline static assets for the no-build Unified Harness UI."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga Harness Chat Cockpit</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      line-height: 1.4;
      --bg: #111315;
      --panel: #181b20;
      --panel-soft: #20242b;
      --panel-strong: #252a32;
      --border: #343b46;
      --text: #f2f4f7;
      --muted: #98a2b3;
      --accent: #14b8a6;
      --accent-strong: #2dd4bf;
      --blue: #60a5fa;
      --amber: #fbbf24;
      --red: #f87171;
      --green: #34d399;
      --violet: #a78bfa;
      --mono-bg: #0b0d10;
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
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
      min-height: 32px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: #06201d;
      padding: 6px 10px;
      font-weight: 700;
      cursor: pointer;
    }
    button:hover:not(:disabled) {
      background: var(--accent-strong);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    button.secondary,
    button.tab {
      border-color: var(--border);
      background: var(--panel-soft);
      color: var(--text);
    }
    button.danger {
      border-color: #7f1d1d;
      background: #451a1a;
      color: #fecaca;
    }
    button.tab.active {
      border-color: var(--accent);
      color: var(--accent-strong);
    }
    input,
    select,
    textarea {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #111418;
      color: var(--text);
      padding: 7px 9px;
    }
    input:disabled,
    select:disabled,
    textarea:disabled {
      color: #6b7280;
      background: #191d23;
    }
    textarea {
      min-height: 104px;
      resize: vertical;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
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
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      background: #15181d;
    }
    h1,
    h2,
    h3 {
      margin: 0;
      letter-spacing: 0;
    }
    h1 {
      font-size: 18px;
    }
    h2 {
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
    }
    h3 {
      font-size: 14px;
    }
    .top-actions,
    .inline-actions,
    .badge-row,
    .check-row,
    .tabs {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .status-line,
    .hint {
      color: var(--muted);
      font-size: 12px;
    }
    .top-summary {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
    }
    .project-panel {
      display: grid;
      gap: 4px;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel-soft);
    }
    .project-title {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
      font-weight: 800;
    }
    .model-picker {
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 34px;
    }
    .model-picker input {
      min-width: 0;
      border-radius: 6px 0 0 6px;
    }
    .model-picker:focus-within input,
    .model-picker:focus-within .model-menu-button {
      border-color: #93c5fd;
      box-shadow: 0 0 0 1px #93c5fd;
    }
    .model-menu-button {
      min-height: 0;
      border-color: var(--border);
      border-left: 0;
      border-radius: 0 6px 6px 0;
      background: #111418;
      color: var(--muted);
      padding: 0;
    }
    .model-menu-button:hover:not(:disabled) {
      background: var(--panel-soft);
      color: var(--text);
    }
    .model-menu-button:disabled {
      border-left: 0;
    }
    .model-list {
      position: absolute;
      z-index: 40;
      top: calc(100% + 6px);
      right: 0;
      left: 0;
      max-height: 220px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #111418;
      box-shadow: 0 16px 40px rgb(0 0 0 / 0.38);
      padding: 4px;
    }
    .model-list[hidden] {
      display: none;
    }
    .model-option {
      display: block;
      width: 100%;
      min-height: 32px;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--text);
      padding: 6px 8px;
      text-align: left;
      font-weight: 700;
    }
    .model-option:hover,
    .model-option.active {
      background: var(--panel-strong);
      color: var(--accent-strong);
    }
    .model-option.empty {
      color: var(--muted);
      cursor: default;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-height: 24px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--panel-soft);
      color: var(--muted);
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .badge.ok {
      color: var(--green);
      border-color: #166534;
    }
    .badge.warn {
      color: var(--amber);
      border-color: #92400e;
    }
    .badge.error {
      color: var(--red);
      border-color: #7f1d1d;
    }
    .badge.info {
      color: var(--blue);
      border-color: #1d4ed8;
    }
    .shell {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr) 360px;
      min-height: 0;
    }
    .sidebar,
    .inspector {
      min-width: 0;
      border-right: 1px solid var(--border);
      background: var(--panel);
    }
    .inspector {
      border-right: 0;
      border-left: 1px solid var(--border);
    }
    .sidebar-scroll,
    .chat-scroll,
    .inspector-scroll {
      overflow: auto;
      min-height: 0;
    }
    .sidebar,
    .center,
    .inspector {
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: calc(100vh - 57px);
    }
    .section {
      padding: 12px;
      border-bottom: 1px solid var(--border);
    }
    .sidebar-controls {
      display: grid;
      gap: 8px;
    }
    .session-list,
    #harness-list {
      display: grid;
      gap: 6px;
      padding: 10px;
    }
    .group-title {
      margin: 12px 0 4px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }
    .session-row,
    .harness-card {
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      padding: 8px;
      cursor: pointer;
    }
    .session-row:hover,
    .harness-card:hover,
    .session-row.active {
      border-color: var(--border);
      background: var(--panel-soft);
    }
    .session-row.active {
      border-color: var(--accent);
    }
    .session-title {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 750;
    }
    .session-meta,
    .message-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
    }
    .center {
      min-width: 0;
      background: #13161a;
    }
    .config-grid {
      display: grid;
      grid-template-columns: minmax(150px, 1.1fr) minmax(160px, 1.2fr) 130px 120px;
      gap: 10px;
      align-items: end;
    }
    .span-2 {
      grid-column: span 2;
    }
    .span-4 {
      grid-column: 1 / -1;
    }
    fieldset {
      margin: 0;
      border: 0;
      padding: 0;
    }
    .choice {
      display: inline-flex;
      width: auto;
      grid-template-columns: auto;
      align-items: center;
      gap: 6px;
      color: var(--text);
      font-size: 13px;
    }
    .choice input {
      width: auto;
    }
    .message-list {
      display: grid;
      gap: 10px;
      padding: 16px;
    }
    .message {
      max-width: min(860px, 92%);
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      padding: 10px 12px;
    }
    .message.user {
      justify-self: end;
      background: #14312d;
      border-color: #115e59;
    }
    .message.assistant {
      justify-self: start;
    }
    .message.error {
      justify-self: start;
      border-color: #7f1d1d;
      background: #2b1717;
    }
    .message-content {
      margin-top: 6px;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 14px;
    }
    .composer {
      display: grid;
      gap: 10px;
      padding: 12px;
      border-top: 1px solid var(--border);
      background: var(--panel);
    }
    .details,
    .warning {
      min-height: 20px;
      color: var(--muted);
      font-size: 12px;
    }
    .warning {
      color: var(--amber);
    }
    .inspector-body {
      display: grid;
      gap: 10px;
      padding: 12px;
    }
    .mono-panel {
      min-height: 160px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--mono-bg);
      color: #d1d5db;
      padding: 10px;
      font-size: 12px;
    }
    .tab-panel {
      display: none;
    }
    .tab-panel.active {
      display: block;
    }
    .event-row {
      border-bottom: 1px solid #232830;
      padding: 8px 0;
    }
    .event-row:last-child {
      border-bottom: 0;
    }
    .empty {
      color: var(--muted);
      padding: 18px;
      text-align: center;
    }
    @media (max-width: 1100px) {
      .shell {
        grid-template-columns: 240px minmax(0, 1fr);
      }
      .inspector {
        grid-column: 1 / -1;
        min-height: auto;
        border-left: 0;
        border-top: 1px solid var(--border);
      }
      .config-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 760px) {
      .topbar,
      .shell {
        display: block;
      }
      .sidebar,
      .center,
      .inspector {
        min-height: auto;
        border-left: 0;
        border-right: 0;
      }
      .config-grid {
        grid-template-columns: 1fr;
      }
      .span-2,
      .span-4 {
        grid-column: auto;
      }
      .message {
        max-width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div>
        <h1>gpt2giga Project Cockpit</h1>
        <div id="project-status" class="status-line">Loading project...</div>
        <div class="top-summary">
          <span id="current-model-badge" class="badge info">Model: loading</span>
          <span id="current-route-badge" class="badge info">Route: /v2/chat/completions</span>
          <span id="model-status" class="badge">Models: loading</span>
        </div>
      </div>
      <div class="top-actions">
        <span id="proxy-status" class="badge warn">Proxy: checking</span>
        <button id="init-project-button" class="secondary" type="button" hidden>Init project</button>
        <button id="refresh-health-button" class="secondary" type="button">Refresh proxy</button>
        <button id="refresh-models-button" class="secondary" type="button">Refresh models</button>
      </div>
    </header>

    <main class="shell">
      <aside class="sidebar" aria-label="Session history">
        <div class="section sidebar-controls">
          <div class="project-panel">
            <h2>Project</h2>
            <div id="project-name" class="project-title">Loading...</div>
            <div id="project-meta" class="session-meta"></div>
          </div>
          <div class="inline-actions">
            <button id="new-chat-button" type="button">+ New chat</button>
            <span id="session-count" class="badge info">0</span>
          </div>
          <input id="session-search" placeholder="Search" autocomplete="off">
          <label>Workspace
            <input id="session-workspace-filter" placeholder="All workspaces" autocomplete="off">
          </label>
          <label>Harness
            <select id="session-harness-filter">
              <option value="">All harnesses</option>
            </select>
          </label>
          <label class="choice" for="include-archived-checkbox">
            <input id="include-archived-checkbox" type="checkbox">
            Include archived
          </label>
        </div>
        <div class="sidebar-scroll">
          <div id="session-list" class="session-list"></div>
          <div class="section">
            <div class="inline-actions">
              <h2>Harnesses</h2>
              <span id="harness-count" class="badge info">0</span>
            </div>
            <div id="harness-list"></div>
          </div>
        </div>
      </aside>

      <section class="center" aria-label="Chat and run surface">
        <div class="section">
          <div class="config-grid">
            <label>Harness
              <select id="harness-select"></select>
            </label>
            <label>Model
              <div id="model-picker" class="model-picker">
                <input id="model-input" placeholder="GigaChat-2-Max" autocomplete="off" aria-controls="model-list">
                <button id="model-menu-button" class="model-menu-button" type="button" aria-label="Show model suggestions">v</button>
                <div id="model-list" class="model-list" role="listbox" hidden></div>
              </div>
            </label>
            <fieldset aria-label="API mode">
              <div class="badge-row">
                <label class="choice" for="api-mode-v2">
                  <input id="api-mode-v2" name="api-mode" type="radio" value="v2" checked>
                  v2
                </label>
                <label class="choice" for="api-mode-v1">
                  <input id="api-mode-v1" name="api-mode" type="radio" value="v1">
                  v1
                </label>
              </div>
              <div id="route-note" class="hint">Current route: /v2/chat/completions</div>
            </fieldset>
            <label>Mode
              <select id="mode-select">
                <option value="plan">plan</option>
                <option value="read">read</option>
                <option value="edit">edit</option>
              </select>
            </label>
            <label>Capability
              <select id="capability-select"></select>
            </label>
            <label class="span-2">Workspace
              <input id="workspace-input" placeholder="." autocomplete="off">
            </label>
            <div class="check-row">
              <label class="choice" for="dry-run-checkbox">
                <input id="dry-run-checkbox" type="checkbox">
                dry run
              </label>
              <label class="choice" for="stream-checkbox">
                <input id="stream-checkbox" type="checkbox">
                stream
              </label>
            </div>
            <div id="harness-warning" class="warning span-4"></div>
            <div id="harness-details" class="details span-4"></div>
          </div>
        </div>
        <div id="output-panel" class="chat-scroll">
          <div id="message-list" class="message-list"></div>
        </div>
        <div class="composer">
          <label>Prompt
            <textarea id="prompt-input" spellcheck="true"></textarea>
          </label>
          <div class="inline-actions">
            <button id="run-button" type="button">Run</button>
            <button id="copy-cli-button" class="secondary" type="button">Copy CLI</button>
            <button id="copy-curl-button" class="secondary" type="button">Copy curl</button>
            <button id="reset-button" class="secondary" type="button">Reset</button>
          </div>
        </div>
      </section>

      <aside class="inspector" aria-label="Inspector">
        <div class="section">
          <div class="inline-actions">
            <h2>Inspector</h2>
            <button id="rename-session-button" class="secondary" type="button">Rename</button>
            <button id="pin-session-button" class="secondary" type="button">Pin</button>
            <button id="archive-session-button" class="secondary" type="button">Archive</button>
            <button id="delete-session-button" class="danger" type="button">Delete</button>
          </div>
          <div id="selected-session-line" class="status-line">No session selected</div>
        </div>
        <div class="inspector-scroll">
          <div class="inspector-body">
            <div class="tabs" role="tablist">
              <button class="tab active" type="button" data-tab="run">Run</button>
              <button class="tab" type="button" data-tab="events">Events</button>
              <button class="tab" type="button" data-tab="raw-request">Raw request</button>
              <button class="tab" type="button" data-tab="raw-response">Raw response</button>
              <button class="tab" type="button" data-tab="command">Command</button>
              <button class="tab" type="button" data-tab="diff">Diff</button>
              <button class="tab" type="button" data-tab="storage">Storage</button>
            </div>
            <pre id="run-panel" class="mono-panel tab-panel active">No run selected.</pre>
            <div id="events-panel" class="mono-panel tab-panel">No events yet.</div>
            <pre id="raw-request-panel" class="mono-panel tab-panel">{}</pre>
            <pre id="raw-response-panel" class="mono-panel tab-panel">{}</pre>
            <pre id="command-panel" class="mono-panel tab-panel">No command yet.</pre>
            <pre id="diff-panel" class="mono-panel tab-panel">No diff captured.</pre>
            <pre id="storage-panel" class="mono-panel tab-panel">No storage selected.</pre>
          </div>
        </div>
      </aside>
    </main>
  </div>

  <script>
    const state = {
      defaults: {},
      harnesses: [],
      sessions: [],
      models: [],
      modelSource: "",
      project: null,
      projectConfig: null,
      selectedHarness: null,
      currentSessionId: null,
      currentBundle: null,
      lastPayload: null
    };

    const byId = (id) => document.getElementById(id);
    const pretty = (value) => JSON.stringify(value || {}, null, 2);
    const setText = (id, value) => {
      const node = byId(id);
      if (node) node.textContent = value == null ? "" : String(value);
    };

    async function getJson(url, options) {
      const response = await fetch(url, options);
      let data = {};
      try {
        data = await response.json();
      } catch (error) {
        data = { detail: "non-JSON response" };
      }
      return { ok: response.ok, status: response.status, data };
    }

    async function loadDefaults() {
      const result = await getJson("/api/defaults");
      if (!result.ok) return;
      state.defaults = result.data;
      byId("model-input").value = result.data.default_model || "GigaChat-2-Max";
      const mode = result.data.default_api_mode || "v2";
      byId(`api-mode-${mode}`).checked = true;
      updateRouteNote();
      updateHeaderBadges();
      if (result.data.note) setText("model-status", result.data.note);
    }

    async function loadProject() {
      const result = await getJson("/api/project");
      if (!result.ok) {
        setText("project-status", result.data.detail || "Project unavailable.");
        setText("project-name", "Project unavailable");
        byId("init-project-button").hidden = true;
        return;
      }
      state.project = result.data.project || null;
      state.projectConfig = result.data.config || null;
      applyProject();
    }

    function applyProject() {
      const project = state.project || {};
      const config = state.projectConfig || {};
      setText("project-name", project.name || "Unassigned");
      const branch = project.git_branch ? `branch ${project.git_branch}` : "no git branch";
      const dirty = project.dirty_summary || {};
      const dirtyText = project.is_git_repo ? `dirty +${dirty.added || 0} -${dirty.deleted || 0} ~${dirty.changed || 0}` : "not a git repo";
      setText("project-meta", `${branch} | ${dirtyText}`);
      setText("project-status", `${project.name || "Project"} / ${project.root || ""}`);
      byId("init-project-button").hidden = Boolean(config.exists);
      if (project.root && !byId("workspace-input").value) {
        byId("workspace-input").value = project.root;
      }
      if (config.exists && config.defaults) {
        byId("model-input").value = config.defaults.model || byId("model-input").value;
        byId("mode-select").value = config.defaults.mode || "plan";
        const mode = config.defaults.api_mode || "v2";
        const apiMode = byId(`api-mode-${mode}`);
        if (apiMode) apiMode.checked = true;
        updateRouteNote();
      }
    }

    async function initProject() {
      const workspace = state.project && state.project.root ? state.project.root : null;
      const result = await getJson("/api/project/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace })
      });
      if (!result.ok) {
        setText("project-status", result.data.detail || "Project init failed.");
        return;
      }
      state.project = result.data.project || null;
      state.projectConfig = result.data.config || null;
      applyProject();
      await loadSessions();
    }

    async function refreshHealth() {
      const result = await getJson("/api/health");
      const badge = byId("proxy-status");
      if (result.ok && result.data.ok) {
        badge.className = "badge ok";
        badge.textContent = `Proxy: ${result.data.path || "ok"}`;
      } else {
        badge.className = "badge warn";
        badge.textContent = "Proxy: unavailable";
      }
    }

    async function loadModels() {
      const mode = currentApiMode();
      const result = await getJson(`/api/models?api_mode=${encodeURIComponent(mode)}`);
      const data = result.data || {};
      state.models = Array.isArray(data.models) ? data.models : [];
      state.modelSource = data.source || `/${mode}/models`;
      renderModelList();
      if (!byId("model-input").value && state.models[0]) byId("model-input").value = state.models[0];
      const status = data.ok ? `Models: ${data.source}` : `Models: ${state.modelSource} unavailable${data.error ? " - " + data.error : ""}`;
      setText("model-status", data.note ? `${status}. ${data.note}` : status);
      updateHeaderBadges();
    }

    function renderModelList() {
      const list = byId("model-list");
      const query = byId("model-input").value.trim().toLowerCase();
      const models = state.models.filter((model) => String(model).toLowerCase().includes(query));
      list.textContent = "";
      if (!models.length) {
        const empty = document.createElement("button");
        empty.className = "model-option empty";
        empty.type = "button";
        empty.disabled = true;
        empty.textContent = state.models.length ? "No matching models" : `No models from ${state.modelSource || "selected route"}`;
        list.appendChild(empty);
        return;
      }
      for (const model of models) {
        const option = document.createElement("button");
        option.className = `model-option${model === byId("model-input").value ? " active" : ""}`;
        option.type = "button";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", model === byId("model-input").value ? "true" : "false");
        option.textContent = model;
        option.addEventListener("click", () => selectModel(model));
        list.appendChild(option);
      }
    }

    function openModelList() {
      if (byId("model-input").disabled) return;
      renderModelList();
      byId("model-list").hidden = false;
    }

    function closeModelList() {
      byId("model-list").hidden = true;
    }

    function toggleModelList() {
      if (byId("model-list").hidden) {
        openModelList();
      } else {
        closeModelList();
      }
    }

    function selectModel(model) {
      byId("model-input").value = model;
      renderModelList();
      closeModelList();
      updateHeaderBadges();
      byId("model-input").focus();
    }

    async function loadHarnesses() {
      const result = await getJson("/api/harnesses");
      if (!result.ok) {
        setText("harness-details", result.data.detail || "Harness registry failed.");
        return;
      }
      state.harnesses = result.data.harnesses || [];
      renderHarnessSelect();
      renderHarnessCards();
      chooseInitialHarness();
    }

    function renderHarnessSelect() {
      const select = byId("harness-select");
      const filter = byId("session-harness-filter");
      select.textContent = "";
      filter.textContent = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = "All harnesses";
      filter.appendChild(all);
      for (const item of state.harnesses) {
        const spec = item.spec || {};
        const option = document.createElement("option");
        option.value = spec.id;
        option.textContent = spec.title || spec.id;
        select.appendChild(option);
        const filterOption = option.cloneNode(true);
        filter.appendChild(filterOption);
      }
      byId("harness-count").textContent = String(state.harnesses.length);
    }

    function renderHarnessCards() {
      const list = byId("harness-list");
      list.textContent = "";
      for (const item of state.harnesses) {
        const spec = item.spec || {};
        const availability = item.availability || {};
        const capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.slice(0, 3) : [];
        const extras = [];
        if (spec.supports_workspace) extras.push("workspace");
        if (spec.supports_streaming) extras.push("stream");
        const card = document.createElement("div");
        card.className = "harness-card";
        card.innerHTML = `
          <div class="session-title">${escapeHtml(spec.title || spec.id)}</div>
          <div class="session-meta">
            <span>${escapeHtml(spec.id || "")}</span>
            <span>${escapeHtml(availability.status || "unknown")}</span>
          </div>
          <div class="session-meta">
            <span>${escapeHtml(capabilities.join(", ") || "no capabilities")}</span>
          </div>
          <div class="session-meta">
            <span>${escapeHtml(extras.join(", ") || "prompt only")}</span>
          </div>
        `;
        card.addEventListener("click", () => selectHarness(spec.id));
        list.appendChild(card);
      }
    }

    function chooseInitialHarness() {
      const configDefaults = state.projectConfig && state.projectConfig.exists ? state.projectConfig.defaults || {} : {};
      const preferred = configDefaults.harness || byId("harness-select").value || "echo";
      const first = state.harnesses.find((item) => item.spec && item.spec.id === preferred) || state.harnesses[0];
      if (first && first.spec) selectHarness(first.spec.id);
    }

    function selectHarness(harnessId) {
      const item = state.harnesses.find((entry) => entry.spec && entry.spec.id === harnessId);
      if (!item) return;
      state.selectedHarness = item;
      byId("harness-select").value = harnessId;
      renderCapabilityOptions(item.spec);
      updateHarnessDrivenControls();
      const capabilities = Array.isArray(item.spec.capabilities) ? item.spec.capabilities.join(", ") : "";
      setText("harness-details", `${item.spec.title || harnessId} - ${item.spec.description || ""}${capabilities ? " Capabilities: " + capabilities : ""}`);
    }

    function renderCapabilityOptions(spec) {
      const select = byId("capability-select");
      select.textContent = "";
      const capabilities = spec.capabilities && spec.capabilities.length ? spec.capabilities : ["chat_completions"];
      for (const capability of capabilities) {
        const option = document.createElement("option");
        option.value = capability;
        option.textContent = capability;
        select.appendChild(option);
      }
    }

    function updateHarnessDrivenControls() {
      const spec = state.selectedHarness && state.selectedHarness.spec ? state.selectedHarness.spec : {};
      byId("model-input").disabled = spec.supports_model_selection === false;
      byId("model-menu-button").disabled = spec.supports_model_selection === false;
      if (spec.supports_model_selection === false) closeModelList();
      byId("api-mode-v1").disabled = spec.supports_api_mode_selection === false;
      byId("api-mode-v2").disabled = spec.supports_api_mode_selection === false;
      byId("workspace-input").disabled = spec.supports_workspace === false;
      byId("stream-checkbox").disabled = spec.supports_streaming !== true;
      byId("copy-curl-button").disabled = spec.id !== "direct-chat";
      const availability = state.selectedHarness && state.selectedHarness.availability ? state.selectedHarness.availability : {};
      const warning = availability.status === "missing" || availability.status === "error" ? availability.reason || availability.status : "";
      setText("harness-warning", warning);
    }

    async function loadSessions() {
      const params = new URLSearchParams();
      const q = byId("session-search").value.trim();
      const workspace = byId("session-workspace-filter").value.trim();
      const harness = byId("session-harness-filter").value;
      if (q) params.set("q", q);
      if (workspace) params.set("workspace", workspace);
      if (!workspace && state.project && state.project.id) params.set("project_id", state.project.id);
      if (harness) params.set("harness_id", harness);
      if (byId("include-archived-checkbox").checked) params.set("include_archived", "true");
      const result = await getJson(`/api/sessions?${params.toString()}`);
      state.sessions = result.ok ? result.data.sessions || [] : [];
      renderSessions();
    }

    function renderSessions() {
      const list = byId("session-list");
      list.textContent = "";
      byId("session-count").textContent = String(state.sessions.length);
      if (!state.sessions.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No sessions";
        list.appendChild(empty);
        return;
      }
      const groups = groupSessions(state.sessions);
      for (const [label, sessions] of groups) {
        if (!sessions.length) continue;
        const title = document.createElement("div");
        title.className = "group-title";
        title.textContent = label;
        list.appendChild(title);
        for (const session of sessions) {
          const row = document.createElement("div");
          row.className = `session-row${session.id === state.currentSessionId ? " active" : ""}`;
          row.innerHTML = `
            <div class="session-title">${escapeHtml(session.title || "Untitled session")}</div>
            <div class="session-meta">
              <span>${escapeHtml(session.default_harness_id || "")}</span>
              <span>${escapeHtml(session.default_api_mode || "")}</span>
              <span>${escapeHtml(session.last_run_status || "new")}</span>
            </div>
          `;
          row.addEventListener("click", () => loadSession(session.id));
          list.appendChild(row);
        }
      }
    }

    function groupSessions(sessions) {
      const today = new Date();
      const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const buckets = new Map([
        ["Pinned", []],
        ["Today", []],
        ["Yesterday", []],
        ["Previous 7 days", []],
        ["Older", []]
      ]);
      for (const session of sessions) {
        if (session.pinned) {
          buckets.get("Pinned").push(session);
          continue;
        }
        const updated = new Date(session.updated_at);
        const days = Math.floor((startToday - new Date(updated.getFullYear(), updated.getMonth(), updated.getDate())) / 86400000);
        const label = days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : "Older";
        buckets.get(label).push(session);
      }
      return [...buckets.entries()];
    }

    async function loadSession(sessionId) {
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}`);
      if (!result.ok) return;
      state.currentSessionId = sessionId;
      state.currentBundle = result.data;
      applySessionDefaults(result.data.session || {});
      renderAll();
      await loadSessions();
    }

    function applySessionDefaults(session) {
      if (session.default_harness_id) selectHarness(session.default_harness_id);
      byId("model-input").value = session.default_model || state.defaults.default_model || "";
      renderModelList();
      const mode = session.default_api_mode || state.defaults.default_api_mode || "v2";
      byId(`api-mode-${mode}`).checked = true;
      byId("mode-select").value = session.default_mode || "plan";
      byId("workspace-input").value = session.workspace || "";
      updateRouteNote();
    }

    async function newChat() {
      const payload = buildSessionDefaults();
      const result = await getJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (result.ok) {
        byId("prompt-input").value = "";
        await loadSession(result.data.session.id);
      }
    }

    function buildSessionDefaults() {
      return {
        harness_id: currentHarnessId(),
        model: byId("model-input").value.trim() || null,
        api_mode: currentApiMode(),
        mode: byId("mode-select").value,
        workspace: byId("workspace-input").value.trim() || null
      };
    }

    function buildPayload() {
      return {
        ...buildSessionDefaults(),
        prompt: byId("prompt-input").value,
        capability: byId("capability-select").value || "chat_completions",
        stream: byId("stream-checkbox").checked,
        dry_run: byId("dry-run-checkbox").checked
      };
    }

    async function runHarness() {
      const payload = buildPayload();
      if (!payload.prompt.trim()) return;
      state.lastPayload = payload;
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      setText("diff-panel", "No diff captured.");
      byId("run-button").disabled = true;
      byId("run-button").textContent = "Running...";
      try {
        const url = state.currentSessionId ? `/api/sessions/${encodeURIComponent(state.currentSessionId)}/run` : "/api/sessions/run";
        const result = await getJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const body = result.data || {};
        if (result.ok) {
          state.currentSessionId = body.session.id;
          state.currentBundle = body;
          byId("prompt-input").value = "";
          renderAll();
          await loadSessions();
        } else {
          setText("raw-response-panel", pretty(body));
          setText("run-panel", body.detail || `Request failed with HTTP ${result.status}`);
        }
      } finally {
        byId("run-button").disabled = false;
        byId("run-button").textContent = "Run";
      }
    }

    function renderAll() {
      renderMessages();
      renderInspector();
      renderSessions();
    }

    function renderMessages() {
      const list = byId("message-list");
      list.textContent = "";
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      if (!messages.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "New session";
        list.appendChild(empty);
        return;
      }
      for (const message of messages) {
        const item = document.createElement("article");
        item.className = `message ${message.role || "assistant"}`;
        item.innerHTML = `
          <div class="message-meta">
            <span>${escapeHtml(message.role || "")}</span>
            <span>${escapeHtml(message.harness_id || "")}</span>
            <span>${escapeHtml(message.api_mode || "")}</span>
          </div>
          <div class="message-content">${escapeHtml(message.content || "")}</div>
        `;
        list.appendChild(item);
      }
      byId("output-panel").scrollTop = byId("output-panel").scrollHeight;
    }

    function renderInspector() {
      const bundle = state.currentBundle || {};
      const session = bundle.session || null;
      const runs = Array.isArray(bundle.runs) ? bundle.runs : [];
      const events = Array.isArray(bundle.events) ? bundle.events : [];
      const rawRequests = Array.isArray(bundle.raw_requests) ? bundle.raw_requests : [];
      const rawResponses = Array.isArray(bundle.raw_responses) ? bundle.raw_responses : [];
      const run = runs[runs.length - 1] || null;
      setText("selected-session-line", session ? `${session.title} - ${session.id}` : "No session selected");
      setText("run-panel", run ? pretty(run) : "No run selected.");
      renderEvents(events);
      setText("raw-request-panel", rawRequests.length ? pretty(rawRequests[rawRequests.length - 1].payload) : "{}");
      setText("raw-response-panel", rawResponses.length ? pretty(rawResponses[rawResponses.length - 1].payload) : "{}");
      setText("command-panel", run && run.command && run.command.length ? run.command.join(" ") : commandPreview(state.lastPayload));
      const diff = run && run.metadata ? run.metadata.diff : "";
      setText("diff-panel", diff || "No diff captured.");
      setText("storage-panel", pretty(bundle.storage || {}));
      byId("pin-session-button").textContent = session && session.pinned ? "Unpin" : "Pin";
      byId("archive-session-button").textContent = session && session.archived ? "Unarchive" : "Archive";
    }

    function renderEvents(events) {
      const panel = byId("events-panel");
      panel.textContent = "";
      if (!events || !events.length) {
        panel.textContent = "No events yet.";
        return;
      }
      for (const event of events) {
        const row = document.createElement("div");
        row.className = "event-row";
        row.innerHTML = `
          <div class="badge-row">
            <span class="badge info">${escapeHtml(event.type || "event")}</span>
            <span class="hint">${escapeHtml(event.created_at || "")}</span>
          </div>
          <div>${escapeHtml(event.message || "")}</div>
          <pre>${escapeHtml(pretty(event.payload || {}))}</pre>
        `;
        panel.appendChild(row);
      }
    }

    async function patchCurrentSession(patch) {
      if (!state.currentSessionId) return;
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      });
      if (result.ok) await loadSession(state.currentSessionId);
    }

    async function deleteCurrentSession() {
      if (!state.currentSessionId) return;
      const sessionId = state.currentSessionId;
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
      if (result.ok) {
        state.currentSessionId = null;
        state.currentBundle = null;
        renderAll();
        await loadSessions();
      }
    }

    function renameCurrentSession() {
      if (!state.currentBundle || !state.currentBundle.session) return;
      const title = window.prompt("Rename session", state.currentBundle.session.title || "");
      if (title != null) patchCurrentSession({ title });
    }

    function currentHarnessId() {
      return byId("harness-select").value || "echo";
    }

    function currentApiMode() {
      return byId("api-mode-v1").checked ? "v1" : "v2";
    }

    function updateRouteNote() {
      setText("route-note", `Current route: /${currentApiMode()}/chat/completions`);
      updateHeaderBadges();
    }

    function updateHeaderBadges() {
      const model = byId("model-input").value.trim() || "unset";
      setText("current-model-badge", `Model: ${model}`);
      setText("current-route-badge", `Route: /${currentApiMode()}/chat/completions`);
    }

    function commandPreview(payload) {
      if (!payload) return "No command yet.";
      const args = ["giga", "harness", "run", payload.harness_id || "echo", "--api-mode", payload.api_mode || "v2"];
      if (payload.model) args.push("--model", payload.model);
      args.push("--prompt", payload.prompt || "");
      return args.map(shellQuote).join(" ");
    }

    function curlPreview() {
      const payload = state.lastPayload || buildPayload();
      if (payload.harness_id !== "direct-chat") return "curl is only available for direct-chat.";
      const body = {
        model: payload.model || state.defaults.default_model || "GigaChat",
        messages: [{ role: "user", content: payload.prompt || "" }],
        stream: Boolean(payload.stream)
      };
      const url = `${state.defaults.proxy_url || "http://127.0.0.1:8090"}/${payload.api_mode || "v2"}/chat/completions`;
      return [
        "curl -sS",
        shellQuote(url),
        "-H",
        shellQuote("Content-Type: application/json"),
        "-H",
        shellQuote("Authorization: Bearer <GPT2GIGA_API_KEY>"),
        "-d",
        shellQuote(JSON.stringify(body))
      ].join(" ");
    }

    async function copyText(text, status) {
      try {
        await navigator.clipboard.writeText(text);
        setText("model-status", status);
      } catch (error) {
        setText("model-status", "Clipboard unavailable.");
      }
    }

    function showTab(name) {
      for (const tab of document.querySelectorAll(".tab")) {
        tab.classList.toggle("active", tab.dataset.tab === name);
      }
      for (const panel of document.querySelectorAll(".tab-panel")) {
        panel.classList.remove("active");
      }
      const panelId = name === "run" ? "run-panel" : `${name}-panel`;
      const panel = byId(panelId);
      if (panel) panel.classList.add("active");
    }

    function resetComposer() {
      byId("prompt-input").value = "";
      byId("dry-run-checkbox").checked = false;
      byId("stream-checkbox").checked = false;
    }

    function shellQuote(value) {
      const text = String(value == null ? "" : value);
      if (/^[A-Za-z0-9_./:=@-]+$/.test(text)) return text;
      return `'${text.replace(/'/g, "'\\\\''")}'`;
    }

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function bindEvents() {
      byId("refresh-health-button").addEventListener("click", refreshHealth);
      byId("refresh-models-button").addEventListener("click", loadModels);
      byId("init-project-button").addEventListener("click", initProject);
      byId("new-chat-button").addEventListener("click", newChat);
      byId("harness-select").addEventListener("change", (event) => selectHarness(event.target.value));
      byId("api-mode-v1").addEventListener("change", () => { updateRouteNote(); loadModels(); });
      byId("api-mode-v2").addEventListener("change", () => { updateRouteNote(); loadModels(); });
      byId("model-menu-button").addEventListener("click", toggleModelList);
      byId("model-input").addEventListener("focus", openModelList);
      byId("model-input").addEventListener("input", () => {
        updateHeaderBadges();
        openModelList();
      });
      byId("model-input").addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeModelList();
        if (event.key === "ArrowDown") {
          event.preventDefault();
          openModelList();
          const first = byId("model-list").querySelector(".model-option:not(.empty)");
          if (first) first.focus();
        }
      });
      byId("model-list").addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closeModelList();
          byId("model-input").focus();
        }
      });
      document.addEventListener("click", (event) => {
        if (!byId("model-picker").contains(event.target)) closeModelList();
      });
      byId("run-button").addEventListener("click", runHarness);
      byId("reset-button").addEventListener("click", resetComposer);
      byId("copy-cli-button").addEventListener("click", () => copyText(commandPreview(state.lastPayload || buildPayload()), "Copied CLI command."));
      byId("copy-curl-button").addEventListener("click", () => copyText(curlPreview(), "Copied curl command."));
      byId("session-search").addEventListener("input", loadSessions);
      byId("session-workspace-filter").addEventListener("change", loadSessions);
      byId("session-harness-filter").addEventListener("change", loadSessions);
      byId("include-archived-checkbox").addEventListener("change", loadSessions);
      byId("rename-session-button").addEventListener("click", renameCurrentSession);
      byId("pin-session-button").addEventListener("click", () => {
        const pinned = !(state.currentBundle && state.currentBundle.session && state.currentBundle.session.pinned);
        patchCurrentSession({ pinned });
      });
      byId("archive-session-button").addEventListener("click", () => {
        const archived = !(state.currentBundle && state.currentBundle.session && state.currentBundle.session.archived);
        patchCurrentSession({ archived });
      });
      byId("delete-session-button").addEventListener("click", deleteCurrentSession);
      byId("prompt-input").addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          runHarness();
        }
      });
      for (const tab of document.querySelectorAll(".tab")) {
        tab.addEventListener("click", () => showTab(tab.dataset.tab));
      }
    }

    async function boot() {
      bindEvents();
      await loadDefaults();
      await loadProject();
      await Promise.all([loadHarnesses(), refreshHealth(), loadModels()]);
      await loadSessions();
      renderAll();
    }

    boot();
  </script>
</body>
</html>
"""
