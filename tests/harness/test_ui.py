import pytest
from fastapi.testclient import TestClient

from gpt2giga_harness import proxy
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.ui.app import create_app, validate_ui_bind
from gpt2giga_harness.ui.static import (
    INDEX_HTML,
    UIAssetNotFoundError,
    load_asset,
    load_text_asset,
)


APP_CSS = load_text_asset("app.css")
APP_JS = load_text_asset("app.js")
UI_SOURCE = "\n".join((INDEX_HTML, APP_CSS, APP_JS))


def test_ui_assets_load_from_package_resources():
    assert load_asset("index.html").startswith(b"<!doctype html>")
    assert load_asset("favicon.ico").startswith(b"\x00\x00\x01\x00")
    assert "function boot()" in APP_JS
    assert "function agentPlanSummary(agent)" in APP_JS
    assert "executable with current adapter options" in APP_JS
    assert "transport_by" in APP_JS
    assert 'delivery.rich ? "rich" : "reference-only"' in APP_JS
    assert ".app {" in APP_CSS
    with pytest.raises(UIAssetNotFoundError):
        load_asset("missing.js")


def test_ui_serves_packaged_assets_with_mime_and_cache_headers():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    index_response = client.get("/")
    css_response = client.get("/assets/app.css")
    js_response = client.get("/assets/app.js")
    favicon_response = client.get("/assets/favicon.ico")
    missing_response = client.get("/assets/missing.js")
    traversal_response = client.get("/assets/nested/app.js")

    assert index_response.status_code == 200
    assert index_response.headers["content-type"].startswith("text/html")
    assert index_response.headers["cache-control"] == "no-cache"
    assert (
        '<link rel="stylesheet" href="/assets/app.css?v=38.35">' in index_response.text
    )
    assert (
        '<link rel="icon" href="/assets/favicon.ico" sizes="any">'
        in index_response.text
    )
    assert '<script src="/assets/app.js?v=38.39"></script>' in index_response.text
    assert "<style>" not in index_response.text
    assert "<script>" not in index_response.text
    assert css_response.status_code == 200
    assert css_response.headers["content-type"] == "text/css; charset=utf-8"
    assert css_response.headers["cache-control"] == "public, max-age=3600"
    assert css_response.text == APP_CSS
    assert js_response.status_code == 200
    assert js_response.headers["content-type"] == "text/javascript; charset=utf-8"
    assert js_response.headers["cache-control"] == "public, max-age=3600"
    assert js_response.text == APP_JS
    assert favicon_response.status_code == 200
    assert favicon_response.headers["content-type"] == "image/vnd.microsoft.icon"
    assert favicon_response.headers["cache-control"] == "public, max-age=3600"
    assert favicon_response.content == load_asset("favicon.ico")
    assert missing_response.status_code == 404
    assert traversal_response.status_code == 404


