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
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    body {
      margin: 0;
      background: #f6f7f9;
      color: #1f2937;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }
    h1 {
      margin: 0 0 18px;
      font-size: 28px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(280px, 380px) 1fr;
      gap: 18px;
      align-items: start;
    }
    section {
      background: #ffffff;
      border: 1px solid #d9dee7;
      border-radius: 8px;
      padding: 16px;
    }
    label {
      display: block;
      margin: 0 0 12px;
      font-size: 13px;
      font-weight: 600;
    }
    select,
    input,
    textarea {
      box-sizing: border-box;
      width: 100%;
      margin-top: 5px;
      border: 1px solid #c7cedb;
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      background: #ffffff;
      color: #111827;
    }
    textarea {
      min-height: 160px;
      resize: vertical;
    }
    button {
      border: 1px solid #0f766e;
      border-radius: 6px;
      background: #0f766e;
      color: white;
      padding: 8px 12px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }
    button.secondary {
      background: #ffffff;
      color: #0f766e;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }
    .status {
      min-height: 20px;
      margin: 0 0 10px;
      color: #4b5563;
      font-size: 13px;
    }
    pre {
      overflow: auto;
      min-height: 130px;
      margin: 8px 0 0;
      padding: 12px;
      border-radius: 6px;
      background: #111827;
      color: #f9fafb;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .warning {
      display: none;
      margin: 8px 0 12px;
      color: #92400e;
      font-size: 13px;
    }
    @media (max-width: 800px) {
      .layout {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <h1>gpt2giga Unified Harness</h1>
    <div class="layout">
      <section>
        <label>Harness
          <select id="harness"></select>
        </label>
        <p id="warning" class="warning">
          This harness may run external commands or modify workspace depending on mode.
        </p>
        <label>Model
          <input id="model" list="model-list" placeholder="GigaChat-2-Max">
          <datalist id="model-list"></datalist>
        </label>
        <label>API mode
          <select id="api-mode">
            <option value="v2" selected>v2</option>
            <option value="v1">v1</option>
          </select>
        </label>
        <label>Capability
          <select id="capability">
            <option value="chat_completions" selected>chat_completions</option>
            <option value="agent_cli">agent_cli</option>
            <option value="responses">responses</option>
          </select>
        </label>
        <label>Mode
          <select id="mode">
            <option value="plan" selected>plan</option>
            <option value="read">read</option>
            <option value="edit">edit</option>
          </select>
        </label>
        <label>Prompt
          <textarea id="prompt" spellcheck="true"></textarea>
        </label>
        <div class="actions">
          <button id="run">Run</button>
          <button id="copy-cli" class="secondary" type="button">Copy CLI</button>
          <button id="copy-curl" class="secondary" type="button">Copy curl</button>
        </div>
      </section>
      <section>
        <p id="status" class="status"></p>
        <label>Output
          <pre id="output"></pre>
        </label>
        <label>Raw JSON
          <pre id="raw"></pre>
        </label>
      </section>
    </div>
  </main>
  <script>
    const state = { harnesses: [], last: null };
    const byId = (id) => document.getElementById(id);

    async function loadHarnesses() {
      const response = await fetch("/api/harnesses");
      const data = await response.json();
      state.harnesses = data.harnesses || [];
      const select = byId("harness");
      select.textContent = "";
      for (const item of state.harnesses) {
        const spec = item.spec;
        const option = document.createElement("option");
        option.value = spec.id;
        option.textContent = `${spec.id} (${item.availability.status})`;
        select.appendChild(option);
      }
      select.value = "direct-chat";
      updateHarnessMode();
    }

    async function loadModels() {
      const mode = byId("api-mode").value;
      const response = await fetch(`/api/models?api_mode=${encodeURIComponent(mode)}`);
      const data = await response.json();
      const list = byId("model-list");
      list.textContent = "";
      for (const model of data.models || []) {
        const option = document.createElement("option");
        option.value = model;
        list.appendChild(option);
      }
      if (!byId("model").value && data.models && data.models.length) {
        byId("model").value = data.models[0];
      }
      if (data.note) {
        byId("status").textContent = data.note;
      }
    }

    function updateHarnessMode() {
      const harnessId = byId("harness").value;
      const item = state.harnesses.find((entry) => entry.spec.id === harnessId);
      const caps = item ? item.spec.capabilities : [];
      byId("warning").style.display = caps.includes("agent_cli") ? "block" : "none";
      if (caps.includes("agent_cli")) {
        byId("capability").value = "agent_cli";
      } else {
        byId("capability").value = "chat_completions";
      }
    }

    async function runHarness() {
      byId("status").textContent = "Running...";
      const payload = {
        harness_id: byId("harness").value,
        prompt: byId("prompt").value,
        model: byId("model").value,
        api_mode: byId("api-mode").value,
        capability: byId("capability").value,
        mode: byId("mode").value
      };
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      state.last = data;
      byId("status").textContent = data.ok ? "Done" : "Failed";
      byId("output").textContent = data.text || data.error || "";
      byId("raw").textContent = JSON.stringify(data, null, 2);
    }

    function shellQuote(value) {
      return "'" + String(value).replaceAll("'", "'\\''") + "'";
    }

    async function copyCommand(kind) {
      if (!state.last) {
        return;
      }
      let command = "";
      if (kind === "curl" && state.last.raw && state.last.raw.curl_command) {
        command = state.last.raw.curl_command.map(shellQuote).join(" ");
      } else if (state.last.command) {
        command = state.last.command.map(shellQuote).join(" ");
      }
      if (command) {
        await navigator.clipboard.writeText(command);
        byId("status").textContent = "Copied";
      }
    }

    byId("harness").addEventListener("change", updateHarnessMode);
    byId("api-mode").addEventListener("change", loadModels);
    byId("run").addEventListener("click", runHarness);
    byId("copy-cli").addEventListener("click", () => copyCommand("cli"));
    byId("copy-curl").addEventListener("click", () => copyCommand("curl"));
    loadHarnesses().then(loadModels).catch((error) => {
      byId("status").textContent = String(error);
    });
  </script>
</body>
</html>
"""
