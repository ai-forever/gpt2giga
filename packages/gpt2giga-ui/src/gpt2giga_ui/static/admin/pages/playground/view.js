import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import { pathForPage } from "../../routes.js";
import { card, kpi, pill, renderDefinitionList, renderFormSection, renderGuideLinks, renderWorkflowCard, } from "../../templates.js";
import { asRecord, escapeHtml, formatBytes, formatDurationMs, } from "../../utils.js";
import { DEFAULT_ASSISTANT_OUTPUT, DEFAULT_OUTPUT, DEFAULT_PLAYGROUND_PRESET, PLAYGROUND_PRESETS, } from "./state.js";
export function renderPlaygroundHeroActions() {
    return `
    <button class="button button--secondary" id="playground-stop" type="button" disabled>Stop request</button>
    <button class="button button--secondary" id="playground-reset" type="button">Reset output</button>
  `;
}
export function renderPlaygroundPage(setup, initialRequest) {
    const bootstrapRequired = asRecord(setup.bootstrap).required;
    return `
    ${kpi("GigaChat", setup.gigachat_ready ? "ready" : "missing")}
    ${kpi("Security", setup.security_ready ? "ready" : "pending")}
    ${kpi("Persisted", setup.persisted ? "yes" : "defaults")}
    ${kpi("Bootstrap", bootstrapRequired ? "active" : "off")}
    ${card("Request builder", `
        <form id="playground-form" class="form-shell">
          <div class="form-shell__intro">
            <span class="eyebrow">Smoke flow</span>
            <p class="muted">
              Load a preset, adjust the key fields, and send one proof request.
            </p>
          </div>
          ${renderFormSection({
        title: "Smoke presets",
        body: `
              <div class="toolbar">
                ${PLAYGROUND_PRESETS.map((preset) => `
                    <button class="button button--secondary playground-preset" data-preset="${escapeHtml(preset.id)}" type="button">
                      ${escapeHtml(preset.label)}
                    </button>
                  `).join("")}
              </div>
            `,
    })}
          ${renderFormSection({
        title: "Request targeting",
        body: `
              <div class="dual-grid">
                <label class="field">
                  <span>Surface</span>
                  <select name="surface">
                    <option value="openai-chat">OpenAI chat/completions</option>
                    <option value="openai-responses">OpenAI responses</option>
                    <option value="anthropic-messages">Anthropic messages</option>
                    <option value="gemini-generate">Gemini generateContent</option>
                  </select>
                </label>
                <label class="field">
                  <span>Model</span>
                  <input name="model" value="${escapeHtml(String(initialRequest.body.model ?? "GigaChat"))}" />
                </label>
              </div>
              <label class="field">
                <span>System prompt</span>
                <textarea name="system_prompt" placeholder="Optional system prompt">${escapeHtml(DEFAULT_PLAYGROUND_PRESET.systemPrompt)}</textarea>
              </label>
              <label class="field">
                <span>User prompt</span>
                <textarea name="user_prompt">${escapeHtml(DEFAULT_PLAYGROUND_PRESET.userPrompt)}</textarea>
              </label>
            `,
    })}
          ${renderFormSection({
        title: "Transport posture",
        body: `
              <div class="dual-grid">
                <label class="field">
                  <span>Stream</span>
                  <select name="stream">
                    <option value="false">off</option>
                    <option value="true">on</option>
                  </select>
                </label>
                <div class="surface">
                  <div class="stack">
                    <h4>Gateway auth</h4>
                    <p class="muted" id="playground-auth-note">
                      Requests reuse the gateway key from the rail.
                    </p>
                  </div>
                </div>
              </div>
            `,
    })}
          <div class="form-actions">
            <button class="button" id="playground-submit" type="submit">Send request</button>
            <span class="muted" id="playground-form-note">Preview updates live as you type.</span>
          </div>
        </form>
      `, "panel panel--span-8 panel--measure")}
    ${card("Smoke workflow handoff", `
        <div class="stack">
          <div id="playground-bootstrap-banner"></div>
          <div class="workflow-grid">
            ${renderWorkflowCard({
        workflow: "start",
        title: setup.gigachat_ready ? "Run one smoke request" : "Finish bootstrap first",
        compact: true,
        pills: [
            pill(`GigaChat: ${setup.gigachat_ready ? "ready" : "missing"}`, setup.gigachat_ready ? "good" : "warn"),
            pill(`Security: ${setup.security_ready ? "ready" : "pending"}`, setup.security_ready ? "good" : "warn"),
            pill(`Bootstrap: ${bootstrapRequired ? "active" : "off"}`, bootstrapRequired ? "warn" : "default"),
        ],
        actions: [
            { label: setup.gigachat_ready ? "Run smoke request" : "Open setup", href: setup.gigachat_ready ? "#playground-submit" : pathForPage("setup"), primary: true },
            { label: "API Keys", href: pathForPage("keys") },
        ],
    })}
            ${renderWorkflowCard({
        workflow: "observe",
        title: "Hand off to traffic or logs",
        compact: true,
        pills: [
            pill(`Persisted: ${setup.persisted ? "yes" : "defaults"}`, setup.persisted ? "good" : "default"),
            pill(`Gateway auth: ${setup.security_ready ? "protected" : "open"}`),
            pill(`Zero-env path: ready`),
        ],
        actions: [
            { label: "Traffic", href: pathForPage("traffic"), primary: true },
            { label: "Logs", href: pathForPage("logs") },
        ],
    })}
          </div>
          <div class="surface">
            <div class="stack">
              <div class="surface__header">
                <div class="stack">
                  <h4>Current bootstrap posture</h4>
                </div>
                <div class="surface__meta">
                  ${pill("setup")}
                  ${pill("keys")}
                  ${pill("smoke")}
                </div>
              </div>
              <div id="playground-bootstrap-summary"></div>
            </div>
          </div>
        </div>
      `, "panel panel--span-4 panel--aside")}
    ${card("Request preview", `
        <div class="stack">
          <div class="surface">
            <div class="stack">
              <div class="surface__header">
                <h4>Current request posture</h4>
              </div>
              <div id="playground-request-summary"></div>
            </div>
          </div>
          <details class="details-disclosure">
            <summary>Current request payload</summary>
            <pre class="code-block code-block--tall" id="playground-request-body">${escapeHtml(JSON.stringify(initialRequest.body, null, 2))}</pre>
          </details>
        </div>
      `, "panel panel--span-8 panel--measure")}
    ${card("Current posture and handoff", `
        <div class="stack">
          <div class="surface">
            <div class="stack">
              <div class="surface__header">
                <h4>Request lifecycle</h4>
                <div class="surface__meta" id="playground-status-pill">${pill("idle")}</div>
              </div>
              <div id="playground-run-note" class="field-note">${escapeHtml(DEFAULT_OUTPUT)}</div>
              <div id="playground-run-summary"></div>
            </div>
          </div>
          ${renderGuideLinks([
        {
            label: "Overview workflow guide",
            href: OPERATOR_GUIDE_LINKS.overview,
            note: "Use the broader operator map when Playground is no longer the right surface and you need to step back into setup, settings, or request diagnostics.",
        },
        {
            label: "Troubleshooting handoff map",
            href: OPERATOR_GUIDE_LINKS.troubleshooting,
            note: "Open the escalation map when the smoke request succeeded but the next page is still unclear.",
        },
        {
            label: "Rollout backend v2",
            href: OPERATOR_GUIDE_LINKS.rolloutV2,
            note: "Use the rollout notes when the result difference looks tied to backend mode rather than request construction.",
        },
    ], {
        collapsibleSummary: "Operator guides",
        compact: true,
        intro: "Open these only when one smoke request still does not explain the next step.",
    })}
        </div>
      `, "panel panel--span-4 panel--aside")}
    ${card("Assistant output", `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <h4>Parsed response</h4>
              <div class="surface__meta" id="playground-output-meta">${pill("waiting")}</div>
            </div>
            <pre class="code-block code-block--tall playground-output" id="playground-assistant-output">${escapeHtml(DEFAULT_ASSISTANT_OUTPUT)}</pre>
          </div>
        </div>
      `, "panel panel--span-8 panel--measure")}
    ${card("Transport transcript", `
        <div class="stack">
          <div class="surface">
            <div class="surface__header">
              <h4>Transport posture</h4>
              <div class="surface__meta" id="playground-transport-meta">${pill("idle")}</div>
            </div>
          </div>
          <details class="details-disclosure">
            <summary>Current transport snapshot</summary>
            <pre class="code-block code-block--tall playground-output" id="playground-output">${escapeHtml(DEFAULT_OUTPUT)}</pre>
          </details>
        </div>
      `, "panel panel--span-4 panel--aside")}
  `;
}
export function resolvePlaygroundElements(pageContent) {
    const form = pageContent.querySelector("#playground-form");
    const requestSummary = pageContent.querySelector("#playground-request-summary");
    const requestBody = pageContent.querySelector("#playground-request-body");
    const bootstrapBanner = pageContent.querySelector("#playground-bootstrap-banner");
    const bootstrapSummary = pageContent.querySelector("#playground-bootstrap-summary");
    const authNote = pageContent.querySelector("#playground-auth-note");
    const formNote = pageContent.querySelector("#playground-form-note");
    const runNote = pageContent.querySelector("#playground-run-note");
    const runSummary = pageContent.querySelector("#playground-run-summary");
    const statusPill = pageContent.querySelector("#playground-status-pill");
    const assistantOutput = pageContent.querySelector("#playground-assistant-output");
    const outputMeta = pageContent.querySelector("#playground-output-meta");
    const transportMeta = pageContent.querySelector("#playground-transport-meta");
    const output = pageContent.querySelector("#playground-output");
    const submitButton = pageContent.querySelector("#playground-submit");
    if (!form ||
        !requestSummary ||
        !requestBody ||
        !bootstrapBanner ||
        !bootstrapSummary ||
        !authNote ||
        !formNote ||
        !runNote ||
        !runSummary ||
        !statusPill ||
        !assistantOutput ||
        !outputMeta ||
        !transportMeta ||
        !output ||
        !submitButton) {
        return null;
    }
    return {
        assistantOutput,
        authNote,
        bootstrapBanner,
        bootstrapSummary,
        form,
        formNote,
        gatewayKeyInput: document.getElementById("gateway-key-input"),
        output,
        outputMeta,
        presetButtons: Array.from(pageContent.querySelectorAll(".playground-preset")),
        requestBody,
        requestSummary,
        resetButton: document.getElementById("playground-reset"),
        runNote,
        runSummary,
        statusPill,
        stopButton: document.getElementById("playground-stop"),
        submitButton,
        transportMeta,
    };
}
export function updatePlaygroundRequestPreview(options) {
    const { elements, gatewayKey, request, setup } = options;
    const gatewayKeyState = gatewayKey ? "configured" : "empty";
    const bootstrap = asRecord(setup.bootstrap);
    elements.requestSummary.innerHTML = renderDefinitionList([
        { label: "Surface", value: request.label },
        { label: "Endpoint", value: `POST ${request.url}` },
        { label: "Streaming", value: request.stream ? "on" : "off" },
        { label: "Auth", value: request.authLabel },
        { label: "Gateway key", value: gatewayKeyState },
        {
            label: "Payload size",
            value: formatBytes(new Blob([JSON.stringify(request.body)]).size),
        },
        {
            label: "Bootstrap",
            value: bootstrap.required ? "active" : "not required",
            note: bootstrap.required
                ? "If the gateway key is still empty, save the bootstrap/admin token into the left-rail gateway field first."
                : "Normal gateway auth flow.",
        },
    ]);
    elements.requestBody.textContent = JSON.stringify(request.body, null, 2);
    elements.authNote.textContent = gatewayKey
        ? `Gateway key is present and will be attached as ${request.authLabel}.`
        : "Gateway key is empty. The request will be sent without proxy auth headers.";
    elements.formNote.textContent = describePreviewState(request, gatewayKey, setup);
    elements.bootstrapBanner.innerHTML = renderBootstrapBanner(setup, gatewayKey);
    elements.bootstrapSummary.innerHTML = renderDefinitionList(buildBootstrapSteps(setup, gatewayKey));
}
export function updatePlaygroundRunPanels(options) {
    const { elements, state } = options;
    const { activeController, runState } = state;
    elements.statusPill.innerHTML = renderPhasePill(runState.phase);
    elements.outputMeta.innerHTML = pill(runState.assistantOutput.trim()
        ? "parsed"
        : runState.phase === "error"
            ? "error"
            : "waiting", runState.phase === "success"
        ? "good"
        : runState.phase === "error"
            ? "warn"
            : "default");
    elements.transportMeta.innerHTML = pill(runState.eventCount > 0 ? `${runState.eventCount} events` : runState.phase, runState.phase === "success"
        ? "good"
        : runState.phase === "error"
            ? "warn"
            : "default");
    elements.runNote.textContent = runState.note;
    elements.runSummary.innerHTML = renderDefinitionList([
        { label: "Phase", value: humanizePhase(runState.phase) },
        { label: "Status", value: formatStatus(runState.statusCode, runState.statusText) },
        {
            label: "Duration",
            value: runState.startedAt === null
                ? "0 ms"
                : formatDurationMs((runState.finishedAt ?? performance.now()) - runState.startedAt),
        },
        { label: "Bytes", value: formatBytes(runState.bytesReceived) },
        { label: "Chunks", value: String(runState.chunkCount) },
        { label: "Content type", value: runState.contentType || "n/a" },
        {
            label: "Request",
            value: runState.request ? `POST ${runState.request.url}` : "No request yet",
            note: runState.request ? runState.request.label : undefined,
        },
        ...(runState.errorText ? [{ label: "Error", value: runState.errorText }] : []),
    ]);
    elements.assistantOutput.textContent =
        runState.assistantOutput || DEFAULT_ASSISTANT_OUTPUT;
    elements.output.textContent = runState.rawOutput || DEFAULT_OUTPUT;
    if (elements.stopButton) {
        elements.stopButton.disabled = activeController === null;
        elements.stopButton.textContent = "Stop request";
    }
    elements.submitButton.disabled = activeController !== null;
}
function renderBootstrapBanner(setup, gatewayKey) {
    const bootstrap = asRecord(setup.bootstrap);
    if (!setup.gigachat_ready) {
        return `
      <div class="banner banner--warn">
        GigaChat credentials are still missing. Use <a href="/admin/setup"><strong>/admin/setup</strong></a>
        before relying on playground smoke results.
      </div>
    `;
    }
    if (bootstrap.required && !gatewayKey) {
        return `
      <div class="banner banner--warn">
        Bootstrap mode is active and the gateway key field is empty. Save the bootstrap/admin token in the
        left rail, then re-run a preset from this page.
      </div>
    `;
    }
    if (!setup.security_ready && !gatewayKey) {
        return `
      <div class="banner banner--warn">
        Gateway auth is not configured yet. Playground can still help validate GigaChat wiring, but protected
        routes will need a global or scoped key from <a href="/admin/keys"><strong>/admin/keys</strong></a>.
      </div>
    `;
    }
    return `
    <div class="banner">
      Playground is ready for smoke traffic. The safest first run is the <strong>OpenAI hello</strong> preset,
      followed by a streaming preset to verify cleanup.
    </div>
  `;
}
function buildBootstrapSteps(setup, gatewayKey) {
    const bootstrap = asRecord(setup.bootstrap);
    return [
        {
            label: "Persisted config",
            value: setup.persisted ? "yes" : "not yet",
            note: setup.persisted
                ? "Runtime changes survive restart."
                : "Current values still look like defaults until settings are saved.",
        },
        {
            label: "GigaChat",
            value: setup.gigachat_ready ? "ready" : "missing",
            note: setup.gigachat_ready
                ? "Upstream credentials are present."
                : "Configure credentials in setup before expecting successful completions.",
        },
        {
            label: "Gateway key",
            value: gatewayKey ? "present" : "empty",
            note: gatewayKey
                ? "Playground will attach it to outgoing requests."
                : "Use the left-rail gateway input if proxy auth is enabled.",
        },
        {
            label: "Bootstrap gate",
            value: bootstrap.required ? "active" : "off",
            note: bootstrap.required
                ? "Use the bootstrap token or localhost allowance until setup is complete."
                : "No special first-run gate is active.",
        },
    ];
}
function describePreviewState(request, gatewayKey, setup) {
    if (!setup.gigachat_ready) {
        return "The payload is ready, but upstream GigaChat credentials are still missing.";
    }
    if (!gatewayKey && (setup.security_ready || asRecord(setup.bootstrap).required)) {
        return `Preview is valid, but ${request.authLabel} will be absent until the gateway key field is filled.`;
    }
    if (request.stream) {
        return `Streaming is enabled. ${request.url} will stay cancellable from the hero action bar.`;
    }
    return `Plain POST preview is ready for ${request.url}.`;
}
function renderPhasePill(phase) {
    if (phase === "success") {
        return pill("success", "good");
    }
    if (phase === "error") {
        return pill("error", "warn");
    }
    if (phase === "streaming") {
        return pill("streaming");
    }
    if (phase === "sending") {
        return pill("sending");
    }
    if (phase === "aborted") {
        return pill("aborted", "warn");
    }
    return pill("idle");
}
function formatStatus(statusCode, statusText) {
    if (statusCode === null) {
        return "n/a";
    }
    return `${statusCode}${statusText ? ` ${statusText}` : ""}`;
}
function humanizePhase(phase) {
    if (phase === "idle") {
        return "Idle";
    }
    if (phase === "sending") {
        return "Sending";
    }
    if (phase === "streaming") {
        return "Streaming";
    }
    if (phase === "success") {
        return "Success";
    }
    if (phase === "error") {
        return "Error";
    }
    return "Aborted";
}
