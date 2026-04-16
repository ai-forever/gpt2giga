import { OPERATOR_GUIDE_LINKS } from "../../docs-links.js";
import { pathForPage } from "../../routes.js";
import {
  card,
  kpi,
  pill,
  renderDefinitionList,
  renderFormSection,
  renderGuideLinks,
  renderWorkflowCard,
} from "../../templates.js";
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
  const bootstrapRequired = asRecord(setup.bootstrap).required;
  return `
    ${kpi("GigaChat", setup.gigachat_ready ? "ready" : "missing")}
    ${kpi("Security", setup.security_ready ? "ready" : "pending")}
    ${kpi("Persisted", setup.persisted ? "yes" : "defaults")}
    ${kpi("Bootstrap", bootstrapRequired ? "active" : "off")}
    ${card(
      "Request builder",
      `
        <form id="playground-form" class="form-shell">
          <div class="form-shell__intro">
            <span class="eyebrow">Smoke flow</span>
            <p class="muted">
              Keep Playground narrow: load a preset, tweak only the request fields that matter, then send one proof request before widening into Traffic or Logs.
            </p>
          </div>
          ${renderFormSection({
            title: "Smoke presets",
            intro: "Start from a known-good request shape, then adjust only the surface, model, or prompt fields you really need.",
            body: `
              <div class="toolbar">
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
            `,
          })}
          ${renderFormSection({
            title: "Request targeting",
            intro: "Choose the compatibility surface and model first, then edit prompts inside one quieter shell.",
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
            title: "Transport posture",
            intro: "Streaming and gateway auth stay explicit so the operator always knows what the proxy will attach and how the response should arrive.",
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
                      Requests reuse the gateway key from the left rail. Keep it aligned with bootstrap or scoped keys.
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
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Smoke workflow handoff",
      `
        <div class="stack">
          <div id="playground-bootstrap-banner"></div>
          <div class="workflow-grid">
            ${renderWorkflowCard({
              workflow: "start",
              title: setup.gigachat_ready ? "Smoke the mounted compatibility surface" : "Finish bootstrap before smoke",
              note: setup.gigachat_ready
                ? "Use one preset request as proof that the mounted route really works from inside the console, then widen into request-level diagnostics only if the result still feels wrong."
                : "Missing upstream credentials or bootstrap posture should be closed before Playground output is treated as a real signal.",
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
              title: "Hand off only after one request narrows the story",
              note: "Traffic and Logs stay secondary until one request, failure, or usage signal becomes the real debugging target.",
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
                  <p class="muted">
                    Keep bootstrap facts close to the smoke flow, but out of the main request builder.
                  </p>
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
      `,
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Request preview",
      `
        <div class="stack">
          <div class="surface">
            <div class="stack">
              <div class="surface__header">
                <div class="stack">
                  <h4>Current request posture</h4>
                  <p class="muted">
                    Summary stays primary. Open the raw request payload only when a specific field still needs inspection.
                  </p>
                </div>
              </div>
              <div id="playground-request-summary"></div>
            </div>
          </div>
          <details class="details-disclosure">
            <summary>Current request payload</summary>
            <pre class="code-block code-block--tall" id="playground-request-body">${escapeHtml(
              JSON.stringify(initialRequest.body, null, 2),
            )}</pre>
          </details>
        </div>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Current posture and handoff",
      `
        <div class="stack">
          <div class="surface">
            <div class="stack">
              <div class="surface__header">
                <div class="stack">
                  <h4>Request lifecycle</h4>
                  <p class="muted">
                    Pending, first-byte, stream, success, and abort states stay explicit so the UI never looks hung.
                  </p>
                </div>
                <div class="surface__meta" id="playground-status-pill">${pill("idle")}</div>
              </div>
              <div id="playground-run-note" class="field-note">${escapeHtml(DEFAULT_OUTPUT)}</div>
              <div id="playground-run-summary"></div>
            </div>
          </div>
          ${renderGuideLinks(
            [
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
            ],
            "Playground stays narrow. Use the longer guides only after one smoke request and its summary still do not explain what the operator should do next.",
          )}
        </div>
      `,
      "panel panel--span-4 panel--aside",
    )}
    ${card(
      "Assistant output",
      `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Parsed response</h4>
                <p class="muted">
                  Best-effort extraction keeps the operator focused on model output instead of protocol noise.
                </p>
              </div>
              <div class="surface__meta" id="playground-output-meta">${pill("waiting")}</div>
            </div>
            <pre class="code-block code-block--tall playground-output" id="playground-assistant-output">${escapeHtml(
              DEFAULT_ASSISTANT_OUTPUT,
            )}</pre>
          </div>
        </div>
      `,
      "panel panel--span-8 panel--measure",
    )}
    ${card(
      "Transport transcript",
      `
        <div class="stack">
          <div class="surface">
            <div class="surface__header">
              <div class="stack">
                <h4>Transport posture</h4>
                <p class="muted">
                  Rendered output stays primary. Open the transcript only when transport-level detail is the actual debugging target.
                </p>
              </div>
              <div class="surface__meta" id="playground-transport-meta">${pill("idle")}</div>
            </div>
          </div>
          <details class="details-disclosure">
            <summary>Current transport snapshot</summary>
            <pre class="code-block code-block--tall playground-output" id="playground-output">${escapeHtml(
              DEFAULT_OUTPUT,
            )}</pre>
          </details>
        </div>
      `,
      "panel panel--span-4 panel--aside",
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
