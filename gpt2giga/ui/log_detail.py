"""Render the built-in traffic log detail UI."""

from __future__ import annotations

import html
import json

_SCRIPT_NONCE_PLACEHOLDER = "__GPT2GIGA_LOG_DETAIL_SCRIPT_NONCE__"
_EVENT_ID_PLACEHOLDER = "__GPT2GIGA_LOG_EVENT_ID__"
_EVENT_ID_JSON_PLACEHOLDER = '"__GPT2GIGA_LOG_EVENT_ID_JSON__"'


def render_log_detail_html(script_nonce: str, event_id: str) -> str:
    """Render one traffic log detail HTML page with a per-response script nonce."""
    event_id_json = json.dumps(event_id).replace("</", "<\\/")
    return (
        _LOG_DETAIL_HTML.replace(_SCRIPT_NONCE_PLACEHOLDER, script_nonce)
        .replace(_EVENT_ID_PLACEHOLDER, html.escape(event_id, quote=True))
        .replace(_EVENT_ID_JSON_PLACEHOLDER, event_id_json)
    )


_LOG_DETAIL_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>gpt2giga log detail</title>
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
    input {
      font: inherit;
    }

    button {
      cursor: pointer;
    }

    button:focus-visible,
    input:focus-visible {
      outline: none;
      box-shadow: var(--focus);
    }

    .brand {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .brand-mark {
      color: var(--teal);
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .event-id {
      max-width: min(760px, 88vw);
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
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
    .controls,
    .tabs,
    .tab-panel {
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

    .control-grid {
      display: grid;
      grid-template-columns: minmax(220px, 360px) auto auto minmax(0, 1fr);
      gap: 10px;
      align-items: end;
    }

    .field {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    label {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.25;
      font-weight: 760;
    }

    input {
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

    .button {
      min-height: 38px;
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

    .button.danger {
      color: var(--red);
      border-color: rgb(180 35 24 / 30%);
      background: rgb(180 35 24 / 8%);
    }

    .button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    .tab-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .tab-button {
      min-height: 34px;
      padding: 0 10px;
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--muted);
      background: var(--surface);
      font-size: 12px;
      font-weight: 780;
    }

    .tab-button[aria-selected="true"] {
      color: var(--blue);
      border-color: rgb(29 78 216 / 35%);
      background: rgb(29 78 216 / 7%);
    }

    .kv-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    .kv {
      min-width: 0;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface-soft);
    }

    .kv-key {
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
    }

    .kv-value {
      color: var(--ink);
      font-size: 13px;
      font-weight: 720;
      overflow-wrap: anywhere;
    }

    .mono {
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    pre {
      min-height: 220px;
      max-height: 560px;
      margin: 0;
      overflow: auto;
      padding: 13px;
      color: var(--code-text);
      border-radius: 8px;
      background: var(--code-bg);
      font-family:
        "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .placeholder {
      display: grid;
      place-items: center;
      min-height: 180px;
      padding: 20px;
      color: var(--muted);
      border: 1px dashed var(--border);
      border-radius: 8px;
      background: var(--surface-soft);
      font-size: 13px;
      line-height: 1.45;
      font-weight: 700;
      text-align: center;
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

    .muted {
      color: var(--muted);
    }

    [hidden] {
      display: none !important;
    }

    @media (max-width: 1100px) {
      .workspace {
        grid-template-columns: 1fr;
      }

      .nav {
        position: static;
      }

      .control-grid,
      .kv-grid {
        grid-template-columns: 1fr;
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
        <h1>Traffic log detail</h1>
        <p class="event-id mono">__GPT2GIGA_LOG_EVENT_ID__</p>
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
          <span class="badge ready">detail</span>
        </a>
        <a class="nav-item" href="/_admin/compat/analyze">
          <span>Compatibility</span>
          <span class="badge">API</span>
        </a>
      </nav>

      <div class="stage">
        <section class="panel controls" aria-label="Log detail controls">
          <div class="section-head">
            <div>
              <h2>Lookup</h2>
              <p id="detail-status" class="ok-text">Ready</p>
            </div>
          </div>
          <div class="control-grid">
            <div class="field">
              <label for="admin-key">Admin key</label>
              <input id="admin-key" type="password" autocomplete="off" spellcheck="false">
            </div>
            <button id="load-button" class="button primary" type="button">Load</button>
            <button id="replay-button" class="button ghost" type="button" disabled>Replay</button>
            <button id="redact-button" class="button danger" type="button" disabled>Redact payloads</button>
          </div>
        </section>

        <section class="panel tabs" aria-label="Log detail tabs">
          <div class="tab-list" role="tablist">
            <button class="tab-button" type="button" role="tab" aria-selected="true" data-tab="summary">Summary</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="request">Request</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="response">Response</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="compatibility">Compatibility analysis</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="normalized">Normalized</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="provider">Provider</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="observability">Observability</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="metrics">Metrics context</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="replay">Replay</button>
            <button class="tab-button" type="button" role="tab" aria-selected="false" data-tab="redaction">Redaction audit</button>
          </div>
        </section>

        <section id="summary-panel" class="panel tab-panel" data-panel="summary">
          <div class="section-head">
            <div>
              <h2>Summary</h2>
              <p class="muted">Gateway metadata without stored payload bodies.</p>
            </div>
          </div>
          <div id="summary-grid" class="kv-grid"></div>
        </section>

        <section id="request-panel" class="panel tab-panel" data-panel="request" hidden>
          <div class="section-head">
            <div>
              <h2>Request</h2>
              <p id="request-status" class="muted">Not loaded</p>
            </div>
          </div>
          <pre id="request-json"></pre>
        </section>

        <section id="response-panel" class="panel tab-panel" data-panel="response" hidden>
          <div class="section-head">
            <div>
              <h2>Response</h2>
              <p id="response-status" class="muted">Not loaded</p>
            </div>
          </div>
          <pre id="response-json"></pre>
        </section>

        <section id="compatibility-panel" class="panel tab-panel" data-panel="compatibility" hidden>
          <div class="section-head">
            <div>
              <h2>Compatibility analysis</h2>
              <p id="compatibility-status" class="muted">Not loaded</p>
            </div>
          </div>
          <pre id="compatibility-json"></pre>
        </section>

        <section id="normalized-panel" class="panel tab-panel" data-panel="normalized" hidden>
          <div class="section-head">
            <div>
              <h2>Normalized</h2>
              <p class="muted">Captured metadata or explicit no-capture state.</p>
            </div>
          </div>
          <pre id="normalized-json"></pre>
        </section>

        <section id="provider-panel" class="panel tab-panel" data-panel="provider" hidden>
          <div class="section-head">
            <div>
              <h2>Provider</h2>
              <p class="muted">Provider-facing metadata recorded by the gateway.</p>
            </div>
          </div>
          <pre id="provider-json"></pre>
        </section>

        <section id="observability-panel" class="panel tab-panel" data-panel="observability" hidden>
          <div class="section-head">
            <div>
              <h2>Observability</h2>
              <p class="muted">Trace and span identifiers only.</p>
            </div>
          </div>
          <div id="observability-grid" class="kv-grid"></div>
        </section>

        <section id="metrics-panel" class="panel tab-panel" data-panel="metrics" hidden>
          <div class="section-head">
            <div>
              <h2>Metrics context</h2>
              <p class="muted">Latency, status, and token counters from the log event.</p>
            </div>
          </div>
          <div id="metrics-grid" class="kv-grid"></div>
        </section>

        <section id="replay-panel" class="panel tab-panel" data-panel="replay" hidden>
          <div class="section-head">
            <div>
              <h2>Replay</h2>
              <p id="replay-status" class="muted">Replay is opt-in and uses the existing admin replay endpoint.</p>
            </div>
          </div>
          <pre id="replay-json"></pre>
        </section>

        <section id="redaction-panel" class="panel tab-panel" data-panel="redaction" hidden>
          <div class="section-head">
            <div>
              <h2>Redaction audit</h2>
              <p class="muted">Payload capture and redaction state for this event.</p>
            </div>
          </div>
          <div id="redaction-grid" class="kv-grid"></div>
        </section>
      </div>
    </div>
  </main>

  <script nonce="__GPT2GIGA_LOG_DETAIL_SCRIPT_NONCE__">
    (() => {
      const eventId = "__GPT2GIGA_LOG_EVENT_ID_JSON__";
      const state = {
        summary: null,
        request: null,
        response: null,
        analysis: null
      };

      const els = {
        adminKey: document.getElementById("admin-key"),
        loadButton: document.getElementById("load-button"),
        replayButton: document.getElementById("replay-button"),
        redactButton: document.getElementById("redact-button"),
        detailStatus: document.getElementById("detail-status"),
        summaryGrid: document.getElementById("summary-grid"),
        requestStatus: document.getElementById("request-status"),
        responseStatus: document.getElementById("response-status"),
        compatibilityStatus: document.getElementById("compatibility-status"),
        requestJson: document.getElementById("request-json"),
        responseJson: document.getElementById("response-json"),
        compatibilityJson: document.getElementById("compatibility-json"),
        normalizedJson: document.getElementById("normalized-json"),
        providerJson: document.getElementById("provider-json"),
        observabilityGrid: document.getElementById("observability-grid"),
        metricsGrid: document.getElementById("metrics-grid"),
        replayStatus: document.getElementById("replay-status"),
        replayJson: document.getElementById("replay-json"),
        redactionGrid: document.getElementById("redaction-grid")
      };

      function adminHeaders(extra) {
        const headers = { accept: "application/json", ...(extra || {}) };
        const adminKey = els.adminKey.value.trim();
        if (adminKey) {
          headers["x-admin-api-key"] = adminKey;
        }
        return headers;
      }

      async function fetchJson(url, options) {
        const response = await fetch(url, {
          ...(options || {}),
          headers: adminHeaders(options?.headers)
        });
        const text = await response.text();
        let body = text;
        try {
          body = text ? JSON.parse(text) : null;
        } catch (error) {
          body = text;
        }
        if (!response.ok) {
          const detail = typeof body === "object" && body !== null
            ? body.detail || JSON.stringify(body)
            : String(body || response.statusText);
          throw new Error(`${response.status} ${detail}`);
        }
        return body;
      }

      async function loadDetail() {
        setStatus("Loading", false);
        els.loadButton.disabled = true;
        els.replayButton.disabled = true;
        els.redactButton.disabled = true;
        try {
          const summary = await fetchJson(`/_admin/logs/${encodeURIComponent(eventId)}`);
          const [requestPayload, responsePayload] = await Promise.all([
            fetchJson(`/_admin/logs/${encodeURIComponent(eventId)}/request`),
            fetchJson(`/_admin/logs/${encodeURIComponent(eventId)}/response`)
          ]);
          state.summary = summary;
          state.request = requestPayload;
          state.response = responsePayload;
          renderLoadedState();
          await analyzeCapturedRequest();
          setStatus("Ready", false);
        } catch (error) {
          setStatus(error.message, true);
          renderErrorState(error);
        } finally {
          els.loadButton.disabled = false;
          els.replayButton.disabled = state.summary === null;
          els.redactButton.disabled = state.summary === null;
        }
      }

      function renderLoadedState() {
        const summary = state.summary || {};
        renderKeyValues(els.summaryGrid, [
          ["id", summary.id],
          ["created_at", formatDate(summary.created_at)],
          ["status_code", summary.status_code],
          ["protocol", summary.protocol],
          ["route", summary.route],
          ["operation", summary.operation],
          ["route_group", summary.route_group],
          ["method", summary.method],
          ["model_requested", summary.model_requested],
          ["model_effective", summary.model_effective],
          ["provider", summary.provider],
          ["request_id", summary.request_id],
          ["trace_id", summary.trace_id],
          ["span_id", summary.span_id],
          ["api_key_hash", summary.api_key_hash],
          ["error_type", summary.error_type],
          ["error_message", summary.error_message]
        ]);
        renderRequest();
        renderResponse();
        renderDerivedPanels();
      }

      function renderRequest() {
        const payload = state.request || {};
        const hasHeaders = payload.request_headers !== null && payload.request_headers !== undefined;
        const hasBody = payload.request_body !== null && payload.request_body !== undefined;
        els.requestStatus.textContent = hasBody
          ? "Captured redacted request payload"
          : "Request body was not captured or was manually redacted";
        setJson(els.requestJson, {
          id: payload.id,
          request_headers: hasHeaders ? payload.request_headers : "not captured",
          request_body: hasBody ? payload.request_body : "not captured"
        });
      }

      function renderResponse() {
        const payload = state.response || {};
        const hasBody = payload.response_body !== null && payload.response_body !== undefined;
        els.responseStatus.textContent = hasBody
          ? "Captured redacted response payload"
          : "Response body was not captured, was streamed, or was manually redacted";
        setJson(els.responseJson, {
          id: payload.id,
          response_body: hasBody ? payload.response_body : "not captured"
        });
      }

      function renderDerivedPanels() {
        const summary = state.summary || {};
        const metadata = isObject(summary.metadata) ? summary.metadata : {};
        setJson(els.normalizedJson, {
          available: Boolean(metadata.normalized),
          normalized: metadata.normalized || null,
          note: metadata.normalized
            ? "normalized metadata was captured on this event"
            : "normalized request/response payloads are not persisted in traffic logs"
        });
        setJson(els.providerJson, {
          provider: summary.provider || null,
          upstream_status_code: summary.upstream_status_code || null,
          upstream_latency_ms: summary.upstream_latency_ms || null,
          provider_metadata: metadata.provider || null,
          note: metadata.provider
            ? "provider metadata was captured on this event"
            : "provider request/response bodies are not persisted in traffic logs"
        });
        renderKeyValues(els.observabilityGrid, [
          ["trace_id", summary.trace_id],
          ["span_id", summary.span_id],
          ["request_id", summary.request_id],
          ["lifecycle", metadata.lifecycle],
          ["annotations", metadata.annotations ? JSON.stringify(metadata.annotations) : null]
        ]);
        renderKeyValues(els.metricsGrid, [
          ["status_code", summary.status_code],
          ["upstream_status_code", summary.upstream_status_code],
          ["latency_ms", ms(summary.latency_ms)],
          ["upstream_latency_ms", ms(summary.upstream_latency_ms)],
          ["input_tokens", summary.input_tokens],
          ["output_tokens", summary.output_tokens],
          ["total_tokens", summary.total_tokens],
          ["stream", boolText(summary.stream)],
          ["has_error", boolText(summary.has_error)]
        ]);
        renderKeyValues(els.redactionGrid, [
          ["request_headers", captureState(state.request?.request_headers)],
          ["request_body", captureState(state.request?.request_body)],
          ["response_body", captureState(state.response?.response_body)],
          ["summary_has_request_body", boolText(summary.has_request_body)],
          ["summary_has_response_body", boolText(summary.has_response_body)],
          ["content_capture_policy", "payloads appear only when traffic-log content capture stored them"],
          ["secret_redaction_policy", "admin log APIs return stored redacted payloads"]
        ]);
      }

      async function analyzeCapturedRequest() {
        const summary = state.summary || {};
        const requestPayload = state.request || {};
        if (!isObject(requestPayload.request_body)) {
          state.analysis = null;
          els.compatibilityStatus.textContent = "Request body was not captured; analysis was skipped";
          setJson(els.compatibilityJson, {
            skipped: true,
            reason: "Traffic log request body was not captured or is not a JSON object.",
            route: summary.route || null,
            protocol: summary.protocol || null
          });
          return;
        }
        const routeParts = splitRoute(summary.route || "");
        const envelope = {
          protocol: summary.protocol || "",
          route: routeParts.path,
          headers: isObject(requestPayload.request_headers) ? requestPayload.request_headers : {},
          query: routeParts.query,
          body: requestPayload.request_body
        };
        els.compatibilityStatus.textContent = "Running local Compatibility Doctor";
        try {
          const analysis = await fetchJson("/_admin/compat/analyze", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(envelope)
          });
          state.analysis = analysis;
          els.compatibilityStatus.textContent = "Compatibility Doctor analysis ready";
          setJson(els.compatibilityJson, analysis);
        } catch (error) {
          state.analysis = null;
          els.compatibilityStatus.textContent = `Analysis failed: ${error.message}`;
          setJson(els.compatibilityJson, {
            error: error.message,
            envelope
          });
        }
      }

      async function replayEvent() {
        els.replayButton.disabled = true;
        els.replayStatus.textContent = "Replay running";
        try {
          const replay = await fetchJson(`/_admin/logs/${encodeURIComponent(eventId)}/replay`, {
            method: "POST"
          });
          els.replayStatus.textContent = "Replay complete";
          setJson(els.replayJson, replay);
        } catch (error) {
          els.replayStatus.textContent = `Replay unavailable: ${error.message}`;
          setJson(els.replayJson, { error: error.message });
        } finally {
          els.replayButton.disabled = state.summary === null;
        }
      }

      async function redactPayloads() {
        els.redactButton.disabled = true;
        setStatus("Redacting payloads", false);
        try {
          const result = await fetchJson(`/_admin/logs/${encodeURIComponent(eventId)}/redact`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
              fields: ["request_headers", "request_body", "response_body"]
            })
          });
          setJson(els.replayJson, result);
          els.replayStatus.textContent = "Payload fields redacted";
          await loadDetail();
        } catch (error) {
          setStatus(`Redaction failed: ${error.message}`, true);
          setJson(els.replayJson, { error: error.message });
        } finally {
          els.redactButton.disabled = state.summary === null;
        }
      }

      function renderErrorState(error) {
        const message = { error: error.message };
        renderKeyValues(els.summaryGrid, [["error", error.message]]);
        setJson(els.requestJson, message);
        setJson(els.responseJson, message);
        setJson(els.compatibilityJson, message);
        setJson(els.normalizedJson, message);
        setJson(els.providerJson, message);
        renderKeyValues(els.observabilityGrid, [["error", error.message]]);
        renderKeyValues(els.metricsGrid, [["error", error.message]]);
        renderKeyValues(els.redactionGrid, [["error", error.message]]);
      }

      function setStatus(message, isError) {
        els.detailStatus.textContent = message;
        els.detailStatus.className = isError ? "error-text" : "ok-text";
      }

      function renderKeyValues(container, rows) {
        container.replaceChildren();
        rows.forEach(([key, value]) => {
          const item = document.createElement("div");
          item.className = "kv";
          const keyEl = document.createElement("div");
          keyEl.className = "kv-key mono";
          keyEl.textContent = key;
          const valueEl = document.createElement("div");
          valueEl.className = "kv-value mono";
          valueEl.textContent = display(value);
          item.append(keyEl, valueEl);
          container.append(item);
        });
      }

      function setJson(target, value) {
        target.textContent = JSON.stringify(value, null, 2);
      }

      function splitRoute(route) {
        try {
          const parsed = new URL(route, window.location.origin);
          const query = {};
          parsed.searchParams.forEach((value, key) => {
            query[key] = value;
          });
          return { path: parsed.pathname || route || "/", query };
        } catch (error) {
          return { path: route || "/", query: {} };
        }
      }

      function switchTab(tab) {
        document.querySelectorAll(".tab-button").forEach((button) => {
          button.setAttribute("aria-selected", button.dataset.tab === tab ? "true" : "false");
        });
        document.querySelectorAll("[data-panel]").forEach((panel) => {
          panel.hidden = panel.dataset.panel !== tab;
        });
      }

      function isObject(value) {
        return value !== null && typeof value === "object" && !Array.isArray(value);
      }

      function captureState(value) {
        return value === null || value === undefined ? "not captured or redacted" : "captured";
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

      document.querySelectorAll(".tab-button").forEach((button) => {
        button.addEventListener("click", () => switchTab(button.dataset.tab));
      });
      els.loadButton.addEventListener("click", loadDetail);
      els.replayButton.addEventListener("click", replayEvent);
      els.redactButton.addEventListener("click", redactPayloads);

      setJson(els.requestJson, { status: "not loaded" });
      setJson(els.responseJson, { status: "not loaded" });
      setJson(els.compatibilityJson, { status: "not loaded" });
      setJson(els.normalizedJson, { status: "not loaded" });
      setJson(els.providerJson, { status: "not loaded" });
      setJson(els.replayJson, { status: "not run" });
      renderKeyValues(els.summaryGrid, [["id", eventId]]);
      renderKeyValues(els.observabilityGrid, [["trace_id", "not loaded"]]);
      renderKeyValues(els.metricsGrid, [["status_code", "not loaded"]]);
      renderKeyValues(els.redactionGrid, [["payloads", "not loaded"]]);
    })();
  </script>
</body>
</html>"""
