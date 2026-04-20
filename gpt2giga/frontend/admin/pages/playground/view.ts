import { pathForPage } from "../../routes.js";
import {
  card,
  pill,
  renderDefinitionList,
  renderFormSection,
  renderGuideLinks,
  renderPageFrame,
  renderPageSection,
} from "../../templates.js";
import type { SetupPayload } from "../../types.js";
import {
  asRecord,
  describeGigachatAuth,
  describePersistenceStatus,
  escapeHtml,
  formatBytes,
  formatDurationMs,
  formatNumber,
} from "../../utils.js";
import type { PlaygroundPageState, PlaygroundRequest, RunPhase } from "./state.js";
import {
  DEFAULT_ASSISTANT_OUTPUT,
  DEFAULT_OUTPUT,
  DEFAULT_PLAYGROUND_PRESET,
  PLAYGROUND_PRESETS,
} from "./state.js";

export interface PlaygroundPageElements {
  assistantOutput: HTMLDivElement;
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
  responseShell: HTMLDivElement;
  responseState: HTMLElement;
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
    <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic"))}">Traffic</a>
    <a class="button button--secondary" href="${escapeHtml(pathForPage("logs"))}">Logs</a>
  `;
}

export function renderPlaygroundPage(
  setup: SetupPayload,
  initialRequest: PlaygroundRequest,
): string {
  const bootstrapRequired = Boolean(asRecord(setup.bootstrap).required);
  const persistence = describePersistenceStatus(setup);
  const gigachatAuth = describeGigachatAuth(setup);
  const surfaceCount = new Set(PLAYGROUND_PRESETS.map((preset) => preset.surface)).size;

  return renderPageFrame({
    className: "page-frame--playground",
    toolbar: renderPlaygroundToolbar(setup, persistence, gigachatAuth, bootstrapRequired),
    sections: [
      renderPageSection({
        eyebrow: "Workspace",
        title: "Run one smoke request",
        description:
          "Start with the form, keep parsed output beside it, and use Traffic or Logs after one useful smoke call.",
        actions: `
          <a class="button button--secondary" href="${escapeHtml(pathForPage("traffic"))}">Traffic</a>
          <a class="button button--secondary" href="${escapeHtml(pathForPage("logs"))}">Logs</a>
        `,
        bodyClassName: "page-grid",
        body: `
          ${card(
            "Request controls",
            renderPlaygroundForm(initialRequest),
            "panel panel--span-5 panel--aside playground-panel playground-panel--primary",
          )}
          ${card(
            "Response workspace",
            `
              <div class="stack">
                <div class="surface surface--dark">
                  <div class="stack">
                    <div class="surface__header">
                      <div class="stack">
                        <h4>Parsed response</h4>
                        <p class="muted">Keep parsed output primary.</p>
                      </div>
                      <div class="surface__meta" id="playground-output-meta">${pill("waiting")}</div>
                    </div>
                    <div class="playground-response-shell" id="playground-response-shell" data-phase="idle">
                      <div class="playground-response-body playground-output" id="playground-assistant-output">${escapeHtml(
                        DEFAULT_ASSISTANT_OUTPUT,
                      )}</div>
                      <div class="playground-response-footer">
                        <span class="playground-response-state" id="playground-response-state">Waiting for assistant output.</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="surface">
                  <div class="stack">
                    <div class="surface__header">
                      <div class="stack">
                        <h4>Current run</h4>
                        <p class="muted">Keep lifecycle and transport visible.</p>
                      </div>
                      <div class="surface__meta" id="playground-status-pill">${pill("idle")}</div>
                    </div>
                    <div id="playground-run-note" class="field-note">${escapeHtml(DEFAULT_OUTPUT)}</div>
                    <div id="playground-run-summary"></div>
                  </div>
                </div>
              </div>
            `,
            "panel panel--span-7 playground-panel",
          )}
          ${card(
            "Run inspector",
            `
              <div class="stack">
                <div id="playground-bootstrap-banner"></div>
                <div class="surface">
                  <div class="stack">
                    <div class="surface__header">
                      <div class="stack">
                        <h4>Transport state</h4>
                        <p class="muted">Preview updates live beside the form.</p>
                      </div>
                      <div class="surface__meta" id="playground-transport-meta">${pill("idle")}</div>
                    </div>
                    <p class="field-note" id="playground-form-note">Preview updates live.</p>
                  </div>
                </div>
                <details class="details-disclosure">
                  <summary>Bootstrap posture</summary>
                  <div id="playground-bootstrap-summary"></div>
                </details>
              </div>
            `,
            "panel panel--span-5 panel--aside playground-panel",
          )}
          ${card(
            "Request preview",
            `
              <div class="stack">
                <div class="surface">
                  <div class="stack">
                    <div class="surface__header">
                      <div class="stack">
                        <h4>Request summary</h4>
                        <p class="muted" id="playground-auth-note">Reuses the rail gateway key.</p>
                      </div>
                    </div>
                    <div id="playground-request-summary"></div>
                  </div>
                </div>
                <details class="details-disclosure">
                  <summary>Payload JSON</summary>
                  <pre class="code-block code-block--tall" id="playground-request-body">${escapeHtml(
                    JSON.stringify(initialRequest.body, null, 2),
                  )}</pre>
                </details>
              </div>
            `,
            "panel panel--span-7 playground-panel",
          )}
        `,
      }),
      renderPageSection({
        eyebrow: "Diagnostics",
        title: "Transcript and handoff",
        description:
          "Keep the raw exchange available, but move into adjacent surfaces only after the smoke request narrows the question.",
        actions: `
          <a class="button button--secondary" href="${escapeHtml(pathForPage("setup"))}">Setup</a>
          <a class="button button--secondary" href="${escapeHtml(pathForPage("keys"))}">API Keys</a>
        `,
        bodyClassName: "page-grid",
        body: `
          ${card(
            "Transport transcript",
            `
              <div class="stack">
                <div class="surface">
                  <div class="surface__header">
                    <div class="stack">
                      <h4>Raw transport transcript</h4>
                      <p class="muted">Open full body and SSE only when parsed output is not enough.</p>
                    </div>
                  </div>
                </div>
                <pre class="code-block code-block--tall playground-output" id="playground-output">${escapeHtml(
                  DEFAULT_OUTPUT,
                )}</pre>
              </div>
            `,
            "panel panel--span-8",
          )}
          ${card(
            "Operational handoff",
            renderGuideLinks(
              [
                {
                  label: setup.gigachat_ready ? "Traffic inventory" : "Setup",
                  href: setup.gigachat_ready ? pathForPage("traffic") : pathForPage("setup"),
                  note: setup.gigachat_ready
                    ? "Reopen request and error inventory after one useful smoke call."
                    : "Finish upstream auth and bootstrap posture first.",
                },
                {
                  label: "Logs",
                  href: pathForPage("logs"),
                  note: "Switch here when parsed output is insufficient and you need request-level correlation.",
                },
                {
                  label: "API Keys",
                  href: pathForPage("keys"),
                  note: "Use this only when proxy auth or scoped keys block the smoke request.",
                },
              ],
              {
                compact: true,
                intro: bootstrapRequired
                  ? "Bootstrap mode is active, so keep auth posture visible."
                  : "Use adjacent surfaces only after playground narrows the question.",
              },
            ),
            "panel panel--span-4 panel--aside",
          )}
        `,
      }),
    ],
  });
}

function renderPlaygroundToolbar(
  setup: SetupPayload,
  persistence: ReturnType<typeof describePersistenceStatus>,
  gigachatAuth: ReturnType<typeof describeGigachatAuth>,
  bootstrapRequired: boolean,
): string {
  return `
    <div class="playground-toolbar">
      <p class="playground-toolbar__lead">
        Smoke one route first. Use Traffic or Logs only after the response stops being enough.
      </p>
      <div class="playground-toolbar__meta">
        <div class="playground-toolbar__stats" aria-label="Playground context">
          ${renderPlaygroundInlineStat("Surfaces", String(new Set(PLAYGROUND_PRESETS.map((preset) => preset.surface)).size))}
          ${renderPlaygroundInlineStat("Presets", String(PLAYGROUND_PRESETS.length))}
          ${renderPlaygroundInlineStat("GigaChat", gigachatAuth.value)}
          ${renderPlaygroundInlineStat("Persistence", persistence.value)}
        </div>
        <div class="pill-row">
          ${pill(gigachatAuth.pillLabel, gigachatAuth.tone)}
          ${pill(`Security: ${setup.security_ready ? "ready" : "pending"}`, setup.security_ready ? "good" : "warn")}
          ${pill(persistence.pillLabel, persistence.tone)}
          ${pill(`Bootstrap: ${bootstrapRequired ? "active" : "off"}`, bootstrapRequired ? "warn" : "default")}
        </div>
      </div>
    </div>
  `;
}

function renderPlaygroundInlineStat(label: string, value: string): string {
  return `
    <div class="playground-toolbar__stat">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}