def test_ui_defaults_endpoint_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_API_KEY", "super-secret-api-key")
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "super-secret-gigachat")
    app = create_app(
        HarnessConfig.from_env(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/defaults")

    assert response.status_code == 200
    body = response.json()
    assert body["proxy_url"] == "http://127.0.0.1:8090"
    assert body["default_api_mode"] == "v2"
    assert "super-secret-api-key" not in str(body)
    assert "super-secret-gigachat" not in str(body)


def test_ui_harnesses_endpoint_returns_specs():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    harnesses = response.json()["harnesses"]
    ids = {item["spec"]["id"] for item in harnesses}
    assert "direct-chat" in ids
    assert "echo" in ids
    codex = next(item for item in harnesses if item["spec"]["id"] == "codex-cli")
    assert codex["compatibility"]["event_schema"] == "codex-exec-jsonl-v1"
    assert codex["compatibility"]["history_schema"] == "codex-session-jsonl-v1"
    assert codex["compatibility"]["native_event_schema"] == "raw-terminal-v1"
    assert codex["compatibility"]["native_structured_events"] is False


def test_ui_harnesses_endpoint_includes_discovery_errors():
    registry = HarnessRegistry.with_builtins()
    registry.discovery_errors.append("broken-plugin: import failed")
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    assert response.json()["discovery_errors"] == ["broken-plugin: import failed"]


def test_ui_harnesses_endpoint_includes_plugin_metadata():
    registry = HarnessRegistry()
    registry.register(_SchemaPluginHarness())
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.get("/api/harnesses")

    assert response.status_code == 200
    item = response.json()["harnesses"][0]
    assert item["spec"]["id"] == "schema-plugin"
    assert item["spec"]["plugin_metadata"]["icon"] == "plug"
    assert (
        item["spec"]["plugin_metadata"]["config_schema"]["properties"]["endpoint"][
            "type"
        ]
        == "string"
    )
    assert item["validation"]["ok"] is True


def test_ui_static_includes_plugin_config_schema_renderer():
    assert "function simpleConfigFields" in UI_SOURCE
    assert "harness-config-" in UI_SOURCE


def test_ui_static_includes_safe_dom_markdown_renderer():
    for fragment in (
        "function renderMarkdownInto",
        "function appendMarkdownBlocks",
        "function appendInlineMarkdown",
        "function normalizeMarkdownFenceLines",
        "function isSafeMarkdownHref",
        "function parseLocalFilePath",
        "function appendSourcesBlock",
        "function sourceLinkFromLine",
        "document.createElement(`h${heading[1].length}`)",
        'document.createElement("blockquote")',
        'document.createElement(isOrdered ? "ol" : "ul")',
        'document.createElement("pre")',
        'document.createElement("code")',
        'document.createElement("strong")',
        'document.createElement("em")',
        'document.createElement("a")',
        "document.createTextNode(buffer)",
        '["http:", "https:", "mailto:"]',
        "resolved.origin === window.location.origin",
        'link.setAttribute("rel", "noopener noreferrer")',
        'section.className = "markdown-sources"',
        "domain.textContent = new URL(source.href, window.location.href).hostname",
        "line.match(/^(.*\\S)[ \\t]+```([A-Za-z0-9_-]+)",
        "normalized.push(prefixedFence[1], `\\`\\`\\`${prefixedFence[2]}`)",
        "const lines = normalizeMarkdownFenceLines(value)",
    ):
        assert fragment in UI_SOURCE

    markdown_source = UI_SOURCE[
        UI_SOURCE.index("function isSafeMarkdownHref") : UI_SOURCE.index(
            "function eventToolPayload"
        )
    ]
    assert "innerHTML" not in markdown_source
    assert "DOMParser" not in markdown_source
    assert "insertAdjacentHTML" not in markdown_source
    assert '"javascript:"' not in markdown_source
    assert "<img" not in markdown_source
    assert "onerror" not in markdown_source
    assert "cdn.jsdelivr" not in UI_SOURCE
    assert "unpkg.com" not in UI_SOURCE


def test_ui_static_includes_live_execution_renderer():
    for fragment in (
        "liveRuns: new Map()",
        "function consumeLiveEvent",
        "function renderLiveDraft",
        "function persistedMessageForRun",
        "function toolsFromEvents",
        "function generatedFilesFromEvents",
        "function appendGeneratedFiles",
        "function planPayloadFromTool",
        "function appendPlanBody",
        "function planProgressText",
        "function latestPlanFromTools",
        "function renderCurrentPlan",
        "function renderRunSummary",
        "function mergeUsage",
        "usage = mergeUsage(usage, event.payload || {})",
        "draft.usage = mergeUsage(draft.usage, payload)",
        'event.type === "message_delta"',
        'event.type === "stdout_delta"',
        'event.type === "stderr_delta"',
        '"tool_call_started", "tool_call_delta", "tool_call_finished"',
        'event.type === "usage"',
        'event.type === "generated_file"',
        "state.liveRuns.delete(runId)",
        "isChatNearBottom()",
        'class="message-list" aria-live="polite"',
        'id="run-panel" class="run-summary tab-panel active"',
        ".execution-rail-label",
        ".tool-call-card",
        ".generated-file-card",
        ".live-cursor",
        ".token-chip",
        'tokenChip("Input", normalized.input_tokens)',
        'tokenChip("Output", normalized.output_tokens)',
        'tokenChip("Total", normalized.total_tokens)',
        'payload.error ? "failed" : "completed"',
        '"requested", "completed", "succeeded", "running"',
        ".code-block-header",
        ".code-block-copy",
        ".run-summary-grid",
        ".markdown-body",
        ".markdown-sources",
        ".markdown-file-link",
        'link.className = "markdown-file-link"',
        "href: `/api/files/preview?${params.toString()}`",
        'tool.status === "failed" ? "Failure reason" : "Output"',
        "No failure details were reported by the harness.",
        'name.textContent = plan ? "Plan" : tool.name || "tool"',
        "row.className = `plan-item ${item.status}`",
        ".plan-progress-row",
        ".plan-item.in_progress",
        ".plan-item.completed",
        'id="current-plan" class="current-plan"',
        ".chat-plan-layer",
        ".current-plan-details",
    ):
        assert fragment in UI_SOURCE


def test_ui_static_resumes_active_stream_after_session_reload():
    load_session_source = UI_SOURCE[
        UI_SOURCE.index("async function loadSession") : UI_SOURCE.index(
            "async function loadAttachments"
        )
    ]
    resume_source = UI_SOURCE[
        UI_SOURCE.index("function activeHeadlessRunFromBundle") : UI_SOURCE.index(
            "function finiteToken"
        )
    ]
    stream_source = UI_SOURCE[
        UI_SOURCE.index("function openHeadlessEventStream") : UI_SOURCE.index(
            "function appendStreamEvent"
        )
    ]

    assert "resumeActiveHeadlessRun();" in load_session_source
    for fragment in (
        'runs.filter((run) => run.invocation_mode !== "native")',
        'headless.find((run) => run.status === "running")',
        'headless.find((run) => run.status === "queued")',
        "state.activeHeadlessRun = run",
        "ensureLiveRun(run.id, run)",
        "for (const event of eventsForRun(run.id)) consumeLiveEvent(event)",
        "setHeadlessRunning(true)",
        "renderLiveDraft(run.id)",
        "openHeadlessEventStream(run.id)",
    ):
        assert fragment in resume_source
    for fragment in (
        "headlessEventSourceRunId",
        "latestEventIdForRun(runId)",
        "?after_id=",
        "if (!state.activeHeadlessRun || state.activeHeadlessRun.id !== runId) return;",
        "finishHeadlessStream(runId)",
    ):
        assert fragment in stream_source
    assert (
        "if (!runId || !state.activeHeadlessRun || "
        "state.activeHeadlessRun.id !== runId) return;"
    ) in UI_SOURCE
    assert "state.liveRuns.delete(run.id);" in resume_source
    assert "if (!preserveTerminalPartialDraft(draft))" in UI_SOURCE


def test_ui_static_surfaces_codex_native_trust_and_reconnects_process():
    load_session_source = UI_SOURCE[
        UI_SOURCE.index("async function loadSession") : UI_SOURCE.index(
            "async function loadAttachments"
        )
    ]
    start_source = UI_SOURCE[
        UI_SOURCE.index("async function startNativeProcess") : UI_SOURCE.index(
            "async function ensureSessionForNative"
        )
    ]
    reconnect_source = UI_SOURCE[
        UI_SOURCE.index("function activeNativeProcessFromBundle") : UI_SOURCE.index(
            "function nativeInspectorText"
        )
    ]
    trust_source = UI_SOURCE[
        UI_SOURCE.index("function maybeShowNativeTrustPrompt") : UI_SOURCE.index(
            "async function stopNativeProcess"
        )
    ]

    assert load_session_source.count("restoreActiveNativeProcess();") == 2
    for fragment in (
        'run.invocation_mode !== "native"',
        "metadata.native_process_id",
        "metadata.process_status",
        "nativeTrustDecisionRecorded(bundle, process.id)",
        "setActiveNativeProcess(candidate",
    ):
        assert fragment in reconnect_source
    assert "setActiveNativeProcess(result.data.process || null, result.data)" in (
        start_source
    )
    assert 'showTab("native")' not in start_source
    assert "setInspectorOpen(true)" not in start_source
    for fragment in (
        "doyoutrustthecontentsofthisdirectory",
        "yescontinue",
        "noquit",
        "nativeTrustResolvedProcessIds",
        "rememberNativeTrustDecision(process.id)",
        'allowed ? "1\\r" : "2\\r"',
        'showTab("native")',
        "setInspectorOpen(true)",
    ):
        assert fragment in trust_source


def test_ui_static_handles_terminal_stream_edge_cases():
    load_session_source = UI_SOURCE[
        UI_SOURCE.index("async function loadSession") : UI_SOURCE.index(
            "async function loadAttachments"
        )
    ]
    message_source = UI_SOURCE[
        UI_SOURCE.index("function buildMessageNode") : UI_SOURCE.index(
            "function ensureLiveRun"
        )
    ]
    cancel_source = UI_SOURCE[
        UI_SOURCE.index("async function cancelHeadlessRun") : UI_SOURCE.index(
            "async function startNativeProcess"
        )
    ]
    partial_source = UI_SOURCE[
        UI_SOURCE.index("function restoreTerminalPartialDrafts") : UI_SOURCE.index(
            "function finiteToken"
        )
    ]

    assert "restoreTerminalPartialDrafts();" in load_session_source
    assert (
        'const liveNonterminal = options.live && !["succeeded", "failed", '
        '"canceled"].includes(options.liveStatus);'
    ) in message_source
    assert "} else if (liveNonterminal) {" in message_source
    assert 'waiting.textContent = "Waiting for model output…";' in message_source
    assert 'type: "cancel_requested"' not in cancel_source
    for fragment in (
        '["failed", "canceled"].includes(run.status)',
        'event.type === "message_delta" && liveDelta(event)',
        "ensureLiveRun(run.id, run)",
        "for (const event of events) consumeLiveEvent(event)",
        "draft.status = run.status",
    ):
        assert fragment in partial_source
    assert "function preserveTerminalPartialDraft" in UI_SOURCE
    assert "renderedPartialDrafts" in UI_SOURCE


def test_ui_native_terminal_streams_with_poll_fallback_and_resizes():
    transport_source = APP_JS[
        APP_JS.index("async function consumeNativeOutputPayload") : APP_JS.index(
            "function maybeShowNativeTrustPrompt"
        )
    ]
    lifecycle_source = APP_JS[
        APP_JS.index("function stopNativePolling") : APP_JS.index(
            "function clearNativeTerminal"
        )
    ]

    for fragment in (
        "nativeEventSource: null",
        "nativeEventSourceProcessId: null",
        "nativeResizeObserver: null",
        "nativeResizeTimer: null",
        "nativeTerminalSize: null",
    ):
        assert fragment in APP_JS
    for fragment in (
        "function startNativeOutputTransport()",
        "function openNativeOutputStream(processId)",
        "/output/stream${query}",
        "state.nativeOutputCursor",
        "NATIVE_STREAM_FAILURE_LIMIT",
        "scheduleNativePoll(NATIVE_ACTIVE_POLL_MS)",
        "await consumeNativeOutputPayload(payload, processId)",
        "stopNativeOutputTransport();",
    ):
        assert fragment in transport_source
    for fragment in (
        "function stopNativeOutputTransport()",
        "closeNativeOutputStream();",
        "stopNativePolling();",
        "stopNativeResizeObserver();",
        "function nativeTerminalDimensions()",
        "NATIVE_MIN_ROWS",
        "NATIVE_MAX_COLUMNS",
        "/resize`, {",
        "new ResizeObserver(scheduleNativeResize)",
        "state.nativeResizeObserver.disconnect();",
    ):
        assert fragment in lifecycle_source
    assert (
        'window.addEventListener("beforeunload", stopNativeOutputTransport);' in APP_JS
    )
    assert (
        'byId("native-terminal-diagnostics").addEventListener("toggle", scheduleNativeResize);'
        in APP_JS
    )
    assert 'id="native-terminal-diagnostics"' in INDEX_HTML
    assert "polling remains available as a fallback" in INDEX_HTML


def test_ui_static_refreshes_native_run_after_process_exit():
    terminal_source = UI_SOURCE[
        UI_SOURCE.index("function renderNativeTerminalStatus") : UI_SOURCE.index(
            "function maybeShowNativeTrustPrompt"
        )
    ]

    for fragment in (
        'effectiveStatus === "running" ? "active" : effectiveStatus',
        "function syncNativeRunInBundle(run)",
        "syncNativeRunInBundle(body.run);",
        "function syncNativeMessagesInBundle(messages)",
        "function syncNativeEventsInBundle(events)",
        "const nativeMessages = Array.isArray(body.messages) ? body.messages : [];",
        "const nativeEvents = Array.isArray(body.events) ? body.events : [];",
        "const messagesChanged = syncNativeMessagesInBundle(nativeMessages);",
        "const eventsChanged = syncNativeEventsInBundle(nativeEvents);",
        "if (messagesChanged || eventsChanged)",
        "renderMessages();",
        "renderInspector();",
        'status !== "running"',
        "await loadSession(state.currentSessionId",
        "syncRoute: false",
    ):
        assert fragment in terminal_source
    run_summary_source = UI_SOURCE[
        UI_SOURCE.index("function renderRunSummary") : UI_SOURCE.index(
            "function renderInspector"
        )
    ]
    assert 'effectiveStatus === "running" && run.invocation_mode === "native"' in (
        run_summary_source
    )
    assert '? "active"' in run_summary_source
    assert 'displayStatus === "active" ? "active"' in run_summary_source
    assert "Native CLIs stay active between turns." in INDEX_HTML


def test_ui_native_continuation_requests_a_separate_submit_key():
    continuation_source = APP_JS[
        APP_JS.index("async function continueNativeConversation") : APP_JS.index(
            "async function ensureSessionForNative"
        )
    ]
    input_source = APP_JS[
        APP_JS.index("async function sendNativeProcessInput") : APP_JS.index(
            "async function stopNativeProcess"
        )
    ]

    assert "sendNativeProcessInput(prompt, prompt, true)" in continuation_source
    assert "if (submit) body.submit = true;" in input_source
    assert "body: JSON.stringify(body)" in input_source


def test_ui_native_tools_render_once_stream_live_and_keep_expansion_state():
    render_source = APP_JS[
        APP_JS.index("function renderMessages") : APP_JS.index(
            "function runStatusBadgeClass"
        )
    ]
    tool_source = APP_JS[
        APP_JS.index("function toolCard") : APP_JS.index(
            "function appendGeneratedFiles"
        )
    ]
    poll_source = APP_JS[
        APP_JS.index("async function consumeNativeOutputPayload") : APP_JS.index(
            "function maybeShowNativeTrustPrompt"
        )
    ]
    native_stream_source = APP_JS[
        APP_JS.index("function setActiveNativeProcess") : APP_JS.index(
            "async function pollNativeOutput"
        )
    ]

    for fragment in (
        "const latestMessageIdsByRun = new Map();",
        "latestMessageIdsByRun.set(message.run_id, message.id);",
        "const events = eventsForMessage(message, messages);",
        "const tools = executionMessage ? toolsFromEvents(events) : new Map();",
        "if (latestExecutionMessage && preserveTerminalPartialDraft(draft))",
    ):
        assert fragment in render_source
    for fragment in (
        "toolCallExpansion: new Map()",
        "state.toolCallExpansion.get(expansionKey)",
        "state.toolCallExpansion.set(expansionKey, details.open)",
        "toolCard(tool, messageKey)",
        "message.id || message.run_id",
        "subagentType",
        "tool-call-origin",
        "`${tool.subagentType} subagent`",
    ):
        source = (
            APP_JS
            if fragment
            in {"toolCallExpansion: new Map()", "message.id || message.run_id"}
            else tool_source
        )
        assert fragment in source
    for fragment in (
        "let nativeStreamChanged = false;",
        "nativeStreamChanged = appendNativeTerminal",
        "const messagesChanged = syncNativeMessagesInBundle(nativeMessages);",
        "const eventsChanged = syncNativeEventsInBundle(nativeEvents);",
        "if (hasNewAssistantMessage)",
        "if (messagesChanged || eventsChanged)",
        "else if (nativeStreamChanged)",
    ):
        assert fragment in poll_source
    assert (
        native_stream_source.count(
            '["claude-code", "gemini-cli"].includes(process.harness_id)'
        )
        == 3
    )
    assert "consumeLiveEvent(event)" not in poll_source


def test_ui_native_gemini_streaming_handles_terminal_screen_redraws():
    parser_source = APP_JS[
        APP_JS.index("function geminiStreamingTextFromTerminal") : APP_JS.index(
            "function maybeShowNativeTrustPrompt"
        )
    ]

    for fragment in (
        "if (/^\\s*>\\s+\\S/.test(lines[index])) promptIndex = index;",
        "if (/^\\s*✦(?:\\s|$)/.test(lines[index])) {",
    ):
        assert fragment in parser_source
    for fragment in (
        'raw.includes("\\x1B[2J")',
        'raw.includes("\\x1B[3J")',
        "return updateNativeStreamingFromTerminal();",
    ):
        assert fragment in APP_JS


def test_ui_static_routes_codex_work_through_structured_chat():
    run_source = UI_SOURCE[
        UI_SOURCE.index("async function runHarness") : UI_SOURCE.index(
            "async function loadArenaCenter"
        )
    ]
    team_source = UI_SOURCE[
        UI_SOURCE.index("async function loadWorkAgentTeam") : UI_SOURCE.index(
            "async function loadRunsTrace"
        )
    ]
    controls_source = UI_SOURCE[
        UI_SOURCE.index("function usesStructuredWorkChat") : UI_SOURCE.index(
            "async function loadSessions"
        )
    ]
    terminal_source = UI_SOURCE[
        UI_SOURCE.index("function setActiveNativeProcess") : UI_SOURCE.index(
            "function renderEvents"
        )
    ]

    assert "retireLegacyNativeProcessForStructuredChat" in run_source
    assert 'run.invocation_mode === "native"' in team_source
    assert 'selected.id === "codex-cli"' in controls_source
    assert 'invocation.value = "headless";' in controls_source
    assert 'byId("stream-checkbox").checked = true' in controls_source
    assert "nativeTab.hidden = structuredWorkChat" in controls_source
    assert '? "Send"' in controls_source
    assert "function legacyNativeProcessForStructuredChat" in UI_SOURCE
    assert "async function retireLegacyNativeProcessForStructuredChat" in UI_SOURCE
    assert 'method: "DELETE"' in UI_SOURCE
    assert "function nativeChatTranscriptNode()" not in UI_SOURCE
    assert 'output.className = "native-chat-output";' not in UI_SOURCE
    assert "NATIVE_ACTIVE_POLL_MS" in terminal_source
    assert "NATIVE_IDLE_POLL_MS" in terminal_source
    assert "scheduleNativePoll" in terminal_source
    assert "setInterval(pollNativeOutput" not in terminal_source
    assert "native-terminal-input" not in INDEX_HTML
    assert "send-native-input-button" not in INDEX_HTML
    assert "Technical terminal output" in INDEX_HTML


def test_ui_static_keeps_advanced_panel_above_chat_and_closes_it_for_runs():
    run_source = UI_SOURCE[
        UI_SOURCE.index("async function runHarness") : UI_SOURCE.index(
            "async function runArena"
        )
    ]
    config_css = UI_SOURCE[
        UI_SOURCE.index(".config-section {") : UI_SOURCE.index(".workspace-welcome {")
    ]

    assert "function setAdvancedSettings(open)" in UI_SOURCE
    assert "setAdvancedSettings(false);" in run_source
    assert "await startHeadlessStream(payload);" in run_source
    assert "position: relative;" in config_css
    assert "z-index: 30;" in config_css


def test_ui_static_keeps_arena_out_of_the_work_surface():
    work_source = UI_SOURCE[
        UI_SOURCE.index('<section class="center"') : UI_SOURCE.index(
            '<section id="arena-center"'
        )
    ]
    arena_source = UI_SOURCE[
        UI_SOURCE.index('<section id="arena-center"') : UI_SOURCE.index(
            '<section id="agents-center"'
        )
    ]

    assert 'id="arena-harness-options"' not in work_source
    assert 'id="arena-compare-button"' not in work_source
    assert 'id="arena-harness-options"' in arena_source
    assert 'id="arena-compare-button"' in arena_source
    assert 'id="arena-panel"' in arena_source
    assert 'data-tab="arena"' not in UI_SOURCE


def test_ui_static_arena_formats_use_clickable_checkbox_rows():
    for fragment in (
        'arenaCheckbox.type = "checkbox"',
        'arenaCheckbox.name = "arena-harness"',
        'option.classList.toggle("selected", checkbox.checked)',
        'id="arena-selection-count"',
        'id="arena-select-all-button"',
        'id="arena-clear-button"',
        "function selectAllArenaHarnesses(selected)",
    ):
        assert fragment in UI_SOURCE
    assert 'multiple size="6"' not in UI_SOURCE


def test_ui_static_restores_arena_without_replacing_work_session():
    arena_source = UI_SOURCE[
        UI_SOURCE.index("async function runArena") : UI_SOURCE.index(
            "async function startHeadlessStream"
        )
    ]
    load_session_source = UI_SOURCE[
        UI_SOURCE.index("async function loadSession") : UI_SOURCE.index(
            "async function loadAttachments"
        )
    ]
    clear_route_source = UI_SOURCE[
        UI_SOURCE.index("function clearRouteSelection") : UI_SOURCE.index(
            "async function applyCurrentRoute"
        )
    ]
    route_source = UI_SOURCE[
        UI_SOURCE.index("async function loadCurrentRoute") : UI_SOURCE.index(
            "async function boot"
        )
    ]

    for fragment in (
        "async function loadArenaCenter(options = {})",
        "getJson(`/api/arena/runs?${params.toString()}`)",
        "function applyArenaToControls(arena)",
        "function scheduleArenaRefresh(arena)",
        "state.currentArena = body.arena;",
        "updateArenaStatus(state.currentArena);",
    ):
        assert fragment in UI_SOURCE
    assert "state.currentSessionId = body.arena.session_id" not in arena_source
    assert "await loadSession" not in arena_source
    assert "state.currentArena = null" not in load_session_source
    assert "state.currentArena = null" not in clear_route_source
    assert (
        "return loadArenaCenter({ hydrateControls: !state.currentArena });"
        in route_source
    )


def test_ui_static_preserves_selected_defaults_while_stream_starts():
    start_source = UI_SOURCE[
        UI_SOURCE.index("async function startHeadlessStream") : UI_SOURCE.index(
            "function openHeadlessEventStream"
        )
    ]

    assert "function applyRunDefaults(payload)" in UI_SOURCE
    assert "await loadSession(state.currentSessionId);" in start_source
    assert "applyRunDefaults(payload);" in start_source
    assert start_source.index(
        "await loadSession(state.currentSessionId);"
    ) < start_source.index("applyRunDefaults(payload);")


def test_ui_static_renders_fifo_queue_beside_composer():
    queue_source = UI_SOURCE[
        UI_SOURCE.index("function queuedHeadlessTurns") : UI_SOURCE.index(
            "function latestEventIdForRun"
        )
    ]
    mobile_rule = APP_CSS.split("@media (max-width: 720px)", 1)[1]

    assert 'run.status === "queued"' in queue_source
    assert 'message.role === "user"' in queue_source
    assert 'position.textContent = turns.length === 1 ? "Queued"' in queue_source
    assert "Waiting for the current turn to finish" in queue_source
    assert "Waiting behind earlier queued messages" in queue_source
    assert 'byId("composer-queue")' in queue_source
    assert ".composer-queue {" in APP_CSS
    assert "position: absolute;" in APP_CSS
    assert ".composer-queue {\n        position: static;" in mobile_rule


def test_ui_static_command_previews_describe_streaming_honestly():
    command_source = UI_SOURCE[
        UI_SOURCE.index("function commandPreview") : UI_SOURCE.index(
            "function curlPreview"
        )
    ]
    curl_source = UI_SOURCE[
        UI_SOURCE.index("function curlPreview") : UI_SOURCE.index(
            "async function copyText"
        )
    ]

    assert "giga harness run has no --stream flag" in command_source
    assert 'args.push("--stream")' not in command_source
    assert 'payload.stream ? "curl -sS -N" : "curl -sS"' in curl_source
    assert 'shellQuote("Accept: text/event-stream")' in curl_source
    assert "stream: Boolean(payload.stream)" in curl_source


def test_ui_models_rejects_invalid_api_mode_non_fatally():
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/models?api_mode=v3")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["source"] == "fallback"
    assert body["models"][0] == "ConfiguredModel"
    assert "api_mode" in body["error"]


def test_ui_models_handles_discovery_exception_safely(monkeypatch):
    def fail_discovery(config, mode, **kwargs):
        raise RuntimeError("super-secret discovery failure")

    monkeypatch.setattr(proxy, "discover_models", fail_discovery)
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/models?api_mode=v2")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["source"] == "/v2/models"
    assert body["models"] == []
    assert body["error"] == "model discovery failed"
    assert "super-secret" not in str(body)


def test_ui_models_uses_selected_versioned_endpoint_only(monkeypatch):
    captured = {}

    def fake_discovery(config, mode, **kwargs):
        captured["mode"] = mode
        captured["kwargs"] = kwargs
        return proxy.ModelDiscovery(
            ok=True,
            models=("v1-only-model",),
            source=f"/{mode.value}/models",
        )

    monkeypatch.setattr(proxy, "discover_models", fake_discovery)
    app = create_app(
        HarnessConfig(default_model="ConfiguredModel"),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/api/models?api_mode=v1")

    assert response.status_code == 200
    body = response.json()
    assert body["models"] == ["v1-only-model"]
    assert body["source"] == "/v1/models"
    assert captured["mode"].value == "v1"
    assert captured["kwargs"] == {
        "include_compat_paths": False,
        "include_fallback": False,
    }


def test_ui_route_recommendation_endpoint_returns_safe_response():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/route/recommendation",
        json={
            "prompt": "Explain this screenshot",
            "mode": "read",
            "attachments": [
                {
                    "kind": "image",
                    "filename": "secret-token-screen.png",
                    "mime_type": "image/png",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()["recommendation"]
    assert body["harness_id"] == "direct-chat"
    assert body["mode"] == "read"
    assert body["invocation_mode"] == "headless"
    assert "secret-token-screen.png" not in response.text


def test_ui_can_run_echo_harness():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={"harness_id": "echo", "prompt": "hello", "api_mode": "v2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["text"] == "hello"


def test_ui_run_passes_stream_and_dry_run_extra():
    harness = _CaptureRequestHarness()
    registry = HarnessRegistry()
    registry.register(harness)
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "capture-run",
            "prompt": "hello",
            "model": "GigaChat-2-Max",
            "api_mode": "v1",
            "capability": "chat_completions",
            "mode": "read",
            "stream": True,
            "dry_run": True,
            "extra": {"custom": "value"},
        },
    )

    assert response.status_code == 200
    assert harness.last_request is not None
    assert harness.last_request.prompt == "hello"
    assert harness.last_request.model == "GigaChat-2-Max"
    assert harness.last_request.api_mode.value == "v1"
    assert harness.last_request.capability.value == "chat_completions"
    assert harness.last_request.mode == "read"
    assert harness.last_request.stream is True
    assert harness.last_request.extra == {"custom": "value", "dry_run": True}


def test_ui_run_passes_explicit_extra_mapping():
    harness = _CaptureRequestHarness()
    registry = HarnessRegistry()
    registry.register(harness)
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "capture-run",
            "prompt": "hello",
            "extra": {"temperature": 0, "dry_run": False},
        },
    )

    assert response.status_code == 200
    assert harness.last_request is not None
    assert harness.last_request.extra == {"temperature": 0, "dry_run": False}


def test_ui_run_maps_v2_builtin_tools_into_direct_chat_payload():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "direct-chat",
            "prompt": "search and calculate",
            "api_mode": "v2",
            "builtin_tools": ["web_search", "code_interpreter"],
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["raw"]["payload"]["tools"] == [
        {"type": "web_search"},
        {"type": "code_interpreter"},
    ]


def test_ui_run_rejects_builtin_tools_outside_supported_v2_harness():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    v1_response = client.post(
        "/api/run",
        json={
            "harness_id": "direct-chat",
            "prompt": "search",
            "api_mode": "v1",
            "builtin_tools": ["web_search"],
        },
    )
    unsupported_response = client.post(
        "/api/run",
        json={
            "harness_id": "echo",
            "prompt": "search",
            "api_mode": "v2",
            "builtin_tools": ["web_search"],
        },
    )

    assert v1_response.status_code == 400
    assert "/v2/chat/completions" in v1_response.json()["detail"]
    assert unsupported_response.status_code == 400
    assert "does not support built-in tools" in unsupported_response.json()["detail"]


def test_ui_run_rejects_invalid_api_mode_with_400():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={"harness_id": "echo", "prompt": "hello", "api_mode": "v3"},
    )

    assert response.status_code == 400
    assert "api_mode" in response.json()["detail"]


def test_ui_run_rejects_invalid_capability_with_400():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "echo",
            "prompt": "hello",
            "capability": "bad_capability",
        },
    )

    assert response.status_code == 400
    assert "capability" in response.json()["detail"].lower()


