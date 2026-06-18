"""Protected built-in UI routes."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import HTMLResponse, RedirectResponse


router = APIRouter(prefix="/ui", include_in_schema=False)


_PLAYGROUND_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga playground</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --panel-soft: #f9fafb;
      --text: #111827;
      --muted: #667085;
      --muted-strong: #475467;
      --border: #d6dae3;
      --border-strong: #b8c0cc;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --blue: #1d4ed8;
      --amber: #b45309;
      --danger: #b42318;
      --code: #101828;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }

    button,
    input,
    select,
    textarea {
      font: inherit;
    }

    main {
      width: min(1280px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 40px;
    }

    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 18px;
    }

    .title-group {
      display: grid;
      gap: 4px;
    }

    .brand {
      color: var(--accent-strong);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      padding: 0 12px;
      color: var(--accent-strong);
      border: 1px solid rgb(15 118 110 / 28%);
      border-radius: 999px;
      background: rgb(15 118 110 / 8%);
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
    }

    .workspace {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgb(17 24 39 / 7%);
    }

    .rail,
    .builder {
      padding: 20px;
    }

    .builder {
      display: grid;
      gap: 16px;
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }

    .panel-title {
      margin: 0;
      color: var(--text);
      font-size: 16px;
      line-height: 1.3;
      font-weight: 750;
    }

    .field-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .field,
    .editor-field {
      display: grid;
      gap: 7px;
    }

    .field-wide {
      grid-column: 1 / -1;
    }

    label,
    .field-label {
      color: var(--muted-strong);
      font-size: 12px;
      font-weight: 700;
      line-height: 1.25;
    }

    input,
    select,
    textarea {
      width: 100%;
      color: var(--text);
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 7px;
      outline: none;
      transition:
        border-color 140ms ease,
        box-shadow 140ms ease;
    }

    input,
    select {
      height: 38px;
      padding: 0 10px;
      font-size: 14px;
    }

    textarea {
      min-height: 148px;
      resize: vertical;
      padding: 11px 12px;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.55;
      tab-size: 2;
    }

    input:focus,
    select:focus,
    textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgb(15 118 110 / 14%);
    }

    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 38px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #ffffff;
    }

    .toggle-row input {
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }

    .examples {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-top: 10px;
    }

    .example-button,
    .action-button {
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #ffffff;
      color: var(--text);
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      text-align: left;
      transition:
        background 140ms ease,
        border-color 140ms ease,
        color 140ms ease;
    }

    .example-button:hover,
    .action-button:hover {
      border-color: var(--border-strong);
      background: var(--panel-soft);
    }

    .example-button.is-active {
      border-color: rgb(29 78 216 / 44%);
      background: rgb(29 78 216 / 8%);
      color: #1e3a8a;
    }

    .editor-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-soft);
    }

    .endpoint {
      overflow-wrap: anywhere;
      color: var(--blue);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      font-weight: 700;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .admin-key-field {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: min(100%, 260px);
    }

    .admin-key-field label {
      white-space: nowrap;
    }

    .admin-key-field input {
      width: 160px;
      height: 36px;
      font-size: 13px;
    }

    .action-button {
      text-align: center;
    }

    .action-button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }

    .action-button.primary:hover {
      border-color: var(--accent-strong);
      background: var(--accent-strong);
    }

    pre {
      min-height: 190px;
      max-height: 420px;
      margin: 0;
      overflow: auto;
      padding: 13px 14px;
      border: 1px solid #202939;
      border-radius: 8px;
      background: var(--code);
      color: #e5e7eb;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .preview-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .response-shell {
      display: grid;
      gap: 14px;
      padding-top: 2px;
    }

    .tabbar {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 6px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-soft);
    }

    .response-tab {
      min-height: 34px;
      padding: 0 11px;
      border: 1px solid transparent;
      border-radius: 7px;
      background: transparent;
      color: var(--muted-strong);
      cursor: pointer;
      font-size: 12.5px;
      font-weight: 750;
      transition:
        background 140ms ease,
        border-color 140ms ease,
        color 140ms ease;
    }

    .response-tab:hover {
      background: #ffffff;
      border-color: var(--border);
      color: var(--text);
    }

    .response-tab.is-active {
      background: #ffffff;
      border-color: var(--border-strong);
      color: var(--accent-strong);
      box-shadow: 0 1px 2px rgb(17 24 39 / 7%);
    }

    .meta-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }

    .meta-item {
      display: grid;
      gap: 5px;
      min-width: 0;
      padding: 10px 11px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #ffffff;
    }

    .meta-label {
      color: var(--muted);
      font-size: 11.5px;
      font-weight: 750;
      line-height: 1.2;
    }

    .meta-value {
      overflow: hidden;
      color: var(--text);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
      font-weight: 700;
      line-height: 1.35;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .meta-value a {
      color: var(--blue);
      text-decoration: none;
    }

    .response-panel {
      display: none;
      gap: 8px;
    }

    .response-panel.is-active {
      display: grid;
    }

    .snippet-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }

    .snippet-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }

    .copy-button {
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #ffffff;
      color: var(--muted-strong);
      cursor: pointer;
      font-size: 12px;
      font-weight: 750;
    }

    .copy-button:hover {
      border-color: var(--border-strong);
      color: var(--text);
    }

    .copy-status {
      min-height: 18px;
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 700;
    }

    .error {
      color: var(--danger);
    }

    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 0 9px;
      border: 1px solid rgb(180 83 9 / 32%);
      border-radius: 999px;
      background: rgb(180 83 9 / 8%);
      color: var(--amber);
      font-size: 12px;
      font-weight: 750;
    }

    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: 0;
    }

    .help-text {
      margin: 0;
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.45;
    }

    @media (max-width: 900px) {
      header,
      .workspace,
      .editor-grid,
      .meta-grid,
      .preview-grid {
        grid-template-columns: 1fr;
      }

      .snippet-grid {
        grid-template-columns: 1fr;
      }

      header {
        align-items: flex-start;
      }

      .status {
        white-space: normal;
      }
    }

    @media (max-width: 620px) {
      main {
        width: min(100vw - 20px, 1280px);
        padding: 18px 0 28px;
      }

      .field-grid {
        grid-template-columns: 1fr;
      }

      .rail,
      .builder {
        padding: 14px;
      }

      h1 {
        font-size: 24px;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="title-group">
        <div class="brand">gpt2giga</div>
        <h1>Playground</h1>
      </div>
      <div class="status">
        <span class="dot"></span>
        <span id="status-label">Local request draft</span>
      </div>
    </header>

    <div class="workspace">
      <aside class="panel rail">
        <div class="panel-head">
          <h2 class="panel-title">Request</h2>
          <span class="pill" id="protocol-pill">OpenAI</span>
        </div>

        <div class="field-grid">
          <div class="field">
            <label for="protocol">Protocol</label>
            <select id="protocol" name="protocol">
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Gemini</option>
            </select>
          </div>

          <div class="field">
            <label for="operation">Operation</label>
            <select id="operation" name="operation"></select>
          </div>

          <div class="field field-wide">
            <label for="model">Model</label>
            <input id="model" name="model" value="GigaChat-2-Max">
          </div>

          <div class="field">
            <label for="temperature">Temperature</label>
            <input
              id="temperature"
              name="temperature"
              type="number"
              min="0"
              max="2"
              step="0.1"
              value="0.3"
            >
          </div>

          <div class="field">
            <label for="max-output">Max output</label>
            <input
              id="max-output"
              name="max-output"
              type="number"
              min="1"
              step="1"
              value="512"
            >
          </div>

          <div class="field field-wide">
            <div class="toggle-row">
              <label for="stream">Stream</label>
              <input id="stream" name="stream" type="checkbox">
            </div>
          </div>
        </div>

        <div class="examples" aria-label="Examples">
          <button
            class="example-button is-active"
            type="button"
            data-example="openai-chat"
          >
            Simple chat
          </button>
          <button
            class="example-button"
            type="button"
            data-example="anthropic-messages"
          >
            Anthropic messages
          </button>
          <button
            class="example-button"
            type="button"
            data-example="gemini-generate"
          >
            Gemini generateContent
          </button>
          <button
            class="example-button"
            type="button"
            data-example="gemini-stream"
          >
            Gemini streamGenerateContent
          </button>
          <button
            class="example-button"
            type="button"
            data-example="tools"
          >
            Tools
          </button>
          <button
            class="example-button"
            type="button"
            data-example="structured-output"
          >
            Structured output
          </button>
          <button
            class="example-button"
            type="button"
            data-example="embeddings"
          >
            Embeddings
          </button>
          <button
            class="example-button"
            type="button"
            data-example="count-tokens"
          >
            Count tokens
          </button>
        </div>
      </aside>

      <section class="panel builder" aria-label="Request builder">
        <div class="toolbar">
          <div class="endpoint" id="endpoint">POST /v1/chat/completions</div>
          <div class="actions">
            <div class="admin-key-field">
              <label for="admin-key">Admin key</label>
              <input
                id="admin-key"
                name="admin-key"
                type="password"
                autocomplete="off"
              >
            </div>
            <button class="action-button" type="button" id="load-examples">
              Examples
            </button>
            <button class="action-button" type="button" id="format-json">
              Format JSON
            </button>
            <button class="action-button" type="button" id="translate">
              Translate
            </button>
            <button class="action-button primary" type="button" id="build">
              Build request
            </button>
            <button class="action-button primary" type="button" id="send">
              Send
            </button>
          </div>
        </div>

        <div class="editor-grid">
          <div class="editor-field">
            <label for="messages">Messages / contents</label>
            <textarea id="messages" spellcheck="false"></textarea>
          </div>

          <div class="editor-field">
            <label for="tools">Tools / function declarations</label>
            <textarea id="tools" spellcheck="false"></textarea>
          </div>

          <div class="editor-field">
            <label for="response-config">
              Response format / generation config
            </label>
            <textarea id="response-config" spellcheck="false"></textarea>
          </div>

          <div class="editor-field">
            <label for="metadata">Metadata</label>
            <textarea id="metadata" spellcheck="false"></textarea>
          </div>

          <div class="editor-field field-wide">
            <label for="headers">Headers</label>
            <textarea id="headers" spellcheck="false"></textarea>
          </div>
        </div>

        <div class="preview-grid">
          <div class="editor-field">
            <div class="field-label">Request preview</div>
            <pre id="request-preview"></pre>
          </div>
          <div class="editor-field">
            <div class="field-label">Redacted headers</div>
            <pre id="headers-preview"></pre>
          </div>
        </div>

        <div class="response-shell" aria-label="Response panels">
          <div class="tabbar" role="tablist" aria-label="Response views">
            <button
              class="response-tab is-active"
              type="button"
              data-panel="stream-panel"
            >
              Stream output
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="raw-request-panel"
            >
              Raw request
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="raw-response-panel"
            >
              Raw response
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="normalized-request-panel"
            >
              Normalized request
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="normalized-response-panel"
            >
              Normalized response
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="provider-request-panel"
            >
              Provider request
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="provider-response-panel"
            >
              Provider response
            </button>
            <button
              class="response-tab"
              type="button"
              data-panel="snippets-panel"
            >
              Snippets
            </button>
          </div>

          <div class="meta-grid" aria-label="Request metadata">
            <div class="meta-item">
              <span class="meta-label">request_id</span>
              <span class="meta-value" id="request-id">draft-request</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">trace_id</span>
              <span class="meta-value" id="trace-id">not emitted</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">traffic_log_id</span>
              <span class="meta-value" id="traffic-log-id">not stored</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">Phoenix</span>
              <span class="meta-value" id="phoenix-link">not configured</span>
            </div>
          </div>

          <div class="response-panel is-active" id="stream-panel">
            <div class="field-label">Stream output</div>
            <pre id="stream-output"></pre>
          </div>

          <div class="response-panel" id="raw-request-panel">
            <div class="field-label">Raw request</div>
            <pre id="raw-request"></pre>
          </div>

          <div class="response-panel" id="raw-response-panel">
            <div class="field-label">Raw response</div>
            <pre id="raw-response"></pre>
          </div>

          <div class="response-panel" id="normalized-request-panel">
            <div class="field-label">Normalized request</div>
            <pre id="normalized-request"></pre>
          </div>

          <div class="response-panel" id="normalized-response-panel">
            <div class="field-label">Normalized response</div>
            <pre id="normalized-response"></pre>
          </div>

          <div class="response-panel" id="provider-request-panel">
            <div class="field-label">Provider request</div>
            <pre id="provider-request"></pre>
          </div>

          <div class="response-panel" id="provider-response-panel">
            <div class="field-label">Provider response</div>
            <pre id="provider-response"></pre>
          </div>

          <div class="response-panel" id="snippets-panel">
            <div class="snippet-grid">
              <div class="editor-field">
                <div class="snippet-head">
                  <div class="field-label">curl</div>
                  <button
                    class="copy-button"
                    type="button"
                    data-copy-target="curl-snippet"
                  >
                    Copy
                  </button>
                </div>
                <pre id="curl-snippet"></pre>
              </div>
              <div class="editor-field">
                <div class="snippet-head">
                  <div class="field-label">Python SDK</div>
                  <button
                    class="copy-button"
                    type="button"
                    data-copy-target="python-snippet"
                  >
                    Copy
                  </button>
                </div>
                <pre id="python-snippet"></pre>
              </div>
              <div class="editor-field">
                <div class="snippet-head">
                  <div class="field-label">Google GenAI</div>
                  <button
                    class="copy-button"
                    type="button"
                    data-copy-target="google-genai-snippet"
                  >
                    Copy
                  </button>
                </div>
                <pre id="google-genai-snippet"></pre>
              </div>
            </div>
            <div class="copy-status" id="copy-status" aria-live="polite"></div>
          </div>
        </div>
      </section>
    </div>
  </main>

  <script>
    const operations = {
      openai: [
        ["chat", "Chat Completions"],
        ["responses", "Responses"],
        ["embeddings", "Embeddings"]
      ],
      anthropic: [
        ["messages", "Messages"],
        ["count_tokens", "Count tokens"]
      ],
      gemini: [
        ["generateContent", "generateContent"],
        ["streamGenerateContent", "streamGenerateContent"],
        ["embedContent", "embedContent"],
        ["batchEmbedContents", "batchEmbedContents"],
        ["countTokens", "countTokens"]
      ]
    };

    let examples = {
      "openai-chat": {
        protocol: "openai",
        operation: "chat",
        model: "GigaChat-2-Max",
        stream: false,
        temperature: 0.3,
        maxOutput: 512,
        messages: [
          { role: "system", content: "Answer concisely." },
          { role: "user", content: "Summarize the release scope." }
        ],
        tools: [],
        responseConfig: {},
        metadata: { source: "playground" },
        headers: { Authorization: "Bearer <GPT2GIGA_API_KEY>" }
      },
      "anthropic-messages": {
        protocol: "anthropic",
        operation: "messages",
        model: "GigaChat-2-Max",
        stream: false,
        temperature: 0.2,
        maxOutput: 512,
        messages: [
          { role: "user", content: "Draft a migration note." }
        ],
        tools: [],
        responseConfig: {},
        metadata: { source: "playground" },
        headers: { "x-api-key": "<GPT2GIGA_API_KEY>" }
      },
      "gemini-generate": {
        protocol: "gemini",
        operation: "generateContent",
        model: "GigaChat-2-Max",
        stream: false,
        temperature: 0.3,
        maxOutput: 512,
        messages: [
          {
            role: "user",
            parts: [{ text: "Write a Gemini-compatible smoke prompt." }]
          }
        ],
        tools: [],
        responseConfig: {},
        metadata: { source: "playground" },
        headers: { "x-goog-api-key": "<GPT2GIGA_API_KEY>" }
      },
      "gemini-stream": {
        protocol: "gemini",
        operation: "streamGenerateContent",
        model: "GigaChat-2-Max",
        stream: true,
        temperature: 0.3,
        maxOutput: 512,
        messages: [
          {
            role: "user",
            parts: [{ text: "Stream three short bullet points." }]
          }
        ],
        tools: [],
        responseConfig: {},
        metadata: { source: "playground" },
        headers: { "x-goog-api-key": "<GPT2GIGA_API_KEY>" }
      },
      tools: {
        protocol: "openai",
        operation: "chat",
        model: "GigaChat-2-Max",
        stream: false,
        temperature: 0.2,
        maxOutput: 512,
        messages: [
          { role: "user", content: "Call get_release_status." }
        ],
        tools: [
          {
            type: "function",
            function: {
              name: "get_release_status",
              description: "Return release status for one version.",
              parameters: {
                type: "object",
                properties: {
                  version: { type: "string" }
                },
                required: ["version"]
              }
            }
          }
        ],
        responseConfig: {},
        metadata: { source: "playground", case: "tools" },
        headers: { Authorization: "Bearer <GPT2GIGA_API_KEY>" }
      },
      "structured-output": {
        protocol: "gemini",
        operation: "generateContent",
        model: "GigaChat-2-Max",
        stream: false,
        temperature: 0.1,
        maxOutput: 512,
        messages: [
          {
            role: "user",
            parts: [{ text: "Return a JSON object with status and risks." }]
          }
        ],
        tools: [],
        responseConfig: {
          responseMimeType: "application/json",
          responseSchema: {
            type: "object",
            properties: {
              status: { type: "string" },
              risks: {
                type: "array",
                items: { type: "string" }
              }
            },
            required: ["status", "risks"]
          }
        },
        metadata: { source: "playground", case: "structured-output" },
        headers: { "x-goog-api-key": "<GPT2GIGA_API_KEY>" }
      },
      embeddings: {
        protocol: "gemini",
        operation: "embedContent",
        model: "EmbeddingsGigaR",
        stream: false,
        temperature: 0,
        maxOutput: 512,
        messages: {
          parts: [{ text: "Compatibility gateways normalize clients." }]
        },
        tools: [],
        responseConfig: {},
        metadata: { source: "playground", case: "embeddings" },
        headers: { "x-goog-api-key": "<GPT2GIGA_API_KEY>" }
      },
      "count-tokens": {
        protocol: "gemini",
        operation: "countTokens",
        model: "GigaChat-2-Max",
        stream: false,
        temperature: 0,
        maxOutput: 512,
        messages: [
          { role: "user", parts: [{ text: "Count these tokens." }] }
        ],
        tools: [],
        responseConfig: {},
        metadata: { source: "playground", case: "count-tokens" },
        headers: { "x-goog-api-key": "<GPT2GIGA_API_KEY>" }
      }
    };

    const secretHeaderNames = new Set([
      "authorization",
      "proxy-authorization",
      "x-api-key",
      "x-goog-api-key",
      "api-key",
      "cookie",
      "set-cookie"
    ]);

    const fields = {
      protocol: document.getElementById("protocol"),
      operation: document.getElementById("operation"),
      model: document.getElementById("model"),
      stream: document.getElementById("stream"),
      temperature: document.getElementById("temperature"),
      maxOutput: document.getElementById("max-output"),
      messages: document.getElementById("messages"),
      tools: document.getElementById("tools"),
      responseConfig: document.getElementById("response-config"),
      metadata: document.getElementById("metadata"),
      headers: document.getElementById("headers"),
      adminKey: document.getElementById("admin-key"),
      endpoint: document.getElementById("endpoint"),
      protocolPill: document.getElementById("protocol-pill"),
      statusLabel: document.getElementById("status-label"),
      requestPreview: document.getElementById("request-preview"),
      headersPreview: document.getElementById("headers-preview"),
      requestId: document.getElementById("request-id"),
      traceId: document.getElementById("trace-id"),
      trafficLogId: document.getElementById("traffic-log-id"),
      phoenixLink: document.getElementById("phoenix-link"),
      streamOutput: document.getElementById("stream-output"),
      rawRequest: document.getElementById("raw-request"),
      rawResponse: document.getElementById("raw-response"),
      normalizedRequest: document.getElementById("normalized-request"),
      normalizedResponse: document.getElementById("normalized-response"),
      providerRequest: document.getElementById("provider-request"),
      providerResponse: document.getElementById("provider-response"),
      curlSnippet: document.getElementById("curl-snippet"),
      pythonSnippet: document.getElementById("python-snippet"),
      googleGenaiSnippet: document.getElementById("google-genai-snippet"),
      copyStatus: document.getElementById("copy-status")
    };

    function pretty(value) {
      return JSON.stringify(value, null, 2);
    }

    function parseJson(id, fallback) {
      const raw = fields[id].value.trim();
      if (!raw) {
        return fallback;
      }
      return JSON.parse(raw);
    }

    function setJson(id, value) {
      fields[id].value = pretty(value);
    }

    function currentEndpoint() {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      const model = encodeURIComponent(fields.model.value || "GigaChat-2-Max");
      if (protocol === "openai" && operation === "chat") {
        return "POST /v1/chat/completions";
      }
      if (protocol === "openai" && operation === "responses") {
        return "POST /v1/responses";
      }
      if (protocol === "openai" && operation === "embeddings") {
        return "POST /v1/embeddings";
      }
      if (protocol === "anthropic" && operation === "messages") {
        return "POST /v1/messages";
      }
      if (protocol === "anthropic" && operation === "count_tokens") {
        return "POST /v1/messages/count_tokens";
      }
      return `POST /v1beta/models/${model}:${operation}`;
    }

    function syncOperations(preferred) {
      const protocol = fields.protocol.value;
      const previous = preferred || fields.operation.value;
      fields.operation.innerHTML = "";
      operations[protocol].forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        fields.operation.append(option);
      });
      const nextValues = operations[protocol].map(([value]) => value);
      fields.operation.value = nextValues.includes(previous)
        ? previous
        : nextValues[0];
    }

    function applyExample(name) {
      const example = examples[name];
      fields.protocol.value = example.protocol;
      syncOperations(example.operation);
      fields.operation.value = example.operation;
      fields.model.value = example.model;
      fields.stream.checked = Boolean(example.stream);
      fields.temperature.value = String(example.temperature);
      fields.maxOutput.value = String(example.maxOutput);
      setJson("messages", example.messages);
      setJson("tools", example.tools);
      setJson("responseConfig", example.responseConfig);
      setJson("metadata", example.metadata);
      setJson("headers", example.headers);
      document.querySelectorAll(".example-button").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.example === name);
      });
      buildPreview();
    }

    function buildBody() {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      const model = fields.model.value || "GigaChat-2-Max";
      const temperature = Number(fields.temperature.value || 0);
      const maxOutput = Number(fields.maxOutput.value || 512);
      const messages = parseJson("messages", []);
      const tools = parseJson("tools", []);
      const responseConfig = parseJson("responseConfig", {});
      const metadata = parseJson("metadata", {});

      if (protocol === "openai" && operation === "responses") {
        return {
          model,
          input: messages,
          temperature,
          max_output_tokens: maxOutput,
          tools,
          response_format: responseConfig,
          metadata
        };
      }

      if (protocol === "openai" && operation === "embeddings") {
        return {
          model,
          input: Array.isArray(messages) ? messages : [messages],
          metadata
        };
      }

      if (protocol === "openai") {
        return {
          model,
          messages,
          stream: fields.stream.checked,
          temperature,
          max_tokens: maxOutput,
          tools,
          response_format: responseConfig,
          metadata
        };
      }

      if (protocol === "anthropic" && operation === "count_tokens") {
        return { model, messages };
      }

      if (protocol === "anthropic") {
        return {
          model,
          messages,
          stream: fields.stream.checked,
          temperature,
          max_tokens: maxOutput,
          tools,
          metadata
        };
      }

      if (operation === "embedContent") {
        return { model, content: messages, metadata };
      }

      if (operation === "batchEmbedContents") {
        const requests = Array.isArray(messages)
          ? messages.map((content) => ({ model, content }))
          : [{ model, content: messages }];
        return { requests, metadata };
      }

      if (operation === "countTokens") {
        return { model, contents: messages };
      }

      const body = {
        contents: messages,
        generationConfig: {
          temperature,
          maxOutputTokens: maxOutput,
          ...responseConfig
        },
        metadata
      };
      if (Array.isArray(tools) && tools.length > 0) {
        body.tools = tools;
      }
      return body;
    }

    function redactHeaders(headers) {
      const safe = {};
      Object.entries(headers || {}).forEach(([key, value]) => {
        const lowered = key.toLowerCase();
        safe[key] = secretHeaderNames.has(lowered) ? "[REDACTED]" : value;
      });
      return safe;
    }

    function endpointPath(endpoint) {
      return endpoint.replace(/^POST\\s+/, "");
    }

    function draftRequestId() {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      return `draft-${protocol}-${operation}`;
    }

    function extractPromptText(value) {
      if (typeof value === "string") {
        return value;
      }
      if (Array.isArray(value)) {
        return value.map(extractPromptText).filter(Boolean).join("\\n");
      }
      if (!value || typeof value !== "object") {
        return "";
      }
      if (typeof value.content === "string") {
        return value.content;
      }
      if (Array.isArray(value.parts)) {
        return value.parts.map(extractPromptText).filter(Boolean).join("\\n");
      }
      if (typeof value.text === "string") {
        return value.text;
      }
      return "";
    }

    function buildPayload() {
      const endpoint = currentEndpoint();
      const headers = parseJson("headers", {});
      const body = buildBody();
      return {
        method: "POST",
        path: endpointPath(endpoint),
        endpoint,
        headers,
        redactedHeaders: redactHeaders(headers),
        body
      };
    }

    function setStatus(text) {
      fields.statusLabel.textContent = text;
    }

    function adminHeaders() {
      const key = fields.adminKey.value.trim();
      return key ? { "x-admin-api-key": key } : {};
    }

    function redactText(value) {
      return String(value)
        .replace(/(Bearer\\s+)\\S+/gi, "$1[REDACTED]")
        .replace(
          /(authorization|x-api-key|x-goog-api-key|api[_-]?key|key)(["']?\\s*[:=]\\s*["']?)[^"',&\\s}]+/gi,
          "$1$2[REDACTED]"
        );
    }

    function helperErrorMessage(response, data, fallbackText) {
      const detail = data && (data.detail || data.error || data.message);
      if (typeof detail === "string") {
        return redactText(detail);
      }
      if (detail) {
        return redactText(pretty(detail));
      }
      return redactText(fallbackText || `HTTP ${response.status}`);
    }

    async function helperFetch(path, options = {}) {
      const method = options.method || "POST";
      const fetchOptions = {
        method,
        headers: {
          ...adminHeaders()
        }
      };
      if (options.body !== undefined) {
        fetchOptions.headers["Content-Type"] = "application/json";
        fetchOptions.body = JSON.stringify(options.body);
      }
      const response = await fetch(path, fetchOptions);
      const text = await response.text();
      let data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (error) {
          data = { text };
        }
      }
      if (!response.ok) {
        throw new Error(helperErrorMessage(response, data, text));
      }
      return data || {};
    }

    function showHelperError(error) {
      const message = redactText(error.message || error);
      [
        fields.rawResponse,
        fields.normalizedRequest,
        fields.normalizedResponse,
        fields.providerRequest,
        fields.providerResponse
      ].forEach((field) => {
        field.classList.add("error");
      });
      fields.rawResponse.textContent = message;
      fields.providerResponse.textContent = message;
      setActivePanel("raw-response-panel");
      setStatus("Helper error");
    }

    async function loadServerExamples() {
      try {
        setStatus("Loading examples");
        const data = await helperFetch("/_admin/playground/examples", {
          method: "GET"
        });
        const items = Array.isArray(data.data) ? data.data : [];
        items.forEach((item) => {
          if (item && item.id && item.request) {
            examples[item.id] = item.request;
          }
        });
        setStatus(`Examples loaded (${items.length})`);
      } catch (error) {
        showHelperError(error);
      }
    }

    async function translateRequest() {
      try {
        const payload = buildPayload();
        setStatus("Translating");
        const result = await helperFetch("/_admin/playground/translate", {
          body: {
            from: fields.protocol.value,
            to: "normalized",
            payload: payload.body,
            requested_model: fields.model.value || "GigaChat-2-Max"
          }
        });
        fields.normalizedRequest.classList.remove("error");
        fields.providerRequest.classList.remove("error");
        fields.normalizedRequest.textContent = pretty(result.payload || {});
        fields.providerRequest.textContent = pretty(result.intermediate || {});
        fields.requestId.textContent = "translated";
        fields.traceId.textContent = "not emitted";
        fields.trafficLogId.textContent = "not stored";
        fields.phoenixLink.textContent = "not configured";
        setActivePanel("normalized-request-panel");
        setStatus("Translated");
      } catch (error) {
        showHelperError(error);
      }
    }

    async function sendRequest() {
      try {
        const payload = buildPayload();
        setStatus("Sending");
        const result = await helperFetch("/_admin/playground/send", {
          body: {
            method: payload.method,
            path: payload.path,
            headers: payload.headers,
            body: payload.body
          }
        });
        const response = result.response || {};
        const responseBody = response.body;
        fields.rawRequest.classList.remove("error");
        fields.rawResponse.classList.remove("error");
        fields.providerResponse.classList.remove("error");
        fields.requestId.textContent = result.request_id || "not emitted";
        fields.traceId.textContent = result.trace_id || "not emitted";
        fields.trafficLogId.textContent =
          result.traffic_log_id || "not stored";
        fields.phoenixLink.textContent = "not configured";
        fields.rawRequest.textContent = pretty(result.request || {});
        fields.rawResponse.textContent = pretty(response);
        fields.providerResponse.textContent = pretty(response);
        fields.streamOutput.textContent =
          typeof responseBody === "string"
            ? responseBody
            : pretty(responseBody || {});
        setActivePanel("raw-response-panel");
        setStatus(`Sent ${response.status_code || ""}`.trim());
      } catch (error) {
        showHelperError(error);
      }
    }

    function buildNormalizedRequest(payload) {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      const body = payload.body;
      return {
        protocol,
        operation,
        model: fields.model.value || "GigaChat-2-Max",
        stream: fields.stream.checked,
        messages:
          body.messages ||
          body.input ||
          body.contents ||
          body.content ||
          body.requests ||
          [],
        tools: body.tools || [],
        generation_config:
          body.generationConfig ||
          body.response_format ||
          {},
        metadata: body.metadata || {}
      };
    }

    function buildProviderRequest(normalizedRequest) {
      return {
        provider: "gigachat",
        model: normalizedRequest.model,
        stream: normalizedRequest.stream,
        messages: normalizedRequest.messages,
        tools: normalizedRequest.tools,
        generation_config: normalizedRequest.generation_config
      };
    }

    function buildNormalizedResponse(normalizedRequest) {
      return {
        id: draftRequestId(),
        model: normalizedRequest.model,
        role: "assistant",
        content: "Draft response preview.",
        finish_reason: "stop",
        tool_calls: [],
        usage: {
          input_tokens: 0,
          output_tokens: 0,
          total_tokens: 0
        }
      };
    }

    function buildRawResponse(normalizedResponse) {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      if (protocol === "gemini" && operation === "countTokens") {
        return { totalTokens: 0 };
      }
      if (protocol === "gemini" && operation.includes("embed")) {
        return { embedding: { values: [] } };
      }
      if (protocol === "gemini") {
        return {
          candidates: [
            {
              content: {
                role: "model",
                parts: [{ text: normalizedResponse.content }]
              },
              finishReason: "STOP",
              index: 0
            }
          ],
          usageMetadata: {
            promptTokenCount: 0,
            candidatesTokenCount: 0,
            totalTokenCount: 0
          }
        };
      }
      if (protocol === "anthropic" && operation === "count_tokens") {
        return { input_tokens: 0 };
      }
      if (protocol === "anthropic") {
        return {
          id: normalizedResponse.id,
          type: "message",
          role: "assistant",
          model: normalizedResponse.model,
          content: [{ type: "text", text: normalizedResponse.content }],
          stop_reason: "end_turn",
          usage: { input_tokens: 0, output_tokens: 0 }
        };
      }
      if (protocol === "openai" && operation === "responses") {
        return {
          id: normalizedResponse.id,
          object: "response",
          status: "completed",
          model: normalizedResponse.model,
          output: [
            {
              type: "message",
              role: "assistant",
              content: [
                { type: "output_text", text: normalizedResponse.content }
              ]
            }
          ],
          usage: normalizedResponse.usage
        };
      }
      if (protocol === "openai" && operation === "embeddings") {
        return {
          object: "list",
          data: [{ object: "embedding", index: 0, embedding: [] }],
          model: normalizedResponse.model,
          usage: normalizedResponse.usage
        };
      }
      return {
        id: normalizedResponse.id,
        object: "chat.completion",
        model: normalizedResponse.model,
        choices: [
          {
            index: 0,
            message: {
              role: "assistant",
              content: normalizedResponse.content
            },
            finish_reason: "stop"
          }
        ],
        usage: normalizedResponse.usage
      };
    }

    function buildStreamOutput(rawResponse) {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      const isStream =
        fields.stream.checked || operation === "streamGenerateContent";
      if (!isStream) {
        return "stream=false";
      }
      if (protocol === "gemini") {
        return [
          "data: " + pretty(rawResponse),
          "",
          "data: [DONE]"
        ].join("\\n");
      }
      if (protocol === "anthropic") {
        return [
          'event: message_start',
          'data: {"type":"message_start"}',
          '',
          'event: content_block_delta',
          'data: {"type":"content_block_delta"}',
          '',
          'event: message_stop',
          'data: {"type":"message_stop"}'
        ].join("\\n");
      }
      return [
        "data: " + pretty(rawResponse),
        "",
        "data: [DONE]"
      ].join("\\n");
    }

    function shellQuote(value) {
      return "'" + String(value).replaceAll("'", "'\\\\''") + "'";
    }

    function buildCurlSnippet(payload) {
      const baseUrl = "http://localhost:8090";
      const headers = {
        "Content-Type": "application/json",
        ...payload.redactedHeaders
      };
      const headerLines = Object.entries(headers)
        .map(([key, value]) => `  -H ${shellQuote(`${key}: ${value}`)} \\\\`)
        .join("\\n");
      return [
        `curl -sS ${shellQuote(baseUrl + payload.path)} \\\\`,
        headerLines,
        `  --data-binary ${shellQuote(pretty(payload.body))}`
      ].join("\\n");
    }

    function buildPythonSnippet(payload) {
      const protocol = fields.protocol.value;
      const operation = fields.operation.value;
      const body = pretty(payload.body);
      if (protocol === "gemini") {
        return [
          "import json",
          "import requests",
          "",
          'url = "http://localhost:8090' + payload.path + '"',
          "headers = " + pretty({
            "Content-Type": "application/json",
            ...payload.redactedHeaders
          }),
          `body = json.loads(${JSON.stringify(body)})`,
          "response = requests.post(url, headers=headers, json=body, timeout=60)",
          "response.raise_for_status()",
          "print(response.json())"
        ].join("\\n");
      }
      if (protocol === "anthropic") {
        const method = operation === "count_tokens"
          ? "messages.count_tokens"
          : "messages.create";
        return [
          "import json",
          "from anthropic import Anthropic",
          "",
          'client = Anthropic(',
          '    base_url="http://localhost:8090",',
          '    api_key="<GPT2GIGA_API_KEY>",',
          ")",
          `body = json.loads(${JSON.stringify(body)})`,
          `response = client.${method}(**body)`,
          "print(response)"
        ].join("\\n");
      }
      const methodMap = {
        chat: "chat.completions.create",
        responses: "responses.create",
        embeddings: "embeddings.create"
      };
      return [
        "import json",
        "from openai import OpenAI",
        "",
        'client = OpenAI(',
        '    base_url="http://localhost:8090/v1",',
        '    api_key="<GPT2GIGA_API_KEY>",',
        ")",
        `body = json.loads(${JSON.stringify(body)})`,
        `response = client.${methodMap[operation] || "chat.completions.create"}(**body)`,
        "print(response)"
      ].join("\\n");
    }

    function buildGoogleGenaiSnippet(payload) {
      if (fields.protocol.value !== "gemini") {
        return "Select Gemini to generate a Google GenAI snippet.";
      }
      const operation = fields.operation.value;
      const model = fields.model.value || "GigaChat-2-Max";
      const body = payload.body;
      const config = body.generationConfig || {};
      if (operation === "embedContent") {
        return [
          "from google import genai",
          "",
          'client = genai.Client(',
          '    api_key="<GPT2GIGA_API_KEY>",',
          '    http_options={"base_url": "http://localhost:8090/v1beta"},',
          ")",
          "response = client.models.embed_content(",
          `    model=${JSON.stringify(model)},`,
          `    contents=${JSON.stringify(body.content)},`,
          ")",
          "print(response)"
        ].join("\\n");
      }
      if (operation === "countTokens") {
        return [
          "from google import genai",
          "",
          'client = genai.Client(',
          '    api_key="<GPT2GIGA_API_KEY>",',
          '    http_options={"base_url": "http://localhost:8090/v1beta"},',
          ")",
          "response = client.models.count_tokens(",
          `    model=${JSON.stringify(model)},`,
          `    contents=${JSON.stringify(body.contents)},`,
          ")",
          "print(response)"
        ].join("\\n");
      }
      const method = operation === "streamGenerateContent"
        ? "generate_content_stream"
        : "generate_content";
      return [
        "from google import genai",
        "",
        'client = genai.Client(',
        '    api_key="<GPT2GIGA_API_KEY>",',
        '    http_options={"base_url": "http://localhost:8090/v1beta"},',
        ")",
        `response = client.models.${method}(`,
        `    model=${JSON.stringify(model)},`,
        `    contents=${JSON.stringify(body.contents || [])},`,
        `    config=${JSON.stringify(config)},`,
        ")",
        "print(response)"
      ].join("\\n");
    }

    function updateResponsePanels(payload) {
      const normalizedRequest = buildNormalizedRequest(payload);
      const providerRequest = buildProviderRequest(normalizedRequest);
      const normalizedResponse = buildNormalizedResponse(normalizedRequest);
      const rawResponse = buildRawResponse(normalizedResponse);
      fields.requestId.textContent = draftRequestId();
      fields.traceId.textContent = "not emitted";
      fields.trafficLogId.textContent = "not stored";
      fields.phoenixLink.textContent = "not configured";
      fields.streamOutput.textContent = buildStreamOutput(rawResponse);
      fields.rawRequest.textContent = pretty({
        method: payload.method,
        path: payload.path,
        headers: payload.redactedHeaders,
        body: payload.body
      });
      fields.rawResponse.textContent = pretty(rawResponse);
      fields.normalizedRequest.textContent = pretty(normalizedRequest);
      fields.normalizedResponse.textContent = pretty(normalizedResponse);
      fields.providerRequest.textContent = pretty(providerRequest);
      fields.providerResponse.textContent = pretty({
        provider: "gigachat",
        status: "draft",
        response: normalizedResponse
      });
      fields.curlSnippet.textContent = buildCurlSnippet(payload);
      fields.pythonSnippet.textContent = buildPythonSnippet(payload);
      fields.googleGenaiSnippet.textContent = buildGoogleGenaiSnippet(payload);
    }

    function setActivePanel(panelId) {
      document.querySelectorAll(".response-tab").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.panel === panelId);
      });
      document.querySelectorAll(".response-panel").forEach((panel) => {
        panel.classList.toggle("is-active", panel.id === panelId);
      });
    }

    function fallbackCopy(text) {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "readonly");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.append(textarea);
      textarea.select();
      let copied = false;
      try {
        copied = document.execCommand("copy");
      } finally {
        textarea.remove();
      }
      return copied;
    }

    function selectSnippet(target) {
      if (!target) {
        return false;
      }
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      if (!selection) {
        return false;
      }
      selection.removeAllRanges();
      selection.addRange(range);
      return true;
    }

    async function copySnippet(targetId) {
      const target = document.getElementById(targetId);
      const text = target ? target.textContent : "";
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else if (!fallbackCopy(text)) {
          throw new Error("Clipboard unavailable");
        }
        fields.copyStatus.textContent = "Copied";
      } catch (error) {
        if (fallbackCopy(text)) {
          fields.copyStatus.textContent = "Copied";
        } else if (selectSnippet(target)) {
          fields.copyStatus.textContent = "Selected";
        } else {
          fields.copyStatus.textContent = "Copy unavailable";
        }
      }
    }

    function buildPreview() {
      try {
        const payload = buildPayload();
        fields.endpoint.textContent = currentEndpoint();
        fields.protocolPill.textContent =
          fields.protocol.options[fields.protocol.selectedIndex].text;
        [
          fields.requestPreview,
          fields.headersPreview,
          fields.streamOutput,
          fields.rawRequest,
          fields.rawResponse,
          fields.normalizedRequest,
          fields.normalizedResponse,
          fields.providerRequest,
          fields.providerResponse,
          fields.curlSnippet,
          fields.pythonSnippet,
          fields.googleGenaiSnippet
        ].forEach((field) => field.classList.remove("error"));
        fields.copyStatus.textContent = "";
        setStatus("Local request draft");
        fields.requestPreview.textContent = pretty(payload.body);
        fields.headersPreview.textContent = pretty(payload.redactedHeaders);
        updateResponsePanels(payload);
      } catch (error) {
        const message = String(error.message || error);
        [
          fields.requestPreview,
          fields.headersPreview,
          fields.streamOutput,
          fields.rawRequest,
          fields.rawResponse,
          fields.normalizedRequest,
          fields.normalizedResponse,
          fields.providerRequest,
          fields.providerResponse,
          fields.curlSnippet,
          fields.pythonSnippet,
          fields.googleGenaiSnippet
        ].forEach((field) => {
          field.classList.add("error");
          field.textContent = message;
        });
        fields.copyStatus.textContent = "";
        setStatus("Invalid draft");
      }
    }

    function formatEditors() {
      ["messages", "tools", "responseConfig", "metadata", "headers"].forEach(
        (id) => {
          fields[id].value = pretty(parseJson(id, id === "messages" ? [] : {}));
        }
      );
      buildPreview();
    }

    fields.protocol.addEventListener("change", () => {
      syncOperations();
      buildPreview();
    });
    fields.operation.addEventListener("change", () => {
      fields.stream.checked =
        fields.protocol.value === "gemini" &&
        fields.operation.value === "streamGenerateContent";
      buildPreview();
    });
    [
      fields.model,
      fields.stream,
      fields.temperature,
      fields.maxOutput,
      fields.messages,
      fields.tools,
      fields.responseConfig,
      fields.metadata,
      fields.headers
    ].forEach((field) => field.addEventListener("input", buildPreview));

    document.querySelectorAll(".example-button").forEach((button) => {
      button.addEventListener("click", () => applyExample(button.dataset.example));
    });
    document.querySelectorAll(".response-tab").forEach((button) => {
      button.addEventListener("click", () => setActivePanel(button.dataset.panel));
    });
    document.querySelectorAll(".copy-button").forEach((button) => {
      button.addEventListener("click", () => copySnippet(button.dataset.copyTarget));
    });
    document
      .getElementById("load-examples")
      .addEventListener("click", loadServerExamples);
    document.getElementById("build").addEventListener("click", buildPreview);
    document.getElementById("translate").addEventListener("click", translateRequest);
    document.getElementById("send").addEventListener("click", sendRequest);
    document.getElementById("format-json").addEventListener("click", formatEditors);

    syncOperations();
    applyExample("openai-chat");
  </script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
async def ui_root():
    """Redirect the UI root to the playground shell."""
    return RedirectResponse(url="/ui/playground")


@router.get("/", response_class=HTMLResponse)
async def ui_root_slash():
    """Redirect the UI root with a trailing slash to the playground shell."""
    return RedirectResponse(url="/ui/playground")


@router.get("/playground", response_class=HTMLResponse)
async def playground():
    """Serve the built-in playground shell."""
    return HTMLResponse(_PLAYGROUND_HTML)