function renderPlaygroundForm(initialRequest: PlaygroundRequest): string {
  return `
    <form id="playground-form" class="form-shell">
      <div class="playground-preset-strip">
        <div class="playground-preset-strip__header">
          <span class="eyebrow">Starting point</span>
          <p class="muted">Pick a baseline request, then edit.</p>
        </div>
        <div class="playground-preset-strip__buttons">
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
      <div class="form-shell__intro">
        <span class="eyebrow">Request config</span>
        <p class="muted">Choose a route, tune prompts, and send.</p>
      </div>
      ${renderFormSection({
        title: "Request",
        intro: "Keep route and model compact, then adjust prompts.",
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
            <textarea name="system_prompt" placeholder="Optional system prompt">${escapeHtml(
              DEFAULT_PLAYGROUND_PRESET.systemPrompt,
            )}</textarea>
          </label>
          <label class="field">
            <span>User prompt</span>
            <textarea name="user_prompt">${escapeHtml(DEFAULT_PLAYGROUND_PRESET.userPrompt)}</textarea>
          </label>
        `,
      })}
      ${renderFormSection({
        title: "Transport",
        intro: "Streaming changes the transport lane only; auth still reuses the rail gateway key.",
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
                <p class="muted">
                  Route auth is inherited from the rail input. Use API Keys only when the request should stay protected outside localhost bootstrap.
                </p>
              </div>
            </div>
          </div>
        `,
      })}
      <div class="form-actions">
        <button class="button" id="playground-submit" type="submit">Send request</button>
      </div>
    </form>
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
  const assistantOutput = pageContent.querySelector<HTMLDivElement>("#playground-assistant-output");
  const outputMeta = pageContent.querySelector<HTMLElement>("#playground-output-meta");
  const transportMeta = pageContent.querySelector<HTMLElement>("#playground-transport-meta");
  const output = pageContent.querySelector<HTMLPreElement>("#playground-output");
  const responseShell = pageContent.querySelector<HTMLDivElement>("#playground-response-shell");
  const responseState = pageContent.querySelector<HTMLElement>("#playground-response-state");
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
    !responseShell ||
    !responseState ||
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
    responseShell,
    responseState,
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
  const gigachatAuth = describeGigachatAuth(setup);
  elements.requestSummary.innerHTML = renderDefinitionList([
    { label: "Surface", value: request.label },
    { label: "Endpoint", value: `POST ${request.url}` },
    { label: "Streaming", value: request.stream ? "on" : "off" },
    {
      label: "Auth",
      value: gatewayKey ? request.authLabel : "gateway key required",
      note: gatewayKey ? "Current rail key will be attached." : `${request.authLabel} appears only when the rail key is filled.`,
    },
    { label: "Gateway key", value: gatewayKeyState },
    {
      label: "Payload size",
      value: formatBytes(new Blob([JSON.stringify(request.body)]).size),
    },
    {
      label: "Bootstrap",
      value: bootstrap.required ? "active" : "not required",
      note: bootstrap.required
        ? "If the rail key is empty, save the bootstrap/admin token first."
        : "Normal gateway auth flow.",
    },
  ]);
  elements.requestBody.textContent = JSON.stringify(request.body, null, 2);
  elements.authNote.textContent = gatewayKey
    ? `Gateway key present. Will attach ${request.authLabel}.`
    : `Gateway key empty. ${request.authLabel} stays absent until the rail key is filled.`;
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

  elements.submitButton.disabled = activeController !== null;
  if (elements.stopButton) {
    elements.stopButton.disabled = activeController === null;
    elements.stopButton.textContent = "Stop request";
  }

  elements.statusPill.innerHTML = renderPhasePill(runState.phase);
  elements.outputMeta.innerHTML = pill(
    runState.phase === "streaming"
      ? "live"
      : runState.assistantOutput.trim()
        ? "parsed"
      : runState.phase === "error"
        ? "error"
        : "waiting",
    runState.phase === "streaming"
      ? "good"
      : runState.phase === "success"
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
    { label: "Input tokens", value: formatTokenCount(runState.tokenUsage.inputTokens) },
    { label: "Output tokens", value: formatTokenCount(runState.tokenUsage.outputTokens) },
    { label: "Total tokens", value: formatTokenCount(runState.tokenUsage.totalTokens) },
    { label: "Content type", value: runState.contentType || "n/a" },
    {
      label: "Request",
      value: runState.request ? `POST ${runState.request.url}` : "No request yet",
      note: runState.request ? runState.request.label : undefined,
    },
    ...(runState.errorText ? [{ label: "Error", value: runState.errorText }] : []),
  ]);
  elements.responseShell.dataset.phase = runState.phase;
  elements.assistantOutput.textContent =
    runState.assistantOutput || DEFAULT_ASSISTANT_OUTPUT;
  elements.responseState.textContent = describeAssistantSurfaceState(runState);
  elements.output.textContent = runState.rawOutput || DEFAULT_OUTPUT;

  if (runState.phase === "streaming") {
    elements.assistantOutput.scrollTop = elements.assistantOutput.scrollHeight;
    elements.output.scrollTop = elements.output.scrollHeight;
  }
}

function renderBootstrapBanner(setup: SetupPayload, gatewayKey: string): string {
  const bootstrap = asRecord(setup.bootstrap);
  const gigachatAuth = describeGigachatAuth(setup);
  if (!setup.gigachat_ready) {
    return `
      <div class="banner banner--warn">
        Effective GigaChat auth is missing. Use <a href="/admin/setup"><strong>/admin/setup</strong></a>
        before trusting smoke results.
      </div>
    `;
  }

  if (bootstrap.required && !gatewayKey) {
    return `
      <div class="banner banner--warn">
        Bootstrap mode is active and the gateway key field is empty. Save the bootstrap/admin token in the
        rail, then rerun.
      </div>
    `;
  }

  if (!setup.security_ready && !gatewayKey) {
    return `
      <div class="banner banner--warn">
        Gateway auth is not configured yet. Playground can still validate upstream wiring, but protected
        routes still need a key from <a href="/admin/keys"><strong>/admin/keys</strong></a>.
      </div>
    `;
  }

  return `
    <div class="banner">
      Playground is ready for smoke traffic. Effective upstream auth uses <strong>${escapeHtml(gigachatAuth.value)}</strong>. Start with <strong>OpenAI hello</strong>, then try streaming.
    </div>
  `;
}

function buildBootstrapSteps(
  setup: SetupPayload,
  gatewayKey: string,
): Array<{ label: string; value: string; note?: string }> {
  const bootstrap = asRecord(setup.bootstrap);
  const persistence = describePersistenceStatus(setup);
  const gigachatAuth = describeGigachatAuth(setup);
  return [
    {
      label: "Persistence",
      value: persistence.value,
      note: persistence.note,
    },
    {
      label: "GigaChat auth",
      value: gigachatAuth.value,
      note: setup.gigachat_ready ? gigachatAuth.note : "Finish Setup before expecting success.",
    },
    {
      label: "Gateway key",
      value: gatewayKey ? "present" : "empty",
      note: gatewayKey ? "Playground will attach it." : "Use the rail input if proxy auth is enabled.",
    },
    {
      label: "Bootstrap gate",
      value: bootstrap.required ? "active" : "off",
      note: bootstrap.required ? "Use the bootstrap token or localhost allowance." : "No special gate is active.",
    },
  ];
}

function describePreviewState(
  request: PlaygroundRequest,
  gatewayKey: string,
  setup: SetupPayload,
): string {
  if (!setup.gigachat_ready) {
    return "Payload is ready, but effective upstream GigaChat auth is still missing.";
  }
  if (!gatewayKey && (setup.security_ready || asRecord(setup.bootstrap).required)) {
    return `Preview is valid, but ${request.authLabel} stays absent until the gateway key field is filled.`;
  }
  if (request.stream) {
    return `Streaming is enabled. ${request.url} stays cancellable from the hero bar.`;
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

function formatTokenCount(value: number | null): string {
  return value === null ? "n/a" : formatNumber(value);
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

function describeAssistantSurfaceState(runState: PlaygroundPageState["runState"]): string {
  if (runState.phase === "sending") {
    return "Opening response stream…";
  }
  if (runState.phase === "streaming") {
    return `Streaming live • ${runState.eventCount} event${runState.eventCount === 1 ? "" : "s"}`;
  }
  if (runState.phase === "success") {
    return runState.eventCount > 0
      ? `Stream complete • ${runState.eventCount} event${runState.eventCount === 1 ? "" : "s"}`
      : "Response complete";
  }
  if (runState.phase === "error") {
    return "Response interrupted";
  }
  if (runState.phase === "aborted") {
    return "Request stopped";
  }
  return "Waiting for assistant output.";
}
