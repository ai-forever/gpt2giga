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
      overflow-wrap: anywhere;
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
      max-width: 100%;
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
    .sidebar-heading {
      padding: 0 10px;
    }
    .session-row,
    .native-session-row,
    .harness-card {
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      padding: 8px;
      cursor: pointer;
    }
    .session-row:hover,
    .native-session-row:hover,
    .harness-card:hover,
    .session-row.active,
    .native-session-row.active {
      border-color: var(--border);
      background: var(--panel-soft);
    }
    .session-row.active,
    .native-session-row.active {
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
    .composer.drag-over {
      outline: 2px solid var(--accent);
      outline-offset: -6px;
      background: #17211f;
    }
    .attachment-toolbar,
    .attachment-list,
    .attachment-card,
    .attachment-chip-row,
    .preset-list {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .attachment-list {
      align-items: stretch;
    }
    .attachment-card {
      max-width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel-soft);
      padding: 7px 8px;
    }
    .attachment-name {
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 750;
    }
    .attachment-remove {
      min-height: 24px;
      border-color: var(--border);
      background: transparent;
      color: var(--muted);
      padding: 0 7px;
    }
    .attachment-remove:hover:not(:disabled) {
      border-color: var(--red);
      background: #2b1717;
      color: #fecaca;
    }
    .attachment-chip-row {
      margin-top: 8px;
    }
    .attachment-chip {
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .preset-list {
      align-items: stretch;
    }
    .preset-button {
      max-width: 180px;
      min-width: 70px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .workspace-file-menu {
      display: grid;
      max-height: 180px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #111418;
      padding: 4px;
    }
    .workspace-file-menu[hidden] {
      display: none;
    }
    .workspace-file-option {
      width: 100%;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--text);
      padding: 7px 8px;
      text-align: left;
      font-weight: 700;
    }
    .workspace-file-option:hover:not(:disabled) {
      background: var(--panel-strong);
      color: var(--accent-strong);
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
    .route-recommendation {
      display: grid;
      gap: 6px;
      min-height: 48px;
    }
    .tool-profile-list {
      display: grid;
      gap: 8px;
      margin: 10px 0;
    }
    .tool-profile-card {
      display: grid;
      gap: 6px;
      border: 1px solid #232830;
      border-radius: 6px;
      background: #111418;
      padding: 8px;
    }
    .tool-profile-title {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      font-weight: 800;
    }
    .tool-profile-statuses {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
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
    #native-terminal-output {
      min-height: 180px;
      margin: 10px 0;
      border: 1px solid #232830;
      border-radius: 6px;
      background: #07090b;
      padding: 8px;
    }
    #native-terminal-input {
      min-height: 70px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
        "Liberation Mono", monospace;
    }
    .native-history-modal,
    .preflight-modal {
      position: fixed;
      z-index: 80;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgb(0 0 0 / 0.58);
    }
    .native-history-modal[hidden],
    .preflight-modal[hidden] {
      display: none;
    }
    .native-history-dialog,
    .preflight-dialog {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      width: min(760px, calc(100vw - 32px));
      max-height: min(760px, calc(100vh - 48px));
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 24px 80px rgb(0 0 0 / 0.55);
      overflow: hidden;
    }
    .native-history-header,
    .native-history-footer,
    .preflight-header,
    .preflight-footer {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid var(--border);
    }
    .native-history-footer,
    .preflight-footer {
      border-top: 1px solid var(--border);
      border-bottom: 0;
    }
    .native-history-title,
    .preflight-title {
      display: grid;
      gap: 4px;
    }
    .native-session-list,
    .preflight-list {
      display: grid;
      align-content: start;
      gap: 8px;
      min-height: 0;
      overflow: auto;
      padding: 12px;
    }
    .preflight-finding {
      display: grid;
      gap: 6px;
      border: 1px solid #232830;
      border-radius: 6px;
      background: #111418;
      padding: 8px;
    }
    .preflight-budget {
      max-height: 160px;
      min-height: 120px;
      margin: 0 12px 12px;
    }
    .native-session-list .native-session-row {
      min-width: 0;
      background: var(--panel-soft);
    }
    .native-session-list .session-title,
    .native-session-list .session-meta,
    .native-session-list .badge-row {
      min-width: 0;
    }
    .native-session-list .inline-actions {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .native-session-list .inline-actions button {
      width: 100%;
      min-width: 0;
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
    .arena-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .arena-card {
      min-width: 0;
      border: 1px solid #232830;
      border-radius: 6px;
      background: #0f1216;
      padding: 10px;
    }
    .arena-card pre {
      margin-top: 8px;
      max-height: 220px;
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
        width: 100%;
        max-width: 100%;
      }
      .top-summary .badge {
        white-space: normal;
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
      .native-history-modal,
      .preflight-modal {
        align-items: stretch;
        padding: 12px;
      }
      .native-history-dialog,
      .preflight-dialog {
        width: 100%;
        max-height: calc(100vh - 24px);
      }
      .native-session-list .inline-actions {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .native-session-list .inline-actions button {
        padding-right: 6px;
        padding-left: 6px;
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
          <div class="group-title sidebar-heading">GPT2Giga chats</div>
          <div id="session-list" class="session-list"></div>
          <div class="section">
            <div class="inline-actions">
              <h2>Native sessions</h2>
              <span id="native-count" class="badge info">0</span>
              <button id="sync-native-button" class="secondary" type="button">Sync native history</button>
              <button id="open-native-history-button" class="secondary" type="button">Browse history</button>
            </div>
            <label class="choice" for="native-all-workspaces-checkbox">
              <input id="native-all-workspaces-checkbox" type="checkbox">
              Show all workspaces
            </label>
            <div id="native-status" class="status-line">Native history not synced</div>
          </div>
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
            <label class="span-2">Arena harnesses
              <select id="arena-harness-select" multiple size="4" aria-label="Arena harnesses"></select>
            </label>
            <label>Invocation
              <select id="invocation-select">
                <option value="headless">Headless</option>
                <option value="native">Native</option>
              </select>
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
            <label>Workspace policy
              <select id="workspace-policy-select">
                <option value="auto">auto</option>
                <option value="current">current</option>
                <option value="worktree">worktree</option>
                <option value="temp_copy">temp copy</option>
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
            <div id="route-recommendation" class="route-recommendation span-4">
              <div class="inline-actions">
                <span id="route-recommendation-badge" class="badge info">Recommended: pending</span>
                <button id="apply-route-recommendation-button" class="secondary" type="button" disabled>Apply recommendation</button>
              </div>
              <div id="route-recommendation-reasons" class="details">Type a prompt or attach context to refresh the recommendation.</div>
            </div>
            <div class="span-4">
              <div class="inline-actions">
                <h2>Presets</h2>
                <span id="preset-status" class="badge info">Presets: loading</span>
              </div>
              <div id="preset-list" class="preset-list"></div>
            </div>
          </div>
        </div>
        <div id="output-panel" class="chat-scroll">
          <div id="message-list" class="message-list"></div>
        </div>
        <div id="composer" class="composer">
          <label>Prompt
            <textarea id="prompt-input" spellcheck="true"></textarea>
          </label>
          <div id="workspace-file-menu" class="workspace-file-menu" hidden></div>
          <div class="attachment-toolbar">
            <input id="attachment-file-input" type="file" multiple hidden>
            <button id="attach-file-button" class="secondary" type="button">Attach</button>
            <span id="attachment-status" class="status-line">No attachments</span>
          </div>
          <div id="attachment-list" class="attachment-list" aria-live="polite"></div>
          <div class="inline-actions">
            <button id="run-button" type="button">Run</button>
            <button id="compare-button" class="secondary" type="button">Compare</button>
            <button id="cancel-run-button" class="danger" type="button" hidden>Cancel</button>
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
              <button class="tab" type="button" data-tab="arena">Arena</button>
              <button class="tab" type="button" data-tab="events">Events</button>
              <button class="tab" type="button" data-tab="raw-request">Raw request</button>
              <button class="tab" type="button" data-tab="raw-response">Raw response</button>
              <button class="tab" type="button" data-tab="command">Command</button>
              <button class="tab" type="button" data-tab="diff">Diff</button>
              <button class="tab" type="button" data-tab="pr">PR</button>
              <button class="tab" type="button" data-tab="provenance">Provenance</button>
              <button class="tab" type="button" data-tab="attachments">Attachments</button>
              <button class="tab" type="button" data-tab="memory">Memory</button>
              <button class="tab" type="button" data-tab="tools">Tools</button>
              <button class="tab" type="button" data-tab="evals">Evals</button>
              <button class="tab" type="button" data-tab="native">Native</button>
              <button class="tab" type="button" data-tab="storage">Storage</button>
            </div>
            <pre id="run-panel" class="mono-panel tab-panel active">No run selected.</pre>
            <div id="arena-panel" class="mono-panel tab-panel">No arena selected.</div>
            <div id="events-panel" class="mono-panel tab-panel">No events yet.</div>
            <pre id="raw-request-panel" class="mono-panel tab-panel">{}</pre>
            <pre id="raw-response-panel" class="mono-panel tab-panel">{}</pre>
            <pre id="command-panel" class="mono-panel tab-panel">No command yet.</pre>
            <div id="diff-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <input id="apply-branch-input" placeholder="optional branch" autocomplete="off" disabled>
                <button id="apply-run-diff-button" type="button" disabled>Apply</button>
                <button id="discard-run-worktree-button" class="danger" type="button" disabled>Discard</button>
                <button id="open-run-worktree-button" class="secondary" type="button" disabled>Open worktree</button>
              </div>
              <pre id="diff-text">No diff captured.</pre>
            </div>
            <div id="pr-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <input id="pr-branch-input" placeholder="branch name" autocomplete="off" disabled>
                <button id="copy-pr-title-button" class="secondary" type="button" disabled>Copy title</button>
                <button id="copy-pr-body-button" class="secondary" type="button" disabled>Copy body</button>
                <button id="copy-pr-patch-button" class="secondary" type="button" disabled>Copy patch</button>
                <button id="create-pr-branch-button" type="button" disabled>Create branch</button>
              </div>
              <pre id="pr-text">No PR artifact.</pre>
            </div>
            <div id="provenance-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <button id="refresh-provenance-button" class="secondary" type="button" disabled>Refresh provenance</button>
                <button id="replay-run-button" type="button" disabled>Replay</button>
                <button id="fork-run-button" class="secondary" type="button" disabled>Fork chat</button>
              </div>
              <pre id="provenance-text">No provenance selected.</pre>
            </div>
            <pre id="attachments-panel" class="mono-panel tab-panel">No attachments selected.</pre>
            <div id="memory-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <span id="memory-status" class="badge info">Memory: loading</span>
                <button id="remember-message-button" class="secondary" type="button" disabled>Remember last message</button>
              </div>
              <label>Project memory
                <textarea id="memory-input" spellcheck="true"></textarea>
              </label>
              <div class="inline-actions">
                <input id="memory-tags-input" placeholder="tags comma-separated" autocomplete="off">
                <button id="add-memory-button" type="button">Add memory</button>
              </div>
              <div id="memory-list" class="tool-profile-list"></div>
            </div>
            <div id="tools-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <span id="tools-status" class="badge info">Tools: loading</span>
                <button id="sync-tools-button" class="secondary" type="button">Dry-run sync</button>
              </div>
              <div id="tool-profile-list" class="tool-profile-list"></div>
              <pre id="tool-sync-preview">No tool sync preview.</pre>
            </div>
            <div id="evals-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <span id="evals-status" class="badge info">Evals: loading</span>
                <button id="refresh-evals-button" class="secondary" type="button">Refresh evals</button>
                <button id="run-eval-button" type="button" disabled>Run eval</button>
              </div>
              <label>Eval spec
                <select id="eval-spec-select"></select>
              </label>
              <label>Override harnesses
                <input id="eval-harness-input" placeholder="echo,codex-cli" autocomplete="off">
              </label>
              <div id="eval-spec-list" class="tool-profile-list"></div>
              <pre id="eval-scorecard">No eval run selected.</pre>
            </div>
            <div id="native-panel" class="mono-panel tab-panel">
              <div class="badge-row">
                <span id="native-terminal-status" class="badge info">Native: idle</span>
                <button id="poll-native-output-button" class="secondary" type="button">Poll output</button>
                <button id="stop-native-process-button" class="danger" type="button">Stop process</button>
                <button id="clear-native-terminal-button" class="secondary" type="button">Clear terminal</button>
              </div>
              <pre id="native-process-summary">No native session selected.</pre>
              <pre id="native-terminal-output">Terminal output will appear here.</pre>
              <label>Native stdin
                <textarea id="native-terminal-input" spellcheck="false"></textarea>
              </label>
              <div class="inline-actions">
                <button id="send-native-input-button" type="button">Send input</button>
              </div>
            </div>
            <pre id="storage-panel" class="mono-panel tab-panel">No storage selected.</pre>
          </div>
        </div>
      </aside>
    </main>
    <div id="native-history-modal" class="native-history-modal" role="dialog" aria-modal="true" aria-labelledby="native-history-title" hidden>
      <div class="native-history-dialog">
        <div class="native-history-header">
          <div class="native-history-title">
            <h2 id="native-history-title">Native sessions</h2>
            <div id="native-modal-status" class="status-line">Native history not synced</div>
          </div>
          <button id="close-native-history-button" class="secondary" type="button" aria-label="Close native history">Close</button>
        </div>
        <div id="native-session-list" class="native-session-list"></div>
        <div class="native-history-footer">
          <div id="native-page-status" class="status-line">Showing 0 of 0</div>
          <button id="load-more-native-button" class="secondary" type="button">Load 5 more</button>
        </div>
      </div>
    </div>
    <div id="preflight-modal" class="preflight-modal" role="dialog" aria-modal="true" aria-labelledby="preflight-title" hidden>
      <div class="preflight-dialog">
        <div class="preflight-header">
          <div class="preflight-title">
            <h2 id="preflight-title">Preflight</h2>
            <div id="preflight-status" class="status-line">Checking run context</div>
          </div>
          <button id="close-preflight-button" class="secondary" type="button" aria-label="Close preflight">Close</button>
        </div>
        <div id="preflight-finding-list" class="preflight-list"></div>
        <pre id="preflight-budget" class="mono-panel preflight-budget">No preflight report.</pre>
        <div class="preflight-footer">
          <div id="preflight-footer-status" class="status-line">Review findings before running.</div>
          <button id="continue-preflight-button" type="button">Continue anyway</button>
        </div>
      </div>
    </div>
  </div>

  <script>
    const NATIVE_SESSION_PAGE_SIZE = 5;
    const state = {
      defaults: {},
      harnesses: [],
      sessions: [],
      models: [],
      modelSource: "",
      project: null,
      projectConfig: null,
      projectState: null,
      projectPresets: [],
      projectMemory: [],
      memoryError: null,
      toolProfiles: [],
      toolSyncPreview: null,
      toolError: null,
      evalSpecs: [],
      evalRuns: [],
      evalErrors: [],
      currentEvalRun: null,
      evalError: null,
      applyingProjectState: false,
      selectedHarness: null,
      arenaSelectionTouched: false,
      nativeSessions: [],
      nativeVisibleLimit: NATIVE_SESSION_PAGE_SIZE,
      nativeModalOpen: false,
      preflightModalOpen: false,
      preflightDecisionResolver: null,
      pendingPreflight: null,
      pendingPreflightPayload: null,
      selectedNativeRefId: null,
      nativePreview: null,
      activeNativeProcess: null,
      nativeOutputCursor: 0,
      nativeTerminalText: "",
      nativePollTimer: null,
      attachments: [],
      fileMentionQuery: null,
      currentSessionId: null,
      currentBundle: null,
      currentArena: null,
      activeHeadlessRun: null,
      headlessEventSource: null,
      routeRecommendation: null,
      routeRecommendationTimer: null,
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
      state.projectState = result.data.state || null;
      state.projectPresets = Array.isArray(result.data.presets) ? result.data.presets : [];
      state.projectMemory = [];
      state.memoryError = null;
      state.toolProfiles = [];
      state.toolSyncPreview = null;
      state.toolError = null;
      state.evalSpecs = [];
      state.evalRuns = [];
      state.evalErrors = [];
      state.currentEvalRun = null;
      state.evalError = null;
      applyProject();
      await loadMemory();
      await loadTools();
      await loadEvals();
    }

    function applyProject() {
      const project = state.project || {};
      const config = state.projectConfig || {};
      const projectState = state.projectState || {};
      state.applyingProjectState = true;
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
        byId("model-input").value = projectState.last_model || config.defaults.model || byId("model-input").value;
        byId("mode-select").value = projectState.last_run_mode || config.defaults.mode || "plan";
        const mode = projectState.last_api_mode || config.defaults.api_mode || "v2";
        const apiMode = byId(`api-mode-${mode}`);
        if (apiMode) apiMode.checked = true;
      } else {
        if (projectState.last_model) byId("model-input").value = projectState.last_model;
        if (projectState.last_run_mode) byId("mode-select").value = projectState.last_run_mode;
        if (projectState.last_api_mode) {
          const apiMode = byId(`api-mode-${projectState.last_api_mode}`);
          if (apiMode) apiMode.checked = true;
        }
      }
      if (projectState.last_invocation_mode) byId("invocation-select").value = projectState.last_invocation_mode;
      updateRouteNote();
      renderPresetButtons();
      state.applyingProjectState = false;
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
      state.projectState = result.data.state || null;
      state.projectPresets = Array.isArray(result.data.presets) ? result.data.presets : [];
      state.projectMemory = [];
      state.memoryError = null;
      state.toolProfiles = [];
      state.toolSyncPreview = null;
      state.toolError = null;
      state.evalSpecs = [];
      state.evalRuns = [];
      state.evalErrors = [];
      state.currentEvalRun = null;
      state.evalError = null;
      applyProject();
      await loadMemory();
      await loadTools();
      await loadEvals();
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
      persistProjectState();
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
      scheduleRouteRecommendation();
    }

    function renderHarnessSelect() {
      const select = byId("harness-select");
      const arenaSelect = byId("arena-harness-select");
      const filter = byId("session-harness-filter");
      select.textContent = "";
      arenaSelect.textContent = "";
      state.arenaSelectionTouched = false;
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
        const arenaOption = option.cloneNode(true);
        arenaSelect.appendChild(arenaOption);
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
        const recommended = state.routeRecommendation && state.routeRecommendation.harness_id === spec.id;
        const card = document.createElement("div");
        card.className = "harness-card";
        card.innerHTML = `
          <div class="session-title">${escapeHtml(spec.title || spec.id)}</div>
          <div class="session-meta">
            <span>${escapeHtml(spec.id || "")}</span>
            <span>${escapeHtml(availability.status || "unknown")}</span>
            ${recommended ? '<span class="badge ok">Recommended</span>' : ''}
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
      const projectState = state.projectState || {};
      const preferred = projectState.last_harness || configDefaults.harness || byId("harness-select").value || "echo";
      const first = state.harnesses.find((item) => item.spec && item.spec.id === preferred) || state.harnesses[0];
      if (first && first.spec) {
        byId("invocation-select").value = projectState.last_invocation_mode || first.spec.default_invocation_mode || "headless";
      }
      if (first && first.spec) selectHarness(first.spec.id);
    }

    function selectHarness(harnessId) {
      const item = state.harnesses.find((entry) => entry.spec && entry.spec.id === harnessId);
      if (!item) return;
      state.selectedHarness = item;
      byId("harness-select").value = harnessId;
      ensureArenaSelection(harnessId);
      renderCapabilityOptions(item.spec);
      updateHarnessDrivenControls();
      renderAttachments();
      const capabilities = Array.isArray(item.spec.capabilities) ? item.spec.capabilities.join(", ") : "";
      setText("harness-details", `${item.spec.title || harnessId} - ${item.spec.description || ""}${capabilities ? " Capabilities: " + capabilities : ""}`);
      renderRouteRecommendation(state.routeRecommendation);
      loadNativeSessions(false);
      persistProjectState();
    }

    function ensureArenaSelection(harnessId) {
      if (state.arenaSelectionTouched) return;
      const select = byId("arena-harness-select");
      for (const option of select.options) {
        option.selected = option.value === harnessId;
      }
    }

    function arenaSelectedHarnessIds() {
      return Array.from(byId("arena-harness-select").selectedOptions)
        .map((option) => option.value)
        .filter(Boolean);
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
      const invocation = byId("invocation-select");
      const supportsNative = spec.supports_native_sessions === true;
      invocation.disabled = !supportsNative;
      if (!supportsNative) {
        invocation.value = "headless";
      } else if (!invocation.value) {
        invocation.value = spec.default_invocation_mode || "native";
      }
      byId("model-input").disabled = spec.supports_model_selection === false;
      byId("model-menu-button").disabled = spec.supports_model_selection === false;
      if (spec.supports_model_selection === false) closeModelList();
      byId("api-mode-v1").disabled = spec.supports_api_mode_selection === false;
      byId("api-mode-v2").disabled = spec.supports_api_mode_selection === false;
      byId("workspace-input").disabled = spec.supports_workspace === false;
      byId("stream-checkbox").disabled = spec.supports_streaming !== true || currentInvocationMode() === "native";
      byId("copy-curl-button").disabled = spec.id !== "direct-chat";
      const availability = state.selectedHarness && state.selectedHarness.availability ? state.selectedHarness.availability : {};
      const warning = availability.status === "missing" || availability.status === "error" ? availability.reason || availability.status : "";
      setText("harness-warning", warning);
      byId("run-button").textContent = currentInvocationMode() === "native" && supportsNative ? "Start native" : "Run";
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

    async function loadNativeSessions(sync, options = {}) {
      if (sync || options.resetVisible) resetNativeVisibleLimit();
      const showAllWorkspaces = byId("native-all-workspaces-checkbox").checked;
      const workspace = showAllWorkspaces ? "" : byId("session-workspace-filter").value.trim() || byId("workspace-input").value.trim();
      const includeExternal = true;
      if (sync) {
        const payload = {
          workspace: showAllWorkspaces ? null : workspace || null,
          include_external: includeExternal
        };
        const synced = await getJson("/api/native/sessions/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!synced.ok) {
          state.nativeSessions = [];
          renderNativeSessions(synced.data.detail || "Native history sync failed.");
          if (options.openModal) openNativeHistory(false);
          return;
        }
        const errors = Array.isArray(synced.data.errors) ? synced.data.errors : [];
        if (errors.length) {
          setText("native-status", `Native sync completed with ${errors.length} warning${errors.length === 1 ? "" : "s"}.`);
        }
      }
      const params = new URLSearchParams({ include_external: "true" });
      if (!showAllWorkspaces && workspace) params.set("workspace", workspace);
      if (!showAllWorkspaces && !workspace && state.project && state.project.id) params.set("project_id", state.project.id);
      const result = await getJson(`/api/native/sessions?${params.toString()}`);
      if (!result.ok) {
        state.nativeSessions = [];
        renderNativeSessions(result.data.detail || "Native history unavailable.");
        if (options.openModal) openNativeHistory(false);
        return;
      }
      state.nativeSessions = result.data.sessions || [];
      renderNativeSessions();
      if (options.openModal) openNativeHistory(false);
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

    function renderNativeSessions(error) {
      const list = byId("native-session-list");
      list.textContent = "";
      byId("native-count").textContent = String(state.nativeSessions.length);
      if (error) {
        setText("native-status", error);
        setText("native-modal-status", error);
      } else {
        const status = state.nativeSessions.length ? "Native history loaded" : "No native sessions cached";
        setText("native-status", status);
        setText("native-modal-status", status);
      }
      const visibleLimit = Math.min(state.nativeVisibleLimit, state.nativeSessions.length);
      setText("native-page-status", `Showing ${visibleLimit} of ${state.nativeSessions.length}`);
      const loadMoreButton = byId("load-more-native-button");
      loadMoreButton.disabled = !state.nativeSessions.length || visibleLimit >= state.nativeSessions.length;
      loadMoreButton.textContent = visibleLimit >= state.nativeSessions.length ? "All loaded" : "Load 5 more";
      if (!state.nativeSessions.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = error || "No native sessions";
        list.appendChild(empty);
        return;
      }
      const groups = groupByHarness(state.nativeSessions.slice(0, visibleLimit));
      for (const [harnessId, sessions] of groups) {
        const title = document.createElement("div");
        title.className = "group-title sidebar-heading";
        title.textContent = harnessTitle(harnessId);
        list.appendChild(title);
        for (const ref of sessions) {
          list.appendChild(nativeSessionRow(ref));
        }
      }
    }

    function nativeSessionRow(ref) {
      const row = document.createElement("div");
      row.className = `native-session-row${ref.id === state.selectedNativeRefId ? " active" : ""}`;
      const status = nativeStatusLabel(ref.status);
      row.innerHTML = `
        <div class="session-title">${escapeHtml(ref.title || "Untitled native session")}</div>
        <div class="session-meta">
          <span>${escapeHtml(ref.harness_id || "")}</span>
          <span>${escapeHtml(status)}</span>
          <span>${escapeHtml(ref.can_resume ? "resumable" : ref.can_import ? "importable" : "readonly")}</span>
        </div>
        <div class="badge-row">
          ${nativeBadge(ref.status)}
          ${ref.can_resume ? '<span class="badge ok">resumable</span>' : ''}
          ${ref.can_import ? '<span class="badge info">importable</span>' : ''}
        </div>
      `;
      row.addEventListener("click", () => selectNativeSession(ref.id));
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      actions.appendChild(nativeActionButton("Preview", () => previewNativeSession(ref.id), !ref.can_preview));
      actions.appendChild(nativeActionButton("Import", () => importNativeSession(ref.id), !ref.can_import));
      actions.appendChild(nativeActionButton("Link to current chat", () => linkNativeSession(ref.id), !state.currentSessionId));
      actions.appendChild(nativeActionButton("Resume native", () => resumeNativeSession(ref.id), !ref.can_resume));
      row.appendChild(actions);
      return row;
    }

    function resetNativeVisibleLimit() {
      state.nativeVisibleLimit = NATIVE_SESSION_PAGE_SIZE;
    }

    function loadMoreNativeSessions() {
      state.nativeVisibleLimit = Math.min(
        state.nativeVisibleLimit + NATIVE_SESSION_PAGE_SIZE,
        state.nativeSessions.length
      );
      renderNativeSessions();
    }

    function openNativeHistory(resetVisible = true) {
      if (resetVisible) resetNativeVisibleLimit();
      state.nativeModalOpen = true;
      byId("native-history-modal").hidden = false;
      renderNativeSessions();
      byId("close-native-history-button").focus();
    }

    function closeNativeHistory() {
      state.nativeModalOpen = false;
      byId("native-history-modal").hidden = true;
    }

    function nativeActionButton(label, handler, disabled) {
      const button = document.createElement("button");
      button.className = "secondary";
      button.type = "button";
      button.textContent = label;
      button.disabled = Boolean(disabled);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        closeNativeHistory();
        handler();
      });
      return button;
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

    function groupByHarness(refs) {
      const buckets = new Map();
      for (const ref of refs) {
        const harnessId = ref.harness_id || "unknown";
        if (!buckets.has(harnessId)) buckets.set(harnessId, []);
        buckets.get(harnessId).push(ref);
      }
      return [...buckets.entries()];
    }

    function harnessTitle(harnessId) {
      const item = state.harnesses.find((entry) => entry.spec && entry.spec.id === harnessId);
      return item && item.spec && item.spec.title ? item.spec.title : harnessId;
    }

    function nativeStatusLabel(status) {
      const value = String(status || "readonly");
      if (value === "managed_native") return "managed";
      if (value === "external_native") return "external";
      return value;
    }

    function nativeBadge(status) {
      const label = nativeStatusLabel(status);
      const className = label === "managed" || label === "linked" || label === "imported" ? "ok" : label === "external" ? "warn" : "info";
      return `<span class="badge ${className}">${escapeHtml(label)}</span>`;
    }

    function selectNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const ref = state.nativeSessions.find((item) => item.id === refId);
      setNativeSummary(ref ? pretty(ref) : "No native session selected.");
      renderNativeSessions();
      showTab("native");
    }

    async function previewNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const result = await getJson(`/api/native/sessions/${encodeURIComponent(refId)}/preview`);
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native preview failed.");
        showTab("native");
        return;
      }
      state.nativePreview = result.data;
      setNativeSummary(pretty(result.data));
      renderNativeSessions();
      showTab("native");
    }

    async function importNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const result = await getJson(`/api/native/sessions/${encodeURIComponent(refId)}/import`, { method: "POST" });
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native import failed.");
        showTab("native");
        return;
      }
      setNativeSummary(pretty(result.data));
      if (result.data.session && result.data.session.id) {
        await loadSession(result.data.session.id);
      }
      await loadNativeSessions(false);
      showTab("native");
    }

    async function linkNativeSession(refId) {
      state.selectedNativeRefId = refId;
      if (!state.currentSessionId) {
        setNativeSummary("Select a GPT2Giga chat before linking a native session.");
        showTab("native");
        return;
      }
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/native/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ native_ref_id: refId })
      });
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native link failed.");
        showTab("native");
        return;
      }
      setNativeSummary(pretty(result.data));
      await loadSession(state.currentSessionId);
      showTab("native");
    }

    async function resumeNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const ref = state.nativeSessions.find((item) => item.id === refId);
      if (!ref) return;
      if (!(await ensureSessionForNative({
        harness_id: ref.harness_id,
        model: byId("model-input").value.trim() || null,
        api_mode: currentApiMode(),
        mode: byId("mode-select").value,
        workspace: ref.workspace || byId("workspace-input").value.trim() || null
      }))) return;
      setNativeSummary("Resuming native session...");
      showTab("native");
      const result = await getJson("/api/native/processes/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.currentSessionId,
          action: "resume",
          native_ref_id: refId,
          workspace: ref.workspace || byId("workspace-input").value.trim() || null
        })
      });
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native resume failed.");
        return;
      }
      setActiveNativeProcess(result.data.process || null, result.data);
      await loadSession(state.currentSessionId);
      showTab("native");
    }

    async function loadSession(sessionId) {
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}`);
      if (!result.ok) return;
      state.currentSessionId = sessionId;
      state.currentBundle = result.data;
      if (state.currentArena && state.currentArena.session_id !== sessionId) state.currentArena = null;
      await loadAttachments(sessionId);
      applySessionDefaults(result.data.session || {});
      persistProjectState({ last_selected_session: sessionId });
      renderAll();
      await loadSessions();
    }

    async function loadAttachments(sessionId) {
      if (!sessionId) {
        state.attachments = [];
        renderAttachments();
        return;
      }
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}/attachments`);
      state.attachments = result.ok && Array.isArray(result.data.attachments) ? result.data.attachments : [];
      renderAttachments();
    }

    async function ensureSessionForAttachments() {
      if (state.currentSessionId) return true;
      const result = await getJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildSessionDefaults())
      });
      if (!result.ok || !result.data.session) {
        setText("attachment-status", result.data.detail || "Attachment session failed.");
        return false;
      }
      await loadSession(result.data.session.id);
      return true;
    }

    async function attachFiles(files, source) {
      const fileList = Array.from(files || []).filter(Boolean);
      if (!fileList.length) return;
      if (!(await ensureSessionForAttachments())) return;
      setText("attachment-status", `Uploading ${fileList.length}...`);
      for (const file of fileList) {
        try {
          const dataBase64 = await readFileAsBase64(file);
          const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/attachments`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              filename: file.name || "clipboard-image.png",
              mime_type: file.type || null,
              data_base64: dataBase64,
              source
            })
          });
          if (result.ok && result.data.attachment) {
            state.attachments.push(result.data.attachment);
          } else {
            setText("attachment-status", result.data.detail || "Attachment upload failed.");
          }
        } catch (error) {
          setText("attachment-status", "Attachment upload failed.");
        }
      }
      renderAttachments();
      await loadSessions();
    }

    function readFileAsBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const value = String(reader.result || "");
          resolve(value.includes(",") ? value.split(",", 2)[1] : value);
        };
        reader.onerror = () => reject(reader.error || new Error("file read failed"));
        reader.readAsDataURL(file);
      });
    }

    async function removeAttachment(attachmentId) {
      const result = await getJson(`/api/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" });
      if (!result.ok) {
        setText("attachment-status", result.data.detail || "Attachment delete failed.");
        return;
      }
      state.attachments = state.attachments.filter((attachment) => attachment.id !== attachmentId);
      renderAttachments();
    }

    async function searchWorkspaceFiles() {
      const query = currentFileMentionQuery();
      state.fileMentionQuery = query;
      if (query == null) {
        hideWorkspaceFileMenu();
        return;
      }
      const workspace = byId("workspace-input").value.trim() || ".";
      const params = new URLSearchParams({ workspace, q: query, limit: "20" });
      const result = await getJson(`/api/workspace/tree?${params.toString()}`);
      if (state.fileMentionQuery !== query) return;
      if (!result.ok) {
        renderWorkspaceFileMenu([], result.data.detail || "Workspace search failed.");
        return;
      }
      renderWorkspaceFileMenu(result.data.files || [], "");
    }

    function currentFileMentionQuery() {
      const input = byId("prompt-input");
      const beforeCursor = input.value.slice(0, input.selectionStart || 0);
      const match = beforeCursor.match(/(?:^|\\s)@([^\\s@]*)$/);
      return match ? match[1] : null;
    }

    function renderWorkspaceFileMenu(files, error) {
      const menu = byId("workspace-file-menu");
      menu.textContent = "";
      if (error) {
        const item = document.createElement("button");
        item.className = "workspace-file-option";
        item.type = "button";
        item.disabled = true;
        item.textContent = error;
        menu.appendChild(item);
        menu.hidden = false;
        return;
      }
      if (!files.length) {
        hideWorkspaceFileMenu();
        return;
      }
      for (const file of files) {
        const item = document.createElement("button");
        item.className = "workspace-file-option";
        item.type = "button";
        item.textContent = `${file.path} (${formatBytes(file.size_bytes || 0)})`;
        item.addEventListener("click", () => attachWorkspaceFile(file.path));
        menu.appendChild(item);
      }
      menu.hidden = false;
    }

    function hideWorkspaceFileMenu() {
      const menu = byId("workspace-file-menu");
      if (menu) {
        menu.textContent = "";
        menu.hidden = true;
      }
    }

    async function attachWorkspaceFile(path) {
      if (!(await ensureSessionForAttachments())) return;
      const workspace = byId("workspace-input").value.trim() || ".";
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/attachments/workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace, path })
      });
      if (!result.ok || !result.data.attachment) {
        setText("attachment-status", result.data.detail || "Workspace attachment failed.");
        return;
      }
      state.attachments.push(result.data.attachment);
      replaceCurrentFileMention(path);
      hideWorkspaceFileMenu();
      renderAttachments();
      await loadSessions();
    }

    function replaceCurrentFileMention(path) {
      const input = byId("prompt-input");
      const start = input.selectionStart || 0;
      const beforeCursor = input.value.slice(0, start);
      const afterCursor = input.value.slice(input.selectionEnd || start);
      const replaced = beforeCursor.replace(/(?:^|\\s)@([^\\s@]*)$/, (match) => {
        const prefix = match.startsWith("@") ? "" : match.slice(0, 1);
        return `${prefix}@${path} `;
      });
      input.value = replaced + afterCursor;
      input.focus();
      input.selectionStart = input.selectionEnd = replaced.length;
    }

    function renderAttachments() {
      const list = byId("attachment-list");
      if (!list) return;
      list.textContent = "";
      if (!state.attachments.length) {
        setText("attachment-status", "No attachments");
        scheduleRouteRecommendation();
        return;
      }
      setText("attachment-status", `${state.attachments.length} attachment${state.attachments.length === 1 ? "" : "s"}`);
      for (const attachment of state.attachments) {
        const card = document.createElement("div");
        card.className = "attachment-card";
        const warning = attachmentWarning(attachment);
        card.innerHTML = `
          <span class="attachment-name">${escapeHtml(attachment.filename || attachment.id)}</span>
          <span class="badge info">${escapeHtml(attachment.kind || "attachment")}</span>
          <span class="status-line">${escapeHtml(attachment.mime_type || "")} ${escapeHtml(formatBytes(attachment.size_bytes || 0))}</span>
          ${warning ? `<span class="badge warn">${escapeHtml(warning)}</span>` : ""}
        `;
        const remove = document.createElement("button");
        remove.className = "attachment-remove";
        remove.type = "button";
        remove.textContent = "x";
        remove.addEventListener("click", () => removeAttachment(attachment.id));
        card.appendChild(remove);
        list.appendChild(card);
      }
      scheduleRouteRecommendation();
    }

    function attachmentWarning(attachment) {
      const harnessId = currentHarnessId();
      const supported = attachment.supported_by || {};
      if (Object.prototype.hasOwnProperty.call(supported, harnessId) && !supported[harnessId]) {
        const warning = (attachment.warnings || []).find((item) => String(item).startsWith(`${harnessId} `));
        return warning || `${harnessId} does not accept this attachment`;
      }
      if (attachment.kind === "image" && harnessId === "gemini-cli") {
        return "path reference only";
      }
      return "";
    }

    function formatBytes(value) {
      const bytes = Number(value) || 0;
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
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
        state.attachments = [];
        renderAttachments();
        await loadSession(result.data.session.id);
      }
    }

    function buildSessionDefaults() {
      return {
        harness_id: currentHarnessId(),
        model: byId("model-input").value.trim() || null,
        api_mode: currentApiMode(),
        mode: byId("mode-select").value,
        workspace_policy: byId("workspace-policy-select").value || "auto",
        workspace: byId("workspace-input").value.trim() || null
      };
    }

    function buildPayload() {
      const payload = {
        ...buildSessionDefaults(),
        prompt: byId("prompt-input").value,
        capability: byId("capability-select").value || "chat_completions",
        invocation_mode: currentInvocationMode(),
        stream: byId("stream-checkbox").checked,
        dry_run: byId("dry-run-checkbox").checked
      };
      const attachmentIds = state.attachments.map((attachment) => attachment.id).filter(Boolean);
      if (attachmentIds.length) payload.attachment_ids = attachmentIds;
      return payload;
    }

    function buildArenaPayload() {
      const payload = {
        ...buildSessionDefaults(),
        prompt: byId("prompt-input").value,
        harness_ids: arenaSelectedHarnessIds(),
        session_id: state.currentSessionId || null
      };
      const attachmentIds = state.attachments.map((attachment) => attachment.id).filter(Boolean);
      if (attachmentIds.length) payload.attachment_ids = attachmentIds;
      return payload;
    }

    function buildRecommendationPayload() {
      const attachments = state.attachments.map((attachment) => ({
        id: attachment.id,
        kind: attachment.kind,
        filename: attachment.filename,
        mime_type: attachment.mime_type,
        size_bytes: attachment.size_bytes,
        workspace_path: attachment.workspace_path || null,
        source: attachment.source || null,
        metadata: attachment.metadata || {}
      }));
      return {
        prompt: byId("prompt-input").value,
        mode: byId("mode-select").value,
        workspace: byId("workspace-input").value.trim() || null,
        current_harness_id: currentHarnessId(),
        attachments,
        selected_files: attachments.map((attachment) => attachment.workspace_path).filter(Boolean)
      };
    }

    function scheduleRouteRecommendation() {
      if (state.routeRecommendationTimer) clearTimeout(state.routeRecommendationTimer);
      state.routeRecommendationTimer = window.setTimeout(refreshRouteRecommendation, 250);
    }

    async function refreshRouteRecommendation() {
      if (!state.harnesses.length) return;
      const payload = buildRecommendationPayload();
      if (!payload.prompt.trim() && !payload.attachments.length && !payload.workspace) {
        state.routeRecommendation = null;
        renderRouteRecommendation(null);
        return;
      }
      const result = await getJson("/api/route/recommendation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!result.ok || !result.data.recommendation) {
        state.routeRecommendation = null;
        setText("route-recommendation-badge", "Recommended: unavailable");
        byId("route-recommendation-badge").className = "badge warn";
        setText("route-recommendation-reasons", result.data.detail || "Recommendation failed.");
        byId("apply-route-recommendation-button").disabled = true;
        renderHarnessCards();
        return;
      }
      state.routeRecommendation = result.data.recommendation;
      renderRouteRecommendation(state.routeRecommendation);
    }

    function renderRouteRecommendation(recommendation) {
      const badge = byId("route-recommendation-badge");
      const applyButton = byId("apply-route-recommendation-button");
      if (!recommendation) {
        badge.className = "badge info";
        badge.textContent = "Recommended: pending";
        setText("route-recommendation-reasons", "Type a prompt or attach context to refresh the recommendation.");
        applyButton.disabled = true;
        renderHarnessCards();
        return;
      }
      const current = recommendation.harness_id === currentHarnessId()
        && recommendation.mode === byId("mode-select").value
        && recommendation.invocation_mode === currentInvocationMode();
      badge.className = current ? "badge ok" : "badge info";
      const confidence = Math.round(Number(recommendation.confidence || 0) * 100);
      badge.textContent = `Recommended: ${harnessTitle(recommendation.harness_id)} (${confidence}%)`;
      const reasons = Array.isArray(recommendation.reasons) ? recommendation.reasons : [];
      const warnings = Array.isArray(recommendation.warnings) ? recommendation.warnings : [];
      const lines = [
        ...reasons.map((reason) => `- ${reason}`),
        ...warnings.map((warning) => `! ${warning}`)
      ];
      setText("route-recommendation-reasons", lines.join("\\n") || "No recommendation details.");
      applyButton.disabled = current;
      renderHarnessCards();
    }

    function applyRouteRecommendation() {
      const recommendation = state.routeRecommendation;
      if (!recommendation || !recommendation.harness_id) return;
      selectHarness(recommendation.harness_id);
      if (recommendation.mode && byId("mode-select").querySelector(`option[value="${recommendation.mode}"]`)) {
        byId("mode-select").value = recommendation.mode;
      }
      if (recommendation.invocation_mode) {
        byId("invocation-select").value = recommendation.invocation_mode;
      }
      updateHarnessDrivenControls();
      renderRouteRecommendation(recommendation);
      persistProjectState();
    }

    function renderPresetButtons() {
      const list = byId("preset-list");
      list.textContent = "";
      const presets = Array.isArray(state.projectPresets) ? state.projectPresets : [];
      setText("preset-status", presets.length ? `Presets: ${presets.length}` : "Presets: none");
      if (!presets.length) {
        const empty = document.createElement("span");
        empty.className = "status-line";
        empty.textContent = "No project presets configured.";
        list.appendChild(empty);
        return;
      }
      for (const preset of presets) {
        const button = document.createElement("button");
        button.className = "secondary preset-button";
        button.type = "button";
        button.textContent = preset.title || preset.name;
        button.title = preset.name || preset.title || "preset";
        button.addEventListener("click", () => applyPreset(preset.name));
        list.appendChild(button);
      }
    }

    async function applyPreset(presetName) {
      if (!presetName || !state.project || !state.project.root) return;
      const result = await getJson(`/api/project/presets/${encodeURIComponent(presetName)}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: state.project.root,
          user_prompt: byId("prompt-input").value,
          selected_files: selectedWorkspaceFiles(),
          last_run_diff: currentLastDiff()
        })
      });
      const body = result.data || {};
      if (!result.ok || !body.preset) {
        setText("preset-status", body.detail || "Preset failed.");
        return;
      }
      const preset = body.preset;
      if (preset.harness) selectHarness(preset.harness);
      if (preset.model) {
        byId("model-input").value = preset.model;
        renderModelList();
      }
      if (preset.api_mode) {
        const apiMode = byId(`api-mode-${preset.api_mode}`);
        if (apiMode) apiMode.checked = true;
      }
      if (preset.mode && byId("mode-select").querySelector(`option[value="${preset.mode}"]`)) {
        byId("mode-select").value = preset.mode;
      }
      if (preset.invocation_mode) byId("invocation-select").value = preset.invocation_mode;
      if (preset.workspace_policy && byId("workspace-policy-select").querySelector(`option[value="${preset.workspace_policy}"]`)) {
        byId("workspace-policy-select").value = preset.workspace_policy;
      }
      byId("prompt-input").value = preset.prompt || "";
      updateHeaderBadges();
      updateRouteNote();
      updateHarnessDrivenControls();
      scheduleRouteRecommendation();
      persistProjectState();
      const warnings = Array.isArray(preset.warnings) && preset.warnings.length ? ` (${preset.warnings.length} warning)` : "";
      setText("preset-status", `Preset: ${preset.title || preset.name}${warnings}`);
    }

    async function loadMemory() {
      if (!state.project || !state.project.root) {
        state.projectMemory = [];
        state.memoryError = null;
        renderMemoryPanel();
        return;
      }
      const result = await getJson(`/api/project/memory?workspace=${encodeURIComponent(state.project.root)}&include_disabled=true`);
      if (!result.ok) {
        state.projectMemory = [];
        state.memoryError = result.data.detail || "Memory unavailable";
        renderMemoryPanel();
        return;
      }
      state.projectMemory = Array.isArray(result.data.memories) ? result.data.memories : [];
      state.memoryError = null;
      renderMemoryPanel();
    }

    async function addMemoryFromInput() {
      if (!state.project || !state.project.root) return;
      const text = byId("memory-input").value.trim();
      if (!text) return;
      const result = await getJson("/api/project/memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: state.project.root,
          text,
          tags: memoryTagsFromInput(),
          source_session_id: state.currentSessionId || null,
          source_run_id: currentRun() && currentRun().id ? currentRun().id : null
        })
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory add failed.";
        renderMemoryPanel();
        return;
      }
      byId("memory-input").value = "";
      byId("memory-tags-input").value = "";
      await loadMemory();
      showTab("memory");
    }

    async function rememberLastMessage() {
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      const message = [...messages].reverse().find((item) => item.content);
      if (!message) return;
      byId("memory-input").value = message.content || "";
      byId("memory-tags-input").value = "message";
      await addMemoryFromInput();
    }

    async function setMemoryEnabled(memoryId, enabled) {
      if (!state.project || !state.project.root || !memoryId) return;
      const result = await getJson(`/api/project/memory/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, enabled })
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory update failed.";
        renderMemoryPanel();
        return;
      }
      await loadMemory();
    }

    async function editMemory(memoryId) {
      const memory = state.projectMemory.find((item) => item.id === memoryId);
      if (!memory || !state.project || !state.project.root) return;
      const text = window.prompt("Edit memory", memory.text || "");
      if (text == null) return;
      const result = await getJson(`/api/project/memory/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, text })
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory edit failed.";
        renderMemoryPanel();
        return;
      }
      await loadMemory();
    }

    async function deleteMemory(memoryId) {
      if (!state.project || !state.project.root || !memoryId) return;
      const params = new URLSearchParams({ workspace: state.project.root });
      const result = await getJson(`/api/project/memory/${encodeURIComponent(memoryId)}?${params.toString()}`, {
        method: "DELETE"
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory delete failed.";
        renderMemoryPanel();
        return;
      }
      await loadMemory();
    }

    function memoryTagsFromInput() {
      return byId("memory-tags-input").value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function renderMemoryPanel() {
      const list = byId("memory-list");
      if (!list) return;
      list.textContent = "";
      const memories = Array.isArray(state.projectMemory) ? state.projectMemory : [];
      const enabledCount = memories.filter((memory) => memory.enabled !== false).length;
      setText("memory-status", state.memoryError || (memories.length ? `Memory: ${enabledCount}/${memories.length} enabled` : "Memory: none"));
      byId("remember-message-button").disabled = !lastPromotableMessage();
      if (state.memoryError) {
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = state.memoryError;
        list.appendChild(error);
        return;
      }
      if (!memories.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No project memory saved.";
        list.appendChild(empty);
        return;
      }
      for (const memory of memories) {
        list.appendChild(memoryCard(memory));
      }
    }

    function memoryCard(memory) {
      const card = document.createElement("div");
      card.className = "tool-profile-card";
      const tags = Array.isArray(memory.tags) && memory.tags.length ? memory.tags.join(", ") : "untagged";
      const enabled = memory.enabled !== false;
      card.innerHTML = `
        <div class="tool-profile-title">
          <span>${escapeHtml(memory.id || "memory")}</span>
          <span class="${enabled ? "badge ok" : "badge"}">${enabled ? "enabled" : "disabled"}</span>
          <span class="badge info">${escapeHtml(tags)}</span>
        </div>
        <div class="details">${escapeHtml(memory.text || "")}</div>
      `;
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      actions.appendChild(memoryActionButton(enabled ? "Disable" : "Enable", () => setMemoryEnabled(memory.id, !enabled)));
      actions.appendChild(memoryActionButton("Edit", () => editMemory(memory.id)));
      actions.appendChild(memoryActionButton("Delete", () => deleteMemory(memory.id), "danger"));
      card.appendChild(actions);
      return card;
    }

    function memoryActionButton(label, handler, className = "secondary") {
      const button = document.createElement("button");
      button.className = className;
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    }

    function lastPromotableMessage() {
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      return [...messages].reverse().find((item) => item.content);
    }

    async function loadTools() {
      if (!state.project || !state.project.root) {
        state.toolProfiles = [];
        state.toolSyncPreview = null;
        state.toolError = null;
        renderToolsPanel();
        return;
      }
      const result = await getJson(`/api/tools?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        state.toolProfiles = [];
        state.toolSyncPreview = null;
        state.toolError = result.data.detail || "Tools unavailable";
        renderToolsPanel();
        return;
      }
      state.toolProfiles = Array.isArray(result.data.profiles) ? result.data.profiles : [];
      state.toolSyncPreview = null;
      state.toolError = null;
      renderToolsPanel();
    }

    async function syncTools() {
      if (!state.project || !state.project.root) return;
      setText("tools-status", "Tools: dry-run syncing");
      const result = await getJson("/api/tools/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, dry_run: true })
      });
      if (!result.ok) {
        setText("tools-status", result.data.detail || "Tool sync failed.");
        return;
      }
      state.toolSyncPreview = result.data;
      state.toolProfiles = Array.isArray(result.data.profiles) ? result.data.profiles : state.toolProfiles;
      renderToolsPanel();
      showTab("tools");
    }

    function renderToolsPanel() {
      const list = byId("tool-profile-list");
      if (!list) return;
      list.textContent = "";
      if (state.toolError) {
        setText("tools-status", "Tools: unavailable");
        byId("sync-tools-button").disabled = true;
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = state.toolError;
        list.appendChild(error);
        setText("tool-sync-preview", "No tool sync preview.");
        return;
      }
      const profiles = Array.isArray(state.toolProfiles) ? state.toolProfiles : [];
      setText("tools-status", profiles.length ? `Tools: ${profiles.length}` : "Tools: none");
      byId("sync-tools-button").disabled = !profiles.length;
      if (!profiles.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No project tool profiles configured.";
        list.appendChild(empty);
        setText("tool-sync-preview", "No tool sync preview.");
        return;
      }
      for (const item of profiles) {
        list.appendChild(toolProfileCard(item));
      }
      if (state.toolSyncPreview) {
        setText("tool-sync-preview", pretty(state.toolSyncPreview));
      } else {
        setText("tool-sync-preview", "Dry-run sync preview has not been generated.");
      }
    }

    function toolProfileCard(item) {
      const profile = item.profile || {};
      const card = document.createElement("div");
      card.className = "tool-profile-card";
      const title = document.createElement("div");
      title.className = "tool-profile-title";
      title.innerHTML = `
        <span>${escapeHtml(profile.title || item.name || "tool")}</span>
        <span class="${toolStatusBadgeClass(profile.enabled ? "ready" : "disabled")}">${escapeHtml(profile.enabled ? "enabled" : "disabled")}</span>
        <span class="badge info">${escapeHtml(profile.kind || "mcp")}</span>
      `;
      card.appendChild(title);
      if (profile.description) {
        const description = document.createElement("div");
        description.className = "details";
        description.textContent = profile.description;
        card.appendChild(description);
      }
      const statuses = document.createElement("div");
      statuses.className = "tool-profile-statuses";
      for (const status of item.harnesses || []) {
        const badge = document.createElement("span");
        badge.className = toolStatusBadgeClass(status.status);
        badge.title = status.reason || "";
        badge.textContent = `${harnessTitle(status.harness_id)}: ${status.status}`;
        statuses.appendChild(badge);
      }
      card.appendChild(statuses);
      const warnings = [
        ...(Array.isArray(item.warnings) ? item.warnings : []),
        ...(item.harnesses || []).flatMap((status) => Array.isArray(status.warnings) ? status.warnings : [])
      ];
      if (warnings.length) {
        const warning = document.createElement("div");
        warning.className = "warning";
        warning.textContent = warnings.join(" ");
        card.appendChild(warning);
      }
      return card;
    }

    function toolStatusBadgeClass(status) {
      if (status === "ready") return "badge ok";
      if (status === "disabled") return "badge";
      if (status === "missing" || status === "unsupported") return "badge warn";
      return "badge info";
    }

    async function loadEvals() {
      if (!state.project || !state.project.root) {
        state.evalSpecs = [];
        state.evalRuns = [];
        state.evalErrors = [];
        state.currentEvalRun = null;
        state.evalError = null;
        renderEvalsPanel();
        return;
      }
      const result = await getJson(`/api/evals?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        state.evalSpecs = [];
        state.evalRuns = [];
        state.evalErrors = [];
        state.currentEvalRun = null;
        state.evalError = result.data.detail || "Evals unavailable";
        renderEvalsPanel();
        return;
      }
      state.evalSpecs = Array.isArray(result.data.specs) ? result.data.specs : [];
      state.evalRuns = Array.isArray(result.data.runs) ? result.data.runs : [];
      state.evalErrors = Array.isArray(result.data.errors) ? result.data.errors : [];
      state.currentEvalRun = state.currentEvalRun || state.evalRuns[0] || null;
      state.evalError = null;
      renderEvalsPanel();
    }

    async function runSelectedEval() {
      const select = byId("eval-spec-select");
      const evalName = select && select.value ? select.value : "";
      if (!evalName || !state.project || !state.project.root) return;
      setText("evals-status", "Evals: running");
      const result = await getJson(`/api/evals/${encodeURIComponent(evalName)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: state.project.root,
          harness_ids: evalHarnessOverride(),
          model: byId("model-input").value.trim() || null,
          api_mode: selectedApiMode(),
          mode: byId("mode-select").value,
          workspace_policy: byId("workspace-policy-select").value,
          dry_run: byId("dry-run-checkbox").checked
        })
      });
      if (!result.ok || !result.data.eval_run) {
        state.evalError = result.data.detail || `Eval failed with HTTP ${result.status}`;
        renderEvalsPanel();
        showTab("evals");
        return;
      }
      state.currentEvalRun = result.data.eval_run;
      state.evalRuns = [result.data.eval_run, ...state.evalRuns.filter((item) => item.id !== result.data.eval_run.id)];
      state.evalError = null;
      renderEvalsPanel();
      showTab("evals");
    }

    function evalHarnessOverride() {
      const input = byId("eval-harness-input");
      if (!input || !input.value.trim()) return [];
      return input.value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function renderEvalsPanel() {
      const select = byId("eval-spec-select");
      const list = byId("eval-spec-list");
      if (!select || !list) return;
      const selected = select.value;
      select.textContent = "";
      list.textContent = "";
      const specs = Array.isArray(state.evalSpecs) ? state.evalSpecs : [];
      const errors = Array.isArray(state.evalErrors) ? state.evalErrors : [];
      const run = state.currentEvalRun || state.evalRuns[0] || null;
      const statusText = state.evalError
        || (specs.length ? `Evals: ${specs.length} spec${specs.length === 1 ? "" : "s"}` : "Evals: none");
      setText("evals-status", statusText);
      byId("run-eval-button").disabled = !specs.length;
      if (!specs.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No eval specs";
        select.appendChild(option);
      }
      for (const spec of specs) {
        const option = document.createElement("option");
        option.value = spec.name || "";
        option.textContent = `${spec.name || "eval"} (${spec.case_count || 0})`;
        select.appendChild(option);
      }
      if (selected && Array.from(select.options).some((option) => option.value === selected)) {
        select.value = selected;
      }
      if (state.evalError) {
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = state.evalError;
        list.appendChild(error);
      }
      for (const errorItem of errors) {
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = `${errorItem.path || "eval"}: ${errorItem.message || "parse failed"}`;
        list.appendChild(error);
      }
      if (!specs.length && !errors.length && !state.evalError) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No project eval specs found under .giga/evals.";
        list.appendChild(empty);
      }
      for (const spec of specs) {
        list.appendChild(evalSpecCard(spec));
      }
      setText("eval-scorecard", run ? evalRunScorecard(run) : "No eval run selected.");
    }

    function evalSpecCard(spec) {
      const card = document.createElement("div");
      card.className = "tool-profile-card";
      const harnesses = Array.isArray(spec.harnesses) && spec.harnesses.length ? spec.harnesses.join(", ") : "echo";
      card.innerHTML = `
        <div class="tool-profile-title">
          <span>${escapeHtml(spec.name || "eval")}</span>
          <span class="badge info">${escapeHtml(String(spec.case_count || 0))} cases</span>
          <span class="badge info">${escapeHtml(harnesses)}</span>
        </div>
        <div class="details">${escapeHtml(spec.description || spec.path || "")}</div>
      `;
      return card;
    }

    function evalRunScorecard(run) {
      const summary = run.summary || {};
      const lines = [
        `Eval: ${run.spec_name || ""} (${run.id || ""})`,
        `Status: ${run.status || "unknown"}`,
        `Score: ${summary.passed || 0}/${summary.total || 0} passed, ${summary.failed || 0} failed, ${summary.errors || 0} errors`,
        `Session: ${run.session_id || "-"}`,
        ""
      ];
      const results = Array.isArray(run.results) ? run.results : [];
      for (const item of results) {
        lines.push(`${item.case_id || "case"} / ${item.harness_id || "harness"}: ${item.status || "unknown"} (${Number(item.score || 0).toFixed(2)})`);
        const checks = Array.isArray(item.checks) ? item.checks : [];
        for (const check of checks) {
          lines.push(`  - ${check.passed ? "pass" : "fail"} ${check.type || "check"}: ${check.message || ""}`);
        }
        if (item.error) lines.push(`  error: ${item.error}`);
      }
      return lines.join("\\n");
    }

    function selectedWorkspaceFiles() {
      return state.attachments
        .map((attachment) => attachment.workspace_path)
        .filter(Boolean);
    }

    async function confirmRunPreflight(payload) {
      const result = await getJson("/api/preflight/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          session_id: state.currentSessionId || null
        })
      });
      const body = result.data || {};
      if (!result.ok || !body.preflight) {
        setText("run-panel", body.detail || `Preflight failed with HTTP ${result.status}`);
        showTab("run");
        return false;
      }
      const report = body.preflight;
      state.pendingPreflight = report;
      state.pendingPreflightPayload = payload;
      if (!Array.isArray(report.findings) || !report.findings.length) return true;
      return openPreflightModal(report, payload);
    }

    function openPreflightModal(report, payload) {
      renderPreflightModal(report, payload);
      byId("preflight-modal").hidden = false;
      state.preflightModalOpen = true;
      return new Promise((resolve) => {
        state.preflightDecisionResolver = resolve;
      });
    }

    function closePreflightModal(allowRun = false) {
      byId("preflight-modal").hidden = true;
      state.preflightModalOpen = false;
      const resolver = state.preflightDecisionResolver;
      state.preflightDecisionResolver = null;
      if (resolver) resolver(Boolean(allowRun));
    }

    function renderPreflightModal(report, payload) {
      const findings = Array.isArray(report.findings) ? report.findings : [];
      const hardBlock = report.hard_block === true || findings.some((finding) => finding.severity === "block");
      setText("preflight-status", hardBlock ? "Hard block: remove blocked context first" : `${findings.length} warning${findings.length === 1 ? "" : "s"}`);
      setText("preflight-footer-status", hardBlock ? "Blocked findings cannot be continued." : "Only warning-level findings can continue.");
      byId("continue-preflight-button").hidden = hardBlock;
      byId("continue-preflight-button").disabled = hardBlock;
      setText("preflight-budget", preflightBudgetText(report.context_budget || {}));
      const list = byId("preflight-finding-list");
      list.textContent = "";
      for (const finding of findings) {
        list.appendChild(preflightFindingCard(finding));
      }
      if (!findings.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No preflight findings.";
        list.appendChild(empty);
      }
      setText("raw-request-panel", pretty({ ...payload, preflight: report }));
    }

    function preflightFindingCard(finding) {
      const card = document.createElement("div");
      card.className = "preflight-finding";
      const badgeClass = finding.severity === "block" ? "badge error" : finding.severity === "warning" ? "badge warn" : "badge info";
      card.innerHTML = `
        <div class="tool-profile-title">
          <span class="${badgeClass}">${escapeHtml(finding.severity || "info")}</span>
          <span>${escapeHtml(finding.message || finding.code || "Preflight finding")}</span>
        </div>
        <div class="details">${escapeHtml(finding.subject || finding.workspace_path || finding.code || "")}</div>
      `;
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      const allowedActions = Array.isArray(finding.actions) ? finding.actions : [];
      if (finding.attachment_id && allowedActions.includes("exclude_attachment")) {
        actions.appendChild(preflightActionButton("Exclude file", () => excludePreflightAttachment(finding.attachment_id)));
      }
      if (finding.attachment_id && finding.workspace_path && allowedActions.includes("send_path_only")) {
        actions.appendChild(preflightActionButton("Send path only", () => sendPreflightPathOnly(finding.attachment_id, finding.workspace_path)));
      }
      if (actions.childNodes.length) card.appendChild(actions);
      return card;
    }

    function preflightActionButton(label, handler) {
      const button = document.createElement("button");
      button.className = "secondary";
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    }

    function excludePreflightAttachment(attachmentId) {
      state.attachments = state.attachments.filter((attachment) => attachment.id !== attachmentId);
      renderAttachments();
      scheduleRouteRecommendation();
      closePreflightModal(false);
    }

    function sendPreflightPathOnly(attachmentId, workspacePath) {
      state.attachments = state.attachments.filter((attachment) => attachment.id !== attachmentId);
      const prompt = byId("prompt-input");
      const line = `Reference path only: @${workspacePath}`;
      prompt.value = prompt.value.trim() ? `${prompt.value.trim()}\\n\\n${line}` : line;
      renderAttachments();
      scheduleRouteRecommendation();
      closePreflightModal(false);
    }

    function preflightBudgetText(budget) {
      const lines = [
        `Estimated tokens: ${budget.total_estimated_tokens || 0}`,
        `Prompt: ${budget.prompt_tokens || 0} tokens / ${budget.prompt_chars || 0} chars`,
        `Project memory: ${budget.project_memory_count || 0} entries / ${budget.project_memory_tokens || 0} tokens`,
        `Previous chat: ${budget.included_previous_message_count || 0}/${budget.previous_message_count || 0} messages / ${budget.previous_message_tokens || 0} tokens`,
        `Attachments: ${budget.attached_file_count || 0} files / ${formatBytes(budget.attached_file_bytes || 0)} / ${budget.attachment_tokens || 0} estimated tokens`,
        `Images: ${budget.image_count || 0} / ${formatBytes(budget.image_bytes || 0)}`
      ];
      const warnings = Array.isArray(budget.truncation_warnings) ? budget.truncation_warnings : [];
      if (warnings.length) {
        lines.push("");
        lines.push("Truncation warnings:");
        for (const warning of warnings) lines.push(`- ${warning}`);
      }
      return lines.join("\\n");
    }

    function currentLastDiff() {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      for (let index = runs.length - 1; index >= 0; index -= 1) {
        const run = runs[index] || {};
        const metadata = run.metadata || {};
        if (metadata.diff) return String(metadata.diff);
      }
      return "";
    }

    async function runHarness() {
      const payload = buildPayload();
      if (!payload.prompt.trim()) return;
      if (!(await confirmRunPreflight(payload))) return;
      if (payload.invocation_mode === "native" && currentHarnessSupportsNative()) {
        await startNativeProcess(payload);
        return;
      }
      if (payload.stream) {
        await startHeadlessStream(payload);
        return;
      }
      state.lastPayload = payload;
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      renderDiffInspector(null);
      renderPrInspector(null);
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
          state.currentArena = null;
          state.currentSessionId = body.session.id;
          state.currentBundle = body;
          byId("prompt-input").value = "";
          state.attachments = [];
          renderAttachments();
          renderAll();
          await loadSessions();
          persistProjectState({ last_selected_session: body.session.id });
        } else {
          setText("raw-response-panel", pretty(body));
          setText("run-panel", body.detail || `Request failed with HTTP ${result.status}`);
        }
      } finally {
        byId("run-button").disabled = false;
        byId("run-button").textContent = "Run";
      }
    }

    async function runArena() {
      const payload = buildArenaPayload();
      if (!payload.prompt.trim()) return;
      if (!payload.harness_ids.length) {
        setText("arena-panel", "Select at least one arena harness.");
        showTab("arena");
        return;
      }
      state.lastPayload = payload;
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", "Arena runs use normalized headless harness execution.");
      renderDiffInspector(null);
      renderPrInspector(null);
      setText("arena-panel", "Arena is starting...");
      showTab("arena");
      byId("compare-button").disabled = true;
      byId("compare-button").textContent = "Comparing...";
      try {
        const result = await getJson("/api/arena/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const body = result.data || {};
        if (!result.ok || !body.arena) {
          setText("raw-response-panel", pretty(body));
          setText("arena-panel", body.detail || `Arena failed with HTTP ${result.status}`);
          return;
        }
        state.currentArena = body.arena;
        state.currentSessionId = body.arena.session_id || state.currentSessionId;
        if (state.currentSessionId) await loadSession(state.currentSessionId);
        byId("prompt-input").value = "";
        state.attachments = [];
        renderAttachments();
        renderArenaInspector(state.currentArena);
        setText("raw-response-panel", pretty(body));
        showTab("arena");
        await loadSessions();
        persistProjectState({ last_selected_session: state.currentSessionId });
      } finally {
        byId("compare-button").disabled = false;
        byId("compare-button").textContent = "Compare";
      }
    }

    async function startHeadlessStream(payload) {
      state.lastPayload = payload;
      closeHeadlessEventSource();
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      renderDiffInspector(null);
      renderPrInspector(null);
      setText("run-panel", "Starting streamed run...");
      renderEvents([]);
      setHeadlessRunning(true);
      try {
        const url = state.currentSessionId ? `/api/sessions/${encodeURIComponent(state.currentSessionId)}/run/start` : "/api/sessions/run/start";
        const result = await getJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const body = result.data || {};
        if (!result.ok || !body.run) {
          setText("raw-response-panel", pretty(body));
          setText("run-panel", body.detail || `Stream start failed with HTTP ${result.status}`);
          setHeadlessRunning(false);
          return;
        }
        state.currentSessionId = body.session && body.session.id ? body.session.id : state.currentSessionId;
        state.currentArena = null;
        state.activeHeadlessRun = body.run;
        if (Array.isArray(body.events) && body.events.length) renderEvents(body.events);
        setText("run-panel", pretty(body.run));
        if (state.currentSessionId) {
          await loadSession(state.currentSessionId);
          persistProjectState({ last_selected_session: state.currentSessionId });
        }
        openHeadlessEventStream(body.run.id);
      } catch (error) {
        setText("run-panel", "Stream start failed.");
        setHeadlessRunning(false);
      }
    }

    function openHeadlessEventStream(runId) {
      closeHeadlessEventSource();
      if (!window.EventSource) {
        setText("run-panel", "This browser does not support EventSource.");
        setHeadlessRunning(false);
        return;
      }
      const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events/stream`);
      state.headlessEventSource = source;
      source.onmessage = (event) => {
        let payload = {};
        try {
          payload = JSON.parse(event.data || "{}");
        } catch (error) {
          payload = { type: "warning", message: "Invalid event payload", payload: {} };
        }
        appendStreamEvent(payload);
        if (payload.type === "run_finished") {
          finishHeadlessStream();
        }
      };
      source.onerror = () => {
        const run = state.activeHeadlessRun || {};
        if (run.status === "succeeded" || run.status === "failed" || run.status === "canceled") {
          finishHeadlessStream();
        }
      };
    }

    function appendStreamEvent(event) {
      if (!state.currentBundle) state.currentBundle = { events: [], runs: [] };
      if (!Array.isArray(state.currentBundle.events)) state.currentBundle.events = [];
      const exists = event.id && state.currentBundle.events.some((item) => item.id === event.id);
      if (!exists) state.currentBundle.events.push(event);
      renderEvents(state.currentBundle.events);
      if (event.type === "run_finished" && event.payload && event.payload.status) {
        state.activeHeadlessRun = {
          ...(state.activeHeadlessRun || {}),
          status: event.payload.status
        };
      }
      if (event.type === "error" || event.type === "run_canceled") showTab("events");
    }

    async function finishHeadlessStream() {
      closeHeadlessEventSource();
      setHeadlessRunning(false);
      if (state.currentSessionId) {
        await loadSession(state.currentSessionId);
        await loadSessions();
      }
      byId("prompt-input").value = "";
      state.attachments = [];
      renderAttachments();
    }

    function closeHeadlessEventSource() {
      if (state.headlessEventSource) {
        state.headlessEventSource.close();
        state.headlessEventSource = null;
      }
    }

    function setHeadlessRunning(running) {
      byId("run-button").disabled = running;
      byId("run-button").textContent = running ? "Running..." : "Run";
      byId("cancel-run-button").hidden = !running;
      byId("cancel-run-button").disabled = !running;
    }

    async function cancelHeadlessRun() {
      const run = state.activeHeadlessRun || {};
      if (!run.id) return;
      byId("cancel-run-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/cancel`, {
        method: "POST"
      });
      if (!result.ok) {
        appendStreamEvent({
          type: "error",
          message: result.data.detail || "Cancel failed.",
          payload: { status: result.status }
        });
        byId("cancel-run-button").disabled = false;
        return;
      }
      appendStreamEvent({
        type: "cancel_requested",
        message: "Harness run cancellation requested.",
        payload: { active: result.data.active === true }
      });
    }

    async function startNativeProcess(payload) {
      if (!(await ensureSessionForNative(payload))) return;
      state.lastPayload = payload;
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      setNativeSummary("Starting native process...");
      showTab("native");
      byId("run-button").disabled = true;
      byId("run-button").textContent = "Starting...";
      try {
        const result = await getJson("/api/native/processes/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: state.currentSessionId,
            action: "start",
            harness_id: payload.harness_id,
            prompt: payload.prompt,
            model: payload.model,
            api_mode: payload.api_mode,
            mode: payload.mode,
            workspace: payload.workspace,
            attachment_ids: payload.attachment_ids || []
          })
        });
        if (!result.ok) {
          setNativeSummary(result.data.detail || `Native start failed with HTTP ${result.status}`);
          return;
        }
        setActiveNativeProcess(result.data.process || null, result.data);
        state.attachments = [];
        renderAttachments();
        if (state.currentSessionId) await loadSession(state.currentSessionId);
      } finally {
        byId("run-button").disabled = false;
        updateHarnessDrivenControls();
      }
    }

    async function ensureSessionForNative(payload) {
      if (state.currentSessionId) return true;
      const result = await getJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!result.ok || !result.data.session) {
        setNativeSummary(result.data.detail || "Native session creation failed.");
        return false;
      }
      state.currentSessionId = result.data.session.id;
      await loadSession(state.currentSessionId);
      return true;
    }

    function renderAll() {
      renderMessages();
      renderInspector();
      renderSessions();
      renderMemoryPanel();
      renderToolsPanel();
      renderEvalsPanel();
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
        const attachments = message.metadata && Array.isArray(message.metadata.attachments) ? message.metadata.attachments : [];
        const attachmentChips = attachments.length ? `
          <div class="attachment-chip-row">
            ${attachments.map((attachment) => `
              <span class="badge attachment-chip">${escapeHtml(attachment.filename || attachment.id || "attachment")}</span>
            `).join("")}
          </div>
        ` : "";
        item.innerHTML = `
          <div class="message-meta">
            <span>${escapeHtml(message.role || "")}</span>
            <span>${escapeHtml(message.harness_id || "")}</span>
            <span>${escapeHtml(message.api_mode || "")}</span>
          </div>
          <div class="message-content">${escapeHtml(message.content || "")}</div>
          ${attachmentChips}
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
      renderArenaInspector(state.currentArena);
      renderEvents(events);
      setText("raw-request-panel", rawRequests.length ? pretty(rawRequests[rawRequests.length - 1].payload) : "{}");
      setText("raw-response-panel", rawResponses.length ? pretty(rawResponses[rawResponses.length - 1].payload) : "{}");
      setText("command-panel", run && run.command && run.command.length ? run.command.join(" ") : commandPreview(state.lastPayload));
      renderDiffInspector(run);
      renderPrInspector(run);
      renderProvenanceInspector(run);
      setText("attachments-panel", run ? attachmentInspectorText(run, rawRequests[rawRequests.length - 1]) : "No attachments selected.");
      setNativeSummary(nativeInspectorText(bundle));
      setText("storage-panel", pretty(bundle.storage || {}));
      byId("pin-session-button").textContent = session && session.pinned ? "Unpin" : "Pin";
      byId("archive-session-button").textContent = session && session.archived ? "Unarchive" : "Archive";
    }

    function renderArenaInspector(arena) {
      const panel = byId("arena-panel");
      if (!panel) return;
      panel.textContent = "";
      if (!arena || !arena.id) {
        panel.textContent = "No arena selected.";
        return;
      }
      const header = document.createElement("div");
      header.innerHTML = `
        <div class="badge-row">
          <span class="badge info">Arena</span>
          <span class="badge ${arena.status === "succeeded" ? "ok" : arena.status === "partial" ? "warn" : arena.status === "failed" ? "warn" : "info"}">${escapeHtml(arena.status || "unknown")}</span>
        </div>
        <div class="session-meta">
          <span>${escapeHtml(arena.id)}</span>
          <span>${escapeHtml(arena.harness_ids ? arena.harness_ids.join(", ") : "")}</span>
          <span>/api/arena/runs/${escapeHtml(arena.id)}/events/stream</span>
        </div>
      `;
      panel.appendChild(header);
      const children = Array.isArray(arena.child_runs) ? arena.child_runs : [];
      if (!children.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Arena is waiting for child runs.";
        panel.appendChild(empty);
        return;
      }
      const grid = document.createElement("div");
      grid.className = "arena-grid";
      for (const child of children) {
        const card = document.createElement("div");
        card.className = "arena-card";
        const message = child.message && child.message.content ? child.message.content : child.result_text || child.error || "No output";
        card.innerHTML = `
          <div class="badge-row">
            <span class="badge info">${escapeHtml(child.harness_id || "harness")}</span>
            <span class="badge ${child.status === "succeeded" ? "ok" : "warn"}">${escapeHtml(child.status || "unknown")}</span>
          </div>
          <div class="session-meta">
            <span>${escapeHtml(child.run_id || "no run")}</span>
            <span>${escapeHtml(String(child.event_count || 0))} events</span>
          </div>
          <pre>${escapeHtml(message)}</pre>
        `;
        grid.appendChild(card);
      }
      panel.appendChild(grid);
    }

    function renderDiffInspector(run) {
      const metadata = run && run.metadata ? run.metadata : {};
      const execution = metadata.workspace_execution || {};
      const patch = execution.patch || metadata.diff || "";
      const changedFiles = Array.isArray(execution.changed_files) ? execution.changed_files : [];
      const untrackedFiles = Array.isArray(execution.untracked_files) ? execution.untracked_files : [];
      const lines = [];
      if (run && run.id) lines.push(`Run: ${run.id}`);
      if (execution.policy) lines.push(`Policy: ${execution.policy}`);
      if (execution.requested_policy && execution.requested_policy !== execution.policy) {
        lines.push(`Requested: ${execution.requested_policy}`);
      }
      if (execution.base_branch) lines.push(`Base branch: ${execution.base_branch}`);
      if (execution.base_commit) lines.push(`Base commit: ${execution.base_commit}`);
      if (execution.worktree_path) lines.push(`Worktree: ${execution.worktree_path}`);
      if (execution.applied_at) lines.push(`Applied: ${execution.applied_at}`);
      if (execution.discarded_at) lines.push(`Discarded: ${execution.discarded_at}`);
      if (execution.fallback_reason) lines.push(`Fallback: ${execution.fallback_reason}`);
      if (changedFiles.length) lines.push(`Changed files: ${changedFiles.join(", ")}`);
      if (untrackedFiles.length) lines.push(`Untracked files: ${untrackedFiles.join(", ")}`);
      const summary = lines.length ? lines.join("\\n") : "No run selected.";
      setText("diff-text", `${summary}\\n\\n${patch || "No diff captured."}`);
      const canApply = Boolean(run && run.id && execution.policy === "worktree" && patch && patch !== "No diff captured." && !execution.applied_at && !execution.discarded_at);
      const canDiscard = Boolean(run && run.id && execution.policy === "worktree" && !execution.discarded_at);
      byId("apply-run-diff-button").disabled = !canApply;
      byId("apply-branch-input").disabled = !canApply;
      byId("discard-run-worktree-button").disabled = !canDiscard;
      byId("open-run-worktree-button").disabled = !(run && run.id && execution.worktree_path);
    }

    function renderPrInspector(run) {
      const artifact = prArtifactFromRun(run);
      const execution = run && run.metadata ? (run.metadata.workspace_execution || {}) : {};
      const canCreateBranch = Boolean(run && run.id && artifact && artifact.patch && artifact.patch !== "No diff captured." && execution.policy === "worktree" && !execution.applied_at && !execution.discarded_at);
      if (!artifact) {
        setText("pr-text", "No PR artifact.");
        byId("pr-branch-input").disabled = true;
        byId("copy-pr-title-button").disabled = true;
        byId("copy-pr-body-button").disabled = true;
        byId("copy-pr-patch-button").disabled = true;
        byId("create-pr-branch-button").disabled = true;
        return;
      }
      if (run && byId("pr-branch-input").dataset.runId !== run.id) {
        byId("pr-branch-input").value = artifact.branch_name_suggestion || "";
        byId("pr-branch-input").dataset.runId = run.id;
      }
      const lines = [
        `Title:\\n${artifact.title || ""}`,
        `Branch:\\n${artifact.applied_branch || artifact.branch_name_suggestion || ""}`,
        `Body:\\n${artifact.body || ""}`,
        `Changed files:\\n${(artifact.changed_files || []).join("\\n") || "None"}`,
        `Patch:\\n${artifact.patch || "No patch captured."}`
      ];
      setText("pr-text", lines.join("\\n\\n"));
      byId("pr-branch-input").disabled = !canCreateBranch;
      byId("copy-pr-title-button").disabled = !(artifact.title || "").trim();
      byId("copy-pr-body-button").disabled = !(artifact.body || "").trim();
      byId("copy-pr-patch-button").disabled = !(artifact.patch || "").trim();
      byId("create-pr-branch-button").disabled = !canCreateBranch;
    }

    function renderProvenanceInspector(run) {
      const hasRun = Boolean(run && run.id);
      byId("refresh-provenance-button").disabled = !hasRun;
      byId("replay-run-button").disabled = !hasRun;
      byId("fork-run-button").disabled = !hasRun;
      if (!hasRun) {
        setText("provenance-text", "No provenance selected.");
        return;
      }
      const provenance = run.metadata && run.metadata.provenance ? run.metadata.provenance : null;
      if (!provenance) {
        setText("provenance-text", `Run: ${run.id}\\nProvenance snapshot is not stored yet. Refresh provenance to reconstruct it from session records.`);
        return;
      }
      setText("provenance-text", pretty(provenance));
    }

    function prArtifactFromRun(run) {
      if (!run || !run.id) return null;
      const metadata = run.metadata || {};
      if (metadata.pr_artifact) return metadata.pr_artifact;
      const execution = metadata.workspace_execution || {};
      const patch = execution.patch || metadata.diff || "";
      const changedFiles = Array.isArray(execution.changed_files) ? execution.changed_files : [];
      if (!patch && !changedFiles.length) return null;
      const title = changedFiles.length ? `Update ${changedFiles[0]}` : `Update from ${run.id}`;
      const changeLines = changedFiles.map((item) => "- Updated `" + item + "`").join("\\n") || "- No changed files captured.";
      return {
        run_id: run.id,
        session_id: run.session_id,
        title,
        body: "## Summary\\n- Generated from stored harness run.\\n\\n## Changes\\n" + changeLines + "\\n\\n## Tests\\n```text\\nNot recorded.\\n```",
        patch,
        changed_files: changedFiles,
        untracked_files: Array.isArray(execution.untracked_files) ? execution.untracked_files : [],
        branch_name_suggestion: `giga/${String(title).toLowerCase().replace(/[^a-z0-9._/-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || run.id}`
      };
    }

    function currentRun() {
      const bundle = state.currentBundle || {};
      const runs = Array.isArray(bundle.runs) ? bundle.runs : [];
      return runs[runs.length - 1] || null;
    }

    async function refreshRunDiff(runId) {
      const result = await getJson(`/api/runs/${encodeURIComponent(runId)}/diff`);
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Diff request failed with HTTP ${result.status}`);
        return null;
      }
      const run = result.data.run || null;
      renderDiffInspector(run);
      return run;
    }

    async function applyRunDiff() {
      const run = currentRun();
      if (!run || !run.id) return;
      const branchName = byId("apply-branch-input").value.trim();
      byId("apply-run-diff-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ branch_name: branchName || null })
      });
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Apply failed with HTTP ${result.status}`);
        renderDiffInspector(run);
        return;
      }
      setText("model-status", "Applied run diff.");
      if (state.currentSessionId) await loadSession(state.currentSessionId);
      await refreshRunDiff(run.id);
      renderPrInspector(currentRun());
    }

    async function discardRunWorktree() {
      const run = currentRun();
      if (!run || !run.id) return;
      byId("discard-run-worktree-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/discard`, {
        method: "POST"
      });
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Discard failed with HTTP ${result.status}`);
        renderDiffInspector(run);
        return;
      }
      setText("model-status", "Discarded run worktree.");
      if (state.currentSessionId) await loadSession(state.currentSessionId);
      await refreshRunDiff(run.id);
      renderPrInspector(currentRun());
    }

    async function openRunWorktree() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/open-worktree`, {
        method: "POST"
      });
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Open worktree failed with HTTP ${result.status}`);
        return;
      }
      const worktree = result.data.worktree || {};
      setText("model-status", worktree.exists ? `Worktree: ${worktree.path}` : "Worktree path is unavailable.");
      await refreshRunDiff(run.id);
    }

    async function createPrBranch() {
      const run = currentRun();
      if (!run || !run.id) return;
      const branchName = byId("pr-branch-input").value.trim();
      byId("create-pr-branch-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/branch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ branch_name: branchName || null })
      });
      if (!result.ok) {
        setText("pr-text", result.data.detail || `Branch creation failed with HTTP ${result.status}`);
        renderPrInspector(run);
        return;
      }
      setText("model-status", `Created branch ${result.data.branch_name}.`);
      if (state.currentSessionId) await loadSession(state.currentSessionId);
      renderPrInspector(currentRun());
      showTab("pr");
    }

    function copyCurrentPrField(field, status) {
      const artifact = prArtifactFromRun(currentRun());
      if (!artifact) return;
      copyText(artifact[field] || "", status);
    }

    async function refreshRunProvenance() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/provenance`);
      if (!result.ok) {
        setText("provenance-text", result.data.detail || `Provenance failed with HTTP ${result.status}`);
        showTab("provenance");
        return;
      }
      const provenance = result.data.provenance || {};
      setText("provenance-text", pretty(provenance));
      if (run.metadata) run.metadata.provenance = provenance;
      showTab("provenance");
    }

    async function replayCurrentRun() {
      const run = currentRun();
      if (!run || !run.id) return;
      byId("replay-run-button").disabled = true;
      setText("provenance-text", `Replaying ${run.id}...`);
      showTab("provenance");
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream: false })
      });
      if (!result.ok) {
        setText("provenance-text", result.data.detail || `Replay failed with HTTP ${result.status}`);
        renderProvenanceInspector(run);
        return;
      }
      state.currentArena = null;
      state.currentSessionId = result.data.session && result.data.session.id ? result.data.session.id : state.currentSessionId;
      state.currentBundle = result.data;
      state.attachments = [];
      byId("prompt-input").value = "";
      renderAll();
      renderAttachments();
      await loadSessions();
      setText("model-status", "Replayed run.");
      showTab("run");
    }

    async function forkCurrentRun() {
      const run = currentRun();
      if (!run || !run.id) return;
      byId("fork-run-button").disabled = true;
      setText("provenance-text", `Forking ${run.id}...`);
      showTab("provenance");
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/fork`, {
        method: "POST"
      });
      if (!result.ok || !result.data.session) {
        setText("provenance-text", result.data.detail || `Fork failed with HTTP ${result.status}`);
        renderProvenanceInspector(run);
        return;
      }
      await loadSession(result.data.session.id);
      await loadSessions();
      setText("model-status", "Forked run into a new chat.");
      showTab("run");
    }

    function nativeInspectorText(bundle) {
      if (state.nativePreview) return pretty(state.nativePreview);
      if (state.activeNativeProcess) return pretty(state.activeNativeProcess);
      const links = bundle && Array.isArray(bundle.native_links) ? bundle.native_links : [];
      if (!links.length) return "No native session selected.";
      return pretty({ native_links: links });
    }

    function setNativeSummary(value) {
      setText("native-process-summary", value);
    }

    function setActiveNativeProcess(process, payload) {
      stopNativePolling();
      state.activeNativeProcess = process;
      state.nativeOutputCursor = 0;
      state.nativeTerminalText = "";
      setNativeSummary(pretty(payload || process || {}));
      setText("native-terminal-output", "Terminal output will appear here.");
      renderNativeTerminalStatus();
      if (process && process.id) {
        pollNativeOutput();
        state.nativePollTimer = window.setInterval(pollNativeOutput, 1000);
      }
    }

    function renderNativeTerminalStatus(status) {
      const process = state.activeNativeProcess || {};
      const effectiveStatus = status || process.status || "idle";
      const badge = byId("native-terminal-status");
      badge.className = effectiveStatus === "running" ? "badge ok" : effectiveStatus === "idle" ? "badge info" : "badge warn";
      badge.textContent = `Native: ${effectiveStatus}`;
      const running = effectiveStatus === "running";
      byId("send-native-input-button").disabled = !running;
      byId("stop-native-process-button").disabled = !process.id || !running;
      byId("poll-native-output-button").disabled = !process.id;
    }

    async function pollNativeOutput() {
      const process = state.activeNativeProcess || {};
      if (!process.id) {
        renderNativeTerminalStatus("idle");
        return;
      }
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}/output?cursor=${state.nativeOutputCursor}`);
      if (!result.ok) {
        appendNativeTerminalLine(result.data.detail || "Native output polling failed.");
        stopNativePolling();
        renderNativeTerminalStatus("error");
        return;
      }
      const body = result.data || {};
      state.nativeOutputCursor = body.cursor || state.nativeOutputCursor;
      const outputs = Array.isArray(body.outputs) ? body.outputs : [];
      for (const output of outputs) {
        appendNativeTerminal(output.text || "");
      }
      const status = body.status || (body.run && body.run.status) || "running";
      state.activeNativeProcess = { ...process, status, exit_code: body.exit_code };
      renderNativeTerminalStatus(status);
      if (status !== "running") stopNativePolling();
      if (body.run) setNativeSummary(pretty({ process: state.activeNativeProcess, run: body.run }));
    }

    async function sendNativeInput() {
      const process = state.activeNativeProcess || {};
      if (!process.id) return;
      const input = byId("native-terminal-input");
      const data = input.value;
      if (!data) return;
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}/input`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data })
      });
      if (!result.ok) {
        appendNativeTerminalLine(result.data.detail || "Native input failed.");
        return;
      }
      input.value = "";
      if (result.data.process) state.activeNativeProcess = result.data.process;
      await pollNativeOutput();
    }

    async function stopNativeProcess() {
      const process = state.activeNativeProcess || {};
      if (!process.id) return;
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}`, { method: "DELETE" });
      if (!result.ok) {
        appendNativeTerminalLine(result.data.detail || "Native stop failed.");
        return;
      }
      if (result.data.process) state.activeNativeProcess = result.data.process;
      setNativeSummary(pretty(result.data));
      await pollNativeOutput();
    }

    function stopNativePolling() {
      if (state.nativePollTimer) {
        window.clearInterval(state.nativePollTimer);
        state.nativePollTimer = null;
      }
    }

    function clearNativeTerminal() {
      state.nativeTerminalText = "";
      setText("native-terminal-output", "Terminal output will appear here.");
    }

    function appendNativeTerminal(text) {
      const clean = stripAnsi(text);
      state.nativeTerminalText += clean;
      setText("native-terminal-output", state.nativeTerminalText || "Terminal output will appear here.");
    }

    function appendNativeTerminalLine(text) {
      appendNativeTerminal(`${text}\\n`);
    }

    function stripAnsi(text) {
      return String(text || "").replace(/\\x1B\\[[0-?]*[ -/]*[@-~]/g, "");
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

    function attachmentInspectorText(run, rawRequest) {
      const metadata = run && run.metadata ? run.metadata : {};
      const requestPayload = rawRequest && rawRequest.payload ? rawRequest.payload : {};
      const attachments = Array.isArray(metadata.attachments) ? metadata.attachments : Array.isArray(requestPayload.attachments) ? requestPayload.attachments : [];
      const renderPlan = metadata.attachment_render_plan || requestPayload.attachment_render_plan || null;
      if (!attachments.length && !renderPlan) return "No attachments selected.";
      const lines = [];
      if (attachments.length) {
        lines.push("Attachments");
        for (const attachment of attachments) {
          lines.push(`- ${attachment.filename || attachment.id} [${attachment.kind || "attachment"}] ${attachment.mime_type || ""} ${formatBytes(attachment.size_bytes || 0)}`);
          if (attachment.workspace_path) lines.push(`  workspace: @${attachment.workspace_path}`);
          if (attachment.source) lines.push(`  source: ${attachment.source}`);
        }
      }
      if (renderPlan) {
        lines.push("");
        lines.push("Render plan");
        const metadata = renderPlan.metadata || {};
        if (metadata.transport) lines.push(`transport: ${metadata.transport}`);
        if (Array.isArray(renderPlan.warnings) && renderPlan.warnings.length) {
          lines.push("warnings:");
          for (const warning of renderPlan.warnings) lines.push(`- ${warning}`);
        }
        if (renderPlan.prompt_prefix) lines.push(`prompt_prefix:\\n${renderPlan.prompt_prefix}`);
        if (Array.isArray(renderPlan.cli_args) && renderPlan.cli_args.length) {
          lines.push(`cli_args: ${renderPlan.cli_args.join(" ")}`);
        }
        if (Array.isArray(renderPlan.content_parts) && renderPlan.content_parts.length) {
          lines.push(`content_parts: ${renderPlan.content_parts.length}`);
        }
        lines.push("");
        lines.push("render_plan_json:");
        lines.push(pretty(renderPlan));
      }
      return lines.join("\\n");
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
        state.currentArena = null;
        state.attachments = [];
        renderAttachments();
        renderAll();
        await loadSessions();
        persistProjectState({ last_selected_session: null });
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

    function currentHarnessSupportsNative() {
      const spec = state.selectedHarness && state.selectedHarness.spec ? state.selectedHarness.spec : {};
      return spec.supports_native_sessions === true;
    }

    function currentInvocationMode() {
      return byId("invocation-select").value || "headless";
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

    async function persistProjectState(patch = {}) {
      if (state.applyingProjectState || !state.project || !state.project.root) return;
      const payload = {
        workspace: state.project.root,
        last_harness: currentHarnessId(),
        last_model: byId("model-input").value.trim() || null,
        last_api_mode: currentApiMode(),
        last_run_mode: byId("mode-select").value,
        last_invocation_mode: currentInvocationMode(),
        last_selected_session: state.currentSessionId || null,
        ...patch
      };
      const result = await getJson("/api/project/state", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (result.ok) state.projectState = result.data.state || state.projectState;
    }

    function commandPreview(payload) {
      if (!payload) return "No command yet.";
      const args = ["giga", "harness", "run", payload.harness_id || "echo", "--api-mode", payload.api_mode || "v2"];
      if (payload.invocation_mode === "native") args.push("--native");
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
      closeHeadlessEventSource();
      setHeadlessRunning(false);
      state.attachments = [];
      renderAttachments();
    }

    function shellQuote(value) {
      const text = String(value == null ? "" : value);
      if (/^[A-Za-z0-9_./:=@-]+$/.test(text)) return text;
      return `'${text.replace(/'/g, "'\\\\''")}'`;
    }

    function bindTabEvents() {
      for (const tabs of document.querySelectorAll(".tabs")) {
        tabs.addEventListener("click", (event) => {
          const tab = event.target && event.target.closest ? event.target.closest(".tab") : null;
          if (tab && tabs.contains(tab)) showTab(tab.dataset.tab);
        });
      }
    }

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function bindEvents() {
      bindTabEvents();
      const composer = byId("composer");
      byId("refresh-health-button").addEventListener("click", refreshHealth);
      byId("refresh-models-button").addEventListener("click", loadModels);
      byId("init-project-button").addEventListener("click", initProject);
      byId("new-chat-button").addEventListener("click", newChat);
      byId("add-memory-button").addEventListener("click", addMemoryFromInput);
      byId("remember-message-button").addEventListener("click", rememberLastMessage);
      byId("sync-tools-button").addEventListener("click", syncTools);
      byId("refresh-evals-button").addEventListener("click", loadEvals);
      byId("run-eval-button").addEventListener("click", runSelectedEval);
      byId("harness-select").addEventListener("change", (event) => {
        selectHarness(event.target.value);
        renderRouteRecommendation(state.routeRecommendation);
      });
      byId("arena-harness-select").addEventListener("change", () => {
        state.arenaSelectionTouched = true;
      });
      byId("invocation-select").addEventListener("change", () => {
        updateHarnessDrivenControls();
        persistProjectState();
      });
      byId("sync-native-button").addEventListener("click", () => loadNativeSessions(true, { openModal: true, resetVisible: true }));
      byId("open-native-history-button").addEventListener("click", () => openNativeHistory(true));
      byId("load-more-native-button").addEventListener("click", loadMoreNativeSessions);
      byId("close-native-history-button").addEventListener("click", closeNativeHistory);
      byId("native-history-modal").addEventListener("click", (event) => {
        if (event.target === byId("native-history-modal")) closeNativeHistory();
      });
      byId("preflight-modal").addEventListener("click", (event) => {
        if (event.target === byId("preflight-modal")) closePreflightModal(false);
      });
      byId("close-preflight-button").addEventListener("click", () => closePreflightModal(false));
      byId("continue-preflight-button").addEventListener("click", () => closePreflightModal(true));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && state.nativeModalOpen) closeNativeHistory();
        if (event.key === "Escape" && state.preflightModalOpen) closePreflightModal(false);
      });
      byId("native-all-workspaces-checkbox").addEventListener("change", () => loadNativeSessions(false, { resetVisible: true }));
      byId("poll-native-output-button").addEventListener("click", pollNativeOutput);
      byId("send-native-input-button").addEventListener("click", sendNativeInput);
      byId("stop-native-process-button").addEventListener("click", stopNativeProcess);
      byId("clear-native-terminal-button").addEventListener("click", clearNativeTerminal);
      byId("api-mode-v1").addEventListener("change", () => { updateRouteNote(); loadModels(); persistProjectState(); });
      byId("api-mode-v2").addEventListener("change", () => { updateRouteNote(); loadModels(); persistProjectState(); });
      byId("mode-select").addEventListener("change", () => {
        persistProjectState();
        scheduleRouteRecommendation();
      });
      byId("workspace-policy-select").addEventListener("change", () => persistProjectState());
      byId("workspace-input").addEventListener("input", scheduleRouteRecommendation);
      byId("workspace-input").addEventListener("change", () => {
        persistProjectState();
        scheduleRouteRecommendation();
      });
      byId("model-menu-button").addEventListener("click", toggleModelList);
      byId("model-input").addEventListener("focus", openModelList);
      byId("model-input").addEventListener("input", () => {
        updateHeaderBadges();
        openModelList();
      });
      byId("model-input").addEventListener("change", () => persistProjectState());
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
      byId("compare-button").addEventListener("click", runArena);
      byId("cancel-run-button").addEventListener("click", cancelHeadlessRun);
      byId("apply-route-recommendation-button").addEventListener("click", applyRouteRecommendation);
      byId("apply-run-diff-button").addEventListener("click", applyRunDiff);
      byId("discard-run-worktree-button").addEventListener("click", discardRunWorktree);
      byId("open-run-worktree-button").addEventListener("click", openRunWorktree);
      byId("copy-pr-title-button").addEventListener("click", () => copyCurrentPrField("title", "Copied PR title."));
      byId("copy-pr-body-button").addEventListener("click", () => copyCurrentPrField("body", "Copied PR body."));
      byId("copy-pr-patch-button").addEventListener("click", () => copyCurrentPrField("patch", "Copied PR patch."));
      byId("create-pr-branch-button").addEventListener("click", createPrBranch);
      byId("refresh-provenance-button").addEventListener("click", refreshRunProvenance);
      byId("replay-run-button").addEventListener("click", replayCurrentRun);
      byId("fork-run-button").addEventListener("click", forkCurrentRun);
      byId("reset-button").addEventListener("click", resetComposer);
      byId("attach-file-button").addEventListener("click", () => byId("attachment-file-input").click());
      byId("attachment-file-input").addEventListener("change", (event) => {
        attachFiles(event.target.files, "upload");
        event.target.value = "";
      });
      composer.addEventListener("dragenter", (event) => {
        event.preventDefault();
        composer.classList.add("drag-over");
      });
      composer.addEventListener("dragover", (event) => {
        event.preventDefault();
        composer.classList.add("drag-over");
      });
      composer.addEventListener("dragleave", (event) => {
        if (!composer.contains(event.relatedTarget)) composer.classList.remove("drag-over");
      });
      composer.addEventListener("drop", (event) => {
        event.preventDefault();
        composer.classList.remove("drag-over");
        attachFiles(event.dataTransfer.files, "upload");
      });
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
        if (event.key === "Escape") hideWorkspaceFileMenu();
      });
      byId("prompt-input").addEventListener("input", () => {
        searchWorkspaceFiles();
        scheduleRouteRecommendation();
      });
      byId("prompt-input").addEventListener("paste", (event) => {
        const items = event.clipboardData && event.clipboardData.items ? Array.from(event.clipboardData.items) : [];
        const files = items
          .filter((item) => item.kind === "file")
          .map((item) => item.getAsFile())
          .filter((file) => file && String(file.type || "").startsWith("image/"));
        if (files.length) attachFiles(files, "paste");
      });
    }

    async function boot() {
      bindEvents();
      renderNativeTerminalStatus("idle");
      await loadDefaults();
      await loadProject();
      await Promise.all([loadHarnesses(), refreshHealth(), loadModels()]);
      await loadSessions();
      if (!state.currentSessionId && state.projectState && state.projectState.last_selected_session) {
        await loadSession(state.projectState.last_selected_session);
      }
      await loadNativeSessions(false);
      renderAll();
    }

    boot();
  </script>
</body>
</html>
"""
