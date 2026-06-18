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
      .preview-grid {
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
      <div class="status"><span class="dot"></span>Local request draft</div>
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
            <button class="action-button" type="button" id="format-json">
              Format JSON
            </button>
            <button class="action-button primary" type="button" id="build">
              Build request
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

    const examples = {
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
      endpoint: document.getElementById("endpoint"),
      protocolPill: document.getElementById("protocol-pill"),
      requestPreview: document.getElementById("request-preview"),
      headersPreview: document.getElementById("headers-preview")
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

    function buildPreview() {
      try {
        const headers = parseJson("headers", {});
        fields.endpoint.textContent = currentEndpoint();
        fields.protocolPill.textContent =
          fields.protocol.options[fields.protocol.selectedIndex].text;
        fields.requestPreview.classList.remove("error");
        fields.headersPreview.classList.remove("error");
        fields.requestPreview.textContent = pretty(buildBody());
        fields.headersPreview.textContent = pretty(redactHeaders(headers));
      } catch (error) {
        fields.requestPreview.classList.add("error");
        fields.headersPreview.classList.add("error");
        fields.requestPreview.textContent = String(error.message || error);
        fields.headersPreview.textContent = String(error.message || error);
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
    document.getElementById("build").addEventListener("click", buildPreview);
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
