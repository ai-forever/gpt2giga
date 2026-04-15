import { card, kpi, pill, renderDefinitionList } from "../templates.js";
import { asRecord, escapeHtml, formatBytes, formatDurationMs, toErrorMessage, } from "../utils.js";
const DEFAULT_OUTPUT = "No request yet.";
const DEFAULT_ASSISTANT_OUTPUT = "Assistant output will appear here.";
const PRESETS = [
    {
        id: "openai-chat-hello",
        label: "OpenAI hello",
        description: "Fast non-stream smoke for the default OpenAI-compatible chat route.",
        surface: "openai-chat",
        model: "GigaChat",
        systemPrompt: "You are concise and answer in one short sentence.",
        userPrompt: "Привет! Ответь одной фразой, что gateway отвечает.",
        stream: false,
    },
    {
        id: "openai-chat-stream",
        label: "OpenAI stream",
        description: "Verifies SSE lifecycle and final completion handling on chat/completions.",
        surface: "openai-chat",
        model: "GigaChat",
        systemPrompt: "You are concise.",
        userPrompt: "Расскажи в двух коротких предложениях, что этот stream живой.",
        stream: true,
    },
    {
        id: "openai-responses",
        label: "Responses API",
        description: "Exercises the newer responses surface with instructions and unified output.",
        surface: "openai-responses",
        model: "GigaChat",
        systemPrompt: "Answer as a terse operations assistant.",
        userPrompt: "Summarize why this proxy is useful in one sentence.",
        stream: false,
    },
    {
        id: "anthropic-messages",
        label: "Anthropic messages",
        description: "Smoke-checks the Anthropic-compatible router with a familiar payload shape.",
        surface: "anthropic-messages",
        model: "GigaChat",
        systemPrompt: "You are concise.",
        userPrompt: "Say hello from the Anthropic-compatible surface.",
        stream: false,
    },
    {
        id: "gemini-stream",
        label: "Gemini stream",
        description: "Targets Gemini-compatible SSE and uses proper systemInstruction mapping.",
        surface: "gemini-generate",
        model: "gemini-test",
        systemPrompt: "Be brief.",
        userPrompt: "Write a short stream smoke response.",
        stream: true,
    },
];
export async function renderPlayground(app, token) {
    const setup = await app.api.json("/admin/api/setup");
    if (!app.isCurrentRender(token)) {
        return;
    }
    const initialRequest = buildRequestFromPreset(PRESETS[0]);
    const runState = createIdleRunState();
    const streamEvents = [];
    let activeController = null;
    let activeRunId = 0;
    app.setHeroActions(`
    <button class="button button--secondary" id="playground-stop" type="button" disabled>Stop request</button>
    <button class="button button--secondary" id="playground-reset" type="button">Reset output</button>
  `);
    app.setContent(`
    ${kpi("GigaChat", setup.gigachat_ready ? "ready" : "missing")}
    ${kpi("Security", setup.security_ready ? "ready" : "pending")}
    ${kpi("Persisted", setup.persisted ? "yes" : "defaults")}
    ${kpi("Bootstrap", asRecord(setup.bootstrap).required ? "active" : "off")}
    ${card("Request Builder", `
        <form id="playground-form" class="stack">
          <div class="surface">
            <div class="surface__header">
              <div class="stack">
                <h4>Smoke presets</h4>
                <p class="muted">Load a ready-made request, then tweak model/prompt fields before sending.</p>
              </div>
              <div class="surface__meta">
                ${PRESETS.map((preset) => `
                    <button class="button button--secondary playground-preset" data-preset="${escapeHtml(preset.id)}" type="button">
                      ${escapeHtml(preset.label)}
                    </button>
                  `).join("")}
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
            <textarea name="system_prompt" placeholder="Optional system prompt">${escapeHtml(PRESETS[0].systemPrompt)}</textarea>
          </label>
          <label class="field">
            <span>User prompt</span>
            <textarea name="user_prompt">${escapeHtml(PRESETS[0].userPrompt)}</textarea>
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
      `, "panel panel--span-4")}
    ${card("Request Preview", `
        <div class="surface">
          <div class="stack">
            <div id="playground-request-summary"></div>
            <pre class="code-block code-block--tall" id="playground-request-body">${escapeHtml(JSON.stringify(initialRequest.body, null, 2))}</pre>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Bootstrap Hints", `
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
      `, "panel panel--span-4")}
    ${card("Run Status", `
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
      `, "panel panel--span-4")}
    ${card("Assistant Output", `
        <div class="surface surface--dark">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Parsed response</h4>
                <p class="muted">Best-effort extraction keeps the operator focused on model output instead of protocol noise.</p>
              </div>
              <div class="surface__meta" id="playground-output-meta">${pill("waiting")}</div>
            </div>
            <pre class="code-block code-block--tall playground-output" id="playground-assistant-output">${escapeHtml(DEFAULT_ASSISTANT_OUTPUT)}</pre>
          </div>
        </div>
      `, "panel panel--span-4")}
    ${card("Raw Response", `
        <div class="surface">
          <div class="stack">
            <div class="surface__header">
              <div class="stack">
                <h4>Transport transcript</h4>
                <p class="muted">Shows the final body for plain requests or a normalized event transcript for SSE.</p>
              </div>
              <div class="surface__meta" id="playground-transport-meta">${pill("idle")}</div>
            </div>
            <pre class="code-block code-block--tall playground-output" id="playground-output">${escapeHtml(DEFAULT_OUTPUT)}</pre>
          </div>
        </div>
      `, "panel panel--span-8")}
  `);
    const form = app.pageContent.querySelector("#playground-form");
    const requestSummary = app.pageContent.querySelector("#playground-request-summary");
    const requestBody = app.pageContent.querySelector("#playground-request-body");
    const bootstrapBanner = app.pageContent.querySelector("#playground-bootstrap-banner");
    const bootstrapSummary = app.pageContent.querySelector("#playground-bootstrap-summary");
    const authNote = app.pageContent.querySelector("#playground-auth-note");
    const formNote = app.pageContent.querySelector("#playground-form-note");
    const runNote = app.pageContent.querySelector("#playground-run-note");
    const runSummary = app.pageContent.querySelector("#playground-run-summary");
    const statusPill = app.pageContent.querySelector("#playground-status-pill");
    const assistantOutput = app.pageContent.querySelector("#playground-assistant-output");
    const outputMeta = app.pageContent.querySelector("#playground-output-meta");
    const transportMeta = app.pageContent.querySelector("#playground-transport-meta");
    const output = app.pageContent.querySelector("#playground-output");
    const stopButton = document.getElementById("playground-stop");
    const resetButton = document.getElementById("playground-reset");
    const submitButton = app.pageContent.querySelector("#playground-submit");
    const gatewayKeyInput = document.getElementById("gateway-key-input");
    const presetButtons = Array.from(app.pageContent.querySelectorAll(".playground-preset"));
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
        return;
    }
    const updateRequestPreview = () => {
        const request = buildRequest(form);
        const gatewayKey = gatewayKeyInput?.value.trim() ?? "";
        const gatewayKeyState = gatewayKey ? "configured" : "empty";
        const bootstrap = asRecord(setup.bootstrap);
        requestSummary.innerHTML = renderDefinitionList([
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
        requestBody.textContent = JSON.stringify(request.body, null, 2);
        authNote.textContent = gatewayKey
            ? `Gateway key is present and will be attached as ${request.authLabel}.`
            : "Gateway key is empty. The request will be sent without proxy auth headers.";
        formNote.textContent = describePreviewState(request, gatewayKey, setup);
        bootstrapBanner.innerHTML = renderBootstrapBanner(setup, gatewayKey);
        bootstrapSummary.innerHTML = renderDefinitionList(buildBootstrapSteps(setup, gatewayKey));
    };
    const updateRunPanels = () => {
        statusPill.innerHTML = renderPhasePill(runState.phase);
        outputMeta.innerHTML = pill(runState.assistantOutput.trim() ? "parsed" : runState.phase === "error" ? "error" : "waiting", runState.phase === "success"
            ? "good"
            : runState.phase === "error"
                ? "warn"
                : "default");
        transportMeta.innerHTML = pill(runState.eventCount > 0 ? `${runState.eventCount} events` : runState.phase, runState.phase === "success"
            ? "good"
            : runState.phase === "error"
                ? "warn"
                : "default");
        runNote.textContent = runState.note;
        runSummary.innerHTML = renderDefinitionList([
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
            ...(runState.errorText
                ? [{ label: "Error", value: runState.errorText }]
                : []),
        ]);
        assistantOutput.textContent = runState.assistantOutput || DEFAULT_ASSISTANT_OUTPUT;
        output.textContent = runState.rawOutput || DEFAULT_OUTPUT;
        if (stopButton) {
            stopButton.disabled = activeController === null;
            stopButton.textContent =
                runState.phase === "streaming" || runState.phase === "sending"
                    ? "Stop request"
                    : "Stop request";
        }
        submitButton.disabled = activeController !== null;
    };
    const resetRunState = () => {
        Object.assign(runState, createIdleRunState());
        streamEvents.length = 0;
        updateRunPanels();
    };
    const abortActiveRequest = () => {
        activeController?.abort();
    };
    app.registerCleanup(() => {
        activeRunId += 1;
        activeController?.abort();
        activeController = null;
    });
    const syncPresetButtons = () => {
        const request = buildRequest(form);
        presetButtons.forEach((button) => {
            const preset = PRESETS.find((item) => item.id === button.dataset.preset);
            const selected = preset !== undefined &&
                preset.surface === request.surface &&
                preset.model === String(request.body.model ?? "") &&
                preset.stream === request.stream &&
                preset.systemPrompt === getFields(form).system_prompt.value &&
                preset.userPrompt === getFields(form).user_prompt.value;
            button.dataset.active = selected ? "true" : "false";
        });
    };
    const refreshAll = () => {
        updateRequestPreview();
        syncPresetButtons();
        updateRunPanels();
    };
    const startRequest = async () => {
        const request = buildRequest(form);
        const fields = getFields(form);
        if (!fields.model.value.trim()) {
            fields.model.setCustomValidity("Model is required.");
            fields.model.reportValidity();
            return;
        }
        if (!fields.user_prompt.value.trim()) {
            fields.user_prompt.setCustomValidity("User prompt is required.");
            fields.user_prompt.reportValidity();
            return;
        }
        activeRunId += 1;
        const runId = activeRunId;
        activeController?.abort();
        activeController = new AbortController();
        streamEvents.length = 0;
        Object.assign(runState, {
            phase: "sending",
            note: `Sending ${request.stream ? "streaming" : "plain"} request to ${request.url}.`,
            request,
            startedAt: performance.now(),
            finishedAt: null,
            statusCode: null,
            statusText: "",
            contentType: "",
            bytesReceived: 0,
            chunkCount: 0,
            eventCount: 0,
            assistantOutput: "",
            rawOutput: "",
            errorText: "",
        });
        updateRunPanels();
        try {
            const response = await fetch(request.url, {
                method: "POST",
                headers: buildGatewayHeaders(request.surface, gatewayKeyInput?.value.trim() ?? ""),
                body: JSON.stringify(request.body),
                signal: activeController.signal,
            });
            if (!app.isCurrentRender(token) || runId !== activeRunId) {
                return;
            }
            runState.statusCode = response.status;
            runState.statusText = response.statusText;
            runState.contentType = response.headers.get("content-type") ?? "";
            if (request.stream || runState.contentType.includes("text/event-stream")) {
                runState.phase = "streaming";
                runState.note = "Stream opened. Waiting for events…";
                updateRunPanels();
                await consumeStreamResponse(response, request, runState, streamEvents, () => {
                    if (!app.isCurrentRender(token) || runId !== activeRunId) {
                        return;
                    }
                    updateRunPanels();
                }, activeController.signal);
            }
            else {
                const rawText = await response.text();
                if (!app.isCurrentRender(token) || runId !== activeRunId) {
                    return;
                }
                runState.bytesReceived = new Blob([rawText]).size;
                runState.chunkCount = rawText ? 1 : 0;
                applyPlainResponse(rawText, request, runState);
            }
            if (!app.isCurrentRender(token) || runId !== activeRunId) {
                return;
            }
            runState.finishedAt = performance.now();
            if (!response.ok) {
                runState.phase = "error";
                runState.errorText = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
                runState.note =
                    "Gateway returned a non-2xx response. Check parsed output, transport body, or bootstrap hints.";
            }
            else if (runState.phase !== "aborted") {
                runState.phase = "success";
                runState.note = request.stream
                    ? `Stream finished cleanly with ${runState.eventCount} event${runState.eventCount === 1 ? "" : "s"}.`
                    : "Request completed successfully.";
            }
        }
        catch (error) {
            if (!app.isCurrentRender(token) || runId !== activeRunId) {
                return;
            }
            runState.finishedAt = performance.now();
            if (isAbortError(error)) {
                runState.phase = "aborted";
                runState.note = "Request aborted. You can adjust the payload and send again.";
            }
            else {
                runState.phase = "error";
                runState.errorText = toErrorMessage(error);
                runState.note = "Transport error before a complete response was received.";
            }
        }
        finally {
            if (runId === activeRunId) {
                activeController = null;
            }
            updateRunPanels();
        }
    };
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        await startRequest();
    });
    form.addEventListener("input", () => {
        const fields = getFields(form);
        fields.model.setCustomValidity("");
        fields.user_prompt.setCustomValidity("");
        refreshAll();
    });
    form.addEventListener("change", refreshAll);
    gatewayKeyInput?.addEventListener("input", refreshAll);
    app.registerCleanup(() => {
        gatewayKeyInput?.removeEventListener("input", refreshAll);
    });
    presetButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const preset = PRESETS.find((item) => item.id === button.dataset.preset);
            if (!preset) {
                return;
            }
            applyPreset(form, preset);
            refreshAll();
        });
    });
    stopButton?.addEventListener("click", abortActiveRequest);
    resetButton?.addEventListener("click", resetRunState);
    refreshAll();
}
function applyPlainResponse(rawText, request, runState) {
    const contentType = runState.contentType.toLowerCase();
    const parsedJson = tryParseJson(rawText);
    const displayText = parsedJson !== null
        ? JSON.stringify(parsedJson, null, 2)
        : contentType.startsWith("text/")
            ? rawText
            : rawText || "(empty response body)";
    runState.rawOutput = displayText || "(empty response body)";
    runState.assistantOutput =
        (parsedJson !== null ? extractAssistantText(parsedJson, request.surface) : rawText).trim() ||
            "";
}
async function consumeStreamResponse(response, request, runState, streamEvents, onUpdate, signal) {
    if (!response.body) {
        const fallback = await response.text();
        runState.bytesReceived = new Blob([fallback]).size;
        runState.chunkCount = fallback ? 1 : 0;
        applyPlainResponse(fallback, request, runState);
        return;
    }
    await readSseStream(response.body, {
        onChunk: (bytes) => {
            runState.bytesReceived += bytes;
            runState.chunkCount += 1;
        },
        onEvent: (event) => {
            streamEvents.push(event);
            runState.eventCount = streamEvents.length;
            runState.rawOutput = formatSseTranscript(streamEvents);
            if (event.data === "[DONE]") {
                runState.note = "Received stream terminator.";
                onUpdate();
                return;
            }
            const payload = tryParseJson(event.data);
            const textDelta = payload === null ? event.data : extractAssistantText(payload, request.surface);
            runState.assistantOutput = mergeAssistantOutput(runState.assistantOutput, textDelta, event.type, payload, request.surface);
            runState.note = `Streaming… ${runState.eventCount} event${runState.eventCount === 1 ? "" : "s"} parsed.`;
            onUpdate();
        },
    }, signal);
}
function applyPreset(form, preset) {
    const fields = getFields(form);
    fields.surface.value = preset.surface;
    fields.model.value = preset.model;
    fields.system_prompt.value = preset.systemPrompt;
    fields.user_prompt.value = preset.userPrompt;
    fields.stream.value = String(preset.stream);
}
function getFields(form) {
    return form.elements;
}
function createIdleRunState() {
    return {
        phase: "idle",
        note: DEFAULT_OUTPUT,
        request: null,
        startedAt: null,
        finishedAt: null,
        statusCode: null,
        statusText: "",
        contentType: "",
        bytesReceived: 0,
        chunkCount: 0,
        eventCount: 0,
        assistantOutput: "",
        rawOutput: "",
        errorText: "",
    };
}
function buildRequest(form) {
    const fields = getFields(form);
    return buildRequestFromState({
        surface: fields.surface.value,
        model: fields.model.value.trim() || "GigaChat",
        systemPrompt: fields.system_prompt.value.trim(),
        userPrompt: fields.user_prompt.value.trim(),
        stream: fields.stream.value === "true",
    });
}
function buildRequestFromPreset(preset) {
    return buildRequestFromState({
        surface: preset.surface,
        model: preset.model,
        systemPrompt: preset.systemPrompt,
        userPrompt: preset.userPrompt,
        stream: preset.stream,
    });
}
function buildRequestFromState({ surface, model, systemPrompt, userPrompt, stream, }) {
    if (surface === "openai-chat") {
        return {
            surface,
            label: "OpenAI chat/completions",
            url: "/v1/chat/completions",
            stream,
            authLabel: "Authorization: Bearer",
            body: {
                model,
                stream,
                messages: [
                    ...(systemPrompt ? [{ role: "system", content: systemPrompt }] : []),
                    { role: "user", content: userPrompt },
                ],
            },
        };
    }
    if (surface === "openai-responses") {
        return {
            surface,
            label: "OpenAI responses",
            url: "/v1/responses",
            stream,
            authLabel: "Authorization: Bearer",
            body: {
                model,
                stream,
                instructions: systemPrompt || undefined,
                input: userPrompt,
            },
        };
    }
    if (surface === "anthropic-messages") {
        return {
            surface,
            label: "Anthropic messages",
            url: "/v1/messages",
            stream,
            authLabel: "Authorization: Bearer",
            body: {
                model,
                stream,
                max_tokens: 256,
                system: systemPrompt || undefined,
                messages: [{ role: "user", content: userPrompt }],
            },
        };
    }
    return {
        surface,
        label: "Gemini generateContent",
        url: stream
            ? `/v1beta/models/${encodeURIComponent(model)}:streamGenerateContent?alt=sse`
            : `/v1beta/models/${encodeURIComponent(model)}:generateContent`,
        stream,
        authLabel: "Authorization: Bearer + x-goog-api-key",
        body: {
            ...(systemPrompt
                ? {
                    systemInstruction: {
                        parts: [{ text: systemPrompt }],
                    },
                }
                : {}),
            contents: [
                {
                    role: "user",
                    parts: [{ text: userPrompt }],
                },
            ],
        },
    };
}
function buildGatewayHeaders(surface, gatewayKey) {
    const headers = new Headers({
        "Content-Type": "application/json",
    });
    if (!gatewayKey) {
        return headers;
    }
    headers.set("Authorization", `Bearer ${gatewayKey}`);
    if (surface === "gemini-generate") {
        headers.set("x-goog-api-key", gatewayKey);
    }
    return headers;
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
function tryParseJson(value) {
    if (!value.trim()) {
        return null;
    }
    try {
        return JSON.parse(value);
    }
    catch {
        return null;
    }
}
function extractAssistantText(payload, surface) {
    const record = asRecord(payload);
    if (typeof record.output_text === "string") {
        return String(record.output_text);
    }
    if (Array.isArray(record.output_text)) {
        return record.output_text.map(String).join("");
    }
    if (Array.isArray(record.choices)) {
        const parts = record.choices.flatMap((choice) => {
            const choiceRecord = asRecord(choice);
            return [
                extractMessageContent(choiceRecord.message),
                extractMessageContent(choiceRecord.delta),
                extractTextValue(choiceRecord.text),
            ].filter(Boolean);
        });
        if (parts.length) {
            return parts.join("");
        }
    }
    if (Array.isArray(record.content)) {
        const text = record.content
            .flatMap((item) => {
            const itemRecord = asRecord(item);
            if (typeof itemRecord.text === "string") {
                return [itemRecord.text];
            }
            if (Array.isArray(itemRecord.content)) {
                return itemRecord.content.map((part) => extractTextValue(part)).filter(Boolean);
            }
            return [];
        })
            .join("");
        if (text) {
            return text;
        }
    }
    if (record.delta) {
        const deltaText = extractMessageContent(record.delta) || extractTextValue(record.delta);
        if (deltaText) {
            return deltaText;
        }
    }
    if (Array.isArray(record.candidates)) {
        const candidateText = record.candidates
            .flatMap((candidate) => {
            const content = asRecord(asRecord(candidate).content);
            return Array.isArray(content.parts)
                ? content.parts.map((part) => extractTextValue(part)).filter(Boolean)
                : [];
        })
            .join("");
        if (candidateText) {
            return candidateText;
        }
    }
    if (surface === "openai-responses" && Array.isArray(record.output)) {
        const outputText = record.output
            .flatMap((item) => {
            const itemRecord = asRecord(item);
            if (Array.isArray(itemRecord.content)) {
                return itemRecord.content.map((part) => extractTextValue(part)).filter(Boolean);
            }
            return [];
        })
            .join("");
        if (outputText) {
            return outputText;
        }
    }
    return "";
}
function extractMessageContent(value) {
    const record = asRecord(value);
    if (typeof record.content === "string") {
        return record.content;
    }
    if (Array.isArray(record.content)) {
        return record.content.map((part) => extractTextValue(part)).filter(Boolean).join("");
    }
    return "";
}
function extractTextValue(value) {
    if (typeof value === "string") {
        return value;
    }
    const record = asRecord(value);
    if (typeof record.text === "string") {
        return record.text;
    }
    if (typeof record.value === "string") {
        return record.value;
    }
    if (typeof record.partial_json === "string") {
        return record.partial_json;
    }
    return "";
}
function mergeAssistantOutput(current, next, eventType, payload, surface) {
    const candidate = next.trim();
    if (!candidate) {
        return current;
    }
    const lowerType = eventType.toLowerCase();
    const payloadRecord = asRecord(payload);
    const choiceList = Array.isArray(payloadRecord.choices) ? payloadRecord.choices : [];
    const isDeltaEvent = lowerType.includes("delta") ||
        lowerType.includes("chunk") ||
        Boolean(payloadRecord.delta) ||
        Boolean(asRecord(choiceList[0]).delta);
    if (!current) {
        return candidate;
    }
    if (candidate.startsWith(current) || candidate.length > current.length * 1.5) {
        return candidate;
    }
    if (!isDeltaEvent || surface === "gemini-generate") {
        return candidate.length >= current.length ? candidate : current;
    }
    if (current.endsWith(candidate)) {
        return current;
    }
    return current + candidate;
}
function formatSseTranscript(events) {
    if (!events.length) {
        return DEFAULT_OUTPUT;
    }
    return events
        .map((event, index) => {
        if (event.data === "[DONE]") {
            return `#${index + 1} ${event.type}\n[DONE]`;
        }
        const parsed = tryParseJson(event.data);
        const body = parsed === null ? event.data : JSON.stringify(parsed, null, 2);
        return `#${index + 1} ${event.type}\n${body}`;
    })
        .join("\n\n");
}
async function readSseStream(stream, handlers, signal) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const abortReader = () => {
        void reader.cancel().catch(() => {
            // Ignore cancellation races after the stream has already closed.
        });
    };
    signal?.addEventListener("abort", abortReader, { once: true });
    try {
        while (true) {
            if (signal?.aborted) {
                throw new DOMException("The operation was aborted.", "AbortError");
            }
            const { value, done } = await reader.read();
            if (done) {
                buffer += decoder.decode();
                flushSseFrames(buffer, handlers.onEvent);
                return;
            }
            handlers.onChunk(value.byteLength);
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split(/\r?\n\r?\n/u);
            buffer = frames.pop() ?? "";
            frames.forEach((frame) => flushSseFrames(frame, handlers.onEvent));
        }
    }
    finally {
        signal?.removeEventListener("abort", abortReader);
        reader.releaseLock();
    }
}
function flushSseFrames(rawFrame, onEvent) {
    const frame = rawFrame.trim();
    if (!frame) {
        return;
    }
    let eventType = "message";
    const dataLines = [];
    frame.split(/\r?\n/u).forEach((line) => {
        if (!line || line.startsWith(":")) {
            return;
        }
        if (line.startsWith("event:")) {
            eventType = line.slice("event:".length).trim() || "message";
            return;
        }
        if (line.startsWith("data:")) {
            dataLines.push(line.slice("data:".length).trimStart());
        }
    });
    if (!dataLines.length && eventType === "message") {
        return;
    }
    onEvent({
        type: eventType,
        data: dataLines.join("\n"),
    });
}
function isAbortError(error) {
    return error instanceof DOMException
        ? error.name === "AbortError"
        : error instanceof Error && error.name === "AbortError";
}
