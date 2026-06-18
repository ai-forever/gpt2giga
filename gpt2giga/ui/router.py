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


_LOGS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga logs</title>
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
      --success: #047857;
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
    select {
      font: inherit;
    }

    main {
      width: min(1360px, calc(100vw - 32px));
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

    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: 0;
    }

    .nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }

    .nav a,
    .action-button,
    .pager-button {
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #ffffff;
      color: var(--text);
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      text-align: center;
      text-decoration: none;
      transition:
        background 140ms ease,
        border-color 140ms ease,
        color 140ms ease;
    }

    .nav a {
      display: inline-flex;
      align-items: center;
    }

    .nav a:hover,
    .action-button:hover,
    .pager-button:hover:not(:disabled) {
      border-color: var(--border-strong);
      background: var(--panel-soft);
    }

    .nav a.is-active,
    .action-button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }

    .action-button.primary:hover {
      border-color: var(--accent-strong);
      background: var(--accent-strong);
    }

    .pager-button:disabled {
      cursor: not-allowed;
      opacity: 0.52;
    }

    .shell {
      display: grid;
      gap: 16px;
      min-width: 0;
    }

    .panel {
      min-width: 0;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgb(17 24 39 / 7%);
    }

    .filters,
    .table-panel {
      min-width: 0;
      padding: 20px;
    }

    .filter-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      align-items: end;
    }

    .field {
      display: grid;
      gap: 7px;
      min-width: 0;
    }

    .field-wide {
      grid-column: span 2;
    }

    label,
    .field-label {
      color: var(--muted-strong);
      font-size: 12px;
      font-weight: 700;
      line-height: 1.25;
    }

    input,
    select {
      width: 100%;
      height: 38px;
      padding: 0 10px;
      color: var(--text);
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 7px;
      outline: none;
      font-size: 14px;
      transition:
        border-color 140ms ease,
        box-shadow 140ms ease;
    }

    input:focus,
    select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgb(15 118 110 / 14%);
    }

    .filter-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .status-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
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
    }

    .status.error {
      color: var(--danger);
      border-color: rgb(180 35 24 / 28%);
      background: rgb(180 35 24 / 8%);
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
    }

    .status.error .dot {
      background: var(--danger);
    }

    .pager {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .pager-label {
      color: var(--muted);
      font-size: 12.5px;
      font-weight: 700;
    }

    .table-scroll {
      width: 100%;
      min-width: 0;
      max-width: 100%;
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #ffffff;
    }

    table {
      width: 100%;
      min-width: 1160px;
      border-collapse: collapse;
    }

    th,
    td {
      padding: 10px 11px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }

    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--panel-soft);
      color: var(--muted-strong);
      font-size: 11.5px;
      font-weight: 800;
      line-height: 1.2;
      text-transform: uppercase;
    }

    td {
      color: var(--text);
      font-size: 12.5px;
      line-height: 1.38;
    }

    tbody tr:hover {
      background: rgb(15 118 110 / 4%);
    }

    tbody tr:last-child td {
      border-bottom: 0;
    }

    .mono {
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    .route-cell {
      max-width: 260px;
      overflow-wrap: anywhere;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }

    .badge.ok {
      color: var(--success);
      background: rgb(4 120 87 / 9%);
    }

    .badge.warn {
      color: var(--amber);
      background: rgb(180 83 9 / 9%);
    }

    .badge.error {
      color: var(--danger);
      background: rgb(180 35 24 / 9%);
    }

    .empty {
      display: none;
      margin-top: 12px;
      padding: 14px;
      color: var(--muted-strong);
      border: 1px dashed var(--border-strong);
      border-radius: 8px;
      background: var(--panel-soft);
      font-size: 13px;
      font-weight: 700;
    }

    .empty.is-visible {
      display: block;
    }

    @media (max-width: 1120px) {
      .filter-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 760px) {
      main {
        width: min(100vw - 20px, 1360px);
        padding: 18px 0 28px;
      }

      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .nav {
        justify-content: flex-start;
      }

      .filter-grid {
        grid-template-columns: 1fr;
      }

      .field-wide {
        grid-column: auto;
      }

      .filters,
      .table-panel {
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
        <h1>Traffic logs</h1>
      </div>
      <nav class="nav" aria-label="UI navigation">
        <a href="/ui/playground">Playground</a>
        <a class="is-active" href="/ui/logs">Logs</a>
      </nav>
    </header>

    <div class="shell">
      <section class="panel filters" aria-label="Log filters">
        <form id="filters">
          <div class="filter-grid">
            <div class="field">
              <label for="admin-key">Admin key</label>
              <input
                id="admin-key"
                name="admin-key"
                type="password"
                autocomplete="off"
              >
            </div>

            <div class="field">
              <label for="from">From</label>
              <input id="from" name="from" type="datetime-local">
            </div>

            <div class="field">
              <label for="to">To</label>
              <input id="to" name="to" type="datetime-local">
            </div>

            <div class="field">
              <label for="protocol">Protocol</label>
              <select id="protocol" name="protocol">
                <option value="">Any</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="gemini">Gemini</option>
                <option value="litellm">LiteLLM</option>
                <option value="other">Other</option>
              </select>
            </div>

            <div class="field">
              <label for="status-code">Status</label>
              <input
                id="status-code"
                name="status-code"
                inputmode="numeric"
                pattern="[0-9]*"
                placeholder="200"
              >
            </div>

            <div class="field">
              <label for="has-error">Error</label>
              <select id="has-error" name="has-error">
                <option value="">Any</option>
                <option value="true">Errors</option>
                <option value="false">Clean</option>
              </select>
            </div>

            <div class="field field-wide">
              <label for="model">Model</label>
              <input id="model" name="model" placeholder="GigaChat-2-Max">
            </div>

            <div class="field field-wide">
              <label for="route">Route</label>
              <input id="route" name="route" placeholder="/v1/chat/completions">
            </div>

            <div class="field">
              <label for="request-id">request_id</label>
              <input id="request-id" name="request-id">
            </div>

            <div class="field">
              <label for="trace-id">trace_id</label>
              <input id="trace-id" name="trace-id">
            </div>

            <div class="field">
              <label for="api-key-hash">api_key_hash</label>
              <input id="api-key-hash" name="api-key-hash">
            </div>

            <div class="field">
              <label for="limit">Limit</label>
              <select id="limit" name="limit">
                <option value="25">25</option>
                <option value="50" selected>50</option>
                <option value="100">100</option>
                <option value="250">250</option>
              </select>
            </div>

            <div class="filter-actions">
              <button class="action-button primary" type="submit" id="apply">
                Apply
              </button>
              <button class="action-button" type="button" id="reset">
                Reset
              </button>
            </div>
          </div>
        </form>
      </section>

      <section class="panel table-panel" aria-label="Traffic log list">
        <div class="status-row">
          <div class="status" id="status-label" aria-live="polite">
            <span class="dot"></span>
            <span id="status-text">Enter admin key to load logs</span>
          </div>
          <div class="pager">
            <button class="pager-button" type="button" id="prev-page" disabled>
              Prev
            </button>
            <span class="pager-label" id="page-label">Page 1</span>
            <button class="pager-button" type="button" id="next-page" disabled>
              Next
            </button>
          </div>
        </div>

        <div class="table-scroll">
          <table aria-label="Traffic logs">
            <thead>
              <tr>
                <th>Time</th>
                <th>Status</th>
                <th>Protocol</th>
                <th>Route</th>
                <th>Operation</th>
                <th>Model requested</th>
                <th>Model effective</th>
                <th>Latency</th>
                <th>Upstream</th>
                <th>Tokens</th>
                <th>request_id</th>
                <th>trace_id</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody id="log-rows"></tbody>
          </table>
        </div>

        <div class="empty is-visible" id="empty-state">
          Enter an admin key and apply filters.
        </div>
      </section>
    </div>
  </main>

  <script>
    const fields = {
      form: document.getElementById("filters"),
      adminKey: document.getElementById("admin-key"),
      from: document.getElementById("from"),
      to: document.getElementById("to"),
      protocol: document.getElementById("protocol"),
      statusCode: document.getElementById("status-code"),
      hasError: document.getElementById("has-error"),
      model: document.getElementById("model"),
      route: document.getElementById("route"),
      requestId: document.getElementById("request-id"),
      traceId: document.getElementById("trace-id"),
      apiKeyHash: document.getElementById("api-key-hash"),
      limit: document.getElementById("limit"),
      statusLabel: document.getElementById("status-label"),
      statusText: document.getElementById("status-text"),
      rows: document.getElementById("log-rows"),
      empty: document.getElementById("empty-state"),
      previous: document.getElementById("prev-page"),
      next: document.getElementById("next-page"),
      pageLabel: document.getElementById("page-label")
    };

    let currentCursor = "";
    let nextCursor = null;
    let previousCursors = [];

    function redactText(value) {
      return String(value || "")
        .replace(/(Bearer\\s+)\\S+/gi, "$1[REDACTED]")
        .replace(
          /(authorization|x-api-key|x-goog-api-key|api[_-]?key|key)(["']?\\s*[:=]\\s*["']?)[^"',&\\s}]+/gi,
          "$1$2[REDACTED]"
        );
    }

    function adminHeaders() {
      const key = fields.adminKey.value.trim();
      return key ? { "x-admin-api-key": key } : {};
    }

    function setStatus(text, mode = "ready") {
      fields.statusText.textContent = text;
      fields.statusLabel.classList.toggle("error", mode === "error");
    }

    function setEmpty(text, visible) {
      fields.empty.textContent = text;
      fields.empty.classList.toggle("is-visible", visible);
    }

    function addParam(params, key, value) {
      const text = String(value || "").trim();
      if (text) {
        params.set(key, text);
      }
    }

    function queryParams(cursor) {
      const params = new URLSearchParams();
      addParam(params, "from", fields.from.value);
      addParam(params, "to", fields.to.value);
      addParam(params, "protocol", fields.protocol.value);
      addParam(params, "status_code", fields.statusCode.value);
      addParam(params, "has_error", fields.hasError.value);
      addParam(params, "model", fields.model.value);
      addParam(params, "route", fields.route.value);
      addParam(params, "request_id", fields.requestId.value);
      addParam(params, "trace_id", fields.traceId.value);
      addParam(params, "api_key_hash", fields.apiKeyHash.value);
      addParam(params, "limit", fields.limit.value);
      if (cursor) {
        params.set("cursor", cursor);
      }
      return params;
    }

    function formatDate(value) {
      if (!value) {
        return "-";
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      return date.toLocaleString();
    }

    function valueOrDash(value) {
      if (value === null || value === undefined || value === "") {
        return "-";
      }
      return String(value);
    }

    function statusKind(code, errorType) {
      const statusCode = Number(code);
      if (errorType || statusCode >= 500) {
        return "error";
      }
      if (statusCode >= 400) {
        return "warn";
      }
      return "ok";
    }

    function operationLabel(row) {
      const metadata = row && typeof row.metadata === "object"
        ? row.metadata
        : {};
      if (metadata.operation) {
        return String(metadata.operation);
      }
      const route = String(row.route || "");
      const geminiMatch = route.match(/:([A-Za-z0-9_]+)(?:\\?|$)/);
      if (geminiMatch) {
        return geminiMatch[1];
      }
      if (route.includes("/chat/completions")) {
        return "chat";
      }
      if (route.includes("/responses")) {
        return "responses";
      }
      if (route.includes("/embeddings")) {
        return "embeddings";
      }
      if (route.includes("/messages/count_tokens")) {
        return "count_tokens";
      }
      if (route.includes("/messages")) {
        return "messages";
      }
      if (route.includes("/model/info")) {
        return "model_info";
      }
      return "-";
    }

    function latencyLabel(value) {
      return value === null || value === undefined ? "-" : `${value} ms`;
    }

    function tokensLabel(row) {
      if (row.total_tokens !== null && row.total_tokens !== undefined) {
        return String(row.total_tokens);
      }
      const input = valueOrDash(row.input_tokens);
      const output = valueOrDash(row.output_tokens);
      return input === "-" && output === "-" ? "-" : `${input}/${output}`;
    }

    function appendCell(row, value, className) {
      const cell = document.createElement("td");
      cell.textContent = valueOrDash(value);
      if (className) {
        cell.className = className;
      }
      row.append(cell);
      return cell;
    }

    function appendDetailLinkCell(row, record) {
      const cell = document.createElement("td");
      cell.className = "mono";
      if (!record.id) {
        cell.textContent = valueOrDash(record.request_id);
        row.append(cell);
        return cell;
      }
      const link = document.createElement("a");
      link.href = `/ui/logs/${encodeURIComponent(record.id)}`;
      link.textContent = valueOrDash(record.request_id || record.id);
      link.rel = "noreferrer";
      cell.append(link);
      row.append(cell);
      return cell;
    }

    function appendStatusCell(row, record) {
      const cell = document.createElement("td");
      const badge = document.createElement("span");
      badge.className = `badge ${statusKind(record.status_code, record.error_type)}`;
      badge.textContent = valueOrDash(record.status_code);
      cell.append(badge);
      row.append(cell);
    }

    function renderRows(
      records,
      emptyText = "No traffic logs matched the current filters."
    ) {
      fields.rows.replaceChildren();
      records.forEach((record) => {
        const row = document.createElement("tr");
        appendCell(row, formatDate(record.created_at), "mono");
        appendStatusCell(row, record);
        appendCell(row, record.protocol);
        appendCell(row, record.route, "mono route-cell");
        appendCell(row, operationLabel(record));
        appendCell(row, record.model_requested);
        appendCell(row, record.model_effective);
        appendCell(row, latencyLabel(record.latency_ms));
        appendCell(row, latencyLabel(record.upstream_latency_ms));
        appendCell(row, tokensLabel(record));
        appendDetailLinkCell(row, record);
        appendCell(row, record.trace_id, "mono");
        appendCell(row, record.error_type || "");
        fields.rows.append(row);
      });
      setEmpty(emptyText, records.length === 0);
    }

    async function parseResponse(response) {
      const text = await response.text();
      if (!text) {
        return {};
      }
      try {
        return JSON.parse(text);
      } catch (error) {
        return { text };
      }
    }

    function errorMessage(response, data) {
      const detail = data && (data.detail || data.error || data.message || data.text);
      if (response.status === 404) {
        return "Admin logs API unavailable";
      }
      if (response.status === 503) {
        return "Log store unavailable";
      }
      if (typeof detail === "string") {
        return redactText(detail);
      }
      if (detail) {
        return redactText(JSON.stringify(detail));
      }
      return `HTTP ${response.status}`;
    }

    function updatePager(data) {
      nextCursor = data.next_cursor || null;
      fields.previous.disabled = previousCursors.length === 0;
      fields.next.disabled = !nextCursor;
      fields.pageLabel.textContent = `Page ${previousCursors.length + 1}`;
    }

    async function loadLogs(cursor = "", direction = "replace") {
      if (!fields.adminKey.value.trim()) {
        renderRows([], "Enter an admin key and apply filters.");
        setStatus("Admin key required", "error");
        updatePager({ next_cursor: null });
        return;
      }

      setStatus("Loading logs");
      const response = await fetch(`/_admin/logs?${queryParams(cursor)}`, {
        headers: adminHeaders()
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        const message = errorMessage(response, data);
        renderRows([], message);
        setStatus(message, "error");
        updatePager({ next_cursor: null });
        return;
      }

      if (direction === "next") {
        previousCursors.push(currentCursor);
      } else if (direction === "replace") {
        previousCursors = [];
      }
      currentCursor = cursor;
      const records = Array.isArray(data.data) ? data.data : [];
      renderRows(records);
      updatePager(data);
      setStatus(`Loaded ${records.length} log rows`);
    }

    function resetFilters() {
      [
        fields.from,
        fields.to,
        fields.protocol,
        fields.statusCode,
        fields.hasError,
        fields.model,
        fields.route,
        fields.requestId,
        fields.traceId,
        fields.apiKeyHash
      ].forEach((field) => {
        field.value = "";
      });
      fields.limit.value = "50";
      renderRows([], "Enter an admin key and apply filters.");
      setStatus("Filters reset");
      currentCursor = "";
      nextCursor = null;
      previousCursors = [];
      updatePager({ next_cursor: null });
    }

    fields.form.addEventListener("submit", (event) => {
      event.preventDefault();
      loadLogs();
    });
    document.getElementById("reset").addEventListener("click", resetFilters);
    fields.next.addEventListener("click", () => {
      if (nextCursor) {
        loadLogs(nextCursor, "next");
      }
    });
    fields.previous.addEventListener("click", () => {
      const cursor = previousCursors.pop();
      loadLogs(cursor || "", "previous");
    });

    renderRows([], "Enter an admin key and apply filters.");
  </script>
</body>
</html>"""


_LOG_DETAIL_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>gpt2giga log detail</title>
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
      --success: #047857;
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
    input {
      font: inherit;
    }

    main {
      width: min(1240px, calc(100vw - 32px));
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
      min-width: 0;
    }

    .brand {
      color: var(--accent-strong);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: 0;
    }

    .nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }

    .nav a,
    .action-button,
    .tab-button,
    .copy-button {
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: #ffffff;
      color: var(--text);
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
      text-align: center;
      text-decoration: none;
      transition:
        background 140ms ease,
        border-color 140ms ease,
        color 140ms ease;
    }

    .nav a {
      display: inline-flex;
      align-items: center;
    }

    .nav a:hover,
    .action-button:hover,
    .tab-button:hover,
    .copy-button:hover {
      border-color: var(--border-strong);
      background: var(--panel-soft);
    }

    .nav a.is-active,
    .action-button.primary,
    .tab-button.is-active {
      border-color: var(--accent);
      background: var(--accent);
      color: #ffffff;
    }

    .action-button.primary:hover,
    .tab-button.is-active:hover {
      border-color: var(--accent-strong);
      background: var(--accent-strong);
    }

    .shell {
      display: grid;
      gap: 16px;
      min-width: 0;
    }

    .panel {
      min-width: 0;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgb(17 24 39 / 7%);
    }

    .controls,
    .detail-panel {
      padding: 20px;
    }

    .control-grid {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(260px, 2fr) auto;
      gap: 12px;
      align-items: end;
    }

    .field {
      display: grid;
      gap: 7px;
      min-width: 0;
    }

    label,
    .field-label {
      color: var(--muted-strong);
      font-size: 12px;
      font-weight: 700;
      line-height: 1.25;
    }

    input {
      width: 100%;
      height: 38px;
      padding: 0 10px;
      color: var(--text);
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 7px;
      outline: none;
      font-size: 14px;
      transition:
        border-color 140ms ease,
        box-shadow 140ms ease;
    }

    input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgb(15 118 110 / 14%);
    }

    input[readonly] {
      color: var(--muted-strong);
      background: var(--panel-soft);
    }

    .status-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
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
    }

    .status.error {
      color: var(--danger);
      border-color: rgb(180 35 24 / 28%);
      background: rgb(180 35 24 / 8%);
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
    }

    .status.error .dot {
      background: var(--danger);
    }

    .identity-row,
    .tab-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .copy-button {
      min-height: 30px;
      padding: 0 9px;
      font-size: 12px;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }

    .summary-item {
      display: grid;
      gap: 5px;
      min-width: 0;
      padding: 11px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-soft);
    }

    .summary-label {
      color: var(--muted-strong);
      font-size: 11.5px;
      font-weight: 800;
      line-height: 1.2;
      text-transform: uppercase;
    }

    .summary-value {
      min-height: 18px;
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .summary-value.mono,
    .mono {
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
    }

    .tab-panels {
      margin-top: 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #ffffff;
      overflow: hidden;
    }

    .tab-panel {
      display: none;
      padding: 16px;
    }

    .tab-panel.is-active {
      display: grid;
      gap: 12px;
    }

    pre {
      min-height: 220px;
      max-height: 520px;
      margin: 0;
      padding: 14px;
      overflow: auto;
      color: #f8fafc;
      background: var(--code);
      border-radius: 7px;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
      line-height: 1.55;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .empty {
      padding: 13px 14px;
      color: var(--muted-strong);
      border: 1px dashed var(--border-strong);
      border-radius: 8px;
      background: var(--panel-soft);
      font-size: 13px;
      font-weight: 700;
    }

    a {
      color: var(--blue);
      font-weight: 700;
    }

    @media (max-width: 980px) {
      .control-grid,
      .summary-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 720px) {
      main {
        width: min(100vw - 20px, 1240px);
        padding: 18px 0 28px;
      }

      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .nav {
        justify-content: flex-start;
      }

      .control-grid,
      .summary-grid {
        grid-template-columns: 1fr;
      }

      .controls,
      .detail-panel {
        padding: 14px;
      }

      h1 {
        font-size: 24px;
      }

      .tab-button {
        flex: 1 1 140px;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="title-group">
        <div class="brand">gpt2giga</div>
        <h1>Traffic log detail</h1>
      </div>
      <nav class="nav" aria-label="UI navigation">
        <a href="/ui/playground">Playground</a>
        <a class="is-active" href="/ui/logs">Logs</a>
      </nav>
    </header>

    <div class="shell">
      <section class="panel controls" aria-label="Log detail controls">
        <form id="detail-form">
          <div class="control-grid">
            <div class="field">
              <label for="admin-key">Admin key</label>
              <input
                id="admin-key"
                name="admin-key"
                type="password"
                autocomplete="off"
              >
            </div>
            <div class="field">
              <label for="log-id">Traffic log id</label>
              <input id="log-id" name="log-id" readonly>
            </div>
            <button class="action-button primary" type="submit" id="load-detail">
              Load detail
            </button>
          </div>
        </form>
      </section>

      <section class="panel detail-panel" aria-label="Traffic log detail">
        <div class="status-row">
          <div class="status" id="status-label" aria-live="polite">
            <span class="dot"></span>
            <span id="status-text">Enter admin key to load detail</span>
          </div>
          <div class="identity-row">
            <span class="field-label">request_id</span>
            <span class="mono" id="request-id">-</span>
            <button class="copy-button" type="button" data-copy-source="request-id">
              Copy
            </button>
            <span class="field-label">trace_id</span>
            <span class="mono" id="trace-id">-</span>
            <button class="copy-button" type="button" data-copy-source="trace-id">
              Copy
            </button>
          </div>
        </div>

        <div class="summary-grid" id="summary-grid"></div>

        <div class="tab-row" role="tablist" aria-label="Log detail tabs">
          <button class="tab-button is-active" type="button" data-panel="summary-panel">
            Summary
          </button>
          <button class="tab-button" type="button" data-panel="request-panel">
            Request
          </button>
          <button class="tab-button" type="button" data-panel="response-panel">
            Response
          </button>
          <button class="tab-button" type="button" data-panel="normalized-panel">
            Normalized
          </button>
          <button class="tab-button" type="button" data-panel="provider-panel">
            Provider
          </button>
          <button class="tab-button" type="button" data-panel="observability-panel">
            Observability
          </button>
          <button class="tab-button" type="button" data-panel="metrics-panel">
            Metrics context
          </button>
        </div>

        <div class="tab-panels">
          <div class="tab-panel is-active" id="summary-panel">
            <div class="empty" id="summary-empty">
              Load one traffic log to inspect summary metadata.
            </div>
            <pre id="summary-json">{}</pre>
          </div>
          <div class="tab-panel" id="request-panel">
            <div class="empty" id="request-empty">
              Stored request headers and body appear here when content capture is enabled.
            </div>
            <div class="field-label">Gemini contents / parts</div>
            <pre id="gemini-contents">not available</pre>
            <div class="field-label">Redacted request</div>
            <pre id="request-json">{}</pre>
          </div>
          <div class="tab-panel" id="response-panel">
            <div class="empty" id="response-empty">
              Stored response body appears here when response capture is enabled.
            </div>
            <pre id="response-json">{}</pre>
          </div>
          <div class="tab-panel" id="normalized-panel">
            <div class="empty" id="normalized-empty">
              Normalized snapshots are shown when present in traffic metadata.
            </div>
            <pre id="normalized-json">{}</pre>
          </div>
          <div class="tab-panel" id="provider-panel">
            <div class="empty" id="provider-empty">
              Provider payloads are shown only when redacted copies are stored in metadata.
            </div>
            <pre id="provider-json">{}</pre>
          </div>
          <div class="tab-panel" id="observability-panel">
            <div class="empty" id="observability-empty">
              Trace identifiers and safe span context appear here.
            </div>
            <pre id="observability-json">{}</pre>
          </div>
          <div class="tab-panel" id="metrics-panel">
            <div class="empty" id="metrics-empty">
              Bounded protocol, route, model, and status labels appear here.
            </div>
            <pre id="metrics-json">{}</pre>
          </div>
        </div>
      </section>
    </div>
  </main>

  <script>
    const fields = {
      form: document.getElementById("detail-form"),
      adminKey: document.getElementById("admin-key"),
      logId: document.getElementById("log-id"),
      statusLabel: document.getElementById("status-label"),
      statusText: document.getElementById("status-text"),
      requestId: document.getElementById("request-id"),
      traceId: document.getElementById("trace-id"),
      summaryGrid: document.getElementById("summary-grid"),
      summaryJson: document.getElementById("summary-json"),
      requestJson: document.getElementById("request-json"),
      responseJson: document.getElementById("response-json"),
      normalizedJson: document.getElementById("normalized-json"),
      providerJson: document.getElementById("provider-json"),
      observabilityJson: document.getElementById("observability-json"),
      metricsJson: document.getElementById("metrics-json"),
      geminiContents: document.getElementById("gemini-contents"),
      summaryEmpty: document.getElementById("summary-empty"),
      requestEmpty: document.getElementById("request-empty"),
      responseEmpty: document.getElementById("response-empty"),
      normalizedEmpty: document.getElementById("normalized-empty"),
      providerEmpty: document.getElementById("provider-empty"),
      observabilityEmpty: document.getElementById("observability-empty"),
      metricsEmpty: document.getElementById("metrics-empty")
    };

    const sensitivePattern =
      /(authorization|x-api-key|x-goog-api-key|api[_-]?key|cookie|set-cookie|key)(["']?\\s*[:=]\\s*["']?)[^"',&\\s}]+/gi;

    function eventIdFromPath() {
      const parts = window.location.pathname.split("/").filter(Boolean);
      return decodeURIComponent(parts[parts.length - 1] || "");
    }

    function redactText(value) {
      return String(value || "")
        .replace(/(Bearer\\s+)\\S+/gi, "$1[REDACTED]")
        .replace(sensitivePattern, "$1$2[REDACTED]");
    }

    function pretty(value) {
      return redactText(JSON.stringify(value ?? {}, null, 2));
    }

    function adminHeaders() {
      const key = fields.adminKey.value.trim();
      return key ? { "x-admin-api-key": key } : {};
    }

    function setStatus(text, mode = "ready") {
      fields.statusText.textContent = text;
      fields.statusLabel.classList.toggle("error", mode === "error");
    }

    function valueOrDash(value) {
      if (value === null || value === undefined || value === "") {
        return "-";
      }
      return String(value);
    }

    function formatDate(value) {
      if (!value) {
        return "-";
      }
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      return date.toLocaleString();
    }

    function tokensLabel(row) {
      if (row.total_tokens !== null && row.total_tokens !== undefined) {
        return String(row.total_tokens);
      }
      const input = valueOrDash(row.input_tokens);
      const output = valueOrDash(row.output_tokens);
      return input === "-" && output === "-" ? "-" : `${input}/${output}`;
    }

    function operationLabel(row) {
      const metadata = row && typeof row.metadata === "object"
        ? row.metadata
        : {};
      if (metadata.operation) {
        return String(metadata.operation);
      }
      const route = String(row.route || "");
      const geminiMatch = route.match(/:([A-Za-z0-9_]+)(?:\\?|$)/);
      if (geminiMatch) {
        return geminiMatch[1];
      }
      if (route.includes("/chat/completions")) {
        return "chat";
      }
      if (route.includes("/responses")) {
        return "responses";
      }
      if (route.includes("/embeddings")) {
        return "embeddings";
      }
      if (route.includes("/messages/count_tokens")) {
        return "count_tokens";
      }
      if (route.includes("/messages")) {
        return "messages";
      }
      if (route.includes("/model/info")) {
        return "model_info";
      }
      return "-";
    }

    function setEmpty(node, visible) {
      node.hidden = !visible;
    }

    function safeObject(value) {
      return value && typeof value === "object" && !Array.isArray(value)
        ? value
        : {};
    }

    function pickFirstObject(...values) {
      for (const value of values) {
        if (value && typeof value === "object") {
          return value;
        }
      }
      return null;
    }

    function metadataPath(metadata, ...keys) {
      let current = metadata;
      for (const key of keys) {
        if (!current || typeof current !== "object" || !(key in current)) {
          return null;
        }
        current = current[key];
      }
      return current && typeof current === "object" ? current : null;
    }

    function renderSummary(summary) {
      const items = [
        ["created_at", formatDate(summary.created_at)],
        ["status", summary.status_code],
        ["protocol", summary.protocol],
        ["route", summary.route],
        ["operation", operationLabel(summary)],
        ["method", summary.method],
        ["provider", summary.provider],
        ["model requested", summary.model_requested],
        ["model effective", summary.model_effective],
        ["latency", summary.latency_ms == null ? "-" : `${summary.latency_ms} ms`],
        [
          "upstream latency",
          summary.upstream_latency_ms == null ? "-" : `${summary.upstream_latency_ms} ms`
        ],
        ["tokens", tokensLabel(summary)],
        ["upstream status", summary.upstream_status_code],
        ["api_key_hash", summary.api_key_hash],
        ["span_id", summary.span_id],
        ["error", summary.error_type || summary.error_message]
      ];
      fields.summaryGrid.replaceChildren();
      items.forEach(([label, value]) => {
        const item = document.createElement("div");
        item.className = "summary-item";
        const labelNode = document.createElement("div");
        labelNode.className = "summary-label";
        labelNode.textContent = label;
        const valueNode = document.createElement("div");
        valueNode.className = "summary-value";
        if (String(label).includes("id") || label === "route" || label === "api_key_hash") {
          valueNode.classList.add("mono");
        }
        valueNode.textContent = valueOrDash(value);
        item.append(labelNode, valueNode);
        fields.summaryGrid.append(item);
      });
    }

    function renderRequest(summary, requestPayload) {
      const request = {
        headers: requestPayload.request_headers ?? null,
        body: requestPayload.request_body ?? null
      };
      fields.requestJson.textContent = pretty(request);
      const body = requestPayload.request_body;
      const contents = body && typeof body === "object"
        ? body.contents || body.requests || body.parts || null
        : null;
      fields.geminiContents.textContent = contents ? pretty(contents) : "not available";
      setEmpty(fields.requestEmpty, !summary.has_request_body && !request.headers);
    }

    function renderResponse(summary, responsePayload) {
      const response = { body: responsePayload.response_body ?? null };
      fields.responseJson.textContent = pretty(response);
      setEmpty(fields.responseEmpty, !summary.has_response_body);
    }

    function renderMetadataPanels(summary) {
      const metadata = safeObject(summary.metadata);
      const normalized = pickFirstObject(
        metadataPath(metadata, "normalized"),
        metadataPath(metadata, "diagnostics", "normalized"),
        metadataPath(metadata, "snapshots", "normalized")
      );
      const provider = pickFirstObject(
        metadataPath(metadata, "provider"),
        metadataPath(metadata, "provider_payload"),
        metadataPath(metadata, "snapshots", "provider")
      );
      const observability = {
        request_id: summary.request_id ?? null,
        trace_id: summary.trace_id ?? null,
        span_id: summary.span_id ?? null,
        protocol: summary.protocol ?? null,
        provider: summary.provider ?? null,
        model: summary.model_effective || summary.model_requested || null,
        route: summary.route ?? null
      };
      const metrics = {
        protocol: summary.protocol ?? null,
        route: summary.route ?? null,
        model: summary.model_effective || summary.model_requested || null,
        provider: summary.provider ?? null,
        status_code: summary.status_code ?? null,
        error_type: summary.error_type ?? null
      };

      fields.normalizedJson.textContent = pretty(normalized || {});
      fields.providerJson.textContent = pretty(provider || {});
      fields.observabilityJson.textContent = pretty(observability);
      fields.metricsJson.textContent = pretty(metrics);
      setEmpty(fields.normalizedEmpty, !normalized);
      setEmpty(fields.providerEmpty, !provider);
      setEmpty(fields.observabilityEmpty, false);
      setEmpty(fields.metricsEmpty, false);
    }

    async function parseResponse(response) {
      const text = await response.text();
      if (!text) {
        return {};
      }
      try {
        return JSON.parse(text);
      } catch (error) {
        return { text };
      }
    }

    function errorMessage(response, data) {
      const detail = data && (data.detail || data.error || data.message || data.text);
      if (response.status === 404) {
        return "Traffic log not found or admin logs API unavailable";
      }
      if (response.status === 503) {
        return "Log store unavailable";
      }
      if (typeof detail === "string") {
        return redactText(detail);
      }
      if (detail) {
        return redactText(JSON.stringify(detail));
      }
      return `HTTP ${response.status}`;
    }

    async function fetchJson(path) {
      const response = await fetch(path, { headers: adminHeaders() });
      const data = await parseResponse(response);
      if (!response.ok) {
        throw new Error(errorMessage(response, data));
      }
      return data;
    }

    async function loadDetail() {
      const id = fields.logId.value.trim();
      if (!id) {
        setStatus("Traffic log id missing", "error");
        return;
      }
      if (!fields.adminKey.value.trim()) {
        setStatus("Admin key required", "error");
        return;
      }

      setStatus("Loading detail");
      try {
        const encoded = encodeURIComponent(id);
        const summary = await fetchJson(`/_admin/logs/${encoded}`);
        const [requestPayload, responsePayload] = await Promise.all([
          fetchJson(`/_admin/logs/${encoded}/request`).catch((error) => ({
            error: error.message
          })),
          fetchJson(`/_admin/logs/${encoded}/response`).catch((error) => ({
            error: error.message
          }))
        ]);
        fields.requestId.textContent = valueOrDash(summary.request_id);
        fields.traceId.textContent = valueOrDash(summary.trace_id);
        renderSummary(summary);
        fields.summaryJson.textContent = pretty(summary);
        renderRequest(summary, requestPayload);
        renderResponse(summary, responsePayload);
        renderMetadataPanels(summary);
        setEmpty(fields.summaryEmpty, false);
        setStatus(`Loaded ${valueOrDash(summary.request_id)}`);
      } catch (error) {
        setStatus(error.message || "Failed to load detail", "error");
      }
    }

    function setActivePanel(panelId) {
      document.querySelectorAll(".tab-button").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.panel === panelId);
      });
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("is-active", panel.id === panelId);
      });
    }

    async function copyValue(sourceId) {
      const node = document.getElementById(sourceId);
      const value = node ? node.textContent.trim() : "";
      if (!value || value === "-") {
        setStatus("Nothing to copy", "error");
        return;
      }
      try {
        await navigator.clipboard.writeText(value);
        setStatus(`Copied ${sourceId}`);
      } catch (error) {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(node);
        selection.removeAllRanges();
        selection.addRange(range);
        setStatus(`Selected ${sourceId}`);
      }
    }

    fields.logId.value = eventIdFromPath();
    fields.form.addEventListener("submit", (event) => {
      event.preventDefault();
      loadDetail();
    });
    document.querySelectorAll(".tab-button").forEach((button) => {
      button.addEventListener("click", () => setActivePanel(button.dataset.panel));
    });
    document.querySelectorAll(".copy-button").forEach((button) => {
      button.addEventListener("click", () => copyValue(button.dataset.copySource));
    });
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


@router.get("/logs", response_class=HTMLResponse)
async def logs():
    """Serve the built-in traffic logs list shell."""
    return HTMLResponse(_LOGS_HTML)


@router.get("/logs/{event_id}", response_class=HTMLResponse)
async def log_detail(event_id: str):
    """Serve the built-in traffic log detail shell."""
    return HTMLResponse(_LOG_DETAIL_HTML)
