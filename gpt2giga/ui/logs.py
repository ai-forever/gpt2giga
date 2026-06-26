"""Render the built-in traffic logs UI."""

from __future__ import annotations

_SCRIPT_NONCE_PLACEHOLDER = "__GPT2GIGA_LOGS_SCRIPT_NONCE__"


def render_logs_html(script_nonce: str) -> str:
    """Render the logs list HTML with a per-response script nonce."""
    return _LOGS_HTML.replace(_SCRIPT_NONCE_PLACEHOLDER, script_nonce)


_LOGS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>gpt2giga logs</title>
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
      width: min(1360px, calc(100vw - 32px));
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
    select {
      font: inherit;
    }

    button {
      cursor: pointer;
    }

    button:focus-visible,
    input:focus-visible,
    select:focus-visible {
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
    .filters,
    .results {
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
      gap: 14px;
      min-width: 0;
    }

    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 32px;
      margin-bottom: 14px;
    }

    .section-head p {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .filter-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(128px, 1fr));
      gap: 12px;
    }

    .field {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .field.wide {
      grid-column: span 2;
    }

    label,
    .label {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
      font-weight: 760;
    }

    input,
    select {
      width: 100%;
      min-width: 0;
      min-height: 38px;
      padding: 0 10px;
      color: var(--ink);
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface);
      font-size: 13px;
      line-height: 1.35;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
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

    .button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
    }

    table {
      width: 100%;
      min-width: 1180px;
      border-collapse: collapse;
      font-size: 12.5px;
    }

    th,
    td {
      padding: 10px 9px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }

    th {
      position: sticky;
      top: 0;
      z-index: 1;
      color: var(--muted);
      background: var(--surface-soft);
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }

    td {
      color: var(--ink);
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

    .muted {
      color: var(--muted);
    }

    [hidden] {
      display: none !important;
    }

    th:nth-child(1),
    td:nth-child(1) {
      min-width: 150px;
      white-space: nowrap;
    }

    th:nth-child(2),
    td:nth-child(2) {
      min-width: 72px;
      white-space: nowrap;
    }

    th:nth-child(3),
    td:nth-child(3) {
      min-width: 90px;
    }

    th:nth-child(4),
    td:nth-child(4) {
      min-width: 260px;
      white-space: nowrap;
    }

    th:nth-child(5),
    td:nth-child(5) {
      min-width: 170px;
      white-space: nowrap;
    }

    th:nth-child(12),
    th:nth-child(13),
    td:nth-child(12),
    td:nth-child(13) {
      min-width: 150px;
      white-space: nowrap;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface-soft);
      color: var(--muted);
      font-size: 12px;
      font-weight: 780;
      white-space: nowrap;
    }

    .pill.ok {
      color: var(--green);
      border-color: rgb(4 120 87 / 28%);
      background: rgb(4 120 87 / 8%);
    }

    .pill.warn {
      color: var(--amber);
      border-color: rgb(180 83 9 / 30%);
      background: rgb(180 83 9 / 8%);
    }

    .pill.error {
      color: var(--red);
      border-color: rgb(180 35 24 / 30%);
      background: rgb(180 35 24 / 8%);
    }

    .empty {
      display: grid;
      place-items: center;
      min-height: 160px;
      color: var(--muted);
      border: 1px dashed var(--border);
      border-radius: 8px;
      background: var(--surface-soft);
      font-size: 13px;
      font-weight: 700;
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

    @media (max-width: 1100px) {
      .workspace {
        grid-template-columns: 1fr;
      }

      .nav {
        position: static;
      }

      .filter-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 680px) {
      main {
        width: min(100vw - 20px, 1360px);
        padding: 18px 0 28px;
      }

      header {
        align-items: flex-start;
        flex-direction: column;
      }

      h1 {
        font-size: 24px;
      }

      .filter-grid {
        grid-template-columns: 1fr;
      }

      .field.wide {
        grid-column: auto;
      }

      .status {
        white-space: normal;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div class="brand">
        <div class="brand-mark">gpt2giga</div>
        <h1>Traffic logs</h1>
      </div>
      <div class="status">
        <span class="dot"></span>
        <span>Local admin UI</span>
      </div>
    </header>

    <div class="workspace">
      <nav class="panel nav" aria-label="UI navigation">
        <a class="nav-item" href="/ui/playground">
          <span>Playground</span>
          <span class="badge ready">builder</span>
        </a>
        <a class="nav-item" aria-current="page" href="/ui/logs">
          <span>Logs</span>
          <span class="badge ready">list</span>
        </a>
        <a class="nav-item" href="/_admin/compat/analyze">
          <span>Compatibility</span>
          <span class="badge">API</span>
        </a>
      </nav>

      <div class="stage">
        <section class="panel filters" aria-label="Log filters">
          <div class="section-head">
            <div>
              <h2>Filters</h2>
              <p id="logs-status" class="ok-text">Ready</p>
            </div>
          </div>

          <form id="filters-form" autocomplete="off">
            <div class="filter-grid">
              <div class="field wide">
                <label for="admin-key">Admin key</label>
                <input id="admin-key" type="password" autocomplete="off" spellcheck="false">
              </div>
              <div class="field">
                <label for="from">From</label>
                <input id="from" type="datetime-local">
              </div>
              <div class="field">
                <label for="to">To</label>
                <input id="to" type="datetime-local">
              </div>
              <div class="field">
                <label for="protocol">Protocol</label>
                <select id="protocol">
                  <option value="">all</option>
                  <option value="openai">openai</option>
                  <option value="anthropic">anthropic</option>
                  <option value="gemini">gemini</option>
                  <option value="litellm">litellm</option>
                  <option value="system">system</option>
                </select>
              </div>
              <div class="field">
                <label for="route-group">Route group</label>
                <select id="route-group">
                  <option value="">all</option>
                  <option value="chat">chat</option>
                  <option value="responses">responses</option>
                  <option value="embeddings">embeddings</option>
                  <option value="messages">messages</option>
                  <option value="models">models</option>
                  <option value="system">system</option>
                  <option value="other">other</option>
                </select>
              </div>
              <div class="field">
                <label for="operation">Operation</label>
                <input id="operation" spellcheck="false">
              </div>
              <div class="field">
                <label for="status-class">Status class</label>
                <select id="status-class">
                  <option value="">all</option>
                  <option value="2xx">2xx</option>
                  <option value="3xx">3xx</option>
                  <option value="4xx">4xx</option>
                  <option value="5xx">5xx</option>
                  <option value="unknown">unknown</option>
                </select>
              </div>
              <div class="field">
                <label for="has-error">Error</label>
                <select id="has-error">
                  <option value="">all</option>
                  <option value="true">yes</option>
                  <option value="false">no</option>
                </select>
              </div>
              <div class="field">
                <label for="stream">Stream</label>
                <select id="stream">
                  <option value="">all</option>
                  <option value="true">yes</option>
                  <option value="false">no</option>
                </select>
              </div>
              <div class="field">
                <label for="model">Model</label>
                <input id="model" spellcheck="false">
              </div>
              <div class="field wide">
                <label for="route">Route</label>
                <input id="route" spellcheck="false">
              </div>
              <div class="field">
                <label for="request-id">Request id</label>
                <input id="request-id" spellcheck="false">
              </div>
              <div class="field">
                <label for="trace-id">Trace id</label>
                <input id="trace-id" spellcheck="false">
              </div>
              <div class="field">
                <label for="api-key-hash">API key hash</label>
                <input id="api-key-hash" spellcheck="false">
              </div>
              <div class="field">
                <label for="limit">Limit</label>
                <select id="limit">
                  <option value="50">50</option>
                  <option value="100" selected>100</option>
                  <option value="250">250</option>
                  <option value="500">500</option>
                </select>
              </div>
            </div>

            <div class="actions" aria-label="Log actions">
              <button id="refresh-button" class="button primary" type="submit">Refresh</button>
              <button id="next-button" class="button ghost" type="button" disabled>Next page</button>
              <button id="clear-button" class="button" type="button">Clear</button>
            </div>
          </form>
        </section>

        <section class="panel results" aria-label="Log results">
          <div class="section-head">
            <div>
              <h2>Log events</h2>
              <p id="results-status" class="ok-text">No page loaded</p>
            </div>
          </div>

          <div id="empty-state" class="empty">No log rows loaded</div>
          <div id="table-wrap" class="table-wrap" hidden>
            <table>
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
                  <th>Stream</th>
                  <th>Request id</th>
                  <th>Trace id</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody id="logs-body"></tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  </main>

  <script nonce="__GPT2GIGA_LOGS_SCRIPT_NONCE__">
    (() => {
      let nextCursor = null;

      const els = {
        form: document.getElementById("filters-form"),
        adminKey: document.getElementById("admin-key"),
        from: document.getElementById("from"),
        to: document.getElementById("to"),
        protocol: document.getElementById("protocol"),
        routeGroup: document.getElementById("route-group"),
        operation: document.getElementById("operation"),
        statusClass: document.getElementById("status-class"),
        hasError: document.getElementById("has-error"),
        stream: document.getElementById("stream"),
        model: document.getElementById("model"),
        route: document.getElementById("route"),
        requestId: document.getElementById("request-id"),
        traceId: document.getElementById("trace-id"),
        apiKeyHash: document.getElementById("api-key-hash"),
        limit: document.getElementById("limit"),
        logsStatus: document.getElementById("logs-status"),
        resultsStatus: document.getElementById("results-status"),
        emptyState: document.getElementById("empty-state"),
        tableWrap: document.getElementById("table-wrap"),
        logsBody: document.getElementById("logs-body"),
        refreshButton: document.getElementById("refresh-button"),
        nextButton: document.getElementById("next-button"),
        clearButton: document.getElementById("clear-button")
      };

      function adminHeaders() {
        const headers = { accept: "application/json" };
        const adminKey = els.adminKey.value.trim();
        if (adminKey) {
          headers["x-admin-api-key"] = adminKey;
        }
        return headers;
      }

      function isoFromDatetimeLocal(value) {
        if (!value) {
          return "";
        }
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
      }

      function addParam(params, key, value) {
        const normalized = String(value || "").trim();
        if (normalized) {
          params.set(key, normalized);
        }
      }

      function buildQuery(cursor) {
        const params = new URLSearchParams();
        addParam(params, "from", isoFromDatetimeLocal(els.from.value));
        addParam(params, "to", isoFromDatetimeLocal(els.to.value));
        addParam(params, "protocol", els.protocol.value);
        addParam(params, "route_group", els.routeGroup.value);
        addParam(params, "operation", els.operation.value);
        addParam(params, "status_class", els.statusClass.value);
        addParam(params, "has_error", els.hasError.value);
        addParam(params, "stream", els.stream.value);
        addParam(params, "model", els.model.value);
        addParam(params, "route", els.route.value);
        addParam(params, "request_id", els.requestId.value);
        addParam(params, "trace_id", els.traceId.value);
        addParam(params, "api_key_hash", els.apiKeyHash.value);
        addParam(params, "limit", els.limit.value);
        addParam(params, "cursor", cursor || "");
        return params.toString();
      }

      async function loadLogs(cursor) {
        els.logsStatus.textContent = "Loading";
        els.logsStatus.className = "ok-text";
        els.refreshButton.disabled = true;
        els.nextButton.disabled = true;
        try {
          const query = buildQuery(cursor);
          const response = await fetch(`/_admin/logs?${query}`, {
            headers: adminHeaders()
          });
          const text = await response.text();
          let body = text;
          try {
            body = text ? JSON.parse(text) : null;
          } catch (error) {
            body = text;
          }
          if (!response.ok) {
            throw new Error(JSON.stringify({
              status_code: response.status,
              body
            }));
          }
          const rows = Array.isArray(body?.data) ? body.data : [];
          nextCursor = body?.next_cursor || null;
          renderRows(rows);
          els.logsStatus.textContent = "Ready";
          els.logsStatus.className = "ok-text";
          els.resultsStatus.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"} loaded`;
        } catch (error) {
          nextCursor = null;
          els.logsStatus.textContent = "Load failed";
          els.logsStatus.className = "error-text";
          els.resultsStatus.textContent = error.message;
          els.resultsStatus.className = "error-text";
          renderRows([]);
        } finally {
          els.refreshButton.disabled = false;
          els.nextButton.disabled = !nextCursor;
        }
      }

      function renderRows(rows) {
        els.logsBody.replaceChildren();
        els.tableWrap.hidden = rows.length === 0;
        els.emptyState.hidden = rows.length !== 0;
        rows.forEach((record) => {
          const row = document.createElement("tr");
          appendCell(row, formatDate(record.created_at), "mono");
          appendStatus(row, record.status_code, record.has_error);
          appendCell(row, record.protocol);
          appendCell(row, record.route, "mono");
          appendCell(row, operationOf(record));
          appendCell(row, record.model_requested);
          appendCell(row, record.model_effective);
          appendCell(row, ms(record.latency_ms));
          appendCell(row, ms(record.upstream_latency_ms));
          appendCell(row, tokens(record));
          appendCell(row, boolText(record.stream));
          appendCell(row, record.request_id, "mono");
          appendCell(row, record.trace_id, "mono");
          appendCell(row, record.error_type || record.error_message, "mono");
          els.logsBody.append(row);
        });
      }

      function appendCell(row, value, className) {
        const cell = document.createElement("td");
        cell.textContent = display(value);
        if (className) {
          cell.className = className;
        }
        row.append(cell);
      }

      function appendStatus(row, statusCode, hasError) {
        const cell = document.createElement("td");
        const pill = document.createElement("span");
        pill.className = `pill ${statusKind(statusCode, hasError)}`;
        pill.textContent = display(statusCode);
        cell.append(pill);
        row.append(cell);
      }

      function statusKind(statusCode, hasError) {
        if (hasError || Number(statusCode) >= 500) {
          return "error";
        }
        if (Number(statusCode) >= 400) {
          return "warn";
        }
        if (Number(statusCode) >= 200 && Number(statusCode) < 300) {
          return "ok";
        }
        return "";
      }

      function operationOf(record) {
        return record.operation || record.metadata?.operation || "unknown";
      }

      function tokens(record) {
        const values = [record.input_tokens, record.output_tokens, record.total_tokens]
          .map((value) => value ?? "-");
        return values.join(" / ");
      }

      function boolText(value) {
        if (value === true) {
          return "yes";
        }
        if (value === false) {
          return "no";
        }
        return "unknown";
      }

      function ms(value) {
        if (value === null || value === undefined || value === "") {
          return "-";
        }
        return `${Math.round(Number(value))} ms`;
      }

      function display(value) {
        if (value === null || value === undefined || value === "") {
          return "-";
        }
        return String(value);
      }

      function formatDate(value) {
        if (!value) {
          return "-";
        }
        return String(value).replace("T", " ").replace("+00:00", "Z");
      }

      function clearFilters() {
        [
          els.from,
          els.to,
          els.operation,
          els.model,
          els.route,
          els.requestId,
          els.traceId,
          els.apiKeyHash
        ].forEach((input) => {
          input.value = "";
        });
        [
          els.protocol,
          els.routeGroup,
          els.statusClass,
          els.hasError,
          els.stream
        ].forEach((select) => {
          select.value = "";
        });
        els.limit.value = "100";
        nextCursor = null;
        els.nextButton.disabled = true;
      }

      els.form.addEventListener("submit", (event) => {
        event.preventDefault();
        nextCursor = null;
        loadLogs(null);
      });
      els.nextButton.addEventListener("click", () => loadLogs(nextCursor));
      els.clearButton.addEventListener("click", clearFilters);
    })();
  </script>
</body>
</html>"""
