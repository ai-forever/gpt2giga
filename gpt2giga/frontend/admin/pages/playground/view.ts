import { card, kpi, pill, renderDefinitionList } from "../../templates.js";
import type { SetupPayload } from "../../types.js";
import {
  asRecord,
  escapeHtml,
  formatBytes,
  formatDurationMs,
} from "../../utils.js";
import type { PlaygroundPageState, PlaygroundRequest, RunPhase } from "./state.js";
import {
  DEFAULT_ASSISTANT_OUTPUT,
  DEFAULT_OUTPUT,
  DEFAULT_PLAYGROUND_PRESET,
  PLAYGROUND_PRESETS,
} from "./state.js";

export interface PlaygroundPageElements {
  assistantOutput: HTMLPreElement;
  authNote: HTMLElement;
  bootstrapBanner: HTMLElement;
  bootstrapSummary: HTMLElement;
  form: HTMLFormElement;
  formNote: HTMLElement;
  gatewayKeyInput: HTMLInputElement | null;
  output: HTMLPreElement;
  outputMeta: HTMLElement;
  presetButtons: HTMLButtonElement[];
  requestBody: HTMLPreElement;
  requestSummary: HTMLElement;
  resetButton: HTMLButtonElement | null;
  runNote: HTMLElement;
  runSummary: HTMLElement;
  statusPill: HTMLElement;
  stopButton: HTMLButtonElement | null;
  submitButton: HTMLButtonElement;
  transportMeta: HTMLElement;
}

export function renderPlaygroundHeroActions(): string {
  return `
    <button class="button button--secondary" id="playground-stop" type="button" disabled>Stop request</button>
    <button class="button button--secondary" id="playground-reset" type="button">Reset output</button>
  `;
}

