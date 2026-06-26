"""Render the built-in playground UI."""

from __future__ import annotations

import secrets

_SCRIPT_NONCE_PLACEHOLDER = "__GPT2GIGA_SCRIPT_NONCE__"


def new_script_nonce() -> str:
    """Create a CSP nonce for a single playground response."""
    return secrets.token_urlsafe(16)


def security_headers(script_nonce: str | None = None) -> dict[str, str]:
    """Build security headers for UI responses."""
    script_src = "'none'"
    if script_nonce is not None:
        script_src = f"'nonce-{script_nonce}'"
    return {
        "Content-Security-Policy": (
            "default-src 'none'; "
            "base-uri 'none'; "
            "connect-src 'none'; "
            "form-action 'none'; "
            "frame-ancestors 'none'; "
            "img-src 'self' data:; "
            f"script-src {script_src}; "
            "style-src 'unsafe-inline'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def render_playground_html(script_nonce: str) -> str:
    """Render the playground HTML with a per-response script nonce."""
    return _PLAYGROUND_HTML.replace(_SCRIPT_NONCE_PLACEHOLDER, script_nonce)


_PLAYGROUND_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>gpt2giga playground</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --surface: #ffffff;
      --surface-soft: #f3f6f8;
      --surface-strong: #e8eef5;
      --text: #101828;
      --muted: #5f6c7b;
      --border: #d7dde5;
      --teal: #0f766e;
      --blue: #1d4ed8;
      --amber: #b45309;
      --red: #b42318;
      --green: #047857;
      --ink: #111827;
      --code-bg: #111827;
      --code-text: #e5e7eb;
      --focus: 0 0 0 3px rgb(29 78 216 / 18%);
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

    main {
      width: min(1280px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }

    header {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 16px;
    }

    h1,
    h2,
    h3,
    p {
      margin: 0;
    }

    h1 {
      font-size: 28px;
      line-height: 1.2;
      font-weight: 800;
      letter-spacing: 0;
    }

    h2 {
      font-size: 16px;
      line-height: 1.3;
      font-weight: 780;
    }

    h3 {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
      font-weight: 780;
      letter-spacing: 0;
      text-transform: uppercase;
    }

    button,
    input,
    select,
    textarea {
      font: inherit;
    }

    button {
      cursor: pointer;
    }

    button:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible {
      outline: none;
      box-shadow: var(--focus);
    }

    .brand {
      display: grid;
      gap: 4px;
    }

    .brand-mark {
      color: var(--teal);
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      padding: 0 12px;
      color: var(--teal);
      border: 1px solid rgb(15 118 110 / 28%);
      border-radius: 999px;
      background: rgb(15 118 110 / 8%);
      font-size: 13px;
      font-weight: 760;
      white-space: nowrap;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--teal);
    }

    .workspace {
      display: grid;
      grid-template-columns: 232px minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }

    .panel {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgb(17 24 39 / 7%);
    }

    .nav,
    .builder,
    .preview {
      padding: 16px;
    }

    .nav {
      display: grid;
      gap: 10px;
      position: sticky;
      top: 14px;
    }

    .nav-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 44px;
      padding: 0 12px;
      color: var(--ink);
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface);
      font-size: 14px;
      font-weight: 760;
      text-decoration: none;
    }

    .nav-item[aria-current="page"] {
      color: var(--blue);
      border-color: rgb(29 78 216 / 35%);
      background: rgb(29 78 216 / 7%);
    }

    .badge {
      min-height: 24px;
      padding: 0 8px;
      color: var(--amber);
      border: 1px solid rgb(180 83 9 / 30%);
      border-radius: 999px;
      background: rgb(180 83 9 / 8%);
      font-size: 12px;
      line-height: 22px;
      font-weight: 780;
      white-space: nowrap;
    }

    .badge.ready {
      color: var(--green);
      border-color: rgb(4 120 87 / 28%);
      background: rgb(4 120 87 / 8%);
    }

    .stage {
      display: grid;
      grid-template-columns: minmax(360px, 0.92fr) minmax(380px, 1.08fr);
      gap: 14px;
      align-items: start;
    }

    .builder,
    .preview {
      display: grid;
      gap: 14px;
    }

    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 32px;
    }

    .section-head p {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .segmented {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
      padding: 4px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-soft);
    }

    .segment {
      min-height: 36px;
      border: 0;
      border-radius: 6px;
      color: var(--muted);
      background: transparent;
      font-size: 13px;
      font-weight: 780;
    }

    .segment[aria-pressed="true"] {
      color: var(--blue);
      background: var(--surface);
      box-shadow: 0 1px 4px rgb(17 24 39 / 9%);
    }

    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .field {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .field.full {
      grid-column: 1 / -1;
    }

    .field.inline {
      align-content: end;
    }

    label,
    .label {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
      font-weight: 760;
    }

    input,
    select,
    textarea {
      width: 100%;
      min-width: 0;
      color: var(--ink);
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface);
      font-size: 13px;
      line-height: 1.35;
    }

    input,
    select {
      min-height: 38px;
      padding: 0 10px;
    }

    textarea {
      min-height: 116px;
      resize: vertical;
      padding: 10px;
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.5;
      tab-size: 2;
    }

    textarea.compact {
      min-height: 82px;
    }

    .toggle {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 38px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface);
    }

    .toggle input {
      width: 18px;
      height: 18px;
      min-height: 18px;
      accent-color: var(--blue);
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .button {
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      color: var(--ink);
      background: var(--surface);
      font-size: 13px;
      font-weight: 760;
    }

    .button.primary {
      color: #ffffff;
      border-color: var(--blue);
      background: var(--blue);
    }

    .button.ghost {
      color: var(--blue);
      border-color: rgb(29 78 216 / 28%);
      background: rgb(29 78 216 / 7%);
    }

    .preview-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 4px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface-soft);
    }

    .tab {
      min-height: 32px;
      padding: 0 10px;
      border: 0;
      border-radius: 6px;
      color: var(--muted);
      background: transparent;
      font-size: 12.5px;
      font-weight: 780;
    }

    .tab[aria-selected="true"] {
      color: var(--blue);
      background: var(--surface);
      box-shadow: 0 1px 4px rgb(17 24 39 / 9%);
    }

    .preview-stack {
      display: grid;
      gap: 10px;
    }

    .route-line {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      min-height: 40px;
      padding: 0 12px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface-soft);
    }

    .method {
      color: var(--green);
      font-size: 12px;
      font-weight: 820;
      white-space: nowrap;
    }

    .route {
      min-width: 0;
      color: var(--ink);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .terminal {
      min-height: 360px;
      margin: 0;
      overflow: auto;
      padding: 14px;
      color: var(--code-text);
      border-radius: 8px;
      background: var(--code-bg);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .terminal.small {
      min-height: 118px;
      background: #172033;
    }

    .hidden {
      display: none;
    }

    .error-text {
      color: var(--red);
      font-size: 12px;
      line-height: 1.35;
      font-weight: 720;
    }

    .ok-text {
      color: var(--green);
      font-size: 12px;
      line-height: 1.35;
      font-weight: 720;
    }

    @media (max-width: 980px) {
      .workspace,
      .stage {
        grid-template-columns: 1fr;
      }

      .nav {
        position: static;
      }
    }

    @media (max-width: 680px) {
      main {
        width: min(100vw - 20px, 1280px);
        padding: 18px 0 28px;
      }

      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .form-grid,
      .segmented {
        grid-template-columns: 1fr;
      }

      .status {
        white-space: normal;
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
      <div class="brand">
        <div class="brand-mark">gpt2giga</div>
        <h1>Playground</h1>
      </div>
      <div class="status">
        <span class="dot"></span>
        <span>Local admin UI</span>
      </div>
    </header>

    <div class="workspace">
      <nav class="panel nav" aria-label="UI navigation">
        <a class="nav-item" aria-current="page" href="/ui/playground">
          <span>Playground</span>
          <span class="badge ready">builder</span>
        </a>
        <a class="nav-item" href="/_admin/compat/analyze">
          <span>Compatibility</span>
          <span class="badge">API</span>
        </a>
      </nav>

      <div class="stage">
        <section class="panel builder" aria-label="Request builder">
          <div class="section-head">
            <div>
              <h2>Request builder</h2>
              <p id="builder-status" class="ok-text">No upstream calls</p>
            </div>
          </div>

          <div class="segmented" aria-label="Protocol">
            <button class="segment" type="button" data-protocol="openai" aria-pressed="true">OpenAI</button>
            <button class="segment" type="button" data-protocol="anthropic" aria-pressed="false">Anthropic</button>
            <button class="segment" type="button" data-protocol="gemini" aria-pressed="false">Gemini</button>
          </div>

          <form id="builder-form" class="form-grid" autocomplete="off">
            <div class="field">
              <label for="operation">Operation</label>
              <select id="operation"></select>
            </div>
            <div class="field">
              <label for="prefix">Backend prefix</label>
              <select id="prefix">
                <option value="">root</option>
                <option value="/v1">/v1</option>
                <option value="/v2" selected>/v2</option>
              </select>
            </div>
            <div class="field">
              <label for="model">Model</label>
              <input id="model" value="GigaChat-2-Max" spellcheck="false">
            </div>
            <div class="field inline">
              <span class="label">Stream</span>
              <label class="toggle" for="stream">
                <input id="stream" type="checkbox">
                <span id="stream-label">disabled</span>
              </label>
            </div>
            <div class="field">
              <label for="temperature">Temperature</label>
              <input id="temperature" type="number" min="0" max="2" step="0.1" value="0.2">
            </div>
            <div class="field">
              <label for="max-tokens">Max tokens</label>
              <input id="max-tokens" type="number" min="1" step="1" value="512">
            </div>
            <div class="field full">
              <label id="messages-label" for="messages">messages / contents JSON</label>
              <textarea id="messages" spellcheck="false"></textarea>
            </div>
            <div class="field full">
              <label for="tools">tools / function declarations JSON</label>
              <textarea id="tools" class="compact" spellcheck="false"></textarea>
            </div>
            <div class="field full">
              <label id="format-label" for="format-json">response_format / generation_config JSON</label>
              <textarea id="format-json" class="compact" spellcheck="false"></textarea>
            </div>
            <div class="field full">
              <label for="metadata">metadata JSON</label>
              <textarea id="metadata" class="compact" spellcheck="false"></textarea>
            </div>
            <div class="field full">
              <label for="headers-json">headers JSON</label>
              <textarea id="headers-json" class="compact" spellcheck="false"></textarea>
            </div>
          </form>

          <div class="actions" aria-label="Builder actions">
            <button id="format-button" class="button primary" type="button">Format JSON</button>
            <button id="reset-button" class="button ghost" type="button">Reset operation</button>
          </div>
        </section>

        <section class="panel preview" aria-label="Request preview">
          <div class="section-head">
            <div>
              <h2>Preview</h2>
              <p id="preview-status" class="ok-text">Ready</p>
            </div>
          </div>

          <div class="preview-tabs" role="tablist" aria-label="Preview tabs">
            <button id="tab-request" class="tab" type="button" role="tab" aria-selected="true" data-preview="request">Request</button>
            <button id="tab-analyze" class="tab" type="button" role="tab" aria-selected="false" data-preview="analyze">Analyze</button>
            <button id="tab-redaction" class="tab" type="button" role="tab" aria-selected="false" data-preview="redaction">Redaction</button>
          </div>

          <div class="preview-stack">
            <div class="route-line">
              <span id="method-preview" class="method">POST</span>
              <span id="route-preview" class="route">/v2/chat/completions</span>
            </div>
            <pre id="request-preview" class="terminal" aria-labelledby="tab-request"></pre>
            <pre id="analyze-preview" class="terminal hidden" aria-labelledby="tab-analyze"></pre>
            <pre id="redaction-preview" class="terminal small hidden" aria-labelledby="tab-redaction"></pre>
          </div>
        </section>
      </div>
    </div>
  </main>

  <script nonce="__GPT2GIGA_SCRIPT_NONCE__">
    (() => {
      const defaultModel = "GigaChat-2-Max";
      const jsonSpaces = 2;
      let currentProtocol = "openai";
      let currentPreview = "request";

      const operations = {
        openai: [
          { id: "chat_completions", label: "Chat Completions", method: "POST", route: "chat/completions", stream: true },
          { id: "responses", label: "Responses", method: "POST", route: "responses", stream: true },
          { id: "embeddings", label: "Embeddings", method: "POST", route: "embeddings", stream: false },
          { id: "models", label: "Models", method: "GET", route: "models", stream: false }
        ],
        anthropic: [
          { id: "messages", label: "Messages", method: "POST", route: "messages", stream: true },
          { id: "count_tokens", label: "Count Tokens", method: "POST", route: "messages/count_tokens", stream: false },
          { id: "models", label: "Models", method: "GET", route: "models", stream: false }
        ],
        gemini: [
          { id: "generate_content", label: "GenerateContent", method: "POST", action: "generateContent", stream: false },
          { id: "stream_generate_content", label: "StreamGenerateContent", method: "POST", action: "streamGenerateContent", stream: true },
          { id: "count_tokens", label: "CountTokens", method: "POST", action: "countTokens", stream: false },
          { id: "embed_content", label: "EmbedContent", method: "POST", action: "embedContent", stream: false },
          { id: "batch_embed_contents", label: "BatchEmbedContents", method: "POST", action: "batchEmbedContents", stream: false },
          { id: "models", label: "Models", method: "GET", route: "v1beta/models", stream: false }
        ]
      };

      const defaults = {
        openai: {
          chat_completions: {
            messages: [
              { role: "system", content: "You are a concise assistant." },
              { role: "user", content: "Reply with a one sentence status." }
            ],
            tools: [
              {
                type: "function",
                function: {
                  name: "lookup_status",
                  description: "Look up a status value.",
                  parameters: {
                    type: "object",
                    properties: { id: { type: "string" } },
                    required: ["id"]
                  }
                }
              }
            ],
            format: { type: "text" },
            metadata: { source: "playground" },
            headers: { authorization: "Bearer <token>" }
          },
          responses: {
            messages: "Reply with a one sentence status.",
            tools: [],
            format: { type: "text" },
            metadata: { source: "playground" },
            headers: { authorization: "Bearer <token>" }
          },
          embeddings: {
            messages: ["hello world"],
            tools: [],
            format: {},
            metadata: {},
            headers: { authorization: "Bearer <token>" }
          },
          models: {
            messages: {},
            tools: [],
            format: {},
            metadata: {},
            headers: { authorization: "Bearer <token>" }
          }
        },
        anthropic: {
          messages: {
            messages: [{ role: "user", content: "Reply with a one sentence status." }],
            tools: [
              {
                name: "lookup_status",
                description: "Look up a status value.",
                input_schema: {
                  type: "object",
                  properties: { id: { type: "string" } },
                  required: ["id"]
                }
              }
            ],
            format: {},
            metadata: { source: "playground" },
            headers: { "x-api-key": "<token>", "anthropic-version": "2023-06-01" }
          },
          count_tokens: {
            messages: [{ role: "user", content: "Count these tokens." }],
            tools: [],
            format: {},
            metadata: {},
            headers: { "x-api-key": "<token>", "anthropic-version": "2023-06-01" }
          },
          models: {
            messages: {},
            tools: [],
            format: {},
            metadata: {},
            headers: { "x-api-key": "<token>", "anthropic-version": "2023-06-01" }
          }
        },
        gemini: {
          generate_content: {
            messages: [
              {
                role: "user",
                parts: [{ text: "Reply with a one sentence status." }]
              }
            ],
            tools: [
              {
                functionDeclarations: [
                  {
                    name: "lookup_status",
                    description: "Look up a status value.",
                    parameters: {
                      type: "OBJECT",
                      properties: { id: { type: "STRING" } },
                      required: ["id"]
                    }
                  }
                ]
              }
            ],
            format: { temperature: 0.2, maxOutputTokens: 512 },
            metadata: {},
            headers: { "x-goog-api-key": "<token>" }
          },
          stream_generate_content: {
            messages: [
              {
                role: "user",
                parts: [{ text: "Reply with a one sentence status." }]
              }
            ],
            tools: [],
            format: { temperature: 0.2, maxOutputTokens: 512 },
            metadata: {},
            headers: { "x-goog-api-key": "<token>" }
          },
          count_tokens: {
            messages: [
              {
                role: "user",
                parts: [{ text: "Count these tokens." }]
              }
            ],
            tools: [],
            format: {},
            metadata: {},
            headers: { "x-goog-api-key": "<token>" }
          },
          embed_content: {
            messages: {
              parts: [{ text: "hello world" }]
            },
            tools: [],
            format: {},
            metadata: {},
            headers: { "x-goog-api-key": "<token>" }
          },
          batch_embed_contents: {
            messages: [
              { content: { parts: [{ text: "hello world" }] } },
              { content: { parts: [{ text: "another input" }] } }
            ],
            tools: [],
            format: {},
            metadata: {},
            headers: { "x-goog-api-key": "<token>" }
          },
          models: {
            messages: {},
            tools: [],
            format: {},
            metadata: {},
            headers: { "x-goog-api-key": "<token>" }
          }
        }
      };

      const els = {
        protocolButtons: Array.from(document.querySelectorAll("[data-protocol]")),
        operation: document.getElementById("operation"),
        prefix: document.getElementById("prefix"),
        model: document.getElementById("model"),
        stream: document.getElementById("stream"),
        streamLabel: document.getElementById("stream-label"),
        temperature: document.getElementById("temperature"),
        maxTokens: document.getElementById("max-tokens"),
        messages: document.getElementById("messages"),
        tools: document.getElementById("tools"),
        format: document.getElementById("format-json"),
        metadata: document.getElementById("metadata"),
        headers: document.getElementById("headers-json"),
        messagesLabel: document.getElementById("messages-label"),
        formatLabel: document.getElementById("format-label"),
        methodPreview: document.getElementById("method-preview"),
        routePreview: document.getElementById("route-preview"),
        requestPreview: document.getElementById("request-preview"),
        analyzePreview: document.getElementById("analyze-preview"),
        redactionPreview: document.getElementById("redaction-preview"),
        previewStatus: document.getElementById("preview-status"),
        builderStatus: document.getElementById("builder-status"),
        formatButton: document.getElementById("format-button"),
        resetButton: document.getElementById("reset-button"),
        previewTabs: Array.from(document.querySelectorAll("[data-preview]"))
      };

      function jsonText(value) {
        return JSON.stringify(value, null, jsonSpaces);
      }

      function readJson(el, fallback) {
        const raw = el.value.trim();
        if (raw === "") {
          return { ok: true, value: fallback };
        }
        try {
          return { ok: true, value: JSON.parse(raw) };
        } catch (error) {
          return { ok: false, error: error.message };
        }
      }

      function activeOperation() {
        return operations[currentProtocol].find((item) => item.id === els.operation.value);
      }

      function operationDefaults() {
        return defaults[currentProtocol][els.operation.value] || {};
      }

      function prefixRoute(route) {
        const prefix = els.prefix.value;
        if (!route) {
          return prefix || "/";
        }
        return `${prefix}/${route}`.replace(/\\/+/g, "/");
      }

      function geminiRoute(operation) {
        if (operation.route) {
          return prefixRoute(operation.route);
        }
        const encodedModel = encodeURIComponent(els.model.value.trim() || defaultModel);
        const prefix = els.prefix.value;
        const base = prefix ? `${prefix}/v1beta` : "/v1beta";
        return `${base}/models/${encodedModel}:${operation.action}`;
      }

      function setOperationOptions() {
        els.operation.replaceChildren();
        operations[currentProtocol].forEach((operation) => {
          const option = document.createElement("option");
          option.value = operation.id;
          option.textContent = operation.label;
          els.operation.append(option);
        });
      }

      function setProtocol(protocol) {
        currentProtocol = protocol;
        els.protocolButtons.forEach((button) => {
          button.setAttribute("aria-pressed", String(button.dataset.protocol === protocol));
        });
        setOperationOptions();
        applyOperationDefaults();
      }

      function applyOperationDefaults() {
        const data = operationDefaults();
        els.model.value = defaultModel;
        els.stream.checked = Boolean(activeOperation()?.stream);
        els.messages.value = jsonText(data.messages ?? {});
        els.tools.value = jsonText(data.tools ?? []);
        els.format.value = jsonText(data.format ?? {});
        els.metadata.value = jsonText(data.metadata ?? {});
        els.headers.value = jsonText(data.headers ?? {});
        updateLabels();
        render();
      }

      function updateLabels() {
        if (currentProtocol === "gemini") {
          els.messagesLabel.textContent = "contents JSON";
          els.formatLabel.textContent = "generation_config JSON";
        } else if (currentProtocol === "openai" && els.operation.value === "embeddings") {
          els.messagesLabel.textContent = "input JSON";
          els.formatLabel.textContent = "response_format JSON";
        } else {
          els.messagesLabel.textContent = "messages / contents JSON";
          els.formatLabel.textContent = "response_format / generation_config JSON";
        }
        els.streamLabel.textContent = els.stream.checked ? "enabled" : "disabled";
      }

      function buildRoute(operation) {
        if (currentProtocol === "gemini") {
          return geminiRoute(operation);
        }
        return prefixRoute(operation.route);
      }

      function assignIfUseful(target, key, value) {
        const isEmptyArray = Array.isArray(value) && value.length === 0;
        const isEmptyObject = value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0;
        if (value !== undefined && value !== null && !isEmptyArray && !isEmptyObject) {
          target[key] = value;
        }
      }

      function buildOpenAiBody(operation, values) {
        if (operation.id === "models") {
          return null;
        }
        if (operation.id === "embeddings") {
          const body = { model: els.model.value.trim() || defaultModel, input: values.messages };
          assignIfUseful(body, "metadata", values.metadata);
          return body;
        }
        if (operation.id === "responses") {
          const body = {
            model: els.model.value.trim() || defaultModel,
            input: values.messages,
            stream: els.stream.checked,
            temperature: numberOrNull(els.temperature.value),
            max_output_tokens: numberOrNull(els.maxTokens.value)
          };
          assignIfUseful(body, "tools", values.tools);
          assignIfUseful(body, "text", values.format);
          assignIfUseful(body, "metadata", values.metadata);
          return cleanNulls(body);
        }
        const body = {
          model: els.model.value.trim() || defaultModel,
          messages: values.messages,
          stream: els.stream.checked,
          temperature: numberOrNull(els.temperature.value),
          max_tokens: numberOrNull(els.maxTokens.value)
        };
        assignIfUseful(body, "tools", values.tools);
        assignIfUseful(body, "response_format", values.format);
        assignIfUseful(body, "metadata", values.metadata);
        return cleanNulls(body);
      }

      function buildAnthropicBody(operation, values) {
        if (operation.id === "models") {
          return null;
        }
        const body = {
          model: els.model.value.trim() || defaultModel,
          messages: values.messages,
          max_tokens: numberOrNull(els.maxTokens.value),
          temperature: numberOrNull(els.temperature.value)
        };
        if (operation.id === "messages") {
          body.stream = els.stream.checked;
          assignIfUseful(body, "tools", values.tools);
        }
        assignIfUseful(body, "metadata", values.metadata);
        return cleanNulls(body);
      }

      function buildGeminiBody(operation, values) {
        if (operation.id === "models") {
          return null;
        }
        if (operation.id === "embed_content") {
          return { content: values.messages };
        }
        if (operation.id === "batch_embed_contents") {
          return { requests: values.messages };
        }
        const body = { contents: values.messages };
        assignIfUseful(body, "tools", values.tools);
        const generationConfig = { ...values.format };
        if (numberOrNull(els.temperature.value) !== null) {
          generationConfig.temperature = numberOrNull(els.temperature.value);
        }
        if (numberOrNull(els.maxTokens.value) !== null) {
          generationConfig.maxOutputTokens = numberOrNull(els.maxTokens.value);
        }
        assignIfUseful(body, "generationConfig", generationConfig);
        assignIfUseful(body, "labels", values.metadata);
        return cleanNulls(body);
      }

      function cleanNulls(body) {
        Object.keys(body).forEach((key) => {
          if (body[key] === null || body[key] === undefined) {
            delete body[key];
          }
        });
        return body;
      }

      function numberOrNull(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
      }

      function parseInputs() {
        const parsed = {
          messages: readJson(els.messages, {}),
          tools: readJson(els.tools, []),
          format: readJson(els.format, {}),
          metadata: readJson(els.metadata, {}),
          headers: readJson(els.headers, {})
        };
        const errors = Object.entries(parsed)
          .filter(([, result]) => !result.ok)
          .map(([name, result]) => `${name}: ${result.error}`);
        if (errors.length > 0) {
          return { ok: false, errors };
        }
        return {
          ok: true,
          values: {
            messages: parsed.messages.value,
            tools: parsed.tools.value,
            format: parsed.format.value,
            metadata: parsed.metadata.value,
            headers: parsed.headers.value
          }
        };
      }

      function buildRequest() {
        const parsed = parseInputs();
        const operation = activeOperation();
        if (!operation) {
          return { ok: false, errors: ["operation: unsupported selection"] };
        }
        const route = buildRoute(operation);
        if (!parsed.ok) {
          return { ok: false, route, operation, errors: parsed.errors };
        }
        const builders = {
          openai: buildOpenAiBody,
          anthropic: buildAnthropicBody,
          gemini: buildGeminiBody
        };
        const body = builders[currentProtocol](operation, parsed.values);
        return {
          ok: true,
          protocol: currentProtocol,
          operation,
          route,
          method: operation.method,
          body,
          headers: parsed.values.headers
        };
      }

      function buildAnalyzeEnvelope(request) {
        return {
          protocol: request.protocol,
          route: request.route,
          headers: redactObject(request.headers),
          query: {},
          body: request.body || {}
        };
      }

      function redactObject(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          return {};
        }
        return Object.fromEntries(
          Object.entries(value).map(([key, item]) => [
            key,
            shouldRedactKey(key) ? "<redacted>" : item
          ])
        );
      }

      function redactionRows(headers) {
        const redacted = redactObject(headers);
        const rows = Object.keys(redacted).map((key) => ({
          field: key,
          displayed_value: redacted[key],
          redacted: redacted[key] === "<redacted>"
        }));
        return {
          headers: rows,
          query: [
            { field: "key", displayed_value: "<redacted>", redacted: true },
            { field: "x-api-key", displayed_value: "<redacted>", redacted: true }
          ]
        };
      }

      function shouldRedactKey(key) {
        const normalized = String(key).toLowerCase();
        return (
          normalized === "authorization" ||
          normalized === "cookie" ||
          normalized === "x-api-key" ||
          normalized === "x-goog-api-key" ||
          normalized.includes("token") ||
          normalized.includes("secret") ||
          normalized.includes("credential")
        );
      }

      function setPreviewTab(nextPreview) {
        currentPreview = nextPreview;
        els.previewTabs.forEach((tab) => {
          const selected = tab.dataset.preview === nextPreview;
          tab.setAttribute("aria-selected", String(selected));
        });
        els.requestPreview.classList.toggle("hidden", nextPreview !== "request");
        els.analyzePreview.classList.toggle("hidden", nextPreview !== "analyze");
        els.redactionPreview.classList.toggle("hidden", nextPreview !== "redaction");
      }

      function render() {
        updateLabels();
        const request = buildRequest();
        if (!request.ok) {
          els.previewStatus.textContent = request.errors.join("; ");
          els.previewStatus.className = "error-text";
          els.builderStatus.textContent = "Fix JSON before preview";
          els.builderStatus.className = "error-text";
          els.methodPreview.textContent = request.operation?.method || "POST";
          els.routePreview.textContent = request.route || "/";
          const errorPayload = { errors: request.errors };
          els.requestPreview.textContent = jsonText(errorPayload);
          els.analyzePreview.textContent = jsonText(errorPayload);
          els.redactionPreview.textContent = jsonText(errorPayload);
          return;
        }
        els.previewStatus.textContent = "Ready";
        els.previewStatus.className = "ok-text";
        els.builderStatus.textContent = "No upstream calls";
        els.builderStatus.className = "ok-text";
        els.methodPreview.textContent = request.method;
        els.routePreview.textContent = request.route;
        const requestPayload = {
          method: request.method,
          route: request.route,
          headers: redactObject(request.headers),
          body: request.body
        };
        els.requestPreview.textContent = jsonText(requestPayload);
        els.analyzePreview.textContent = jsonText(buildAnalyzeEnvelope(request));
        els.redactionPreview.textContent = jsonText(redactionRows(request.headers));
      }

      function formatJsonTextareas() {
        [els.messages, els.tools, els.format, els.metadata, els.headers].forEach((textarea) => {
          const parsed = readJson(textarea, {});
          if (parsed.ok) {
            textarea.value = jsonText(parsed.value);
          }
        });
        render();
      }

      els.protocolButtons.forEach((button) => {
        button.addEventListener("click", () => setProtocol(button.dataset.protocol));
      });
      els.operation.addEventListener("change", applyOperationDefaults);
      els.prefix.addEventListener("change", render);
      els.model.addEventListener("input", render);
      els.stream.addEventListener("change", render);
      els.temperature.addEventListener("input", render);
      els.maxTokens.addEventListener("input", render);
      [els.messages, els.tools, els.format, els.metadata, els.headers].forEach((textarea) => {
        textarea.addEventListener("input", render);
      });
      els.previewTabs.forEach((tab) => {
        tab.addEventListener("click", () => setPreviewTab(tab.dataset.preview));
      });
      els.formatButton.addEventListener("click", formatJsonTextareas);
      els.resetButton.addEventListener("click", applyOperationDefaults);

      setProtocol(currentProtocol);
      setPreviewTab(currentPreview);
    })();
  </script>
</body>
</html>"""