def test_ui_run_blocks_private_key_prompt_without_echoing_secret():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)
    prompt = "-----BEGIN PRIVATE KEY-----\nnot-real-secret\n-----END PRIVATE KEY-----"

    response = client.post(
        "/api/run",
        json={"harness_id": "echo", "prompt": prompt},
    )

    assert response.status_code == 400
    assert "Preflight blocked" in response.json()["detail"]
    assert "not-real-secret" not in response.text


def test_ui_run_unknown_harness_returns_404():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={"harness_id": "missing-harness", "prompt": "hello"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown harness"


def test_ui_run_unexpected_error_uses_safe_body():
    registry = HarnessRegistry()
    registry.register(_ExplodingHarness())
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/run",
        json={"harness_id": "explode", "prompt": "hello"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Harness run failed"
    assert "secret" not in response.text


def test_ui_run_resolves_workspace(tmp_path):
    registry = HarnessRegistry()
    registry.register(_WorkspaceCaptureHarness())
    app = create_app(HarnessConfig(), registry=registry)
    client = TestClient(app)

    response = client.post(
        "/api/run",
        json={
            "harness_id": "capture-workspace",
            "prompt": "hello",
            "workspace": str(tmp_path),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["raw"]["workspace"] == str(tmp_path.resolve())


def test_ui_index_contains_control_panel_elements():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    source = "\n".join(
        (
            html,
            client.get("/assets/app.css").text,
            client.get("/assets/app.js").text,
        )
    )
    for element_id in (
        "new-chat-button",
        "session-list",
        "session-search",
        "session-workspace-filter",
        "session-harness-filter",
        "include-archived-checkbox",
        "project-status",
        "project-name",
        "project-meta",
        "init-project-button",
        "current-model-badge",
        "current-route-badge",
        "harness-list",
        "harness-select",
        "arena-harness-options",
        "arena-selection-count",
        "arena-select-all-button",
        "arena-clear-button",
        "invocation-select",
        "model-input",
        "model-menu-button",
        "model-list",
        "api-mode-v2",
        "api-mode-v1",
        "capability-select",
        "mode-select",
        "workspace-policy-select",
        "permission-profile-select",
        "workspace-input",
        "dry-run-checkbox",
        "stream-checkbox",
        "composer",
        "composer-queue",
        "prompt-input",
        "attachment-file-input",
        "attach-file-button",
        "attachment-status",
        "attachment-list",
        "workspace-file-menu",
        "sync-native-button",
        "open-native-history-button",
        "native-all-workspaces-checkbox",
        "native-count",
        "native-status",
        "native-history-modal",
        "native-modal-status",
        "native-page-status",
        "native-session-list",
        "load-more-native-button",
        "close-native-history-button",
        "preflight-modal",
        "preflight-status",
        "preflight-finding-list",
        "preflight-budget",
        "preflight-footer-status",
        "continue-preflight-button",
        "close-preflight-button",
        "native-terminal-status",
        "native-trust-prompt",
        "native-trust-title",
        "native-trust-workspace",
        "native-trust-status",
        "native-trust-yes-button",
        "native-trust-no-button",
        "native-process-summary",
        "native-terminal-output",
        "poll-native-output-button",
        "stop-native-process-button",
        "clear-native-terminal-button",
        "run-button",
        "interrupt-run-button",
        "arena-nav-link",
        "arena-center",
        "arena-prompt-input",
        "arena-model-input",
        "arena-api-mode-select",
        "arena-mode-select",
        "arena-workspace-policy-select",
        "arena-workspace-input",
        "approvals-nav-link",
        "scheduled-nav-link",
        "attention-count",
        "scheduled-center",
        "schedule-list",
        "schedule-calendar",
        "schedule-history",
        "attention-list",
        "schedule-wizard",
        "approval-attention-count",
        "approvals-center",
        "approvals-list",
        "refresh-approvals-button",
        "arena-compare-button",
        "cancel-run-button",
        "copy-cli-button",
        "copy-curl-button",
        "reset-button",
        "proxy-status",
        "model-status",
        "harness-details",
        "route-recommendation",
        "route-recommendation-badge",
        "route-recommendation-reasons",
        "apply-route-recommendation-button",
        "preset-status",
        "preset-list",
        "output-panel",
        "run-panel",
        "arena-panel",
        "events-panel",
        "raw-request-panel",
        "raw-response-panel",
        "command-panel",
        "diff-panel",
        "diff-text",
        "apply-branch-input",
        "apply-run-diff-button",
        "discard-run-worktree-button",
        "open-run-worktree-button",
        "open-run-terminal-button",
        "pr-panel",
        "pr-text",
        "pr-branch-input",
        "copy-pr-title-button",
        "copy-pr-body-button",
        "copy-pr-patch-button",
        "create-pr-branch-button",
        "provenance-panel",
        "provenance-text",
        "refresh-provenance-button",
        "replay-run-button",
        "fork-run-button",
        "editor-panel",
        "open-editor-workspace-button",
        "open-editor-run-button",
        "open-editor-diff-button",
        "open-editor-terminal-button",
        "open-editor-file-input",
        "open-editor-file-button",
        "copy-session-open-command-button",
        "copy-run-open-command-button",
        "editor-text",
        "attachments-panel",
        "memory-panel",
        "memory-status",
        "memory-input",
        "memory-tags-input",
        "add-memory-button",
        "remember-message-button",
        "memory-list",
        "tools-panel",
        "builtin-tools-control",
        "tools-status",
        "tool-profile-list",
        "tool-sync-preview",
        "tools-nav-link",
        "tools-center",
        "tools-center-status",
        "refresh-tools-center-button",
        "tools-center-list",
        "agents-nav-link",
        "agents-center",
        "agents-center-list",
        "agent-source-input",
        "validate-agent-button",
        "apply-agent-button",
        "duplicate-agent-button",
        "run-agent-button",
        "evals-panel",
        "evals-status",
        "refresh-evals-button",
        "run-eval-button",
        "eval-spec-select",
        "eval-harness-input",
        "eval-spec-list",
        "eval-scorecard",
        "evaluate-nav-link",
        "evaluate-center",
        "protocol-matrix",
        "quality-matrix",
        "evaluate-runs",
        "run-evaluate-button",
        "cancel-evaluate-button",
        "pin-evaluate-baseline-button",
        "native-panel",
        "storage-panel",
        "advanced-settings-button",
        "details-toggle-button",
        "close-inspector-button",
        "session-drawer-button",
    ):
        assert element_id in source
    assert ">Stop</button>" in html
    assert ">Interrupt</button>" in html
    assert 'byId("run-button").textContent = "Queue"' in source
    for text in (
        "+ New session",
        "/api/project",
        "/api/project/state",
        "project_id",
        "gpt2giga Harness",
        "What do you want to work on?",
        "Advanced",
        "Run details",
        "Native sessions",
        "Sync native history",
        "Browse history",
        "Show all workspaces",
        "Native history unavailable",
        "Load 5 more",
        "Showing 0 of 0",
        "Preview",
        "Import",
        "Link to current chat",
        "Resume native",
        "Terminal output will appear here",
        "Do you trust the contents of this directory?",
        "Yes, continue",
        "No, quit",
        "Technical terminal output",
        "Stop process",
        "Arena",
        "Compare",
        "Recommended",
        "Apply recommendation",
        "/api/route/recommendation",
        "Presets",
        "/api/project/presets",
        "applyPreset",
        "Attachments",
        "Memory",
        "Project memory",
        "Remember last message",
        "Add memory",
        "/api/project/memory",
        "projectMemory",
        "loadMemory",
        "Tools",
        "discovery only",
        "/api/tool-servers",
        "probeToolServer",
        "/api/tools",
        "/api/tools/sync",
        "toolProfiles",
        "syncTools",
        "Evals",
        "Refresh evals",
        "Run eval",
        "/api/evals",
        "evalSpecs",
        "runSelectedEval",
        "eval-scorecard",
        "Eval Lab",
        "Protocol conformance",
        "Harness quality",
        "/api/evaluate",
        "runEvaluateMatrix",
        "pinEvaluateBaseline",
        "Editor",
        "/api/editor/open-workspace",
        "/api/editor/open-file",
        "/api/editor/open-diff",
        "/api/editor/open-terminal",
        "openEditorDiff",
        "openRunTerminal",
        "copyRunOpenCommand",
        "Storage",
        "Preflight",
        "Continue anyway",
        "Checking run context",
        "/api/preflight/run",
        "confirmRunPreflight",
        "Exclude file",
        "Send path only",
        "Attach",
        "Cancel",
        "EventSource",
        "/api/arena/runs",
        "/events/stream",
        "/cancel",
        "/diff",
        "/apply",
        "/discard",
        "/api/editor/open-workspace",
        "Workspace policy",
        "workspace_policy",
        "Apply",
        "Discard",
        "Open worktree",
        "Open terminal",
        "Copy title",
        "Copy body",
        "Copy patch",
        "Create branch",
        "Choose patch",
        "Review / apply",
        "Discard worktree",
        "Provenance",
        "Refresh provenance",
        "Replay",
        "Fork chat",
        "/provenance",
        "/replay",
        "/fork",
        "refreshRunProvenance",
        "replayCurrentRun",
        "forkCurrentRun",
        "/branch",
        'id="apply-run-diff-button" type="button" disabled',
        'id="discard-run-worktree-button" class="danger" type="button" disabled',
        'id="open-run-worktree-button" class="secondary" type="button" disabled',
        "attachment_ids",
        "data_base64",
        "/api/workspace/tree",
        "/attachments/workspace",
        "/attachments",
        "dragover",
        "clipboardData",
        "persistProjectState",
    ):
        assert text in source


def test_ui_native_submit_sends_a_per_submission_prompt_idempotency_key():
    assert "const promptIdempotencyKey" in APP_JS
    assert "native_prompt_${window.crypto.randomUUID()}" in APP_JS
    assert "idempotency_key: promptIdempotencyKey" in APP_JS
    assert "workspace_policy: payload.workspace_policy" in APP_JS
    assert "permission_profile: payload.permission_profile" in APP_JS
    assert "pendingNativeApproval" in APP_JS


def test_ui_mobile_advanced_panel_uses_viewport_containing_block():
    mobile_rule = APP_CSS.split("@media (max-width: 720px)", 1)[1]

    assert ".quick-config.advanced-open" in mobile_rule
    assert "backdrop-filter: none;" in mobile_rule
    assert "z-index: 81;" in mobile_rule
    assert "position: fixed;" in mobile_rule


def test_ui_rejects_remote_bind_without_allow_remote():
    with pytest.raises(ValueError):
        validate_ui_bind("0.0.0.0", allow_remote=False)


def test_ui_allows_remote_bind_with_explicit_flag():
    validate_ui_bind("0.0.0.0", allow_remote=True)


def test_ui_rejects_non_loopback_hostname_without_explicit_flag():
    with pytest.raises(ValueError, match="harness.example"):
        validate_ui_bind("harness.example", allow_remote=False)


class _WorkspaceCaptureHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture-workspace",
            title="Capture Workspace",
            kind="test",
            description="Capture workspace for UI tests",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_workspace=True,
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(
            ok=True,
            text="ok",
            raw={"workspace": request.workspace},
        )


class _CaptureRequestHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture-run",
            title="Capture Run",
            kind="test",
            description="Capture request for UI tests",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(ok=True, text="ok")


class _SchemaPluginHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="schema-plugin",
            title="Schema Plugin",
            kind="custom",
            description="Schema-backed plugin harness",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            icon="plug",
            config_schema={
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "title": "Endpoint",
                    }
                },
            },
            metadata={"package": "schema-plugin"},
        )

    def availability(self) -> Availability:
        return Availability.available("schema plugin")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)


class _ExplodingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="explode",
            title="Explode",
            kind="test",
            description="Raise for UI tests",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        raise RuntimeError("secret traceback")
