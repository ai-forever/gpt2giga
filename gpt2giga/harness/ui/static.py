"""Inline static assets for the no-build Unified Harness UI."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga Harness</title>
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

    /* Calm, task-first harness workspace. */
    :root {
      color-scheme: dark;
      --bg: #0c1119;
      --panel: #101721;
      --panel-soft: #151e2b;
      --panel-strong: #1a2635;
      --border: #273344;
      --text: #f7f9fc;
      --muted: #8d9aaf;
      --accent: #2bb9bd;
      --accent-strong: #43cbd0;
      --blue: #74a9ff;
      --amber: #f5bf58;
      --red: #f17878;
      --green: #68d391;
      --violet: #aa92f6;
      --mono-bg: #090e15;
      --header-height: 68px;
      --sidebar-width: 286px;
    }
    body {
      overflow: hidden;
      background: var(--bg);
      font-size: 14px;
    }
    button {
      min-height: 38px;
      border-color: #258f94;
      border-radius: 10px;
      padding: 8px 14px;
      font-size: 14px;
      letter-spacing: -0.01em;
    }
    button.secondary,
    button.tab {
      background: transparent;
    }
    button.secondary:hover:not(:disabled),
    button.tab:hover:not(:disabled) {
      border-color: #41526a;
      background: #182231;
    }
    input,
    select,
    textarea {
      min-height: 42px;
      border-color: var(--border);
      border-radius: 10px;
      background: #0e151f;
      padding: 9px 12px;
      font-size: 14px;
      outline: none;
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }
    input:focus,
    select:focus,
    textarea:focus {
      border-color: #3caeb3;
      box-shadow: 0 0 0 3px rgb(43 185 189 / 0.12);
    }
    label {
      gap: 7px;
      font-size: 13px;
      font-weight: 650;
    }
    .app {
      height: 100vh;
      min-height: 0;
      grid-template-rows: var(--header-height) minmax(0, 1fr);
    }
    .topbar {
      position: relative;
      z-index: 50;
      min-height: var(--header-height);
      padding: 0 20px;
      border-color: #202b3a;
      background: #0a1018;
    }
    .brand-lockup,
    .project-context,
    .top-actions {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .brand-lockup h1 {
      font-size: 19px;
      letter-spacing: -0.02em;
      white-space: nowrap;
    }
    .project-context {
      padding-left: 16px;
      border-left: 1px solid var(--border);
    }
    .project-context .project-title {
      max-width: 220px;
      font-size: 14px;
    }
    .project-context .session-meta {
      flex-wrap: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mobile-only {
      display: none;
    }
    .icon-button {
      width: 40px;
      min-width: 40px;
      padding: 0;
      font-size: 18px;
    }
    .proxy-indicator {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      border: 0;
      background: transparent;
      padding: 0;
      color: var(--muted);
      font-weight: 650;
    }
    .proxy-indicator::before {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
      content: "";
    }
    .proxy-indicator.ok {
      color: var(--green);
    }
    .proxy-indicator.warn {
      color: var(--amber);
    }
    .proxy-indicator.error {
      color: var(--red);
    }
    .settings-menu,
    .session-tools,
    .advanced-settings {
      position: relative;
    }
    .settings-menu > summary,
    .session-tools > summary,
    .advanced-settings > summary {
      list-style: none;
      cursor: pointer;
    }
    .settings-menu > summary::-webkit-details-marker,
    .session-tools > summary::-webkit-details-marker,
    .advanced-settings > summary::-webkit-details-marker {
      display: none;
    }
    .settings-menu > summary {
      display: grid;
      width: 40px;
      height: 40px;
      place-items: center;
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--muted);
      font-size: 19px;
    }
    .settings-popover {
      position: absolute;
      top: calc(100% + 10px);
      right: 0;
      display: grid;
      width: min(360px, calc(100vw - 24px));
      gap: 12px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: #101721;
      box-shadow: 0 24px 60px rgb(0 0 0 / 0.36);
      padding: 14px;
    }
    .settings-statuses {
      display: grid;
      gap: 6px;
    }
    .settings-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .settings-actions button {
      min-width: 0;
    }
    .top-summary {
      display: grid;
      gap: 4px;
      margin: 0;
    }
    .top-summary .badge {
      min-height: 0;
      border: 0;
      background: transparent;
      padding: 0;
      white-space: normal;
    }
    .shell {
      position: relative;
      grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
      min-height: 0;
    }
    .sidebar {
      grid-template-rows: auto minmax(0, 1fr);
      min-height: 0;
      border-color: #202b3a;
      background: #0a1018;
    }
    .sidebar .section {
      border: 0;
    }
    .sidebar-controls {
      gap: 12px;
      padding: 16px;
    }
    .new-session-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
    }
    #new-chat-button {
      width: 100%;
      min-height: 46px;
      font-size: 15px;
    }
    #session-count {
      align-self: center;
      min-width: 28px;
      border: 0;
      background: transparent;
      padding: 0;
      color: var(--muted);
    }
    .session-search-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 42px;
      gap: 8px;
    }
    .session-tools > summary {
      display: grid;
      width: 42px;
      height: 42px;
      place-items: center;
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--muted);
      font-size: 17px;
    }
    .session-tools-panel {
      position: absolute;
      z-index: 30;
      top: calc(100% + 8px);
      right: 0;
      display: grid;
      width: 250px;
      max-height: min(620px, calc(100vh - 180px));
      gap: 12px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: #101721;
      box-shadow: 0 20px 50px rgb(0 0 0 / 0.36);
      padding: 14px;
    }
    .session-tools-panel .section {
      display: grid;
      gap: 10px;
      padding: 0;
    }
    .session-tools-panel #harness-list {
      max-height: 220px;
      overflow: auto;
      padding: 0;
    }
    .sidebar-scroll {
      padding: 4px 8px 18px;
    }
    .session-list {
      gap: 2px;
      padding: 0;
    }
    .group-title {
      margin: 16px 10px 7px;
      font-size: 12px;
      font-weight: 650;
      text-transform: none;
    }
    .session-row,
    .native-session-row,
    .harness-card {
      border-radius: 9px;
      padding: 10px 12px;
    }
    .session-row {
      position: relative;
      padding-right: 26px;
    }
    .session-row::after {
      position: absolute;
      top: 50%;
      right: 12px;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #59667a;
      content: "";
      transform: translateY(-50%);
    }
    .session-row.active::after {
      background: var(--accent-strong);
    }
    .session-row.active {
      border-color: #2d6e74;
      background: #121e29;
    }
    .session-title {
      font-size: 14px;
      font-weight: 650;
    }
    .session-meta {
      margin-top: 3px;
      font-size: 11px;
    }
    .session-meta span:nth-child(n + 3) {
      display: none;
    }
    .center {
      display: flex;
      min-height: 0;
      flex-direction: column;
      background: radial-gradient(circle at 55% 18%, #121e2d 0, #0c131d 42%, #0b1119 78%);
    }
    .config-section {
      position: relative;
      z-index: 30;
      width: min(960px, calc(100% - 48px));
      margin: 0 auto;
      padding: 34px 0 0;
      border: 0;
    }
    .workspace-welcome {
      display: none;
      margin: 34px auto 28px;
      text-align: center;
    }
    .workspace-welcome h2 {
      color: var(--text);
      font-size: clamp(30px, 3.2vw, 46px);
      font-weight: 730;
      letter-spacing: -0.035em;
      text-transform: none;
    }
    .workspace-welcome p {
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 16px;
    }
    body.new-session .workspace-welcome {
      display: block;
    }
    .quick-config {
      position: relative;
      display: grid;
      grid-template-columns: minmax(150px, 1fr) minmax(190px, 1.2fr) 128px 104px auto;
      align-items: end;
      border: 1px solid #314055;
      border-radius: 12px;
      background: rgb(15 23 34 / 0.78);
      backdrop-filter: blur(12px);
      padding: 7px;
    }
    .quick-config > label,
    .quick-config > fieldset {
      min-width: 0;
      padding: 0 7px;
    }
    .quick-config label > span,
    .quick-config legend {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
    }
    .quick-config input,
    .quick-config select,
    .quick-config .model-menu-button {
      min-height: 42px;
      border-color: transparent;
      background: transparent;
      box-shadow: none;
      font-weight: 650;
    }
    .quick-config input:hover,
    .quick-config select:hover,
    .quick-config .model-menu-button:hover:not(:disabled) {
      background: #182332;
    }
    .quick-config fieldset {
      align-self: stretch;
    }
    .quick-harness {
      order: 1;
    }
    .quick-model {
      order: 2;
    }
    .quick-mode {
      order: 3;
    }
    .quick-api {
      order: 4;
    }
    .quick-config > .advanced-control,
    .quick-api > .advanced-control {
      display: none;
    }
    .quick-config.advanced-open {
      grid-template-columns: minmax(150px, 1fr) minmax(190px, 1.2fr) 128px 104px auto;
    }
    .quick-config.advanced-open > .advanced-control {
      display: grid;
      order: 6;
      margin: 8px 7px 0;
    }
    .quick-config.advanced-open > .check-row {
      display: flex;
    }
    .quick-config.advanced-open > .warning,
    .quick-config.advanced-open > .details {
      display: block;
    }
    .quick-config.advanced-open .quick-api > .advanced-control {
      display: block;
    }
    .quick-config.advanced-open > .span-2 {
      grid-column: span 2;
    }
    .quick-config.advanced-open > .span-4 {
      grid-column: 1 / -1;
    }
    .advanced-settings-button {
      order: 5;
      min-height: 42px;
      border-color: transparent !important;
      border-left-color: var(--border) !important;
      border-radius: 0;
      color: var(--muted) !important;
      padding: 6px 10px;
    }
    .advanced-settings-button::after {
      margin-left: 7px;
      content: "+";
      font-size: 17px;
    }
    .advanced-settings-button[aria-expanded="true"]::after {
      content: "−";
    }
    .quick-config.advanced-open .advanced-settings-button {
      background: #172533;
      color: #7ce5e9 !important;
    }
    .api-mode-switch {
      display: grid;
      height: 100%;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-items: center;
      gap: 3px;
      border-left: 1px solid var(--border);
      padding-left: 8px;
    }
    .api-mode-switch .choice {
      justify-content: center;
      min-height: 34px;
      border-radius: 8px;
      color: var(--muted);
    }
    .api-mode-switch .choice:has(input:checked) {
      background: #173039;
      color: #7ce5e9;
    }
    .api-mode-switch input {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }
    .advanced-settings > summary {
      display: flex;
      min-height: 42px;
      align-items: center;
      justify-content: center;
      gap: 7px;
      border-left: 1px solid var(--border);
      color: var(--muted);
      font-weight: 650;
    }
    .advanced-settings > summary::after {
      content: "+";
      font-size: 17px;
    }
    .advanced-settings[open] > summary::after {
      content: "−";
    }
    .advanced-panel {
      position: absolute;
      z-index: 25;
      top: calc(100% + 10px);
      right: 0;
      left: 0;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      max-height: min(540px, calc(100vh - 260px));
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: #101721;
      box-shadow: 0 24px 60px rgb(0 0 0 / 0.4);
      padding: 16px;
    }
    .advanced-panel[hidden] {
      display: none;
    }
    .advanced-panel .span-2 {
      grid-column: span 2;
    }
    .advanced-panel .span-4,
    .advanced-panel .advanced-full {
      grid-column: 1 / -1;
    }
    .advanced-panel .route-recommendation {
      padding-top: 4px;
      border-top: 1px solid var(--border);
    }
    .chat-scroll {
      flex: 1 1 auto;
      min-height: 0;
      padding: 10px 0;
    }
    .message-list {
      width: min(960px, calc(100% - 48px));
      margin: 0 auto;
      padding: 18px 0;
    }
    .message-list .empty {
      display: none;
    }
    body.new-session .chat-scroll {
      flex: 0 0 auto;
      padding: 0;
    }
    .message {
      max-width: min(760px, 88%);
      border-radius: 12px;
      padding: 13px 15px;
    }
    .message.assistant,
    .message.tool {
      position: relative;
      width: min(900px, 100%);
      max-width: 100%;
      justify-self: start;
      border: 0;
      background: transparent;
      padding: 8px 12px 18px 36px;
    }
    .message.assistant::before,
    .message.tool::before {
      position: absolute;
      top: 18px;
      bottom: 0;
      left: 12px;
      width: 1px;
      background: linear-gradient(180deg, #4fd1c5 0, #2c5f67 52%, transparent 100%);
      content: "";
    }
    .message.assistant::after,
    .message.tool::after {
      position: absolute;
      top: 14px;
      left: 8px;
      width: 9px;
      height: 9px;
      border: 2px solid #0d151f;
      border-radius: 50%;
      background: #5eead4;
      box-shadow: 0 0 0 3px rgb(45 212 191 / 0.12);
      content: "";
    }
    .message.error::after {
      background: var(--red);
      box-shadow: 0 0 0 3px rgb(248 113 113 / 0.12);
    }
    .message-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px 14px;
      margin-bottom: 8px;
    }
    .message-header .message-meta {
      margin: 0;
    }
    .live-status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: #80e5dc;
      font-size: 11px;
      font-weight: 750;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .live-status::before {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 0 4px rgb(45 212 191 / 0.1);
      content: "";
      animation: live-pulse 1.35s ease-in-out infinite;
    }
    .live-status.failed {
      color: var(--red);
    }
    .live-status.complete {
      color: var(--green);
    }
    .live-status.complete::before,
    .live-status.failed::before {
      animation: none;
    }
    @keyframes live-pulse {
      50% {
        opacity: 0.35;
        transform: scale(0.78);
      }
    }
    .live-cursor {
      display: inline-block;
      width: 2px;
      height: 1.05em;
      margin-left: 3px;
      background: #6ee7df;
      vertical-align: -0.16em;
      animation: cursor-blink 900ms steps(1, end) infinite;
    }
    @keyframes cursor-blink {
      50% {
        opacity: 0;
      }
    }
    .markdown-body {
      min-width: 0;
      color: #e8edf4;
      font-size: 15px;
      line-height: 1.68;
      overflow-wrap: anywhere;
      white-space: normal;
    }
    .message.user .markdown-body {
      color: #effcf9;
    }
    .markdown-body > :first-child {
      margin-top: 0;
    }
    .markdown-body > :last-child {
      margin-bottom: 0;
    }
    .markdown-body h1,
    .markdown-body h2,
    .markdown-body h3,
    .markdown-body h4,
    .markdown-body h5,
    .markdown-body h6 {
      margin: 1.35em 0 0.55em;
      color: #f7fafc;
      font-weight: 720;
      letter-spacing: -0.018em;
      line-height: 1.25;
      text-transform: none;
    }
    .markdown-body h1 {
      font-size: 1.7em;
    }
    .markdown-body h2 {
      font-size: 1.42em;
    }
    .markdown-body h3 {
      font-size: 1.2em;
    }
    .markdown-body h4,
    .markdown-body h5,
    .markdown-body h6 {
      font-size: 1.05em;
    }
    .markdown-body p,
    .markdown-body ul,
    .markdown-body ol,
    .markdown-body blockquote,
    .markdown-body pre {
      margin: 0.72em 0;
    }
    .markdown-body ul,
    .markdown-body ol {
      padding-left: 1.55em;
    }
    .markdown-body li + li {
      margin-top: 0.28em;
    }
    .markdown-body blockquote {
      border-left: 3px solid #3b6d75;
      color: #afbbc9;
      padding: 0.08em 0 0.08em 1em;
    }
    .markdown-body code {
      border: 1px solid #2b394a;
      border-radius: 5px;
      background: #111c28;
      color: #9de8e1;
      padding: 0.12em 0.36em;
      font-size: 0.9em;
    }
    .markdown-body pre {
      max-height: 520px;
      border: 1px solid #263446;
      border-radius: 10px;
      background: #080e15;
      padding: 13px 15px;
      color: #d8e1eb;
      line-height: 1.55;
    }
    .markdown-body pre code {
      border: 0;
      background: transparent;
      color: inherit;
      padding: 0;
      font-size: 12.5px;
    }
    .code-block {
      overflow: hidden;
      margin: 0.82em 0;
      border: 1px solid #263446;
      border-radius: 10px;
      background: #080e15;
    }
    .code-block-header {
      display: flex;
      min-height: 32px;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid #263446;
      background: #101923;
      color: #718198;
      padding: 5px 8px 5px 12px;
      font-size: 10px;
      font-weight: 780;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .code-block-copy {
      min-height: 22px;
      border-color: transparent;
      background: transparent;
      color: #8ca0b7;
      padding: 2px 6px;
      font-size: 10px;
    }
    .code-block-copy:hover:not(:disabled) {
      border-color: #34455a;
      background: #172331;
      color: #d5e2ef;
    }
    .code-block pre {
      margin: 0;
      border: 0;
      border-radius: 0;
    }
    .markdown-body a {
      color: #67e8df;
      text-decoration-color: rgb(103 232 223 / 0.45);
      text-underline-offset: 3px;
    }
    .markdown-body a:hover {
      text-decoration-color: currentColor;
    }
    .tool-call-stack,
    .execution-output-stack {
      display: grid;
      gap: 7px;
      margin-top: 13px;
    }
    .execution-rail-label {
      color: #7f8ea2;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.09em;
      text-transform: uppercase;
    }
    .tool-call-card {
      overflow: hidden;
      border: 1px solid #29384a;
      border-radius: 9px;
      background: rgb(12 20 29 / 0.88);
    }
    .tool-call-card[open] {
      border-color: #365365;
      background: #0e1823;
    }
    .tool-call-card > summary {
      display: flex;
      min-height: 40px;
      align-items: center;
      gap: 9px;
      list-style: none;
      padding: 8px 10px;
      cursor: pointer;
    }
    .tool-call-card > summary::-webkit-details-marker {
      display: none;
    }
    .tool-status-dot {
      flex: 0 0 auto;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--muted);
    }
    .tool-status-dot.running {
      background: var(--amber);
      box-shadow: 0 0 0 4px rgb(251 191 36 / 0.09);
    }
    .tool-status-dot.succeeded {
      background: var(--green);
    }
    .tool-status-dot.completed,
    .tool-status-dot.requested {
      background: var(--green);
    }
    .tool-status-dot.failed {
      background: var(--red);
    }
    .tool-call-name {
      min-width: 0;
      flex: 1 1 auto;
      overflow: hidden;
      color: #dce6f1;
      font-size: 12px;
      font-weight: 760;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tool-call-status {
      color: #7f8ea2;
      font-size: 10px;
      font-weight: 750;
      text-transform: uppercase;
    }
    .tool-call-body {
      display: grid;
      gap: 8px;
      border-top: 1px solid #243142;
      padding: 10px;
    }
    .tool-call-section {
      display: grid;
      gap: 4px;
    }
    .tool-call-section > span {
      color: #718095;
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .tool-call-section pre {
      max-height: 260px;
      border-radius: 6px;
      background: #080d13;
      color: #cbd5e1;
      padding: 9px;
      font-size: 11px;
    }
    .usage-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 12px;
    }
    .token-chip {
      display: inline-flex;
      align-items: baseline;
      gap: 5px;
      border: 1px solid #2a3c4f;
      border-radius: 999px;
      background: #101b27;
      color: #b8c5d4;
      padding: 3px 8px;
      font-size: 11px;
      font-variant-numeric: tabular-nums;
    }
    .token-chip strong {
      color: #72ddd6;
      font-size: 9px;
      letter-spacing: 0.02em;
    }
    .run-summary {
      min-height: 160px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: linear-gradient(155deg, #101923 0, #0a1017 100%);
      color: #dbe5ef;
      padding: 13px;
    }
    .run-summary-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 13px;
    }
    .run-summary-title {
      display: grid;
      gap: 3px;
    }
    .run-summary-title strong {
      color: #f1f5f9;
      font-size: 14px;
    }
    .run-summary-title span {
      color: #718096;
      font-size: 10px;
      overflow-wrap: anywhere;
    }
    .run-summary-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .run-summary-field {
      min-width: 0;
      border: 1px solid #223043;
      border-radius: 7px;
      background: rgb(10 16 24 / 0.68);
      padding: 8px;
    }
    .run-summary-field span {
      display: block;
      color: #66758a;
      font-size: 9px;
      font-weight: 800;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }
    .run-summary-field strong {
      display: block;
      overflow: hidden;
      margin-top: 3px;
      color: #dbe6f1;
      font-size: 11px;
      font-weight: 650;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .run-summary-footer {
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin-top: 12px;
      color: #718096;
      font-size: 10px;
    }
    .composer {
      width: min(960px, calc(100% - 48px));
      margin: 0 auto 22px;
      gap: 10px;
      border: 1px solid #314055;
      border-radius: 14px;
      background: rgb(17 25 36 / 0.94);
      box-shadow: 0 18px 46px rgb(0 0 0 / 0.22);
      padding: 14px;
    }
    body.new-session .composer {
      margin-top: 20px;
      margin-bottom: 8px;
    }
    .composer-main label {
      color: transparent;
      font-size: 0;
    }
    #prompt-input {
      min-height: 112px;
      border: 0;
      background: transparent;
      padding: 8px;
      color: var(--text);
      font-size: 16px;
      line-height: 1.55;
      box-shadow: none;
    }
    #prompt-input::placeholder {
      color: #68768b;
    }
    .composer-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .composer-actions,
    .composer-utilities {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .composer-more {
      position: relative;
    }
    .composer-more > summary {
      display: grid;
      min-height: 38px;
      place-items: center;
      list-style: none;
      border: 1px solid transparent;
      border-radius: 9px;
      color: var(--muted);
      padding: 7px 9px;
      cursor: pointer;
      font-weight: 650;
    }
    .composer-more > summary::-webkit-details-marker {
      display: none;
    }
    .composer-more > summary:hover {
      border-color: var(--border);
      color: var(--text);
    }
    .composer-more-menu {
      position: absolute;
      z-index: 24;
      bottom: calc(100% + 8px);
      left: 0;
      display: grid;
      width: 150px;
      gap: 4px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #101721;
      box-shadow: 0 16px 38px rgb(0 0 0 / 0.34);
      padding: 6px;
    }
    .composer-more-menu button {
      width: 100%;
      justify-content: flex-start;
      text-align: left;
    }
    #run-button {
      min-width: 92px;
    }
    .utility-action {
      min-height: 34px;
      border-color: transparent !important;
      color: var(--muted) !important;
      padding: 6px 8px;
    }
    .attachment-toolbar {
      min-width: 0;
    }
    #attachment-status {
      max-width: 250px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .example-prompts {
      display: none;
      width: min(700px, calc(100% - 48px));
      margin: 12px auto 24px;
      text-align: center;
    }
    body.new-session .example-prompts {
      display: grid;
      gap: 8px;
    }
    .example-prompts p {
      margin: 0 0 2px;
      color: var(--muted);
    }
    .example-prompt {
      min-height: 0;
      border: 0;
      background: transparent;
      color: #5fd7dc;
      padding: 3px;
      font-weight: 500;
    }
    .example-prompt:hover:not(:disabled) {
      background: transparent;
      color: #8be9ec;
      text-decoration: underline;
    }
    .details-toggle {
      position: fixed;
      z-index: 41;
      right: 0;
      bottom: 44%;
      min-height: 126px;
      border-color: var(--border);
      border-right: 0;
      border-radius: 12px 0 0 12px;
      background: #111a26;
      color: var(--muted);
      padding: 10px 8px;
      writing-mode: vertical-rl;
    }
    .details-toggle:hover:not(:disabled) {
      border-color: #3d586f;
      background: #172231;
      color: var(--text);
    }
    .inspector {
      position: fixed;
      z-index: 70;
      top: 0;
      right: 0;
      bottom: 0;
      display: grid;
      width: min(520px, calc(100vw - 36px));
      min-height: 0;
      grid-template-rows: auto minmax(0, 1fr);
      border: 0;
      border-left: 1px solid var(--border);
      background: #0f1620;
      box-shadow: -20px 0 70px rgb(0 0 0 / 0.42);
      transform: translateX(105%);
      transition: transform 180ms ease;
    }
    body.inspector-open .inspector {
      transform: translateX(0);
    }
    .inspector-header {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-bottom: 1px solid var(--border);
    }
    .inspector-title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .inspector-title-row h2 {
      color: var(--text);
      font-size: 17px;
      text-transform: none;
    }
    .inspector-backdrop,
    .sidebar-backdrop {
      position: fixed;
      z-index: 60;
      inset: 0;
      display: none;
      border: 0;
      border-radius: 0;
      background: rgb(0 0 0 / 0.54) !important;
      color: transparent !important;
      padding: 0;
    }
    .inspector-backdrop:hover,
    .sidebar-backdrop:hover {
      background: rgb(0 0 0 / 0.54) !important;
    }
    body.inspector-open .inspector-backdrop {
      display: block;
    }
    .inspector-scroll {
      min-height: 0;
    }
    .inspector-body {
      gap: 14px;
      padding: 14px;
    }
    .tabs {
      display: flex;
      flex-wrap: nowrap;
      gap: 4px;
      overflow-x: auto;
      padding-bottom: 5px;
    }
    button.tab {
      flex: 0 0 auto;
      min-height: 34px;
      border-color: transparent;
      border-radius: 8px;
      padding: 6px 9px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    button.tab.active {
      border-color: transparent;
      background: #173039;
      color: #7ce5e9;
    }
    .mono-panel {
      border-radius: 10px;
    }
    @media (max-width: 980px) {
      :root {
        --sidebar-width: 252px;
      }
      .quick-config {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .quick-config.advanced-open {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .quick-config > * {
        border-bottom: 1px solid var(--border);
      }
      .quick-config > *:nth-last-child(-n + 2) {
        border-bottom: 0;
      }
      .api-mode-switch,
      .advanced-settings > summary,
      .advanced-settings-button {
        border-left: 0;
      }
      .advanced-panel {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 720px) {
      :root {
        --header-height: 64px;
      }
      body {
        overflow: hidden;
      }
      .topbar {
        display: flex;
        width: 100%;
        padding: 0 12px;
      }
      .mobile-only {
        display: inline-grid;
      }
      .brand-lockup {
        gap: 9px;
      }
      .brand-lockup h1 {
        font-size: 16px;
      }
      .project-context,
      .proxy-indicator span,
      .top-actions > .proxy-indicator {
        display: none;
      }
      .shell {
        display: block;
        width: 100%;
        max-width: 100%;
        min-height: 0;
      }
      .sidebar {
        position: fixed;
        z-index: 70;
        top: 0;
        bottom: 0;
        left: 0;
        display: grid;
        width: min(330px, calc(100vw - 44px));
        min-height: 0;
        border-right: 1px solid var(--border);
        box-shadow: 20px 0 70px rgb(0 0 0 / 0.46);
        transform: translateX(-105%);
        transition: transform 180ms ease;
      }
      body.sidebar-open .sidebar {
        transform: translateX(0);
      }
      body.sidebar-open .sidebar-backdrop {
        display: block;
      }
      .center {
        height: calc(100vh - var(--header-height));
        min-height: 0;
      }
      body.new-session .center {
        overflow-y: auto;
        padding-bottom: 66px;
      }
      .config-section,
      .message-list,
      .composer {
        width: calc(100% - 28px);
      }
      .config-section {
        padding-top: 16px;
      }
      .workspace-welcome {
        margin: 14px auto 20px;
        text-align: left;
      }
      .workspace-welcome h2 {
        font-size: 30px;
        line-height: 1.08;
      }
      .workspace-welcome p {
        font-size: 14px;
        line-height: 1.45;
      }
      .quick-config {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .quick-config.advanced-open {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        max-height: calc(100vh - 96px);
        overflow: auto;
      }
      .quick-config > label,
      .quick-config > fieldset,
      .quick-config > details,
      .quick-config > button {
        padding: 3px;
      }
      .quick-config input,
      .quick-config select,
      .quick-config .model-menu-button {
        font-size: 13px;
      }
      #model-input {
        font-size: 12px;
      }
      .advanced-panel {
        position: fixed;
        z-index: 80;
        top: var(--header-height);
        right: 8px;
        bottom: 8px;
        left: 8px;
        display: grid;
        grid-template-columns: 1fr;
        max-height: none;
        align-content: start;
      }
      .advanced-panel .span-2,
      .advanced-panel .span-4,
      .advanced-panel .advanced-full {
        grid-column: auto;
      }
      .chat-scroll {
        padding: 0;
      }
      .composer {
        margin-bottom: 12px;
        padding: 10px;
      }
      body.new-session .composer {
        margin-top: 14px;
      }
      #prompt-input {
        min-height: 126px;
        font-size: 15px;
      }
      .composer-footer {
        display: grid;
        gap: 10px;
      }
      .composer-actions {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1.8fr);
        order: -1;
      }
      #compare-button,
      #run-button {
        width: 100%;
        min-height: 44px;
      }
      .composer-utilities {
        justify-content: space-between;
      }
      .example-prompts {
        width: calc(100% - 36px);
        margin-top: 8px;
        text-align: left;
      }
      .example-prompt {
        min-height: 36px;
        border-bottom: 1px solid #202b3a;
        text-align: left;
      }
      .details-toggle {
        right: 0;
        bottom: 0;
        left: 0;
        width: 100%;
        min-height: 54px;
        border-right: 0;
        border-bottom: 0;
        border-left: 0;
        border-radius: 12px 12px 0 0;
        background: #111a26;
        padding: 10px 14px;
        writing-mode: horizontal-tb;
      }
      .inspector {
        width: 100vw;
      }
      .native-history-modal,
      .preflight-modal {
        padding: 8px;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      *,
      *::before,
      *::after {
        scroll-behavior: auto !important;
        transition-duration: 0.01ms !important;
      }
      .live-status::before,
      .live-cursor {
        animation: none !important;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand-lockup">
        <button id="session-drawer-button" class="secondary icon-button mobile-only" type="button" aria-label="Open sessions">
          <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M4 6h16M4 12h16M4 18h10"/>
          </svg>
        </button>
        <h1>gpt2giga Harness</h1>
        <div class="project-context">
          <div id="project-name" class="project-title">Loading...</div>
          <div id="project-meta" class="session-meta"></div>
        </div>
      </div>
      <div class="top-actions">
        <span id="proxy-status" class="proxy-indicator warn">Proxy: checking</span>
        <details class="settings-menu">
          <summary aria-label="Open settings">
            <svg aria-hidden="true" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21h-4v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H3v-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3.1V3h4v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9A1.7 1.7 0 0 0 20.9 10h.1v4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>
            </svg>
          </summary>
          <div class="settings-popover">
            <div class="settings-statuses">
              <div id="project-status" class="status-line">Loading project...</div>
              <div class="top-summary">
                <span id="current-model-badge" class="badge info">Model: loading</span>
                <span id="current-route-badge" class="badge info">Route: /v2/chat/completions</span>
                <span id="model-status" class="badge">Models: loading</span>
              </div>
            </div>
            <div class="settings-actions">
              <button id="init-project-button" class="secondary" type="button" hidden>Init project</button>
              <button id="refresh-health-button" class="secondary" type="button">Refresh proxy</button>
              <button id="refresh-models-button" class="secondary" type="button">Refresh models</button>
            </div>
          </div>
        </details>
      </div>
    </header>

    <main class="shell">
      <aside class="sidebar" aria-label="Session history">
        <div class="section sidebar-controls">
          <div class="new-session-row">
            <button id="new-chat-button" type="button">+ New session</button>
            <span id="session-count" class="badge info">0</span>
          </div>
          <div class="session-search-row">
            <input id="session-search" placeholder="Search sessions..." autocomplete="off">
            <details class="session-tools">
              <summary aria-label="Filters and history">
                <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                  <path d="M4 7h10M18 7h2M4 17h2M10 17h10M8 4v6M8 14v6M16 4v6M16 14v6"/>
                </svg>
              </summary>
              <div class="session-tools-panel">
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
                <div class="section">
                  <div class="inline-actions">
                    <h2>Native sessions</h2>
                    <span id="native-count" class="badge info">0</span>
                  </div>
                  <button id="sync-native-button" class="secondary" type="button">Sync native history</button>
                  <button id="open-native-history-button" class="secondary" type="button">Browse history</button>
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
            </details>
          </div>
        </div>
        <div class="sidebar-scroll">
          <div id="session-list" class="session-list"></div>
        </div>
      </aside>

      <section class="center" aria-label="Chat and run surface">
        <div class="section config-section">
          <div id="workspace-welcome" class="workspace-welcome">
            <h2>What do you want to work on?</h2>
            <p>Ask a question, plan a task, or describe what you would like to build.</p>
          </div>
          <div class="config-grid quick-config">
            <label class="quick-harness"><span>Harness</span>
              <select id="harness-select"></select>
            </label>
            <label class="span-2 advanced-control">Arena harnesses
              <select id="arena-harness-select" multiple size="4" aria-label="Arena harnesses"></select>
            </label>
            <label class="advanced-control">Invocation
              <select id="invocation-select">
                <option value="headless">Headless</option>
                <option value="native">Native</option>
              </select>
            </label>
            <label class="quick-model"><span>Model</span>
              <div id="model-picker" class="model-picker">
                <input id="model-input" placeholder="GigaChat-2-Max" autocomplete="off" aria-controls="model-list">
                <button id="model-menu-button" class="model-menu-button" type="button" aria-label="Show model suggestions">
                  <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m7 10 5 5 5-5"/></svg>
                </button>
                <div id="model-list" class="model-list" role="listbox" hidden></div>
              </div>
            </label>
            <fieldset class="quick-api" aria-label="API mode"><legend>API mode</legend>
              <div class="api-mode-switch">
                <label class="choice" for="api-mode-v2">
                  <input id="api-mode-v2" name="api-mode" type="radio" value="v2" checked>
                  /v2
                </label>
                <label class="choice" for="api-mode-v1">
                  <input id="api-mode-v1" name="api-mode" type="radio" value="v1">
                  /v1
                </label>
              </div>
              <div id="route-note" class="hint advanced-control">Current route: /v2/chat/completions</div>
            </fieldset>
            <label class="quick-mode"><span>Mode</span>
              <select id="mode-select">
                <option value="plan">plan</option>
                <option value="read">read</option>
                <option value="edit">edit</option>
              </select>
            </label>
            <label class="advanced-control">Workspace policy
              <select id="workspace-policy-select">
                <option value="auto">auto</option>
                <option value="current">current</option>
                <option value="worktree">worktree</option>
                <option value="temp_copy">temp copy</option>
              </select>
            </label>
            <label class="advanced-control">Capability
              <select id="capability-select"></select>
            </label>
            <label class="span-2 advanced-control">Workspace
              <input id="workspace-input" placeholder="." autocomplete="off">
            </label>
            <div class="check-row advanced-control">
              <label class="choice" for="dry-run-checkbox">
                <input id="dry-run-checkbox" type="checkbox">
                dry run
              </label>
              <label class="choice" for="stream-checkbox">
                <input id="stream-checkbox" type="checkbox">
                stream
              </label>
            </div>
            <div id="harness-warning" class="warning span-4 advanced-control"></div>
            <div id="harness-details" class="details span-4 advanced-control"></div>
            <div id="route-recommendation" class="route-recommendation span-4 advanced-control">
              <div class="inline-actions">
                <span id="route-recommendation-badge" class="badge info">Recommended: pending</span>
                <button id="apply-route-recommendation-button" class="secondary" type="button" disabled>Apply recommendation</button>
              </div>
              <div id="route-recommendation-reasons" class="details">Type a prompt or attach context to refresh the recommendation.</div>
            </div>
            <div class="span-4 advanced-control">
              <div class="inline-actions">
                <h2>Presets</h2>
                <span id="preset-status" class="badge info">Presets: loading</span>
              </div>
              <div id="preset-list" class="preset-list"></div>
            </div>
            <button id="advanced-settings-button" class="advanced-settings-button secondary" type="button" aria-expanded="false">Advanced</button>
          </div>
        </div>
        <div id="output-panel" class="chat-scroll">
          <div id="message-list" class="message-list" aria-live="polite" aria-relevant="additions text"></div>
        </div>
        <div id="composer" class="composer">
          <div class="composer-main">
            <label>Prompt
              <textarea id="prompt-input" placeholder="Ask, plan, or describe a task..." spellcheck="true"></textarea>
            </label>
          </div>
          <div id="workspace-file-menu" class="workspace-file-menu" hidden></div>
          <div id="attachment-list" class="attachment-list" aria-live="polite"></div>
          <div class="composer-footer">
            <div class="composer-utilities">
              <div class="attachment-toolbar">
                <input id="attachment-file-input" type="file" multiple hidden>
                <button id="attach-file-button" class="secondary" type="button">Attach</button>
                <span id="attachment-status" class="status-line">No attachments</span>
              </div>
              <details class="composer-more">
                <summary aria-label="More composer actions">More</summary>
                <div class="composer-more-menu">
                  <button id="copy-cli-button" class="secondary utility-action" type="button">Copy CLI</button>
                  <button id="copy-curl-button" class="secondary utility-action" type="button">Copy curl</button>
                  <button id="reset-button" class="secondary utility-action" type="button">Reset</button>
                </div>
              </details>
            </div>
            <div class="composer-actions">
              <button id="compare-button" class="secondary" type="button">Compare</button>
              <button id="run-button" type="button">Run</button>
              <button id="cancel-run-button" class="danger" type="button" hidden>Cancel</button>
            </div>
          </div>
        </div>
        <div class="example-prompts" aria-label="Example prompts">
          <p>Try an example to get started</p>
          <button class="example-prompt" type="button">Explain this codebase architecture</button>
          <button class="example-prompt" type="button">Write tests for the selected function</button>
          <button class="example-prompt" type="button">Refactor this module for clarity</button>
        </div>
      </section>

      <button id="details-toggle-button" class="details-toggle" type="button" aria-expanded="false">Run details</button>

      <aside class="inspector" aria-label="Inspector">
        <div class="inspector-header">
          <div class="inspector-title-row">
            <h2>Run details</h2>
            <button id="close-inspector-button" class="secondary icon-button" type="button" aria-label="Close run details">×</button>
          </div>
          <div class="inline-actions">
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
              <button class="tab" type="button" data-tab="editor">Editor</button>
              <button class="tab" type="button" data-tab="attachments">Attachments</button>
              <button class="tab" type="button" data-tab="memory">Memory</button>
              <button class="tab" type="button" data-tab="tools">Tools</button>
              <button class="tab" type="button" data-tab="evals">Evals</button>
              <button class="tab" type="button" data-tab="native">Native</button>
              <button class="tab" type="button" data-tab="storage">Storage</button>
            </div>
            <div id="run-panel" class="run-summary tab-panel active">No run selected.</div>
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
                <button id="open-run-terminal-button" class="secondary" type="button" disabled>Open terminal</button>
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
            <div id="editor-panel" class="mono-panel tab-panel">
              <div class="inline-actions">
                <button id="open-editor-workspace-button" type="button" disabled>Open workspace</button>
                <button id="open-editor-run-button" class="secondary" type="button" disabled>Open run workspace</button>
                <button id="open-editor-diff-button" class="secondary" type="button" disabled>Open diff</button>
                <button id="open-editor-terminal-button" class="secondary" type="button" disabled>Open run terminal</button>
              </div>
              <div class="inline-actions">
                <input id="open-editor-file-input" placeholder="workspace file" autocomplete="off">
                <button id="open-editor-file-button" class="secondary" type="button" disabled>Open file</button>
              </div>
              <div class="inline-actions">
                <button id="copy-session-open-command-button" class="secondary" type="button" disabled>Copy session link</button>
                <button id="copy-run-open-command-button" class="secondary" type="button" disabled>Copy run link</button>
              </div>
              <pre id="editor-text">No editor action yet.</pre>
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
      <button id="inspector-backdrop" class="inspector-backdrop" type="button" aria-label="Close run details"></button>
      <button id="sidebar-backdrop" class="sidebar-backdrop" type="button" aria-label="Close sessions"></button>
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
      headlessEventSourceRunId: null,
      liveRuns: new Map(),
      renderedSessionId: null,
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
        badge.className = "proxy-indicator ok";
        badge.textContent = `Proxy: ${result.data.path || "ok"}`;
      } else {
        badge.className = "proxy-indicator warn";
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
        const validation = item.validation || {};
        const plugin = spec.plugin_metadata || {};
        const capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.slice(0, 3) : [];
        const configFields = simpleConfigFields(plugin.config_schema || spec.config_schema || {});
        const extras = [];
        if (spec.supports_workspace) extras.push("workspace");
        if (spec.supports_streaming) extras.push("stream");
        if (configFields.length) extras.push(`config: ${configFields.length}`);
        if (validation.ok === false) extras.push("validate");
        const recommended = state.routeRecommendation && state.routeRecommendation.harness_id === spec.id;
        const icon = plugin.icon || spec.icon || "";
        const card = document.createElement("div");
        card.className = "harness-card";
        card.innerHTML = `
          <div class="session-title">${icon ? `<span>${escapeHtml(icon)}</span> ` : ""}${escapeHtml(spec.title || spec.id)}</div>
          <div class="session-meta">
            <span>${escapeHtml(spec.id || "")}</span>
            <span>${escapeHtml(spec.kind || "")}</span>
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
      renderHarnessDetails(item);
      renderRouteRecommendation(state.routeRecommendation);
      loadNativeSessions(false);
      persistProjectState();
    }

    function renderHarnessDetails(item) {
      const spec = item.spec || {};
      const plugin = spec.plugin_metadata || {};
      const validation = item.validation || {};
      const details = byId("harness-details");
      details.textContent = "";
      const capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.join(", ") : "";
      const summary = document.createElement("div");
      summary.textContent = `${spec.title || spec.id} - ${spec.description || ""}${capabilities ? " Capabilities: " + capabilities : ""}`;
      details.appendChild(summary);
      const fields = simpleConfigFields(plugin.config_schema || spec.config_schema || {});
      if (fields.length) {
        const form = document.createElement("div");
        form.className = "config-grid";
        for (const field of fields) {
          const label = document.createElement("label");
          label.textContent = field.title || field.name;
          const input = document.createElement(field.type === "array" ? "textarea" : "input");
          input.name = `harness-config-${field.name}`;
          input.disabled = true;
          input.placeholder = field.description || "";
          if (field.type === "boolean") input.type = "checkbox";
          else if (field.type === "integer" || field.type === "number") input.type = "number";
          else input.type = "text";
          if (field.default !== undefined && field.type !== "boolean") input.value = String(field.default);
          if (field.default !== undefined && field.type === "boolean") input.checked = Boolean(field.default);
          label.appendChild(input);
          form.appendChild(label);
        }
        details.appendChild(form);
      }
      if (validation.ok === false && Array.isArray(validation.issues)) {
        const warnings = validation.issues
          .filter((issue) => issue.level === "error" || issue.level === "warning")
          .slice(0, 3)
          .map((issue) => issue.field ? `${issue.field}: ${issue.message}` : issue.message);
        if (warnings.length) {
          const warning = document.createElement("div");
          warning.className = "warning";
          warning.textContent = warnings.join(" ");
          details.appendChild(warning);
        }
      }
    }

    function simpleConfigFields(schema) {
      if (!schema || typeof schema !== "object") return [];
      const properties = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
      const required = Array.isArray(schema.required) ? new Set(schema.required) : new Set();
      const fields = [];
      for (const [name, value] of Object.entries(properties)) {
        if (!value || typeof value !== "object") continue;
        const type = value.type || "string";
        if (!["string", "integer", "number", "boolean", "array"].includes(type)) continue;
        fields.push({
          name,
          type,
          title: value.title || name,
          description: value.description || "",
          default: value.default,
          required: required.has(name)
        });
      }
      return fields.slice(0, 12);
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
      restoreTerminalPartialDrafts();
      renderAll();
      resumeActiveHeadlessRun();
      setSidebarOpen(false);
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

    function applyRunDefaults(payload) {
      if (payload.harness_id) selectHarness(payload.harness_id);
      byId("model-input").value = payload.model || state.defaults.default_model || "";
      renderModelList();
      const mode = payload.api_mode || state.defaults.default_api_mode || "v2";
      byId(`api-mode-${mode}`).checked = true;
      byId("mode-select").value = payload.mode || "plan";
      byId("workspace-input").value = payload.workspace || "";
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
      setAdvancedSettings(false);
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
      setAdvancedSettings(false);
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
        ensureLiveRun(body.run.id, body.run);
        if (state.currentSessionId) {
          await loadSession(state.currentSessionId);
          applyRunDefaults(payload);
          persistProjectState({ last_selected_session: state.currentSessionId });
        }
        const initialEvents = Array.isArray(body.events) ? body.events : [];
        for (const event of [...eventsForRun(body.run.id), ...initialEvents]) consumeLiveEvent(event);
        renderLiveDraft(body.run.id);
        renderRunSummary(runForId(body.run.id) || body.run, state.currentBundle && state.currentBundle.events ? state.currentBundle.events : initialEvents);
        openHeadlessEventStream(body.run.id);
      } catch (error) {
        setText("run-panel", "Stream start failed.");
        setHeadlessRunning(false);
      }
    }

    function openHeadlessEventStream(runId) {
      if (state.headlessEventSource && state.headlessEventSourceRunId === runId) return;
      closeHeadlessEventSource();
      if (!window.EventSource) {
        setText("run-panel", "This browser does not support EventSource.");
        setHeadlessRunning(false);
        return;
      }
      const lastEventId = latestEventIdForRun(runId);
      const query = lastEventId ? `?after_id=${encodeURIComponent(lastEventId)}` : "";
      const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events/stream${query}`);
      state.headlessEventSource = source;
      state.headlessEventSourceRunId = runId;
      source.onmessage = (event) => {
        if (!state.activeHeadlessRun || state.activeHeadlessRun.id !== runId) return;
        let payload = {};
        try {
          payload = JSON.parse(event.data || "{}");
        } catch (error) {
          payload = { type: "warning", message: "Invalid event payload", payload: {} };
        }
        appendStreamEvent(payload);
        if (payload.type === "run_finished") {
          finishHeadlessStream(runId);
        }
      };
      source.onerror = () => {
        const run = state.activeHeadlessRun || {};
        if (run.id === runId && ["succeeded", "failed", "canceled"].includes(run.status)) {
          finishHeadlessStream(runId);
        }
      };
    }

    function appendStreamEvent(event) {
      if (!state.currentBundle) state.currentBundle = { events: [], runs: [] };
      if (!Array.isArray(state.currentBundle.events)) state.currentBundle.events = [];
      const exists = event.id && state.currentBundle.events.some((item) => item.id === event.id);
      if (!exists) state.currentBundle.events.push(event);
      const draft = consumeLiveEvent(event);
      renderEvents(state.currentBundle.events);
      if (event.type === "run_finished" && event.payload && event.payload.status) {
        state.activeHeadlessRun = {
          ...(state.activeHeadlessRun || {}),
          status: event.payload.status
        };
      }
      if (draft) {
        renderLiveDraft(draft.runId);
        renderRunSummary(runForId(draft.runId) || state.activeHeadlessRun, state.currentBundle.events);
      }
      if (event.type === "error" || event.type === "run_canceled") showTab("events");
    }

    async function finishHeadlessStream(runId) {
      if (!runId || !state.activeHeadlessRun || state.activeHeadlessRun.id !== runId) return;
      closeHeadlessEventSource();
      setHeadlessRunning(false);
      if (state.currentSessionId) {
        await loadSession(state.currentSessionId);
        await loadSessions();
      }
      const draft = state.liveRuns.get(runId);
      if (persistedMessageForRun(runId) && !preserveTerminalPartialDraft(draft)) state.liveRuns.delete(runId);
      state.activeHeadlessRun = null;
      byId("prompt-input").value = "";
      state.attachments = [];
      renderAttachments();
    }

    function closeHeadlessEventSource() {
      if (state.headlessEventSource) {
        state.headlessEventSource.close();
        state.headlessEventSource = null;
      }
      state.headlessEventSourceRunId = null;
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

    function normalizeMessageRole(value) {
      const role = String(value || "assistant").toLowerCase();
      return ["user", "assistant", "error", "tool"].includes(role) ? role : "assistant";
    }

    function isChatNearBottom() {
      const panel = byId("output-panel");
      return panel.scrollHeight - panel.scrollTop - panel.clientHeight < 96;
    }

    function scrollChatToBottom() {
      const panel = byId("output-panel");
      requestAnimationFrame(() => {
        panel.scrollTop = panel.scrollHeight;
      });
    }

    function runForId(runId) {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      return runs.find((run) => run.id === runId) || null;
    }

    function eventsForRun(runId) {
      const events = state.currentBundle && Array.isArray(state.currentBundle.events) ? state.currentBundle.events : [];
      return events.filter((event) => event.run_id === runId || (!event.run_id && state.activeHeadlessRun && state.activeHeadlessRun.id === runId));
    }

    function activeHeadlessRunFromBundle(bundle = state.currentBundle) {
      const runs = bundle && Array.isArray(bundle.runs) ? bundle.runs : [];
      return [...runs].reverse().find((run) =>
        ["queued", "running"].includes(run.status) && run.invocation_mode !== "native"
      ) || null;
    }

    function latestEventIdForRun(runId) {
      const events = eventsForRun(runId);
      const latest = [...events].reverse().find((event) => event && event.id);
      return latest ? latest.id : null;
    }

    function resumeActiveHeadlessRun() {
      const run = activeHeadlessRunFromBundle();
      const previousRunId = state.activeHeadlessRun && state.activeHeadlessRun.id;
      if (!run) {
        if (previousRunId || state.headlessEventSource) closeHeadlessEventSource();
        state.activeHeadlessRun = null;
        setHeadlessRunning(false);
        return;
      }
      if (previousRunId && previousRunId !== run.id) closeHeadlessEventSource();
      state.activeHeadlessRun = run;
      const draft = ensureLiveRun(run.id, run);
      draft.status = run.status;
      for (const event of eventsForRun(run.id)) consumeLiveEvent(event);
      setHeadlessRunning(true);
      renderLiveDraft(run.id);
      renderRunSummary(run, eventsForRun(run.id));
      openHeadlessEventStream(run.id);
    }

    function restoreTerminalPartialDrafts() {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      for (const run of runs) {
        if (!["failed", "canceled"].includes(run.status)) continue;
        const events = eventsForRun(run.id);
        const hasPartialText = events.some((event) => event.type === "message_delta" && liveDelta(event));
        if (!hasPartialText) continue;
        const draft = ensureLiveRun(run.id, run);
        for (const event of events) consumeLiveEvent(event);
        draft.status = run.status;
      }
    }

    function finiteToken(value) {
      if (value == null || value === "") return null;
      const number = Number(value);
      return Number.isFinite(number) && number >= 0 ? Math.round(number) : null;
    }

    function normalizeUsage(value) {
      if (!value || typeof value !== "object") return null;
      const source = value.usage && typeof value.usage === "object" ? value.usage : value;
      const inputTokens = finiteToken(source.input_tokens != null ? source.input_tokens : source.prompt_tokens);
      const outputTokens = finiteToken(source.output_tokens != null ? source.output_tokens : source.completion_tokens);
      let totalTokens = finiteToken(source.total_tokens);
      if (totalTokens == null && inputTokens != null && outputTokens != null) totalTokens = inputTokens + outputTokens;
      if (inputTokens == null && outputTokens == null && totalTokens == null) return null;
      return {
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: totalTokens
      };
    }

    function mergeUsage(current, update) {
      const previous = normalizeUsage(current) || {
        input_tokens: null,
        output_tokens: null,
        total_tokens: null
      };
      const next = normalizeUsage(update);
      if (!next) return normalizeUsage(previous);
      const inputTokens = next.input_tokens != null ? next.input_tokens : previous.input_tokens;
      const outputTokens = next.output_tokens != null ? next.output_tokens : previous.output_tokens;
      let totalTokens = next.total_tokens != null ? next.total_tokens : previous.total_tokens;
      if (
        inputTokens != null
        && outputTokens != null
        && (next.total_tokens == null || totalTokens == null)
      ) {
        totalTokens = inputTokens + outputTokens;
      }
      return normalizeUsage({
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: totalTokens
      });
    }

    function usageFromEvents(events) {
      let usage = null;
      for (const event of events || []) {
        if (event.type !== "usage") continue;
        usage = mergeUsage(usage, event.payload || {});
      }
      return usage;
    }

    function usageForMessage(message, run, events) {
      const metadata = message && message.metadata && typeof message.metadata === "object" ? message.metadata : {};
      const runMetadata = run && run.metadata && typeof run.metadata === "object" ? run.metadata : {};
      return mergeUsage(
        mergeUsage(usageFromEvents(events || []), runMetadata.usage),
        metadata.usage
      );
    }

    function tokenChip(label, value) {
      if (value == null) return null;
      const chip = document.createElement("span");
      chip.className = "token-chip";
      const name = document.createElement("strong");
      name.textContent = label;
      chip.appendChild(name);
      chip.appendChild(document.createTextNode(String(value)));
      return chip;
    }

    function appendUsageChips(parent, usage) {
      const normalized = normalizeUsage(usage);
      if (!normalized) return;
      const row = document.createElement("div");
      row.className = "usage-row";
      for (const chip of [
        tokenChip("Input", normalized.input_tokens),
        tokenChip("Output", normalized.output_tokens),
        tokenChip("Total", normalized.total_tokens)
      ]) {
        if (chip) row.appendChild(chip);
      }
      if (row.childElementCount) parent.appendChild(row);
    }

    function isSafeMarkdownHref(value) {
      const href = String(value || "").trim();
      if (!href || /[\\u0000-\\u001f\\u007f]/.test(href) || href.startsWith("//") || href.includes("\\\\")) return false;
      const explicitScheme = href.match(/^([A-Za-z][A-Za-z0-9+.-]*):/);
      if (explicitScheme) {
        return ["http:", "https:", "mailto:"].includes(`${explicitScheme[1].toLowerCase()}:`);
      }
      try {
        const resolved = new URL(href, window.location.href);
        return ["http:", "https:"].includes(resolved.protocol) && resolved.origin === window.location.origin;
      } catch (error) {
        return false;
      }
    }

    function parseMarkdownLink(source, start) {
      if (source[start] !== "[" || (start > 0 && source[start - 1] === "!")) return null;
      const labelEnd = source.indexOf("](", start + 1);
      if (labelEnd < 0) return null;
      const targetEnd = source.indexOf(")", labelEnd + 2);
      if (targetEnd < 0) return null;
      const label = source.slice(start + 1, labelEnd);
      const rawTarget = source.slice(labelEnd + 2, targetEnd).trim();
      const targetMatch = rawTarget.match(/^(<[^>]+>|\\S+?)(?:\\s+["']([^"']*)["'])?$/);
      if (!targetMatch) return null;
      const href = targetMatch[1].startsWith("<") ? targetMatch[1].slice(1, -1) : targetMatch[1];
      if (!isSafeMarkdownHref(href)) return null;
      return {
        end: targetEnd + 1,
        label,
        href,
        title: targetMatch[2] || ""
      };
    }

    function appendInlineMarkdown(parent, value) {
      const source = String(value == null ? "" : value);
      let index = 0;
      let buffer = "";
      const flush = () => {
        if (!buffer) return;
        parent.appendChild(document.createTextNode(buffer));
        buffer = "";
      };
      while (index < source.length) {
        if (source[index] === "\\\\" && index + 1 < source.length) {
          buffer += source[index + 1];
          index += 2;
          continue;
        }
        if (source[index] === "`") {
          let ticks = 1;
          while (source[index + ticks] === "`") ticks += 1;
          const marker = "`".repeat(ticks);
          const closing = source.indexOf(marker, index + ticks);
          if (closing >= 0) {
            flush();
            const code = document.createElement("code");
            code.textContent = source.slice(index + ticks, closing).replace(/^ | $/g, "");
            parent.appendChild(code);
            index = closing + ticks;
            continue;
          }
        }
        const parsedLink = parseMarkdownLink(source, index);
        if (parsedLink) {
          flush();
          const link = document.createElement("a");
          link.setAttribute("href", parsedLink.href);
          link.setAttribute("target", "_blank");
          link.setAttribute("rel", "noopener noreferrer");
          if (parsedLink.title) link.setAttribute("title", parsedLink.title);
          appendInlineMarkdown(link, parsedLink.label);
          parent.appendChild(link);
          index = parsedLink.end;
          continue;
        }
        const strongMarker = source.startsWith("**", index) ? "**" : source.startsWith("__", index) ? "__" : null;
        if (strongMarker) {
          const closing = source.indexOf(strongMarker, index + 2);
          if (closing > index + 2) {
            flush();
            const strong = document.createElement("strong");
            appendInlineMarkdown(strong, source.slice(index + 2, closing));
            parent.appendChild(strong);
            index = closing + 2;
            continue;
          }
        }
        if (source[index] === "*" || source[index] === "_") {
          const marker = source[index];
          const previous = index > 0 ? source[index - 1] : " ";
          const next = source[index + 1] || " ";
          const insideWord = marker === "_" && /[A-Za-z0-9]/.test(previous) && /[A-Za-z0-9]/.test(next);
          const closing = insideWord ? -1 : source.indexOf(marker, index + 1);
          if (closing > index + 1) {
            flush();
            const emphasis = document.createElement("em");
            appendInlineMarkdown(emphasis, source.slice(index + 1, closing));
            parent.appendChild(emphasis);
            index = closing + 1;
            continue;
          }
        }
        buffer += source[index];
        index += 1;
      }
      flush();
    }

    function markdownListMatch(line, ordered) {
      return ordered ? line.match(/^\\s*\\d+[.)]\\s+(.+)$/) : line.match(/^\\s*[-+*]\\s+(.+)$/);
    }

    function isMarkdownBlockStart(line) {
      return /^#{1,6}\\s+/.test(line) || /^```/.test(line) || /^>\\s?/.test(line) || Boolean(markdownListMatch(line, false)) || Boolean(markdownListMatch(line, true));
    }

    function appendMarkdownBlocks(parent, lines) {
      let index = 0;
      while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) {
          index += 1;
          continue;
        }
        const fence = line.match(/^```([A-Za-z0-9_-]*)\\s*$/);
        if (fence) {
          const codeLines = [];
          index += 1;
          while (index < lines.length && !/^```\\s*$/.test(lines[index])) {
            codeLines.push(lines[index]);
            index += 1;
          }
          if (index < lines.length) index += 1;
          const wrapper = document.createElement("div");
          wrapper.className = "code-block";
          const header = document.createElement("div");
          header.className = "code-block-header";
          const language = document.createElement("span");
          language.textContent = fence[1] || "text";
          const copy = document.createElement("button");
          copy.className = "code-block-copy";
          copy.type = "button";
          copy.textContent = "Copy";
          copy.setAttribute("aria-label", `Copy ${fence[1] || "text"} code`);
          header.append(language, copy);
          const pre = document.createElement("pre");
          const code = document.createElement("code");
          if (fence[1]) code.className = `language-${fence[1]}`;
          code.textContent = codeLines.join("\\n");
          pre.appendChild(code);
          copy.addEventListener("click", async () => {
            try {
              await navigator.clipboard.writeText(code.textContent || "");
              copy.textContent = "Copied";
              setTimeout(() => { copy.textContent = "Copy"; }, 1200);
            } catch (error) {
              copy.textContent = "Unavailable";
            }
          });
          wrapper.append(header, pre);
          parent.appendChild(wrapper);
          continue;
        }
        const heading = line.match(/^(#{1,6})\\s+(.+)$/);
        if (heading) {
          const node = document.createElement(`h${heading[1].length}`);
          appendInlineMarkdown(node, heading[2]);
          parent.appendChild(node);
          index += 1;
          continue;
        }
        if (/^>\\s?/.test(line)) {
          const quoteLines = [];
          while (index < lines.length && /^>\\s?/.test(lines[index])) {
            quoteLines.push(lines[index].replace(/^>\\s?/, ""));
            index += 1;
          }
          const quote = document.createElement("blockquote");
          appendMarkdownBlocks(quote, quoteLines);
          parent.appendChild(quote);
          continue;
        }
        const unordered = markdownListMatch(line, false);
        const ordered = markdownListMatch(line, true);
        if (unordered || ordered) {
          const isOrdered = Boolean(ordered);
          const list = document.createElement(isOrdered ? "ol" : "ul");
          while (index < lines.length) {
            const itemMatch = markdownListMatch(lines[index], isOrdered);
            if (!itemMatch) break;
            const parts = [itemMatch[1]];
            index += 1;
            while (index < lines.length && /^\\s{2,}\\S/.test(lines[index]) && !markdownListMatch(lines[index], isOrdered)) {
              parts.push(lines[index].trim());
              index += 1;
            }
            const item = document.createElement("li");
            appendInlineMarkdown(item, parts.join(" "));
            list.appendChild(item);
          }
          parent.appendChild(list);
          continue;
        }
        const paragraphLines = [line.trim()];
        index += 1;
        while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines[index])) {
          paragraphLines.push(lines[index].trim());
          index += 1;
        }
        const paragraph = document.createElement("p");
        appendInlineMarkdown(paragraph, paragraphLines.join(" "));
        parent.appendChild(paragraph);
      }
    }

    function renderMarkdownInto(node, value) {
      const fragment = document.createDocumentFragment();
      const lines = String(value == null ? "" : value).replace(/\\r\\n?/g, "\\n").split("\\n");
      appendMarkdownBlocks(fragment, lines);
      node.replaceChildren(fragment);
    }

    function eventToolPayload(event) {
      const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
      const toolCall = payload.tool_call && typeof payload.tool_call === "object" ? payload.tool_call : {};
      const delta = payload.delta && typeof payload.delta === "object" ? payload.delta : {};
      return { ...payload, ...toolCall, ...delta };
    }

    function toolValueText(value) {
      if (value == null) return "";
      if (typeof value === "string") return value;
      try {
        return JSON.stringify(value, null, 2);
      } catch (error) {
        return String(value);
      }
    }

    function toolEventId(event, payload, tools) {
      const value = payload.call_id != null ? payload.call_id : payload.tool_call_id != null ? payload.tool_call_id : payload.id != null ? payload.id : payload.index != null ? payload.index : payload.name;
      if (value != null && String(value)) return String(value);
      const existing = [...tools.values()].find((tool) => tool.status === "running");
      return existing ? existing.id : `tool-${tools.size + 1}`;
    }

    function normalizedToolStatus(value, fallback) {
      const status = String(value || fallback || "running").toLowerCase();
      if (["failed", "error", "canceled", "cancelled"].includes(status)) return "failed";
      if (["requested", "completed", "succeeded", "running"].includes(status)) return status;
      return fallback || "running";
    }

    function applyToolEvent(tools, event) {
      if (!event || !["tool_call_started", "tool_call_delta", "tool_call_finished"].includes(event.type)) return;
      const payload = eventToolPayload(event);
      const id = toolEventId(event, payload, tools);
      const current = tools.get(id) || {
        id,
        name: "tool",
        status: "running",
        arguments: "",
        output: "",
        duration_ms: null
      };
      const functionPayload = payload.function && typeof payload.function === "object" ? payload.function : {};
      const name = payload.name || functionPayload.name;
      if (name) current.name = String(name);
      const completeArguments = payload.arguments != null ? payload.arguments : payload.input != null ? payload.input : functionPayload.arguments;
      const argumentDelta = payload.arguments_delta != null ? payload.arguments_delta : payload.input_delta;
      if (event.type === "tool_call_delta" && (argumentDelta != null || completeArguments != null)) {
        current.arguments += toolValueText(argumentDelta != null ? argumentDelta : completeArguments);
      } else if (completeArguments != null) {
        current.arguments = toolValueText(completeArguments);
      }
      const outputDelta = payload.output_delta != null ? payload.output_delta : payload.result_delta;
      const completeOutput = payload.output != null ? payload.output : payload.result != null ? payload.result : payload.error;
      if (event.type === "tool_call_delta" && (outputDelta != null || completeOutput != null)) {
        current.output += toolValueText(outputDelta != null ? outputDelta : completeOutput);
      }
      if (event.type === "tool_call_finished" && completeOutput != null) current.output = toolValueText(completeOutput);
      if (event.type === "tool_call_finished") {
        current.status = normalizedToolStatus(payload.status, payload.error ? "failed" : "completed");
        current.duration_ms = finiteToken(payload.duration_ms);
      } else {
        current.status = normalizedToolStatus(payload.status, current.status || "running");
      }
      tools.set(id, current);
    }

    function toolsFromEvents(events) {
      const tools = new Map();
      for (const event of events || []) applyToolEvent(tools, event);
      return tools;
    }

    function toolCard(tool) {
      const details = document.createElement("details");
      details.className = "tool-call-card";
      details.open = tool.status === "running" || tool.status === "failed" || tool.status === "requested";
      const summary = document.createElement("summary");
      const dot = document.createElement("span");
      dot.className = `tool-status-dot ${tool.status || "running"}`;
      const name = document.createElement("span");
      name.className = "tool-call-name";
      name.textContent = tool.name || "tool";
      const status = document.createElement("span");
      status.className = "tool-call-status";
      status.textContent = tool.duration_ms != null ? `${tool.status} · ${tool.duration_ms} ms` : tool.status || "running";
      summary.append(dot, name, status);
      details.appendChild(summary);
      if (tool.arguments || tool.output) {
        const body = document.createElement("div");
        body.className = "tool-call-body";
        for (const [label, text] of [["Input", tool.arguments], ["Output", tool.output]]) {
          if (!text) continue;
          const section = document.createElement("div");
          section.className = "tool-call-section";
          const heading = document.createElement("span");
          heading.textContent = label;
          const pre = document.createElement("pre");
          pre.textContent = text;
          section.append(heading, pre);
          body.appendChild(section);
        }
        details.appendChild(body);
      }
      return details;
    }

    function appendToolCards(parent, tools) {
      if (!tools || !tools.size) return;
      const stack = document.createElement("div");
      stack.className = "tool-call-stack";
      const label = document.createElement("div");
      label.className = "execution-rail-label";
      label.textContent = `Tool calls · ${tools.size}`;
      stack.appendChild(label);
      for (const tool of tools.values()) stack.appendChild(toolCard(tool));
      parent.appendChild(stack);
    }

    function appendExecutionOutput(parent, draft) {
      if (!draft || (!draft.stdout && !draft.stderr)) return;
      const stack = document.createElement("div");
      stack.className = "execution-output-stack";
      const label = document.createElement("div");
      label.className = "execution-rail-label";
      label.textContent = "Process output";
      stack.appendChild(label);
      const tool = {
        name: "stdout / stderr",
        status: ["failed", "canceled"].includes(draft.status) ? "failed" : ["running", "queued"].includes(draft.status) ? "running" : "succeeded",
        arguments: draft.stdout || "",
        output: draft.stderr || "",
        duration_ms: null
      };
      stack.appendChild(toolCard(tool));
      parent.appendChild(stack);
    }

    function messageHeader(message, liveStatus) {
      const header = document.createElement("div");
      header.className = "message-header";
      const meta = document.createElement("div");
      meta.className = "message-meta";
      for (const value of [message.role, message.harness_id, message.api_mode]) {
        if (!value) continue;
        const item = document.createElement("span");
        item.textContent = String(value);
        meta.appendChild(item);
      }
      header.appendChild(meta);
      if (liveStatus) {
        const status = document.createElement("span");
        const terminal = ["succeeded", "failed", "canceled"].includes(liveStatus);
        status.className = `live-status${liveStatus === "failed" || liveStatus === "canceled" ? " failed" : terminal ? " complete" : ""}`;
        status.textContent = liveStatus === "succeeded" ? "Complete" : liveStatus === "canceled" ? "Canceled" : liveStatus === "failed" ? "Failed" : "Streaming";
        header.appendChild(status);
      }
      return header;
    }

    function appendAttachmentChips(parent, attachments) {
      if (!attachments || !attachments.length) return;
      const row = document.createElement("div");
      row.className = "attachment-chip-row";
      for (const attachment of attachments) {
        const chip = document.createElement("span");
        chip.className = "badge attachment-chip";
        chip.textContent = attachment.filename || attachment.id || "attachment";
        row.appendChild(chip);
      }
      parent.appendChild(row);
    }

    function buildMessageNode(message, options = {}) {
      const role = normalizeMessageRole(message.role);
      const item = document.createElement("article");
      item.className = `message ${role}`;
      if (message.run_id) item.dataset.runId = message.run_id;
      if (options.live) item.dataset.liveRunId = message.run_id;
      item.appendChild(messageHeader({ ...message, role }, options.liveStatus || null));
      const content = document.createElement("div");
      content.className = "message-content markdown-body";
      const liveNonterminal = options.live && !["succeeded", "failed", "canceled"].includes(options.liveStatus);
      if (message.content) {
        renderMarkdownInto(content, message.content);
      } else if (liveNonterminal) {
        const waiting = document.createElement("p");
        waiting.className = "hint";
        waiting.textContent = "Waiting for model output…";
        content.appendChild(waiting);
      }
      if (liveNonterminal) {
        const cursor = document.createElement("span");
        cursor.className = "live-cursor";
        cursor.setAttribute("aria-hidden", "true");
        const last = content.lastElementChild;
        if (last) last.appendChild(cursor);
        else content.appendChild(cursor);
      }
      item.appendChild(content);
      appendToolCards(item, options.tools || new Map());
      appendExecutionOutput(item, options.draft || null);
      appendUsageChips(item, options.usage || null);
      const attachments = message.metadata && Array.isArray(message.metadata.attachments) ? message.metadata.attachments : [];
      appendAttachmentChips(item, attachments);
      return item;
    }

    function ensureLiveRun(runId, seed = {}) {
      if (!runId) return null;
      let draft = state.liveRuns.get(runId);
      if (!draft) {
        draft = {
          runId,
          sessionId: seed.session_id || state.currentSessionId,
          harnessId: seed.harness_id || currentHarnessId(),
          model: seed.model || byId("model-input").value.trim(),
          apiMode: seed.api_mode || currentApiMode(),
          text: "",
          stdout: "",
          stderr: "",
          tools: new Map(),
          usage: null,
          status: seed.status || "running",
          hasMessageDelta: false,
          eventIds: new Set()
        };
        state.liveRuns.set(runId, draft);
      } else {
        draft.sessionId = seed.session_id || draft.sessionId;
        draft.harnessId = seed.harness_id || draft.harnessId;
        draft.model = seed.model || draft.model;
        draft.apiMode = seed.api_mode || draft.apiMode;
      }
      return draft;
    }

    function liveDelta(event) {
      const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
      const value = payload.delta != null ? payload.delta : payload.text_delta != null ? payload.text_delta : payload.text != null ? payload.text : payload.content != null ? payload.content : payload.chunk;
      return typeof value === "string" ? value : "";
    }

    function consumeLiveEvent(event) {
      const activeRun = state.activeHeadlessRun || {};
      const runId = event.run_id || activeRun.id;
      const draft = ensureLiveRun(runId, activeRun);
      if (!draft) return null;
      if (!draft.eventIds) draft.eventIds = new Set();
      if (event.id && draft.eventIds.has(event.id)) return draft;
      if (event.id) draft.eventIds.add(event.id);
      const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
      if (event.type === "run_started") {
        draft.status = "running";
      } else if (event.type === "message_delta") {
        draft.text += liveDelta(event);
        draft.hasMessageDelta = true;
      } else if (event.type === "stdout_delta") {
        draft.stdout += liveDelta(event);
      } else if (event.type === "stderr_delta") {
        draft.stderr += liveDelta(event);
      } else if (["tool_call_started", "tool_call_delta", "tool_call_finished"].includes(event.type)) {
        applyToolEvent(draft.tools, event);
      } else if (event.type === "usage") {
        draft.usage = mergeUsage(draft.usage, payload);
      } else if (event.type === "message_completed" && !draft.text) {
        const completeText = payload.content != null ? payload.content : payload.text;
        if (typeof completeText === "string") draft.text = completeText;
      } else if (event.type === "error") {
        draft.status = "failed";
        if (event.message) draft.stderr += `${event.message}\\n`;
      } else if (event.type === "run_canceled") {
        draft.status = "canceled";
      } else if (event.type === "run_finished") {
        draft.status = String(payload.status || "succeeded");
      }
      return draft;
    }

    function persistedMessageForRun(runId) {
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      return messages.find((message) => message.run_id === runId && ["assistant", "error"].includes(message.role));
    }

    function preserveTerminalPartialDraft(draft) {
      if (!draft || !["failed", "canceled"].includes(draft.status) || !draft.text.trim()) return false;
      const persisted = persistedMessageForRun(draft.runId);
      return !persisted || String(persisted.content || "").trim() !== draft.text.trim();
    }

    function liveMessageNode(draft) {
      return buildMessageNode(
        {
          role: "assistant",
          run_id: draft.runId,
          content: draft.text,
          harness_id: draft.harnessId,
          api_mode: draft.apiMode,
          metadata: {}
        },
        {
          live: true,
          liveStatus: draft.status,
          tools: draft.tools,
          usage: draft.usage,
          draft
        }
      );
    }

    function findLiveMessageNode(runId) {
      return [...byId("message-list").children].find((node) => node.dataset && node.dataset.liveRunId === runId) || null;
    }

    function renderLiveDraft(runId) {
      const draft = state.liveRuns.get(runId);
      if (!draft || draft.sessionId !== state.currentSessionId) return;
      const existing = findLiveMessageNode(runId);
      if (persistedMessageForRun(runId) && !preserveTerminalPartialDraft(draft)) {
        if (existing) existing.remove();
        state.liveRuns.delete(runId);
        return;
      }
      const shouldStick = isChatNearBottom();
      const replacement = liveMessageNode(draft);
      if (existing) existing.replaceWith(replacement);
      else byId("message-list").appendChild(replacement);
      document.body.classList.remove("new-session");
      if (shouldStick) scrollChatToBottom();
    }

    function renderMessages() {
      const list = byId("message-list");
      const panel = byId("output-panel");
      const session = state.currentBundle && state.currentBundle.session ? state.currentBundle.session : null;
      const sessionChanged = state.renderedSessionId !== (session && session.id);
      const shouldStick = sessionChanged || panel.scrollHeight === 0 || isChatNearBottom();
      list.replaceChildren();
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      const persistedRunIds = new Set();
      const renderedPartialDrafts = new Set();
      for (const message of messages) {
        const run = message.run_id ? runForId(message.run_id) : null;
        const events = message.run_id ? eventsForRun(message.run_id) : [];
        const executionMessage = ["assistant", "error"].includes(message.role);
        const tools = message.run_id && executionMessage ? toolsFromEvents(events) : new Map();
        const usage = executionMessage ? usageForMessage(message, run, events) : null;
        if (message.run_id && executionMessage) {
          persistedRunIds.add(message.run_id);
          const draft = state.liveRuns.get(message.run_id);
          if (preserveTerminalPartialDraft(draft)) {
            list.appendChild(liveMessageNode(draft));
            renderedPartialDrafts.add(message.run_id);
          }
        }
        list.appendChild(buildMessageNode(message, { tools, usage }));
      }
      for (const [runId, draft] of [...state.liveRuns.entries()]) {
        if (renderedPartialDrafts.has(runId)) continue;
        if (persistedRunIds.has(runId) && !preserveTerminalPartialDraft(draft)) {
          state.liveRuns.delete(runId);
          continue;
        }
        if (draft.sessionId === (session && session.id)) list.appendChild(liveMessageNode(draft));
      }
      const hasVisibleMessages = list.childElementCount > 0;
      document.body.classList.toggle("new-session", !hasVisibleMessages);
      if (!hasVisibleMessages) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "New session";
        list.appendChild(empty);
      }
      state.renderedSessionId = session && session.id;
      if (shouldStick) scrollChatToBottom();
    }

    function runStatusBadgeClass(status) {
      if (status === "succeeded") return "badge ok";
      if (["failed", "canceled"].includes(status)) return "badge error";
      if (["running", "queued"].includes(status)) return "badge warn";
      return "badge info";
    }

    function runDuration(run) {
      if (!run || !run.started_at) return "-";
      if (["running", "queued"].includes(run.status)) return "running";
      const started = Date.parse(run.started_at);
      const finished = Date.parse(run.finished_at || run.updated_at || "");
      if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return run.status === "running" ? "running" : "-";
      const milliseconds = finished - started;
      return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0)} s`;
    }

    function appendRunSummaryField(grid, label, value) {
      const field = document.createElement("div");
      field.className = "run-summary-field";
      const name = document.createElement("span");
      name.textContent = label;
      const content = document.createElement("strong");
      content.textContent = value == null || value === "" ? "-" : String(value);
      content.title = content.textContent;
      field.append(name, content);
      grid.appendChild(field);
    }

    function renderRunSummary(run, allEvents) {
      const panel = byId("run-panel");
      panel.replaceChildren();
      if (!run) {
        panel.textContent = "No run selected.";
        return;
      }
      const events = (allEvents || []).filter((event) => !event.run_id || event.run_id === run.id);
      const draft = state.liveRuns.get(run.id) || null;
      const effectiveStatus = draft ? draft.status : run.status || "unknown";
      const metadata = run.metadata && typeof run.metadata === "object" ? run.metadata : {};
      const usage = mergeUsage(
        mergeUsage(usageFromEvents(events), metadata.usage),
        draft && draft.usage
      );
      const tools = draft && draft.tools && draft.tools.size ? draft.tools : toolsFromEvents(events);
      const header = document.createElement("div");
      header.className = "run-summary-header";
      const title = document.createElement("div");
      title.className = "run-summary-title";
      const harness = document.createElement("strong");
      harness.textContent = run.harness_id || "Harness run";
      const identifier = document.createElement("span");
      identifier.textContent = run.id || "";
      title.append(harness, identifier);
      const status = document.createElement("span");
      status.className = runStatusBadgeClass(effectiveStatus);
      status.textContent = effectiveStatus;
      header.append(title, status);
      panel.appendChild(header);
      const grid = document.createElement("div");
      grid.className = "run-summary-grid";
      appendRunSummaryField(grid, "Model", run.model || "default");
      appendRunSummaryField(grid, "Route", run.api_mode ? `/${run.api_mode}` : "-");
      appendRunSummaryField(grid, "Mode", run.mode || "-");
      appendRunSummaryField(grid, "Invocation", run.invocation_mode || "headless");
      appendRunSummaryField(grid, "Duration", runDuration({ ...run, status: effectiveStatus }));
      appendRunSummaryField(grid, "Workspace", run.workspace || "current");
      panel.appendChild(grid);
      appendUsageChips(panel, usage);
      const footer = document.createElement("div");
      footer.className = "run-summary-footer";
      const deltaCount = events.filter((event) => ["message_delta", "stdout_delta", "stderr_delta"].includes(event.type)).length;
      for (const value of [`${events.length} events`, `${deltaCount} deltas`, `${tools.size} tool calls`]) {
        const item = document.createElement("span");
        item.textContent = value;
        footer.appendChild(item);
      }
      panel.appendChild(footer);
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
      renderRunSummary(run, events);
      renderArenaInspector(state.currentArena);
      renderEvents(events);
      setText("raw-request-panel", rawRequests.length ? pretty(rawRequests[rawRequests.length - 1].payload) : "{}");
      setText("raw-response-panel", rawResponses.length ? pretty(rawResponses[rawResponses.length - 1].payload) : "{}");
      setText("command-panel", run && run.command && run.command.length ? run.command.join(" ") : commandPreview(state.lastPayload));
      renderDiffInspector(run);
      renderPrInspector(run);
      renderProvenanceInspector(run);
      renderEditorInspector(run);
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
      const canApply = Boolean(run && run.id && execution.policy === "worktree" && patch && patch !== "No diff captured." && !execution.truncated && !execution.applied_at && !execution.discarded_at);
      const canDiscard = Boolean(run && run.id && execution.policy === "worktree" && !execution.discarded_at);
      byId("apply-run-diff-button").disabled = !canApply;
      byId("apply-branch-input").disabled = !canApply;
      byId("discard-run-worktree-button").disabled = !canDiscard;
      byId("open-run-worktree-button").disabled = !(run && run.id && execution.worktree_path);
      byId("open-run-terminal-button").disabled = !(run && run.id && execution.worktree_path);
    }

    function renderPrInspector(run) {
      const artifact = prArtifactFromRun(run);
      const execution = run && run.metadata ? (run.metadata.workspace_execution || {}) : {};
      const canCreateBranch = Boolean(run && run.id && artifact && artifact.patch && artifact.patch !== "No diff captured." && execution.policy === "worktree" && !execution.truncated && !execution.applied_at && !execution.discarded_at);
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

    function renderEditorInspector(run) {
      const workspace = state.project && state.project.root ? state.project.root : byId("workspace-input").value.trim();
      const runWorkspace = editorWorkspaceFromRun(run);
      const patch = editorPatchFromRun(run);
      const hasSession = Boolean(state.currentBundle && state.currentBundle.session && state.currentBundle.session.id);
      const hasRun = Boolean(run && run.id);
      byId("open-editor-workspace-button").disabled = !workspace;
      byId("open-editor-run-button").disabled = !runWorkspace;
      byId("open-editor-diff-button").disabled = !(hasRun && patch && patch !== "No diff captured.");
      byId("open-editor-terminal-button").disabled = !runWorkspace;
      byId("open-editor-file-button").disabled = !workspace;
      byId("copy-session-open-command-button").disabled = !hasSession;
      byId("copy-run-open-command-button").disabled = !hasRun;
      const lines = [
        `Project workspace: ${workspace || "-"}`,
        `Run workspace: ${runWorkspace || "-"}`,
        `Run diff: ${patch && patch !== "No diff captured." ? "available" : "unavailable"}`,
        "Editor and terminal commands come from [editor] in .giga/harness.toml."
      ];
      setText("editor-text", lines.join("\\n"));
    }

    function editorWorkspaceFromRun(run) {
      if (!run || !run.id) return "";
      const execution = run.metadata && run.metadata.workspace_execution ? run.metadata.workspace_execution : {};
      return execution.worktree_path || execution.effective_workspace || execution.source_workspace || run.workspace || "";
    }

    function editorPatchFromRun(run) {
      if (!run || !run.id) return "";
      const metadata = run.metadata || {};
      const execution = metadata.workspace_execution || {};
      return execution.patch || metadata.diff || "";
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
      const workspace = editorWorkspaceFromRun(run);
      if (!workspace) return;
      const result = await getJson("/api/editor/open-workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace })
      });
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Open worktree failed with HTTP ${result.status}`);
        setText("editor-text", result.data.detail || `Open worktree failed with HTTP ${result.status}`);
        return;
      }
      setText("model-status", `Opened editor for ${result.data.editor.target_path}.`);
      setText("editor-text", pretty(result.data.editor));
      showTab("editor");
      await refreshRunDiff(run.id);
    }

    async function openEditorWorkspace(useRunWorkspace = false) {
      const run = currentRun();
      const workspace = useRunWorkspace ? editorWorkspaceFromRun(run) : (state.project && state.project.root ? state.project.root : byId("workspace-input").value.trim());
      if (!workspace) return;
      const result = await getJson("/api/editor/open-workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace })
      });
      renderEditorResult(result, "Open workspace failed");
    }

    async function openEditorFile() {
      const path = byId("open-editor-file-input").value.trim();
      const workspace = state.project && state.project.root ? state.project.root : byId("workspace-input").value.trim();
      if (!path || !workspace) return;
      const result = await getJson("/api/editor/open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace, path })
      });
      renderEditorResult(result, "Open file failed");
    }

    async function openEditorDiff() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson("/api/editor/open-diff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: run.id })
      });
      renderEditorResult(result, "Open diff failed");
    }

    async function openRunTerminal() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson("/api/editor/open-terminal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: run.id })
      });
      renderEditorResult(result, "Open terminal failed");
    }

    function renderEditorResult(result, fallback) {
      if (!result.ok) {
        setText("editor-text", result.data.detail || `${fallback} with HTTP ${result.status}`);
        showTab("editor");
        return;
      }
      const editor = result.data.editor || {};
      setText("editor-text", pretty(editor));
      setText("model-status", editor.executed ? `Opened ${editor.kind || "launcher"} for ${editor.target_path}.` : editor.command_display || "Editor command ready.");
      showTab("editor");
    }

    function copySessionOpenCommand() {
      const session = state.currentBundle && state.currentBundle.session ? state.currentBundle.session : null;
      if (!session || !session.id) return;
      copyText(`giga open session ${shellQuote(session.id)}`, "Copied session open command.");
    }

    function copyRunOpenCommand() {
      const run = currentRun();
      if (!run || !run.id) return;
      copyText(`giga open run ${shellQuote(run.id)}`, "Copied run open command.");
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
      const command = args.map(shellQuote).join(" ");
      if (payload.stream) {
        return `# Non-streaming CLI preview: giga harness run has no --stream flag\n${command}`;
      }
      return command;
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
      const args = [
        payload.stream ? "curl -sS -N" : "curl -sS",
        shellQuote(url),
        "-H",
        shellQuote("Content-Type: application/json")
      ];
      if (payload.stream) args.push("-H", shellQuote("Accept: text/event-stream"));
      args.push(
        "-H",
        shellQuote("Authorization: Bearer <GPT2GIGA_API_KEY>"),
        "-d",
        shellQuote(JSON.stringify(body))
      );
      return args.join(" ");
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

    function setInspectorOpen(open) {
      document.body.classList.toggle("inspector-open", open);
      byId("details-toggle-button").setAttribute("aria-expanded", open ? "true" : "false");
      if (open) setSidebarOpen(false);
    }

    function setSidebarOpen(open) {
      document.body.classList.toggle("sidebar-open", open);
      byId("session-drawer-button").setAttribute("aria-expanded", open ? "true" : "false");
    }

    function prepareAdvancedPanel() {
      const grid = document.querySelector(".quick-config");
      const panel = document.createElement("div");
      panel.id = "advanced-settings-panel";
      panel.className = "advanced-panel";
      panel.hidden = true;
      for (const control of Array.from(grid.querySelectorAll(".advanced-control"))) {
        panel.appendChild(control);
      }
      grid.appendChild(panel);
      byId("advanced-settings-button").setAttribute("aria-controls", panel.id);
    }

    function setAdvancedSettings(open) {
      const grid = document.querySelector(".quick-config");
      grid.classList.toggle("advanced-open", open);
      byId("advanced-settings-button").setAttribute("aria-expanded", open ? "true" : "false");
      byId("advanced-settings-panel").hidden = !open;
    }

    function toggleAdvancedSettings() {
      const grid = document.querySelector(".quick-config");
      setAdvancedSettings(!grid.classList.contains("advanced-open"));
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
      byId("details-toggle-button").addEventListener("click", () => setInspectorOpen(true));
      byId("close-inspector-button").addEventListener("click", () => setInspectorOpen(false));
      byId("inspector-backdrop").addEventListener("click", () => setInspectorOpen(false));
      byId("session-drawer-button").addEventListener("click", () => setSidebarOpen(true));
      byId("sidebar-backdrop").addEventListener("click", () => setSidebarOpen(false));
      byId("advanced-settings-button").addEventListener("click", toggleAdvancedSettings);
      for (const example of document.querySelectorAll(".example-prompt")) {
        example.addEventListener("click", () => {
          byId("prompt-input").value = example.textContent.trim();
          byId("prompt-input").focus();
          scheduleRouteRecommendation();
        });
      }
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
        if (event.key === "Escape" && document.body.classList.contains("inspector-open")) setInspectorOpen(false);
        if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) setSidebarOpen(false);
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
      byId("open-run-terminal-button").addEventListener("click", openRunTerminal);
      byId("copy-pr-title-button").addEventListener("click", () => copyCurrentPrField("title", "Copied PR title."));
      byId("copy-pr-body-button").addEventListener("click", () => copyCurrentPrField("body", "Copied PR body."));
      byId("copy-pr-patch-button").addEventListener("click", () => copyCurrentPrField("patch", "Copied PR patch."));
      byId("create-pr-branch-button").addEventListener("click", createPrBranch);
      byId("refresh-provenance-button").addEventListener("click", refreshRunProvenance);
      byId("replay-run-button").addEventListener("click", replayCurrentRun);
      byId("fork-run-button").addEventListener("click", forkCurrentRun);
      byId("open-editor-workspace-button").addEventListener("click", () => openEditorWorkspace(false));
      byId("open-editor-run-button").addEventListener("click", () => openEditorWorkspace(true));
      byId("open-editor-diff-button").addEventListener("click", openEditorDiff);
      byId("open-editor-terminal-button").addEventListener("click", openRunTerminal);
      byId("open-editor-file-button").addEventListener("click", openEditorFile);
      byId("copy-session-open-command-button").addEventListener("click", copySessionOpenCommand);
      byId("copy-run-open-command-button").addEventListener("click", copyRunOpenCommand);
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
      prepareAdvancedPanel();
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