export function renderPlaygroundPage(
  setup: SetupPayload,
  initialRequest: PlaygroundRequest,
): string {
  return `
    ${kpi("GigaChat", setup.gigachat_ready ? "ready" : "missing")}
    ${kpi("Security", setup.security_ready ? "ready" : "pending")}
    ${kpi("Persisted", setup.persisted ? "yes" : "defaults")}
    ${kpi("Bootstrap", asRecord(setup.bootstrap).required ? "active" : "off")}
    ${card(
      "Request Builder",
      `
        <form id="playground-form" class="stack">
          <div class="surface">
            <div class="surface__header">
              <div class="stack">
                <h4>Smoke presets</h4>
                <p class="muted">Load a ready-made request, then tweak model/prompt fields before sending.</p>
              </div>
              <div class="surface__meta">
                ${PLAYGROUND_PRESETS.map(
                  (preset) => `
                    <button class="button button--secondary playground-preset" data-preset="${escapeHtml(
                      preset.id,
                    )}" type="button">
                      ${escapeHtml(preset.label)}
                    </button>
                  `,
                ).join("")}
              </div>
            </div>
          </div>
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
          <label class="field">
            <span>System prompt</span>
            <textarea name="system_prompt" placeholder="Optional system prompt">${escapeHtml(
              DEFAULT_PLAYGROUND_PRESET.systemPrompt,
            )}</textarea>
          </label>
          <label class="field">
            <span>User prompt</span>
            <textarea name="user_prompt">${escapeHtml(DEFAULT_PLAYGROUND_PRESET.userPrompt)}</textarea>
          </label>
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
                  Requests reuse the gateway key from the left rail. Keep it aligned with bootstrap or scoped keys.
                </p>
              </div>
            </div>
          </div>
          <div class="toolbar">
            <button class="button" id="playground-submit" type="submit">Send request</button>
            <span class="muted" id="playground-form-note">Preview updates live as you type.</span>
          </div>
        </form>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Request Preview",
      `
        <div class="surface">
          <div class="stack">
            <div id="playground-request-summary"></div>
            <pre class="code-block code-block--tall" id="playground-request-body">${escapeHtml(
              JSON.stringify(initialRequest.body, null, 2),
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Bootstrap Hints",
      `
        <div class="stack">
          <div id="playground-bootstrap-banner"></div>
          <div class="surface">
            <div class="stack">
              <div class="surface__header">
                <div class="stack">
                  <h4>Zero-env path</h4>
                  <p class="muted">Use the console as a built-in smoke client even before external SDKs are wired up.</p>
                </div>
                <div class="surface__meta">
                  ${pill("setup")}
                  ${pill("keys")}
                  ${pill("smoke")}
                </div>
              </div>
              <div id="playground-bootstrap-summary"></div>
              <div class="toolbar">
                <a class="button button--secondary" href="/admin/setup">Open setup</a>
                <a class="button button--secondary" href="/admin/keys">Open keys</a>
              </div>
            </div>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Run Status",
      `
        <div class="surface">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Request lifecycle</h4>
                <p class="muted">Pending, first-byte, stream, success, and abort states stay explicit so the UI never looks hung.</p>
              </div>
              <div class="surface__meta" id="playground-status-pill">${pill("idle")}</div>
            </div>
            <div id="playground-run-note" class="field-note">${escapeHtml(DEFAULT_OUTPUT)}</div>
            <div id="playground-run-summary"></div>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Assistant Output",
      `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Parsed response</h4>
                <p class="muted">Best-effort extraction keeps the operator focused on model output instead of protocol noise.</p>
              </div>
              <div class="surface__meta" id="playground-output-meta">${pill("waiting")}</div>
            </div>
            <pre class="code-block code-block--tall playground-output" id="playground-assistant-output">${escapeHtml(
              DEFAULT_ASSISTANT_OUTPUT,
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-4",
    )}
    ${card(
      "Raw Response",
      `
        <div class="surface">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Transport transcript</h4>
                <p class="muted">Shows the final body for plain requests or a normalized event transcript for SSE.</p>
              </div>
              <div class="surface__meta" id="playground-transport-meta">${pill("idle")}</div>
            </div>
            <pre class="code-block code-block--tall playground-output" id="playground-output">${escapeHtml(
              DEFAULT_OUTPUT,
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-8",
    )}
  `;
}

export function resolvePlaygroundElements(
  pageContent: HTMLElement,
): PlaygroundPageElements | null {
  const form = pageContent.querySelector<HTMLFormElement>("#playground-form");
  const requestSummary = pageContent.querySelector<HTMLElement>("#playground-request-summary");
  const requestBody = pageContent.querySelector<HTMLPreElement>("#playground-request-body");
  const bootstrapBanner = pageContent.querySelector<HTMLElement>("#playground-bootstrap-banner");
  const bootstrapSummary = pageContent.querySelector<HTMLElement>("#playground-bootstrap-summary");
  const authNote = pageContent.querySelector<HTMLElement>("#playground-auth-note");
  const formNote = pageContent.querySelector<HTMLElement>("#playground-form-note");
  const runNote = pageContent.querySelector<HTMLElement>("#playground-run-note");
  const runSummary = pageContent.querySelector<HTMLElement>("#playground-run-summary");
  const statusPill = pageContent.querySelector<HTMLElement>("#playground-status-pill");
  const assistantOutput = pageContent.querySelector<HTMLPreElement>("#playground-assistant-output");
  const outputMeta = pageContent.querySelector<HTMLElement>("#playground-output-meta");
  const transportMeta = pageContent.querySelector<HTMLElement>("#playground-transport-meta");
  const output = pageContent.querySelector<HTMLPreElement>("#playground-output");
  const submitButton = pageContent.querySelector<HTMLButtonElement>("#playground-submit");

  if (
    !form ||
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
    !submitButton
  ) {
    return null;
  }

  return {
    assistantOutput,
    authNote,
    bootstrapBanner,
    bootstrapSummary,
    form,
    formNote,
    gatewayKeyInput: document.getElementById("gateway-key-input") as HTMLInputElement | null,
    output,
    outputMeta,
    presetButtons: Array.from(
      pageContent.querySelectorAll<HTMLButtonElement>(".playground-preset"),
    ),
    requestBody,
    requestSummary,
    resetButton: document.getElementById("playground-reset") as HTMLButtonElement | null,
    runNote,
    runSummary,
    statusPill,
    stopButton: document.getElementById("playground-stop") as HTMLButtonElement | null,
    submitButton,
    transportMeta,
  };
}

export function updatePlaygroundRequestPreview(options: {
  elements: PlaygroundPageElements;
  gatewayKey: string;
  request: PlaygroundRequest;
  setup: SetupPayload;
}): void {
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
  elements.bootstrapSummary.innerHTML = renderDefinitionList(
    buildBootstrapSteps(setup, gatewayKey),
  );
}

export function updatePlaygroundRunPanels(options: {
  elements: PlaygroundPageElements;
  state: PlaygroundPageState;
}): void {
  const { elements, state } = options;
  const { activeController, runState } = state;

  elements.statusPill.innerHTML = renderPhasePill(runState.phase);
  elements.outputMeta.innerHTML = pill(
    runState.assistantOutput.trim()
      ? "parsed"
      : runState.phase === "error"
        ? "error"
        : "waiting",
    runState.phase === "success"
      ? "good"
      : runState.phase === "error"
        ? "warn"
        : "default",
  );
  elements.transportMeta.innerHTML = pill(
    runState.eventCount > 0 ? `${runState.eventCount} events` : runState.phase,
    runState.phase === "success"
      ? "good"
      : runState.phase === "error"
        ? "warn"
        : "default",
  );
  elements.runNote.textContent = runState.note;
  elements.runSummary.innerHTML = renderDefinitionList([
    { label: "Phase", value: humanizePhase(runState.phase) },
    { label: "Status", value: formatStatus(runState.statusCode, runState.statusText) },
    {
      label: "Duration",
      value:
        runState.startedAt === null
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

function renderBootstrapBanner(setup: SetupPayload, gatewayKey: string): string {
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

function buildBootstrapSteps(
  setup: SetupPayload,
  gatewayKey: string,
): Array<{ label: string; value: string; note?: string }> {
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

function describePreviewState(
  request: PlaygroundRequest,
  gatewayKey: string,
  setup: SetupPayload,
): string {
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

function renderPhasePill(phase: RunPhase): string {
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

function formatStatus(statusCode: number | null, statusText: string): string {
  if (statusCode === null) {
    return "n/a";
  }
  return `${statusCode}${statusText ? ` ${statusText}` : ""}`;
}

function humanizePhase(phase: RunPhase): string {
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
