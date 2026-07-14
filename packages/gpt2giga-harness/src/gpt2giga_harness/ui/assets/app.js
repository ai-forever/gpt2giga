    const NATIVE_SESSION_PAGE_SIZE = 5;
    const NATIVE_TERMINAL_CHAR_LIMIT = 50000;
    const NATIVE_ACTIVE_POLL_MS = 750;
    const NATIVE_IDLE_POLL_MS = 5000;
    const NATIVE_POLL_BURST_MS = 12000;
    const NATIVE_STREAM_FAILURE_LIMIT = 3;
    const NATIVE_RESIZE_DELAY_MS = 150;
    const NATIVE_MIN_ROWS = 2;
    const NATIVE_MAX_ROWS = 200;
    const NATIVE_MIN_COLUMNS = 20;
    const NATIVE_MAX_COLUMNS = 500;
    const NATIVE_TRUST_STORAGE_KEY = "gpt2giga.nativeTrustResolved.v1";
    const RUNS_CENTER_PAGE_SIZE = 25;
    const RUNS_TRACE_DOM_LIMIT = 200;
    const state = {
      defaults: {},
      harnesses: [],
      sessions: [],
      models: [],
      modelSource: "",
      project: null,
      projectConfig: null,
      projectState: null,
      projectPresets: [],
      projectMemory: [],
      memoryError: null,
      toolProfiles: [],
      toolServers: [],
      toolServerErrors: [],
      managedToolConfigPlan: null,
      agents: [],
      agentErrors: [],
      selectedAgent: null,
      agentDraft: null,
      workflows: [],
      workflowErrors: [],
      workflowTemplates: [],
      promotionDraft: null,
      selectedWorkflow: null,
      toolSyncPreview: null,
      toolError: null,
      evalSpecs: [],
      evalRuns: [],
      evalErrors: [],
      currentEvalRun: null,
      evalError: null,
      evaluateProtocolMatrix: [],
      evaluateQualitySpecs: [],
      evaluateRuns: [],
      evaluateSelectedRun: null,
      applyingProjectState: false,
      selectedHarness: null,
      arenaSelectionTouched: false,
      nativeSessions: [],
      nativeVisibleLimit: NATIVE_SESSION_PAGE_SIZE,
      nativeModalOpen: false,
      preflightModalOpen: false,
      preflightDecisionResolver: null,
      pendingPreflight: null,
      pendingPreflightPayload: null,
      selectedNativeRefId: null,
      nativePreview: null,
      activeNativeProcess: null,
      pendingNativeApproval: null,
      nativeOutputCursor: 0,
      nativeTerminalText: "",
      nativeStreamingActive: false,
      nativeStreamingText: "",
      nativePollTimer: null,
      nativePollBurstUntil: 0,
      nativeEventSource: null,
      nativeEventSourceProcessId: null,
      nativeStreamFailures: 0,
      nativeResizeObserver: null,
      nativeResizeTimer: null,
      nativeTerminalSize: null,
      nativeTrustPromptProcessId: null,
      nativeTrustResolvedProcessIds: readNativeTrustResolvedProcessIds(),
      attachments: [],
      fileMentionQuery: null,
      currentSessionId: null,
      selectedRunId: null,
      currentBundle: null,
      currentArena: null,
      arenaPollTimer: null,
      activeHeadlessRun: null,
      headlessEventSource: null,
      headlessEventSourceRunId: null,
      runsCenterItems: [],
      runsCenterCursor: null,
      runsCenterStatus: "",
      runsCenterSelected: null,
      runsTraceNodes: [],
      runsTraceCursor: null,
      runsEventSource: null,
      runsEventSourceRunId: null,
      approvals: [],
      approvalsStatus: "pending",
      schedules: [],
      scheduleHistory: [],
      scheduleWorker: {},
      attentionItems: [],
      scheduledView: "list",
      selectedScheduleId: null,
      notifiedAttentionIds: new Set(),
      desktopNotificationsEnabled: false,
      liveRuns: new Map(),
      toolCallExpansion: new Map(),
      renderedSessionId: null,
      routeRecommendation: null,
      routeRecommendationTimer: null,
      routeLoadKey: null,
      routeLoadPromise: null,
      routeLoadedKey: null,
      lastPayload: null,
      eventsBound: false
    };

    const byId = (id) => document.getElementById(id);
    const pretty = (value) => JSON.stringify(value || {}, null, 2);
    const setText = (id, value) => {
      const node = byId(id);
      if (node) node.textContent = value == null ? "" : String(value);
    };

    function readNativeTrustResolvedProcessIds() {
      try {
        const values = JSON.parse(window.sessionStorage.getItem(NATIVE_TRUST_STORAGE_KEY) || "[]");
        return new Set(Array.isArray(values) ? values.filter((value) => typeof value === "string").slice(-100) : []);
      } catch (error) {
        return new Set();
      }
    }

    function rememberNativeTrustDecision(processId) {
      state.nativeTrustResolvedProcessIds.add(processId);
      try {
        const values = [...state.nativeTrustResolvedProcessIds].slice(-100);
        window.sessionStorage.setItem(NATIVE_TRUST_STORAGE_KEY, JSON.stringify(values));
      } catch (error) {
        // Native input still succeeds when browser storage is unavailable.
      }
    }

    async function getJson(url, options) {
      const response = await fetch(url, options);
      let data = {};
      try {
        data = await response.json();
      } catch (error) {
        data = { detail: "non-JSON response" };
      }
      return { ok: response.ok, status: response.status, data };
    }

    async function loadDefaults() {
      const result = await getJson("/api/defaults");
      if (!result.ok) return result;
      state.defaults = result.data;
      byId("model-input").value = result.data.default_model || "GigaChat-2-Max";
      byId("arena-model-input").value = result.data.default_model || "GigaChat-2-Max";
      const mode = result.data.default_api_mode || "v2";
      byId(`api-mode-${mode}`).checked = true;
      byId("arena-api-mode-select").value = mode;
      updateRouteNote();
      updateHeaderBadges();
      if (result.data.note) setText("model-status", result.data.note);
      return result;
    }

    function currentRoute() {
      const path = window.location.pathname.replace(/\/+$/, "") || "/";
      if (path === "/") return { area: "legacy", id: null };
      if (path === "/work") return { area: "work", id: null };
      if (path === "/arena") return { area: "arena", id: null };
      if (path === "/runs") return { area: "runs", id: null };
      if (path === "/agents") return { area: "agents", id: null };
      if (path === "/workflows") return { area: "workflows", id: null };
      if (path === "/evaluate") return { area: "evaluate", id: null };
      if (path === "/scheduled") return { area: "scheduled", id: null };
      if (path === "/approvals") return { area: "approvals", id: null };
      if (path === "/tools") return { area: "tools", id: null };
      const work = path.match(/^\/work\/([^/]+)$/);
      const runs = path.match(/^\/runs\/([^/]+)$/);
      const workflows = path.match(/^\/workflows\/([^/]+)$/);
      const scheduled = path.match(/^\/scheduled\/([^/]+)$/);
      try {
        if (work) return { area: "work", id: decodeURIComponent(work[1]) };
        if (runs) return { area: "runs", id: decodeURIComponent(runs[1]) };
        if (workflows) return { area: "workflows", id: decodeURIComponent(workflows[1]) };
        if (scheduled) return { area: "scheduled", id: decodeURIComponent(scheduled[1]) };
      } catch (error) {
        return { area: "invalid", id: null };
      }
      return { area: "invalid", id: null };
    }

    function syncBrowserRoute(area, id, replace = false) {
      const suffix = id ? `/${encodeURIComponent(id)}` : "";
      const path = `/${area}${suffix}`;
      if (window.location.pathname !== path) {
        window.history[replace ? "replaceState" : "pushState"]({}, "", path);
      }
      syncNavigation();
    }

    function syncNavigation() {
      const route = currentRoute();
      const workLink = byId("work-nav-link");
      const arenaLink = byId("arena-nav-link");
      const runsLink = byId("runs-nav-link");
      const approvalsLink = byId("approvals-nav-link");
      const toolsLink = byId("tools-nav-link");
      const agentsLink = byId("agents-nav-link");
      const workflowsLink = byId("workflows-nav-link");
      const evaluateLink = byId("evaluate-nav-link");
      const scheduledLink = byId("scheduled-nav-link");
      workLink.classList.toggle("active", route.area === "work" || route.area === "legacy");
      arenaLink.classList.toggle("active", route.area === "arena");
      runsLink.classList.toggle("active", route.area === "runs");
      approvalsLink.classList.toggle("active", route.area === "approvals");
      toolsLink.classList.toggle("active", route.area === "tools");
      agentsLink.classList.toggle("active", route.area === "agents");
      workflowsLink.classList.toggle("active", route.area === "workflows");
      evaluateLink.classList.toggle("active", route.area === "evaluate");
      scheduledLink.classList.toggle("active", route.area === "scheduled");
      const activeNavLink = document.querySelector(".primary-nav-link.active");
      const primaryNav = activeNavLink && activeNavLink.parentElement;
      if (activeNavLink && primaryNav && window.innerWidth <= 700) {
        const navRect = primaryNav.getBoundingClientRect();
        const activeRect = activeNavLink.getBoundingClientRect();
        primaryNav.scrollLeft += activeRect.left - navRect.left - (navRect.width - activeRect.width) / 2;
      }
      workLink.href = state.currentSessionId ? `/work/${encodeURIComponent(state.currentSessionId)}` : "/work";
      const run = currentRun();
      runsLink.href = run && run.id ? `/runs/${encodeURIComponent(run.id)}` : "/runs";
      const arenaArea = route.area === "arena";
      const runsArea = route.area === "runs";
      const approvalsArea = route.area === "approvals";
      const toolsArea = route.area === "tools";
      const agentsArea = route.area === "agents";
      const workflowsArea = route.area === "workflows";
      const evaluateArea = route.area === "evaluate";
      const scheduledArea = route.area === "scheduled";
      document.body.classList.toggle("arena-area", arenaArea);
      if (!arenaArea) stopArenaRefresh();
      document.body.classList.toggle("runs-area", runsArea);
      document.body.classList.toggle("approvals-area", approvalsArea);
      document.body.classList.toggle("tools-area", toolsArea);
      document.body.classList.toggle("agents-area", agentsArea);
      document.body.classList.toggle("workflows-area", workflowsArea);
      document.body.classList.toggle("evaluate-area", evaluateArea);
      document.body.classList.toggle("scheduled-area", scheduledArea);
      byId("arena-center").hidden = !arenaArea;
      byId("runs-center").hidden = !runsArea;
      byId("approvals-center").hidden = !approvalsArea;
      byId("tools-center").hidden = !toolsArea;
      byId("agents-center").hidden = !agentsArea;
      byId("workflows-center").hidden = !workflowsArea;
      byId("evaluate-center").hidden = !evaluateArea;
      byId("scheduled-center").hidden = !scheduledArea;
    }

    async function loadEvaluateCenter() {
      if (!state.project || !state.project.root) return false;
      setText("evaluate-center-status", "Refreshing compatibility evidence...");
      const result = await getJson(`/api/evaluate?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("evaluate-center-status", result.data.detail || "Eval Lab is unavailable.");
        return false;
      }
      state.evaluateProtocolMatrix = Array.isArray(result.data.protocol_matrix) ? result.data.protocol_matrix : [];
      state.evaluateQualitySpecs = Array.isArray(result.data.quality_specs) ? result.data.quality_specs : [];
      state.evaluateRuns = Array.isArray(result.data.runs) ? result.data.runs : [];
      if (state.evaluateSelectedRun) {
        state.evaluateSelectedRun = state.evaluateRuns.find((item) => item.id === state.evaluateSelectedRun.id) || null;
      }
      renderEvaluateCenter();
      setText("evaluate-center-status", `${state.evaluateQualitySpecs.length} quality specs · ${state.evaluateProtocolMatrix.length} protocol cells`);
      return true;
    }

    function renderEvaluateCenter() {
      const select = byId("evaluate-spec-select");
      const selected = select.value;
      select.textContent = "";
      for (const spec of state.evaluateQualitySpecs) {
        const option = document.createElement("option");
        option.value = spec.name;
        option.textContent = `${spec.name} · ${spec.matrix.length} cells`;
        select.appendChild(option);
      }
      if (selected && state.evaluateQualitySpecs.some((item) => item.name === selected)) select.value = selected;
      byId("run-evaluate-button").disabled = !state.evaluateQualitySpecs.length;
      byId("cancel-evaluate-button").disabled = !state.evaluateSelectedRun || state.evaluateSelectedRun.status !== "running";
      byId("pin-evaluate-baseline-button").disabled = !state.evaluateSelectedRun || !["passed", "failed"].includes(state.evaluateSelectedRun.status);
      renderProtocolMatrix();
      renderQualityMatrix();
      renderEvaluateRuns();
    }

    function renderProtocolMatrix() {
      const root = byId("protocol-matrix");
      root.textContent = "";
      for (const cell of state.evaluateProtocolMatrix) {
        const row = document.createElement("div");
        row.className = "matrix-row";
        const harnesses = Array.isArray(cell.compatible_harness_ids) ? cell.compatible_harness_ids.join(", ") : "";
        row.innerHTML = `<strong>${escapeHtml(cell.fixture_id)}</strong><span>${escapeHtml(cell.api_mode)}</span><span>${escapeHtml(cell.required_capability)}</span><span class="badge ${cell.runnable ? "ok" : "warn"}">${cell.runnable ? escapeHtml(harnesses) : "unsupported"}</span>`;
        root.appendChild(row);
      }
    }

    function renderQualityMatrix() {
      const root = byId("quality-matrix");
      root.textContent = "";
      for (const spec of state.evaluateQualitySpecs) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "matrix-row matrix-action";
        const baseline = spec.baseline ? `baseline ${String(spec.baseline.git_sha || "local").slice(0, 8)}` : "no baseline";
        const dimensions = spec.dimensions || {};
        const agents = Array.isArray(dimensions.agents) ? dimensions.agents.length : 0;
        const workflows = Array.isArray(dimensions.workflow_versions) ? dimensions.workflow_versions.length : 0;
        row.innerHTML = `<strong>${escapeHtml(spec.name)}</strong><span>${spec.case_count} cases</span><span>${spec.matrix.length} cells · ${agents} agents · ${workflows} workflows</span><span class="badge info">${escapeHtml(baseline)}</span>`;
        row.addEventListener("click", () => { byId("evaluate-spec-select").value = spec.name; });
        root.appendChild(row);
      }
    }

    function renderEvaluateRuns() {
      const root = byId("evaluate-runs");
      root.textContent = "";
      for (const run of state.evaluateRuns) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "runs-center-item";
        row.classList.toggle("active", state.evaluateSelectedRun && state.evaluateSelectedRun.id === run.id);
        const summary = run.summary || {};
        const delta = run.baseline_delta && typeof run.baseline_delta.score_delta === "number" ? ` · Δ ${(run.baseline_delta.score_delta * 100).toFixed(1)}pp` : "";
        row.innerHTML = `<span class="runs-center-item-row"><strong>${escapeHtml(run.spec_name)}</strong><span class="badge ${run.status === "passed" ? "ok" : run.status === "running" ? "info" : "warn"}">${escapeHtml(run.status)}</span></span><span class="runs-center-item-meta">${summary.passed || 0}/${summary.total || 0} passed · ${(Number(summary.score || 0) * 100).toFixed(0)}%${escapeHtml(delta)} · ${summary.flakes || 0} flakes</span>`;
        row.addEventListener("click", () => {
          state.evaluateSelectedRun = run;
          byId("cancel-evaluate-button").disabled = run.status !== "running";
          byId("pin-evaluate-baseline-button").disabled = !["passed", "failed"].includes(run.status);
          renderEvaluateRuns();
        });
        row.addEventListener("dblclick", () => {
          const first = Array.isArray(run.results) ? run.results.find((item) => item.run_id) : null;
          if (first) window.location.href = `/runs/${encodeURIComponent(first.run_id)}`;
        });
        root.appendChild(row);
      }
      if (!state.evaluateRuns.length) root.textContent = "No eval runs yet.";
    }

    async function runEvaluateMatrix() {
      const spec = byId("evaluate-spec-select").value;
      if (!spec) return;
      const repetitions = Math.max(1, Math.min(20, Number(byId("evaluate-repetitions").value) || 1));
      byId("run-evaluate-button").disabled = true;
      const result = await getJson(`/api/evals/${encodeURIComponent(spec)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, repetitions })
      });
      if (!result.ok) setText("evaluate-center-status", result.data.detail || "Matrix could not start.");
      await loadEvaluateCenter();
    }

    async function cancelEvaluateRun() {
      if (!state.evaluateSelectedRun) return;
      await getJson(`/api/evaluate/runs/${encodeURIComponent(state.evaluateSelectedRun.id)}/cancel`, { method: "POST" });
      await loadEvaluateCenter();
    }

    async function pinEvaluateBaseline() {
      if (!state.evaluateSelectedRun) return;
      const result = await getJson(`/api/evaluate/runs/${encodeURIComponent(state.evaluateSelectedRun.id)}/baseline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root })
      });
      if (!result.ok) setText("evaluate-center-status", result.data.detail || "Baseline could not be pinned.");
      await loadEvaluateCenter();
    }

    async function loadWorkflowsCenter(selectedId = null) {
      if (!state.project || !state.project.root) return false;
      setText("workflows-center-status", "Refreshing versioned workflows...");
      const result = await getJson(`/api/workflows?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("workflows-center-status", result.data.detail || "Workflow Catalog is unavailable.");
        return false;
      }
      state.workflows = Array.isArray(result.data.workflows) ? result.data.workflows : [];
      state.workflowErrors = Array.isArray(result.data.errors) ? result.data.errors : [];
      state.workflowTemplates = Array.isArray(result.data.templates) ? result.data.templates : [];
      renderWorkflowTemplates();
      renderWorkflowCatalog();
      setText("workflows-center-status", `${state.workflows.length} workflows · YAML history retained locally`);
      if (selectedId) await selectWorkflow(selectedId, false);
      return true;
    }

    function renderWorkflowTemplates() {
      const select = byId("workflow-template-select");
      select.textContent = "";
      for (const template of state.workflowTemplates) {
        const option = document.createElement("option");
        option.value = template.id;
        option.textContent = template.title;
        select.appendChild(option);
      }
    }

    function renderWorkflowCatalog() {
      const list = byId("workflows-center-list");
      const errors = byId("workflows-center-errors");
      list.textContent = "";
      errors.textContent = "";
      for (const error of state.workflowErrors) {
        const row = document.createElement("div");
        row.className = "warning";
        row.textContent = `${error.path}: ${error.error}`;
        errors.appendChild(row);
      }
      for (const workflow of state.workflows) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "agent-card";
        card.classList.toggle("active", state.selectedWorkflow && state.selectedWorkflow.workflow.id === workflow.id);
        card.innerHTML = `<span><strong>${escapeHtml(workflow.title)}</strong><small>${escapeHtml(workflow.description || "Versioned workflow")}</small></span><span class="badge info">v${escapeHtml(workflow.version)}</span><span class="runs-center-item-meta">${workflow.steps.length} steps · ${escapeHtml(String(workflow.source_hash || "").slice(0, 12))}</span>`;
        card.addEventListener("click", () => selectWorkflow(workflow.id));
        list.appendChild(card);
      }
      if (!state.workflows.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No workflows found. Choose a template or import YAML.";
        list.appendChild(empty);
      }
    }

    async function selectWorkflow(workflowId, syncRoute = true) {
      const result = await getJson(`/api/workflows/${encodeURIComponent(workflowId)}?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("workflows-center-status", result.data.detail || "Workflow could not be loaded.");
        return;
      }
      state.selectedWorkflow = result.data;
      const workflow = result.data.workflow;
      byId("workflow-title-input").value = workflow.title || "";
      byId("workflow-version-input").value = workflow.version || "";
      byId("workflow-description-input").value = workflow.description || "";
      byId("workflow-source-input").value = result.data.source || "";
      for (const id of ["workflow-title-input", "workflow-version-input", "workflow-description-input", "workflow-source-input", "validate-workflow-button", "save-workflow-button", "duplicate-workflow-button", "add-workflow-step-button"]) byId(id).disabled = false;
      byId("export-workflow-link").href = `/api/workflows/${encodeURIComponent(workflow.id)}/export?workspace=${encodeURIComponent(state.project.root)}`;
      byId("export-workflow-link").setAttribute("aria-disabled", "false");
      setText("workflow-editor-title", workflow.title);
      setText("workflow-editor-meta", `${workflow.id} · ${workflow.source_path} · ${String(workflow.source_hash || "").slice(0, 12)}`);
      renderWorkflowSteps(workflow.steps || []);
      renderWorkflowDag(result.data.plan || {});
      renderWorkflowHistory(result.data.history || []);
      renderWorkflowCatalog();
      if (syncRoute) syncBrowserRoute("workflows", workflow.id);
    }

    function renderWorkflowSteps(steps) {
      const builder = byId("workflow-step-builder");
      builder.textContent = "";
      for (const step of steps) addWorkflowStepRow(step);
    }

    function addWorkflowStepRow(step = {}) {
      const row = document.createElement("div");
      row.className = "workflow-step-row";
      const kinds = ["agent", "arena", "eval", "approval", "transform", "join"];
      row.innerHTML = `<label>Id<input data-step-field="id" value="${escapeHtml(step.id || "step")}"></label><label>Kind<select data-step-field="kind">${kinds.map((kind) => `<option value="${kind}"${kind === step.kind ? " selected" : ""}>${kind}</option>`).join("")}</select></label><label>Depends on<input data-step-field="depends_on" value="${escapeHtml((step.depends_on || []).join(", "))}" placeholder="step ids"></label><label>Agent / target<input data-step-field="target" value="${escapeHtml(step.agent_id || step.eval_id || step.transform || step.action || "")}"></label><button class="danger" type="button" data-remove-step>Remove</button>`;
      row.querySelector("[data-remove-step]").addEventListener("click", () => row.remove());
      byId("workflow-step-builder").appendChild(row);
    }

    function workflowFormPayload() {
      const original = state.selectedWorkflow.workflow;
      const originalById = new Map((original.steps || []).map((step) => [step.id, step]));
      const steps = [...byId("workflow-step-builder").querySelectorAll(".workflow-step-row")].map((row) => {
        const id = row.querySelector('[data-step-field="id"]').value.trim();
        const kind = row.querySelector('[data-step-field="kind"]').value;
        const target = row.querySelector('[data-step-field="target"]').value.trim();
        const step = { ...(originalById.get(id) || {}), id, kind };
        const depends = row.querySelector('[data-step-field="depends_on"]').value.split(",").map((item) => item.trim()).filter(Boolean);
        if (depends.length) step.depends_on = depends; else delete step.depends_on;
        for (const key of ["agent_id", "eval_id", "transform", "action"]) delete step[key];
        if (target) {
          if (kind === "agent") step.agent_id = target;
          else if (kind === "eval") step.eval_id = target;
          else if (kind === "transform") step.transform = target;
          else if (kind === "approval") step.action = target;
        }
        return step;
      });
      return { title: byId("workflow-title-input").value.trim(), version: byId("workflow-version-input").value.trim(), description: byId("workflow-description-input").value.trim(), steps };
    }

    function renderWorkflowDag(plan) {
      const dag = byId("workflow-dag");
      dag.textContent = "";
      for (const level of plan.levels || []) {
        const group = document.createElement("div");
        group.className = "workflow-dag-level";
        for (const id of level) {
          const node = document.createElement("span");
          node.className = "workflow-dag-node";
          node.textContent = id;
          group.appendChild(node);
        }
        dag.appendChild(group);
      }
    }

    function renderWorkflowHistory(history) {
      const node = byId("workflow-history");
      node.textContent = "";
      for (const revision of history) {
        const row = document.createElement("div");
        row.className = "status-line";
        row.textContent = `${revision.created_at} · ${String(revision.source_hash).slice(0, 12)} · ${revision.path}`;
        node.appendChild(row);
      }
      if (!history.length) node.textContent = "No previous revisions.";
    }

    async function validateWorkflowSource() {
      const result = await getJson("/api/workflows/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: byId("workflow-source-input").value }) });
      if (!result.ok) return setText("workflows-center-status", result.data.detail || "Workflow validation failed.");
      renderWorkflowDag(result.data.plan);
      setText("workflows-center-status", "YAML source is valid. Save revision applies the typed form fields.");
    }

    async function saveSelectedWorkflow() {
      if (!state.selectedWorkflow) return;
      const workflow = state.selectedWorkflow.workflow;
      const result = await getJson(`/api/workflows/${encodeURIComponent(workflow.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspace: state.project.root, content: byId("workflow-source-input").value, expected_hash: workflow.source_hash, form: workflowFormPayload() }) });
      if (!result.ok) return setText("workflows-center-status", result.data.detail || "Workflow save failed.");
      await loadWorkflowsCenter(workflow.id);
      setText("workflows-center-status", "Workflow revision saved atomically; previous YAML retained in history.");
    }

    async function duplicateSelectedWorkflow() {
      if (!state.selectedWorkflow) return;
      const newId = window.prompt("New workflow id", `${state.selectedWorkflow.workflow.id}-copy`);
      if (!newId) return;
      const result = await getJson(`/api/workflows/${encodeURIComponent(state.selectedWorkflow.workflow.id)}/duplicate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspace: state.project.root, new_id: newId }) });
      if (!result.ok) return setText("workflows-center-status", result.data.detail || "Workflow duplicate failed.");
      await loadWorkflowsCenter(result.data.workflow.id);
    }

    async function importWorkflow(content = null, templateId = null) {
      const result = await getJson("/api/workflows/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspace: state.project.root, content, template_id: templateId }) });
      if (!result.ok) return setText("workflows-center-status", result.data.detail || "Workflow import failed.");
      await loadWorkflowsCenter(result.data.workflow.id);
    }

    async function loadAgentsCenter() {
      if (!state.project || !state.project.root) return false;
      setText("agents-center-status", "Refreshing reusable profiles...");
      const result = await getJson(`/api/agents?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("agents-center-status", result.data.detail || "Agent Studio is unavailable.");
        return false;
      }
      state.agents = Array.isArray(result.data.agents) ? result.data.agents : [];
      state.agentErrors = Array.isArray(result.data.errors) ? result.data.errors : [];
      setText("agents-center-status", `${state.agents.length} reusable profiles · immutable snapshots on runs`);
      renderAgentsCenter();
      return true;
    }

    function renderAgentsCenter() {
      const list = byId("agents-center-list");
      const errors = byId("agents-center-errors");
      list.textContent = "";
      errors.textContent = "";
      for (const error of state.agentErrors) {
        const row = document.createElement("div");
        row.className = "warning";
        row.textContent = `${error.path}: ${error.error}`;
        errors.appendChild(row);
      }
      for (const agent of state.agents) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "agent-card";
        card.classList.toggle("active", state.selectedAgent && state.selectedAgent.id === agent.id);
        card.innerHTML = `<span><strong>${escapeHtml(agent.title)}</strong><small>${escapeHtml(agent.description || agent.instructions)}</small></span><span class="badge info">${escapeHtml(agent.mode)}</span><span class="runs-center-item-meta">${escapeHtml(agent.harness_id)} · ${escapeHtml(agent.workspace_policy)} · ${escapeHtml(agent.permission_profile)}</span>`;
        card.addEventListener("click", () => selectAgent(agent.id));
        list.appendChild(card);
      }
      if (!state.agents.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No profiles found. Run giga init to generate starter agents.";
        list.appendChild(empty);
      }
    }

    async function selectAgent(agentId) {
      const result = await getJson(`/api/agents/${encodeURIComponent(agentId)}?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("agents-center-status", result.data.detail || "Agent profile could not be loaded.");
        return;
      }
      state.selectedAgent = result.data.profile;
      state.agentDraft = null;
      byId("agent-source-input").value = result.data.source || "";
      byId("agent-source-input").disabled = false;
      byId("agent-run-prompt").disabled = false;
      byId("validate-agent-button").disabled = false;
      byId("duplicate-agent-button").disabled = false;
      byId("run-agent-button").disabled = false;
      byId("apply-agent-button").disabled = true;
      byId("agent-diff-panel").hidden = true;
      setText("agent-editor-title", state.selectedAgent.title);
      setText("agent-editor-meta", `${state.selectedAgent.id} · ${state.selectedAgent.harness_id} · source ${String(state.selectedAgent.source_hash || "").slice(0, 12)}`);
      renderAgentsCenter();
    }

    async function previewAgent() {
      if (!state.selectedAgent) return;
      const result = await getJson(`/api/agents/${encodeURIComponent(state.selectedAgent.id)}/draft`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, content: byId("agent-source-input").value, expected_hash: state.selectedAgent.source_hash })
      });
      if (!result.ok) {
        setText("agents-center-status", result.data.detail || "Profile validation failed.");
        return;
      }
      state.agentDraft = result.data;
      byId("agent-diff-panel").textContent = result.data.redacted_diff || "No changes.";
      byId("agent-diff-panel").hidden = false;
      byId("apply-agent-button").disabled = false;
      setText("agents-center-status", "Profile valid. Review the redacted diff before Apply.");
    }

    async function applyAgent() {
      if (!state.selectedAgent || !state.agentDraft) return;
      const result = await getJson(`/api/agents/${encodeURIComponent(state.selectedAgent.id)}/apply`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, content: byId("agent-source-input").value, expected_hash: state.agentDraft.source_hash })
      });
      if (!result.ok) {
        setText("agents-center-status", result.data.detail || "Profile apply failed.");
        return;
      }
      await loadAgentsCenter();
      await selectAgent(result.data.profile.id);
      setText("agents-center-status", "Profile applied atomically.");
    }

    async function duplicateAgent() {
      if (!state.selectedAgent) return;
      const newId = window.prompt("New agent id", `${state.selectedAgent.id}-copy`);
      if (!newId) return;
      const result = await getJson(`/api/agents/${encodeURIComponent(state.selectedAgent.id)}/duplicate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, new_id: newId })
      });
      if (!result.ok) {
        setText("agents-center-status", result.data.detail || "Duplicate preview failed.");
        return;
      }
      state.selectedAgent = result.data.profile;
      state.agentDraft = result.data;
      byId("agent-source-input").value = result.data.content;
      byId("agent-diff-panel").textContent = result.data.redacted_diff;
      byId("agent-diff-panel").hidden = false;
      byId("apply-agent-button").disabled = false;
      setText("agent-editor-title", result.data.profile.title);
      setText("agent-editor-meta", `${newId} · duplicate preview · Apply to create`);
    }

    async function runSelectedAgent() {
      if (!state.selectedAgent) return;
      const prompt = byId("agent-run-prompt").value.trim();
      if (!prompt) {
        setText("agents-center-status", "Enter a task before running the agent.");
        return;
      }
      const result = await getJson(`/api/agents/${encodeURIComponent(state.selectedAgent.id)}/run`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, prompt })
      });
      if (!result.ok) {
        setText("agents-center-status", result.data.detail || "Agent run could not be queued.");
        return;
      }
      window.location.assign(`/runs/${encodeURIComponent(result.data.run.id)}`);
    }

    async function loadToolsCenter() {
      if (!state.project || !state.project.root) return false;
      setText("tools-center-status", "Refreshing MCP connections...");
      const result = await getJson(`/api/tool-servers?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("tools-center-status", result.data.detail || "Tools are unavailable.");
        return false;
      }
      state.toolServers = Array.isArray(result.data.servers) ? result.data.servers : [];
      state.toolServerErrors = Array.isArray(result.data.errors) ? result.data.errors : [];
      setText("tools-center-status", `${state.toolServers.length} MCP connections · discovery only · tool execution off`);
      renderToolsCenter();
      return true;
    }

    function renderToolsCenter() {
      const list = byId("tools-center-list");
      const errors = byId("tools-center-errors");
      list.textContent = "";
      errors.textContent = "";
      for (const item of state.toolServerErrors) {
        const row = document.createElement("div");
        row.className = "warning";
        row.textContent = `${item.server_id || "profile"}: ${item.error || "invalid descriptor"}`;
        errors.appendChild(row);
      }
      if (!state.toolServers.length) {
        const empty = document.createElement("div");
        empty.className = "status-line tool-server-empty";
        empty.textContent = "No enabled or disabled MCP profiles are configured in .giga/harness.toml.";
        list.appendChild(empty);
        return;
      }
      for (const item of state.toolServers) {
        const descriptor = item.descriptor || {};
        const probe = item.latest_probe || null;
        const card = document.createElement("article");
        card.className = "tool-server-card";
        const endpoint = descriptor.transport === "stdio" ? [descriptor.command, ...(descriptor.args || [])].filter(Boolean).join(" ") : descriptor.url;
        const compatibility = (item.compatibility || []).map((entry) => `${entry.harness_id}: ${entry.status}`).join(" · ");
        const toolCount = probe && Array.isArray(probe.tools) ? probe.tools.length : 0;
        const resourceCount = probe && Array.isArray(probe.resources) ? probe.resources.length : 0;
        const promptCount = probe && Array.isArray(probe.prompts) ? probe.prompts.length : 0;
        card.innerHTML = `
          <div class="tool-server-card-header">
            <div><strong>${escapeHtml(descriptor.title || descriptor.id)}</strong><p>${escapeHtml(descriptor.description || endpoint || "MCP connection")}</p></div>
            <span class="badge ${probe && probe.status === "healthy" ? "ok" : probe ? "warn" : "info"}">${escapeHtml(probe ? probe.status : descriptor.enabled ? "not probed" : "disabled")}</span>
          </div>
          <div class="runs-center-item-meta">${escapeHtml(descriptor.transport || "mcp")} · ${escapeHtml(descriptor.source || "project")} · ${descriptor.trusted ? "trusted" : "approval required"}</div>
          <div class="details">${escapeHtml(compatibility || "No harness compatibility targets")}</div>
          <div class="badge-row"><span class="badge info">${toolCount} tools</span><span class="badge info">${resourceCount} resources</span><span class="badge info">${promptCount} prompts</span></div>
        `;
        if (probe && probe.error) {
          const warning = document.createElement("div");
          warning.className = "warning";
          warning.textContent = probe.error;
          card.appendChild(warning);
        }
        if (probe && Array.isArray(probe.tools) && probe.tools.length) {
          const schemas = document.createElement("details");
          schemas.innerHTML = `<summary>Discovered schemas and risk labels</summary><pre>${escapeHtml(pretty(probe.tools))}</pre>`;
          card.appendChild(schemas);
        }
        const actions = document.createElement("div");
        actions.className = "inline-actions";
        const probeButton = document.createElement("button");
        probeButton.type = "button";
        probeButton.className = "secondary";
        probeButton.textContent = "Probe";
        probeButton.disabled = !descriptor.enabled;
        probeButton.addEventListener("click", () => probeToolServer(descriptor.id, probeButton));
        actions.appendChild(probeButton);
        card.appendChild(actions);
        list.appendChild(card);
      }
    }

    async function probeToolServer(serverId, button) {
      button.disabled = true;
      button.textContent = "Probing...";
      const result = await getJson(`/api/tool-servers/${encodeURIComponent(serverId)}/probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root })
      });
      if (result.status === 202 && result.data.approval_required) {
        setText("tools-center-status", "Approval required. Decide in Approval Center, then retry the probe.");
        await loadApprovals();
      } else if (!result.ok) {
        setText("tools-center-status", result.data.detail || `Probe failed with HTTP ${result.status}`);
      } else {
        await loadToolsCenter();
      }
      button.disabled = false;
      button.textContent = "Probe";
    }

    async function previewManagedToolConfig() {
      const harnessId = byId("tool-config-harness-select").value;
      setText("tools-center-status", `Building redacted ${harnessId} config diff...`);
      const result = await getJson("/api/tool-config/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, harness_id: harnessId })
      });
      if (!result.ok) {
        state.managedToolConfigPlan = null;
        byId("apply-tool-config-button").disabled = true;
        setText("tools-center-status", result.data.detail || "Managed config preview failed.");
        return;
      }
      state.managedToolConfigPlan = result.data.plan;
      byId("tool-config-diff-panel").hidden = false;
      setText("tool-config-diff", result.data.plan.diff || "No config changes.");
      byId("apply-tool-config-button").disabled = !result.data.plan.changed;
      const warnings = result.data.plan.warnings || [];
      setText("tools-center-status", `${result.data.plan.server_ids.length} trusted servers · delegated CLI enforcement${warnings.length ? ` · ${warnings.length} secret refs skipped` : ""}`);
    }

    async function applyManagedToolConfig() {
      const plan = state.managedToolConfigPlan;
      if (!plan) return;
      const result = await getJson("/api/tool-config/apply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, harness_id: plan.harness_id, expected_hash: plan.current_hash, server_ids: plan.server_ids })
      });
      if (!result.ok) {
        setText("tools-center-status", result.data.detail || "Managed config apply failed.");
        return;
      }
      state.managedToolConfigPlan = null;
      byId("apply-tool-config-button").disabled = true;
      setText("tools-center-status", `Applied managed config ${result.data.provenance.content_hash.slice(0, 12)} · CLI tool calls remain opaque`);
    }

    async function rollbackManagedToolConfig() {
      const harnessId = byId("tool-config-harness-select").value;
      const result = await getJson("/api/tool-config/rollback", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, harness_id: harnessId })
      });
      if (!result.ok) {
        setText("tools-center-status", result.data.detail || "Managed config rollback failed.");
        return;
      }
      state.managedToolConfigPlan = null;
      byId("apply-tool-config-button").disabled = true;
      setText("tools-center-status", "Managed config rolled back to the last Harness backup.");
      await previewManagedToolConfig();
    }

    async function loadApprovals() {
      const params = new URLSearchParams({ limit: "100" });
      if (state.approvalsStatus) params.set("status", state.approvalsStatus);
      setText("approvals-status", "Refreshing policy decisions...");
      const result = await getJson(`/api/approvals?${params.toString()}`);
      if (!result.ok) {
        setText("approvals-status", result.data.detail || "Approval Center is unavailable.");
        return false;
      }
      state.approvals = Array.isArray(result.data.approvals) ? result.data.approvals : [];
      const pendingCount = Number(result.data.pending_count || 0);
      const attention = byId("approval-attention-count");
      attention.hidden = pendingCount < 1;
      attention.textContent = String(pendingCount);
      setText("approvals-status", `${state.approvals.length} decisions · ${pendingCount} pending`);
      renderApprovals();
      return true;
    }

    function renderApprovals() {
      const list = byId("approvals-list");
      list.textContent = "";
      if (!state.approvals.length) {
        const empty = document.createElement("div");
        empty.className = "status-line approval-empty";
        empty.textContent = state.approvalsStatus ? "No pending approvals." : "No approval history yet.";
        list.appendChild(empty);
        return;
      }
      for (const approval of state.approvals) {
        const card = document.createElement("article");
        card.className = "approval-card";
        const header = document.createElement("div");
        header.className = "approval-card-header";
        const title = document.createElement("div");
        const action = document.createElement("strong");
        action.textContent = approval.action || "unknown action";
        const reason = document.createElement("p");
        reason.textContent = approval.reason || "Approval requested.";
        title.append(action, reason);
        const status = document.createElement("span");
        status.className = `runs-status ${approval.status === "approved" ? "completed" : approval.status}`;
        status.textContent = approval.status || "pending";
        header.append(title, status);
        const meta = document.createElement("div");
        meta.className = "runs-center-item-meta";
        meta.textContent = `${approval.enforcement} · ${approval.policy_source}${approval.run_id ? ` · run ${approval.run_id}` : ""}`;
        const preview = document.createElement("pre");
        preview.className = "approval-preview";
        preview.textContent = pretty(approval.preview);
        card.append(header, meta, preview);
        if (approval.status === "pending") {
          const actions = document.createElement("div");
          actions.className = "approval-actions";
          for (const [label, decision, className] of [
            ["Allow once", "allow_once", ""],
            ["Allow for run", "allow_run", "secondary"],
            ["Allow project 24h", "allow_project", "secondary"],
            ["Deny", "deny", "danger"]
          ]) {
            if (decision === "allow_project" && !approval.project_id) continue;
            if (decision === "allow_run" && !approval.run_id) continue;
            const button = document.createElement("button");
            button.type = "button";
            button.className = className;
            button.textContent = label;
            button.addEventListener("click", () => decideApproval(approval.id, decision));
            actions.appendChild(button);
          }
          card.appendChild(actions);
        }
        list.appendChild(card);
      }
    }

    async function decideApproval(approvalId, decision) {
      const payload = { decision };
      if (decision === "allow_project") payload.expires_in_seconds = 86400;
      const result = await getJson(`/api/approvals/${encodeURIComponent(approvalId)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!result.ok) {
        setText("approvals-status", result.data.detail || `Decision failed with HTTP ${result.status}`);
        return;
      }
      setText(
        "model-status",
        result.data.retry_action ? "Approval saved. Retry the original action." : `Approval saved; job is ${result.data.job_status || "updated"}.`
      );
      await loadApprovals();
    }

    async function loadRunsCenter(options = {}) {
      const append = Boolean(options.append);
      const params = new URLSearchParams({ limit: String(RUNS_CENTER_PAGE_SIZE) });
      if (state.runsCenterStatus) params.set("status", state.runsCenterStatus);
      if (append && state.runsCenterCursor) params.set("cursor", state.runsCenterCursor);
      setText("runs-center-status", append ? "Loading more durable work..." : "Refreshing durable work...");
      const result = await getJson(`/api/runs?${params.toString()}`);
      if (!result.ok) {
        setText("runs-center-status", result.data.detail || "Runs Center is unavailable.");
        return false;
      }
      const items = Array.isArray(result.data.runs) ? result.data.runs : [];
      state.runsCenterItems = append ? [...state.runsCenterItems, ...items] : items;
      state.runsCenterCursor = result.data.next_cursor || null;
      const workers = Array.isArray(result.data.workers) ? result.data.workers : [];
      const online = workers.filter((worker) => worker.status === "online").length;
      setText("runs-center-status", `${state.runsCenterItems.length} runs · ${online} workers online`);
      byId("load-more-runs-button").hidden = !state.runsCenterCursor;
      renderRunsCenterList();
      return true;
    }

    function renderRunsCenterList() {
      const list = byId("runs-center-list");
      list.textContent = "";
      if (!state.runsCenterItems.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No durable runs match this filter.";
        list.appendChild(empty);
        return;
      }
      for (const item of state.runsCenterItems) {
        const run = item.run || {};
        const job = item.job || {};
        const button = document.createElement("button");
        button.type = "button";
        button.className = "runs-center-item";
        button.classList.toggle("active", Boolean(state.runsCenterSelected && state.runsCenterSelected.job && state.runsCenterSelected.job.id === job.id));
        button.addEventListener("click", () => selectRunsCenterItem(item));

        const heading = document.createElement("div");
        heading.className = "runs-center-item-row";
        const title = document.createElement("span");
        title.className = "runs-center-item-title";
        title.textContent = item.session_title || "Untitled task";
        const status = document.createElement("span");
        status.className = `runs-status ${item.status_group || "queued"}`;
        status.textContent = String(item.status_group || job.status || "queued").replace(/-/g, " ");
        heading.append(title, status);

        const meta = document.createElement("div");
        meta.className = "runs-center-item-meta";
        for (const value of [
          run.harness_id || job.required_harness_id || "harness",
          `attempts ${item.attempt_count || 0}`,
          item.worker_id ? `worker ${item.worker_id}` : "unowned",
          formatRunsDuration(item.duration_ms)
        ]) {
          const span = document.createElement("span");
          span.textContent = value;
          meta.appendChild(span);
        }
        const metrics = document.createElement("div");
        metrics.className = "runs-metrics";
        metrics.textContent = formatRunsMetrics(item.metrics);
        button.append(heading, meta);
        if (metrics.textContent) button.appendChild(metrics);
        list.appendChild(button);
      }
    }

    async function resolveRunsCenterItem(runId) {
      const existing = state.runsCenterItems.find((item) => item.run_id === runId);
      if (existing) return existing;
      const result = await getJson(`/api/runs/${encodeURIComponent(runId)}/summary`);
      if (!result.ok || !result.data.run) return null;
      state.runsCenterItems = [result.data.run, ...state.runsCenterItems];
      renderRunsCenterList();
      return result.data.run;
    }

    async function selectRunsCenterItem(item, options = {}) {
      state.runsCenterSelected = item;
      renderRunsCenterList();
      renderRunsCenterSelection();
      if (options.syncRoute !== false) syncBrowserRoute("runs", item.run_id);
      await loadRunsTrace(false);
      openRunsCenterEventStream(item);
    }

    function renderRunsCenterSelection() {
      const item = state.runsCenterSelected;
      const actions = item && item.actions ? item.actions : {};
      const job = item && item.job ? item.job : {};
      const run = item && item.run ? item.run : {};
      setText("runs-trace-title", item ? item.session_title : "Select a run");
      setText(
        "runs-trace-meta",
        item
          ? `${run.harness_id || job.required_harness_id || "harness"} · ${item.status_group} · ${item.retry_count || 0} retries · ${item.worker_id || "unowned"} · ${formatRunsDuration(item.duration_ms)}`
          : "Queue, ownership, retries, and trace details appear here."
      );
      byId("runs-open-task-button").disabled = !actions.open_task;
      byId("runs-cancel-button").disabled = !actions.cancel;
      byId("runs-retry-button").disabled = !actions.retry;
      byId("runs-open-worktree-button").disabled = !actions.open_worktree;
      byId("runs-inspect-artifact-button").disabled = !actions.inspect_artifact;
      renderAgentTeam(byId("runs-team-tree"), item && item.workflow, {
        panel: byId("runs-team-panel"),
        title: byId("runs-team-title"),
        progress: byId("runs-team-progress")
      });
      if (!item) {
        byId("runs-trace-list").textContent = "";
        byId("runs-payload-panel").hidden = true;
      }
    }

    function renderAgentTeam(container, workflow, elements = {}) {
      container.textContent = "";
      if (!workflow || !Array.isArray(workflow.steps)) {
        if (elements.panel) elements.panel.hidden = true;
        else container.textContent = "This run is not part of an agent team.";
        return;
      }
      if (elements.panel) elements.panel.hidden = false;
      if (elements.title) elements.title.textContent = workflow.definition_id || "Agent team";
      if (elements.progress) {
        elements.progress.textContent = `${workflow.completed_steps || 0}/${workflow.total_steps || workflow.steps.length} steps · concurrency ${workflow.max_concurrency || 1}`;
      }
      const known = new Set();
      for (const step of workflow.steps) {
        const node = document.createElement("li");
        node.className = "agent-team-node";
        node.dataset.status = step.status || "pending";
        node.dataset.depth = (step.depends_on || []).some((id) => known.has(id)) ? "1" : "0";
        known.add(step.id);
        const row = document.createElement("div");
        row.className = "agent-team-node-row";
        const title = document.createElement("strong");
        title.textContent = step.title || step.id;
        const status = document.createElement("span");
        status.className = `runs-status ${step.status === "succeeded" ? "completed" : step.status || "queued"}`;
        status.textContent = step.status || "pending";
        row.append(title, status);
        const agent = step.agent || {};
        const meta = document.createElement("div");
        meta.className = "agent-team-node-meta";
        for (const value of [
          agent.harness_id || step.kind,
          agent.model || "default model",
          agent.reasoning_effort ? `reasoning ${agent.reasoning_effort}` : null,
          agent.budgets && Number.isFinite(Number(agent.budgets.max_tokens)) ? `${agent.budgets.max_tokens} tokens` : null,
          step.artifact_count ? `${step.artifact_count} artifacts` : null
        ].filter(Boolean)) {
          const label = document.createElement("span");
          label.textContent = value;
          meta.appendChild(label);
        }
        node.append(row, meta);
        const actions = document.createElement("div");
        actions.className = "agent-team-node-actions";
        if (step.actions && step.actions.open_task) {
          const openTask = document.createElement("button");
          openTask.type = "button";
          openTask.className = "secondary";
          openTask.textContent = "Open task";
          openTask.addEventListener("click", () => window.location.assign(step.actions.open_task));
          actions.appendChild(openTask);
        }
        if (step.actions && step.actions.open_run) {
          const openRun = document.createElement("button");
          openRun.type = "button";
          openRun.className = "secondary";
          openRun.textContent = "Open child run";
          openRun.addEventListener("click", () => window.location.assign(step.actions.open_run));
          actions.appendChild(openRun);
        }
        if (step.actions && step.actions.choose) {
          const choose = document.createElement("button");
          choose.type = "button";
          choose.className = step.handoff_selected ? "primary" : "secondary";
          choose.textContent = step.handoff_selected ? "Chosen" : "Choose patch";
          choose.addEventListener("click", async () => {
            choose.disabled = true;
            const result = await getJson(step.actions.choose, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ selected: !step.handoff_selected })
            });
            if (!result.ok) {
              choose.disabled = false;
              setStatus(result.error || "Could not update the merge selection.", "error");
              return;
            }
            step.handoff_selected = !step.handoff_selected;
            choose.className = step.handoff_selected ? "primary" : "secondary";
            choose.textContent = step.handoff_selected ? "Chosen" : "Choose patch";
            choose.disabled = false;
          });
          actions.appendChild(choose);
        }
        if (step.actions && step.actions.apply && step.actions.open_run) {
          const reviewApply = document.createElement("button");
          reviewApply.type = "button";
          reviewApply.className = "secondary";
          reviewApply.textContent = "Review / apply";
          reviewApply.addEventListener("click", () => window.location.assign(step.actions.open_run));
          actions.appendChild(reviewApply);
        }
        if (step.actions && step.actions.discard) {
          const discard = document.createElement("button");
          discard.type = "button";
          discard.className = "danger";
          discard.textContent = "Discard worktree";
          discard.addEventListener("click", async () => {
            if (!window.confirm(`Discard the retained worktree for ${step.title || step.id}?`)) return;
            discard.disabled = true;
            const result = await getJson(step.actions.discard, { method: "POST" });
            if (!result.ok) {
              discard.disabled = false;
              setStatus(result.error || "Could not discard the worktree.", "error");
              return;
            }
            discard.textContent = "Discarded";
          });
          actions.appendChild(discard);
        }
        if (actions.childElementCount) node.appendChild(actions);
        container.appendChild(node);
      }
    }

    async function loadWorkAgentTeam(run) {
      const panel = byId("team-panel");
      if (!run || !run.id || run.invocation_mode === "native") {
        renderAgentTeam(panel, null);
        return;
      }
      const selectedId = run.id;
      const result = await getJson(`/api/runs/${encodeURIComponent(selectedId)}/summary`);
      if (!currentRun() || currentRun().id !== selectedId) return;
      renderAgentTeam(panel, result.ok && result.data.run ? result.data.run.workflow : null);
    }

    async function loadRunsTrace(older = false) {
      const item = state.runsCenterSelected;
      if (!item || !item.run_id) return;
      const params = new URLSearchParams({ limit: String(RUNS_TRACE_DOM_LIMIT) });
      if (older && state.runsTraceCursor) params.set("cursor", state.runsTraceCursor);
      const result = await getJson(`/api/runs/${encodeURIComponent(item.run_id)}/trace?${params.toString()}`);
      if (!result.ok) {
        setText("runs-trace-meta", result.data.detail || "Trace is unavailable.");
        return;
      }
      const nodes = Array.isArray(result.data.nodes) ? result.data.nodes : [];
      if (older) {
        const existing = new Set(state.runsTraceNodes.map((node) => node.id));
        state.runsTraceNodes = [...nodes.filter((node) => !existing.has(node.id)), ...state.runsTraceNodes];
      } else {
        state.runsTraceNodes = nodes.slice(-RUNS_TRACE_DOM_LIMIT);
      }
      state.runsTraceCursor = result.data.next_cursor || null;
      byId("load-older-trace-button").hidden = !state.runsTraceCursor;
      renderRunsTrace();
    }

    function renderRunsTrace() {
      const list = byId("runs-trace-list");
      list.textContent = "";
      if (!state.runsTraceNodes.length) {
        const empty = document.createElement("li");
        empty.className = "status-line";
        empty.textContent = "No trace spans recorded yet.";
        list.appendChild(empty);
        return;
      }
      for (const node of state.runsTraceNodes.slice(-RUNS_TRACE_DOM_LIMIT)) {
        list.appendChild(createRunsTraceNode(node));
      }
    }

    function createRunsTraceNode(node) {
      const item = document.createElement("li");
      item.className = "runs-trace-node";
      item.dataset.depth = String(Math.min(Number(node.depth || 0), 2));
      item.dataset.status = node.status || "";
      const row = document.createElement("div");
      row.className = "runs-trace-node-row";
      const title = document.createElement("strong");
      title.textContent = node.title || node.kind || "Trace span";
      const badge = document.createElement("span");
      badge.className = "runs-status";
      badge.textContent = node.kind || "event";
      row.append(title, badge);
      const meta = document.createElement("div");
      meta.className = "runs-center-item-meta";
      meta.textContent = [node.status, node.worker_id, formatRunsDuration(node.duration_ms), node.created_at].filter(Boolean).join(" · ");
      item.append(row, meta);
      if (node.has_payload && node.event_id) {
        const inspect = document.createElement("button");
        inspect.type = "button";
        inspect.className = "secondary runs-trace-payload-button";
        inspect.textContent = "Inspect payload";
        inspect.addEventListener("click", () => inspectRunsEventPayload(node.event_id));
        item.appendChild(inspect);
      }
      return item;
    }

    async function inspectRunsEventPayload(eventId) {
      const item = state.runsCenterSelected;
      if (!item) return;
      const result = await getJson(`/api/runs/${encodeURIComponent(item.run_id)}/events/${encodeURIComponent(eventId)}`);
      const panel = byId("runs-payload-panel");
      panel.hidden = false;
      panel.textContent = pretty(result.data);
    }

    function appendRunsLiveEvent(event) {
      const type = String(event.type || "").toLowerCase();
      const kind = String(event.span_kind || "").toLowerCase();
      if ([type, kind].some((value) => /reasoning|chain_of_thought|thinking|thought/.test(value))) return;
      const node = {
        id: `event:${event.id || Date.now()}`,
        depth: event.parent_span_id ? 2 : 1,
        event_id: event.id,
        kind: event.span_kind || inferRunsEventKind(type),
        status: event.span_status || (type.includes("failed") || type.includes("error") ? "failed" : type.includes("finished") ? "succeeded" : "running"),
        title: event.message || type.replace(/_/g, " "),
        created_at: event.created_at,
        has_payload: Boolean(event.payload && Object.keys(event.payload).length)
      };
      if (state.runsTraceNodes.some((item) => item.id === node.id)) return;
      state.runsTraceNodes.push(node);
      if (state.runsTraceNodes.length > RUNS_TRACE_DOM_LIMIT) state.runsTraceNodes.shift();
      const list = byId("runs-trace-list");
      if (list.querySelector(".status-line")) list.textContent = "";
      list.appendChild(createRunsTraceNode(node));
      while (list.children.length > RUNS_TRACE_DOM_LIMIT) list.removeChild(list.firstElementChild);
    }

    function openRunsCenterEventStream(item) {
      closeRunsCenterEventStream();
      if (!item || !["queued", "running", "blocked", "approval-needed"].includes(item.status_group) || !window.EventSource) return;
      const latest = [...state.runsTraceNodes].reverse().find((node) => node.event_id);
      const query = latest ? `?after_id=${encodeURIComponent(latest.event_id)}` : "";
      const source = new EventSource(`/api/runs/${encodeURIComponent(item.run_id)}/events/stream${query}`);
      state.runsEventSource = source;
      state.runsEventSourceRunId = item.run_id;
      source.onmessage = (message) => {
        if (!state.runsCenterSelected || state.runsCenterSelected.run_id !== item.run_id) return;
        try {
          const event = JSON.parse(message.data || "{}");
          appendRunsLiveEvent(event);
          if (event.type === "run_finished") {
            closeRunsCenterEventStream();
            loadRunsCenter().then(async () => {
              const refreshed = await resolveRunsCenterItem(item.run_id);
              if (refreshed) await selectRunsCenterItem(refreshed, { syncRoute: false });
            });
          }
        } catch (error) {
          setText("runs-trace-meta", "Received an invalid live trace event.");
        }
      };
    }

    function closeRunsCenterEventStream() {
      if (state.runsEventSource) state.runsEventSource.close();
      state.runsEventSource = null;
      state.runsEventSourceRunId = null;
    }

    async function runCenterAction(name) {
      const item = state.runsCenterSelected;
      const actions = item && item.actions ? item.actions : {};
      const url = actions[name];
      if (!url) return;
      if (name === "open_task") {
        window.history.pushState({}, "", url);
        await applyCurrentRoute();
        return;
      }
      const result = await getJson(url, {
        method: ["cancel", "retry", "open_worktree"].includes(name) ? "POST" : "GET"
      });
      const panel = byId("runs-payload-panel");
      panel.hidden = false;
      panel.textContent = pretty(result.data);
      if (result.ok && ["cancel", "retry"].includes(name)) {
        await loadRunsCenter();
        const refreshed = await resolveRunsCenterItem(item.run_id);
        if (refreshed) await selectRunsCenterItem(refreshed, { syncRoute: false });
      }
    }

    function formatRunsDuration(value) {
      if (value == null) return "duration pending";
      if (value < 1000) return `${value} ms`;
      const seconds = Math.round(value / 1000);
      if (seconds < 60) return `${seconds} s`;
      return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    }

    function formatRunsMetrics(metrics) {
      if (!metrics || typeof metrics !== "object") return "";
      return Object.entries(metrics).map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`).join(" · ");
    }

    function inferRunsEventKind(type) {
      for (const kind of ["command", "tool", "mcp", "file", "approval", "test", "eval", "artifact"]) {
        if (type.includes(kind)) return kind;
      }
      return "event";
    }

    async function loadProject() {
      const result = await getJson("/api/project");
      if (!result.ok) {
        setText("project-status", result.data.detail || "Project unavailable.");
        setText("project-name", "Project unavailable");
        byId("init-project-button").hidden = true;
        return;
      }
      state.project = result.data.project || null;
      state.projectConfig = result.data.config || null;
      state.projectState = result.data.state || null;
      state.projectPresets = Array.isArray(result.data.presets) ? result.data.presets : [];
      state.projectMemory = [];
      state.memoryError = null;
      state.toolProfiles = [];
      state.toolSyncPreview = null;
      state.toolError = null;
      state.evalSpecs = [];
      state.evalRuns = [];
      state.evalErrors = [];
      state.currentEvalRun = null;
      state.evalError = null;
      applyProject();
    }

    function applyProject() {
      const project = state.project || {};
      const config = state.projectConfig || {};
      const projectState = state.projectState || {};
      state.applyingProjectState = true;
      setText("project-name", project.name || "Unassigned");
      const branch = project.git_branch ? `branch ${project.git_branch}` : "no git branch";
      const dirty = project.dirty_summary || {};
      const dirtyText = project.is_git_repo ? `dirty +${dirty.added || 0} -${dirty.deleted || 0} ~${dirty.changed || 0}` : "not a git repo";
      setText("project-meta", `${branch} | ${dirtyText}`);
      setText("project-status", `${project.name || "Project"} / ${project.root || ""}`);
      byId("init-project-button").hidden = Boolean(config.exists);
      if (project.root && !byId("workspace-input").value) {
        byId("workspace-input").value = project.root;
      }
      if (project.root && !byId("arena-workspace-input").value) {
        byId("arena-workspace-input").value = project.root;
      }
      if (config.exists && config.defaults) {
        byId("model-input").value = projectState.last_model || config.defaults.model || byId("model-input").value;
        byId("mode-select").value = projectState.last_run_mode || config.defaults.mode || "plan";
        const mode = projectState.last_api_mode || config.defaults.api_mode || "v2";
        const apiMode = byId(`api-mode-${mode}`);
        if (apiMode) apiMode.checked = true;
      } else {
        if (projectState.last_model) byId("model-input").value = projectState.last_model;
        if (projectState.last_run_mode) byId("mode-select").value = projectState.last_run_mode;
        if (projectState.last_api_mode) {
          const apiMode = byId(`api-mode-${projectState.last_api_mode}`);
          if (apiMode) apiMode.checked = true;
        }
      }
      byId("arena-model-input").value = byId("model-input").value;
      byId("arena-api-mode-select").value = currentApiMode();
      byId("arena-mode-select").value = byId("mode-select").value;
      if (projectState.last_invocation_mode) byId("invocation-select").value = projectState.last_invocation_mode;
      updateRouteNote();
      renderPresetButtons();
      state.applyingProjectState = false;
    }

    async function initProject() {
      const workspace = state.project && state.project.root ? state.project.root : null;
      const result = await getJson("/api/project/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace })
      });
      if (!result.ok) {
        setText("project-status", result.data.detail || "Project init failed.");
        return;
      }
      state.project = result.data.project || null;
      state.projectConfig = result.data.config || null;
      state.projectState = result.data.state || null;
      state.projectPresets = Array.isArray(result.data.presets) ? result.data.presets : [];
      state.projectMemory = [];
      state.memoryError = null;
      state.toolProfiles = [];
      state.toolSyncPreview = null;
      state.toolError = null;
      state.evalSpecs = [];
      state.evalRuns = [];
      state.evalErrors = [];
      state.currentEvalRun = null;
      state.evalError = null;
      applyProject();
      await loadMemory();
      await loadTools();
      await loadEvals();
      await loadSessions();
    }

    async function refreshHealth() {
      const result = await getJson("/api/health");
      const badge = byId("proxy-status");
      if (result.ok && result.data.ok) {
        badge.className = "proxy-indicator ok";
        badge.textContent = `Proxy: ${result.data.path || "ok"}`;
      } else {
        badge.className = "proxy-indicator warn";
        badge.textContent = "Proxy: unavailable";
      }
    }

    async function loadModels() {
      const mode = currentApiMode();
      const result = await getJson(`/api/models?api_mode=${encodeURIComponent(mode)}`);
      const data = result.data || {};
      state.models = Array.isArray(data.models) ? data.models : [];
      state.modelSource = data.source || `/${mode}/models`;
      renderModelList();
      if (!byId("model-input").value && state.models[0]) byId("model-input").value = state.models[0];
      if (!byId("arena-model-input").value && state.models[0]) byId("arena-model-input").value = state.models[0];
      const status = data.ok ? `Models: ${data.source}` : `Models: ${state.modelSource} unavailable${data.error ? " - " + data.error : ""}`;
      setText("model-status", data.note ? `${status}. ${data.note}` : status);
      updateHeaderBadges();
    }

    function renderModelList() {
      const list = byId("model-list");
      const query = byId("model-input").value.trim().toLowerCase();
      const models = state.models.filter((model) => String(model).toLowerCase().includes(query));
      list.textContent = "";
      if (!models.length) {
        const empty = document.createElement("button");
        empty.className = "model-option empty";
        empty.type = "button";
        empty.disabled = true;
        empty.textContent = state.models.length ? "No matching models" : `No models from ${state.modelSource || "selected route"}`;
        list.appendChild(empty);
        return;
      }
      for (const model of models) {
        const option = document.createElement("button");
        option.className = `model-option${model === byId("model-input").value ? " active" : ""}`;
        option.type = "button";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", model === byId("model-input").value ? "true" : "false");
        option.textContent = model;
        option.addEventListener("click", () => selectModel(model));
        list.appendChild(option);
      }
    }

    function openModelList() {
      if (byId("model-input").disabled) return;
      renderModelList();
      byId("model-list").hidden = false;
    }

    function closeModelList() {
      byId("model-list").hidden = true;
    }

    function toggleModelList() {
      if (byId("model-list").hidden) {
        openModelList();
      } else {
        closeModelList();
      }
    }

    function selectModel(model) {
      byId("model-input").value = model;
      renderModelList();
      closeModelList();
      updateHeaderBadges();
      persistProjectState();
      byId("model-input").focus();
    }

    async function loadHarnesses() {
      const result = await getJson("/api/harnesses");
      if (!result.ok) {
        setText("harness-details", result.data.detail || "Harness registry failed.");
        return;
      }
      state.harnesses = result.data.harnesses || [];
      renderHarnessSelect();
      renderHarnessCards();
      chooseInitialHarness();
      scheduleRouteRecommendation();
    }

    function renderHarnessSelect() {
      const select = byId("harness-select");
      const arenaOptions = byId("arena-harness-options");
      const filter = byId("session-harness-filter");
      const selectedArenaIds = new Set(arenaSelectedHarnessIds());
      if (!selectedArenaIds.size && state.currentArena && state.currentArena.id) {
        for (const harnessId of state.currentArena.harness_ids || []) {
          selectedArenaIds.add(harnessId);
        }
      }
      const selectionWasTouched = state.arenaSelectionTouched || Boolean(state.currentArena && state.currentArena.id);
      select.textContent = "";
      arenaOptions.textContent = "";
      state.arenaSelectionTouched = selectionWasTouched;
      filter.textContent = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = "All harnesses";
      filter.appendChild(all);
      for (const item of state.harnesses) {
        const spec = item.spec || {};
        const option = document.createElement("option");
        option.value = spec.id;
        option.textContent = spec.title || spec.id;
        select.appendChild(option);
        const arenaOption = document.createElement("label");
        arenaOption.className = "arena-harness-option";
        const arenaCheckbox = document.createElement("input");
        arenaCheckbox.type = "checkbox";
        arenaCheckbox.name = "arena-harness";
        arenaCheckbox.value = spec.id;
        arenaCheckbox.checked = selectedArenaIds.has(spec.id);
        const arenaCopy = document.createElement("span");
        arenaCopy.className = "arena-harness-option-copy";
        const arenaTitle = document.createElement("strong");
        arenaTitle.textContent = spec.title || spec.id;
        const availability = item.availability || {};
        const compatibility = item.compatibility || {};
        const arenaMeta = document.createElement("small");
        arenaMeta.textContent = `${spec.id} · ${availability.status || "unknown"}${compatibility.version ? ` · ${compatibility.version}` : ""}`;
        arenaCopy.append(arenaTitle, arenaMeta);
        arenaOption.append(arenaCheckbox, arenaCopy);
        arenaOptions.appendChild(arenaOption);
        const filterOption = option.cloneNode(true);
        filter.appendChild(filterOption);
      }
      byId("harness-count").textContent = String(state.harnesses.length);
      updateArenaSelectionUi();
    }

    function renderHarnessCards() {
      const list = byId("harness-list");
      list.textContent = "";
      for (const item of state.harnesses) {
        const spec = item.spec || {};
        const availability = item.availability || {};
        const compatibility = item.compatibility || {};
        const validation = item.validation || {};
        const plugin = spec.plugin_metadata || {};
        const capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.slice(0, 3) : [];
        const configFields = simpleConfigFields(plugin.config_schema || spec.config_schema || {});
        const extras = [];
        if (spec.supports_workspace) extras.push("workspace");
        if (spec.supports_streaming) extras.push("stream");
        if (configFields.length) extras.push(`config: ${configFields.length}`);
        if (validation.ok === false) extras.push("validate");
        const recommended = state.routeRecommendation && state.routeRecommendation.harness_id === spec.id;
        const icon = plugin.icon || spec.icon || "";
        const card = document.createElement("div");
        card.className = "harness-card";
        card.innerHTML = `
          <div class="session-title">${icon ? `<span>${escapeHtml(icon)}</span> ` : ""}${escapeHtml(spec.title || spec.id)}</div>
          <div class="session-meta">
            <span>${escapeHtml(spec.id || "")}</span>
            <span>${escapeHtml(spec.kind || "")}</span>
            <span>${escapeHtml(availability.status || "unknown")}</span>
            ${compatibility.status ? `<span class="badge ${compatibility.compatible ? "ok" : "warn"}">${escapeHtml(compatibility.version || compatibility.status)}</span>` : ""}
            ${recommended ? '<span class="badge ok">Recommended</span>' : ''}
          </div>
          <div class="session-meta">
            <span>${escapeHtml(capabilities.join(", ") || "no capabilities")}</span>
          </div>
          <div class="session-meta">
            <span>${escapeHtml(extras.join(", ") || "prompt only")}</span>
          </div>
        `;
        card.addEventListener("click", () => selectHarness(spec.id));
        list.appendChild(card);
      }
    }

    function chooseInitialHarness() {
      const configDefaults = state.projectConfig && state.projectConfig.exists ? state.projectConfig.defaults || {} : {};
      const projectState = state.projectState || {};
      const preferred = projectState.last_harness || configDefaults.harness || byId("harness-select").value || "echo";
      const first = state.harnesses.find((item) => item.spec && item.spec.id === preferred) || state.harnesses[0];
      if (first && first.spec) {
        byId("invocation-select").value = projectState.last_invocation_mode || first.spec.default_invocation_mode || "headless";
      }
      if (first && first.spec) selectHarness(first.spec.id);
    }

    function selectHarness(harnessId) {
      const item = state.harnesses.find((entry) => entry.spec && entry.spec.id === harnessId);
      if (!item) return;
      state.selectedHarness = item;
      byId("harness-select").value = harnessId;
      ensureArenaSelection(harnessId);
      renderCapabilityOptions(item.spec);
      updateHarnessDrivenControls();
      renderAttachments();
      renderHarnessDetails(item);
      renderRouteRecommendation(state.routeRecommendation);
      loadNativeSessions(false);
      persistProjectState();
    }

    function renderHarnessDetails(item) {
      const spec = item.spec || {};
      const plugin = spec.plugin_metadata || {};
      const validation = item.validation || {};
      const details = byId("harness-details");
      details.textContent = "";
      const capabilities = Array.isArray(spec.capabilities) ? spec.capabilities.join(", ") : "";
      const summary = document.createElement("div");
      summary.textContent = `${spec.title || spec.id} - ${spec.description || ""}${capabilities ? " Capabilities: " + capabilities : ""}`;
      details.appendChild(summary);
      const fields = simpleConfigFields(plugin.config_schema || spec.config_schema || {});
      if (fields.length) {
        const form = document.createElement("div");
        form.className = "config-grid";
        for (const field of fields) {
          const label = document.createElement("label");
          label.textContent = field.title || field.name;
          const input = document.createElement(field.type === "array" ? "textarea" : "input");
          input.name = `harness-config-${field.name}`;
          input.disabled = true;
          input.placeholder = field.description || "";
          if (field.type === "boolean") input.type = "checkbox";
          else if (field.type === "integer" || field.type === "number") input.type = "number";
          else input.type = "text";
          if (field.default !== undefined && field.type !== "boolean") input.value = String(field.default);
          if (field.default !== undefined && field.type === "boolean") input.checked = Boolean(field.default);
          label.appendChild(input);
          form.appendChild(label);
        }
        details.appendChild(form);
      }
      if (validation.ok === false && Array.isArray(validation.issues)) {
        const warnings = validation.issues
          .filter((issue) => issue.level === "error" || issue.level === "warning")
          .slice(0, 3)
          .map((issue) => issue.field ? `${issue.field}: ${issue.message}` : issue.message);
        if (warnings.length) {
          const warning = document.createElement("div");
          warning.className = "warning";
          warning.textContent = warnings.join(" ");
          details.appendChild(warning);
        }
      }
    }

    function simpleConfigFields(schema) {
      if (!schema || typeof schema !== "object") return [];
      const properties = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
      const required = Array.isArray(schema.required) ? new Set(schema.required) : new Set();
      const fields = [];
      for (const [name, value] of Object.entries(properties)) {
        if (!value || typeof value !== "object") continue;
        const type = value.type || "string";
        if (!["string", "integer", "number", "boolean", "array"].includes(type)) continue;
        fields.push({
          name,
          type,
          title: value.title || name,
          description: value.description || "",
          default: value.default,
          required: required.has(name)
        });
      }
      return fields.slice(0, 12);
    }

    function ensureArenaSelection(harnessId) {
      if (state.arenaSelectionTouched) return;
      for (const checkbox of document.querySelectorAll('input[name="arena-harness"]')) {
        checkbox.checked = checkbox.value === harnessId;
      }
      updateArenaSelectionUi();
    }

    function arenaSelectedHarnessIds() {
      return Array.from(document.querySelectorAll('input[name="arena-harness"]:checked'))
        .map((checkbox) => checkbox.value)
        .filter(Boolean);
    }

    function updateArenaSelectionUi() {
      const checkboxes = Array.from(document.querySelectorAll('input[name="arena-harness"]'));
      const selected = checkboxes.filter((checkbox) => checkbox.checked);
      for (const checkbox of checkboxes) {
        const option = checkbox.closest(".arena-harness-option");
        if (option) option.classList.toggle("selected", checkbox.checked);
      }
      const count = byId("arena-selection-count");
      count.textContent = `${selected.length} selected`;
      count.className = `badge ${selected.length >= 2 ? "ok" : "info"}`;
      byId("arena-select-all-button").disabled = checkboxes.length === 0 || selected.length === checkboxes.length;
      byId("arena-clear-button").disabled = selected.length === 0;
    }

    function selectAllArenaHarnesses(selected) {
      state.arenaSelectionTouched = true;
      for (const checkbox of document.querySelectorAll('input[name="arena-harness"]')) {
        checkbox.checked = selected;
      }
      updateArenaSelectionUi();
    }

    function applyArenaToControls(arena) {
      if (!arena || !arena.id) return;
      byId("arena-prompt-input").value = arena.prompt || "";
      byId("arena-model-input").value = arena.model || "";
      byId("arena-api-mode-select").value = arena.api_mode || "v2";
      byId("arena-mode-select").value = arena.mode || "plan";
      byId("arena-workspace-policy-select").value = arena.workspace_policy || "auto";
      byId("arena-workspace-input").value = arena.workspace || "";
      const selected = new Set(Array.isArray(arena.harness_ids) ? arena.harness_ids : []);
      state.arenaSelectionTouched = true;
      for (const checkbox of document.querySelectorAll('input[name="arena-harness"]')) {
        checkbox.checked = selected.has(checkbox.value);
      }
      updateArenaSelectionUi();
    }

    function updateArenaStatus(arena) {
      if (!arena || !arena.id) {
        setText("arena-center-status", "Compare the same prompt across response formats.");
        setText("arena-results-status", "Run a comparison to see responses here.");
        return;
      }
      const children = Array.isArray(arena.child_runs) ? arena.child_runs : [];
      const requested = Array.isArray(arena.harness_ids) ? arena.harness_ids.length : children.length;
      const complete = children.filter((child) => !["queued", "running", "retry_wait"].includes(child.status)).length;
      const status = arena.status || "running";
      setText("arena-center-status", `Comparison ${status}.`);
      setText(
        "arena-results-status",
        `${complete}/${requested} responses ready · same prompt · independent runs`
      );
    }

    function stopArenaRefresh() {
      if (state.arenaPollTimer) window.clearTimeout(state.arenaPollTimer);
      state.arenaPollTimer = null;
    }

    function scheduleArenaRefresh(arena) {
      stopArenaRefresh();
      if (!arena || ["succeeded", "partial", "failed", "canceled"].includes(arena.status)) return;
      state.arenaPollTimer = window.setTimeout(() => {
        state.arenaPollTimer = null;
        if (currentRoute().area === "arena") void loadArenaCenter({ hydrateControls: false });
      }, 1000);
    }

    function renderCapabilityOptions(spec) {
      const select = byId("capability-select");
      select.textContent = "";
      const capabilities = spec.capabilities && spec.capabilities.length ? spec.capabilities : ["chat_completions"];
      for (const capability of capabilities) {
        const option = document.createElement("option");
        option.value = capability;
        option.textContent = capability;
        select.appendChild(option);
      }
    }

    function supportedBuiltinTools() {
      const spec = state.selectedHarness && state.selectedHarness.spec ? state.selectedHarness.spec : {};
      return Array.isArray(spec.supported_builtin_tools) ? spec.supported_builtin_tools : [];
    }

    function selectedBuiltinTools() {
      if (currentApiMode() !== "v2" || byId("builtin-tools-control").hidden) return [];
      return Array.from(document.querySelectorAll('input[name="builtin-tool"]:checked'))
        .map((input) => input.value)
        .filter((value) => supportedBuiltinTools().includes(value));
    }

    function applyBuiltinTools(values) {
      const selected = new Set(Array.isArray(values) ? values : []);
      for (const input of document.querySelectorAll('input[name="builtin-tool"]')) {
        input.checked = selected.has(input.value);
      }
    }

    function updateBuiltinToolControls() {
      const supported = supportedBuiltinTools();
      const available = currentApiMode() === "v2" && supported.length > 0 && currentInvocationMode() === "headless";
      const control = byId("builtin-tools-control");
      control.hidden = !available;
      for (const input of control.querySelectorAll('input[name="builtin-tool"]')) {
        input.disabled = !available || !supported.includes(input.value);
      }
    }

    function usesStructuredWorkChat(spec = null) {
      const selected = spec || (state.selectedHarness && state.selectedHarness.spec) || {};
      return selected.id === "codex-cli" && selected.supports_structured_events === true;
    }

    function updateHarnessDrivenControls() {
      const spec = state.selectedHarness && state.selectedHarness.spec ? state.selectedHarness.spec : {};
      const invocation = byId("invocation-select");
      const supportsNative = spec.supports_native_sessions === true;
      const structuredWorkChat = usesStructuredWorkChat(spec);
      invocation.disabled = !supportsNative || structuredWorkChat;
      if (!supportsNative || structuredWorkChat) {
        invocation.value = "headless";
      } else if (!invocation.value) {
        invocation.value = spec.default_invocation_mode || "native";
      }
      byId("model-input").disabled = spec.supports_model_selection === false;
      byId("model-menu-button").disabled = spec.supports_model_selection === false;
      if (spec.supports_model_selection === false) closeModelList();
      byId("api-mode-v1").disabled = spec.supports_api_mode_selection === false;
      byId("api-mode-v2").disabled = spec.supports_api_mode_selection === false;
      byId("workspace-input").disabled = spec.supports_workspace === false;
      if (structuredWorkChat) byId("stream-checkbox").checked = true;
      byId("stream-checkbox").disabled = structuredWorkChat || spec.supports_streaming !== true || currentInvocationMode() === "native";
      byId("copy-curl-button").disabled = spec.id !== "direct-chat";
      const nativeTab = document.querySelector('[data-tab="native"]');
      if (nativeTab) nativeTab.hidden = structuredWorkChat;
      updateBuiltinToolControls();
      const availability = state.selectedHarness && state.selectedHarness.availability ? state.selectedHarness.availability : {};
      const compatibility = state.selectedHarness && state.selectedHarness.compatibility ? state.selectedHarness.compatibility : {};
      const warning = availability.status === "missing" || availability.status === "error"
        ? compatibility.warning || availability.reason || availability.status
        : compatibility.warning || "";
      setText("harness-warning", warning);
      const continuingNative = Boolean(activeNativeConversation());
      byId("run-button").textContent = structuredWorkChat
        ? "Send"
        : continuingNative
        ? "Send"
        : currentInvocationMode() === "native" && supportsNative ? "Start native" : "Run";
      byId("prompt-input").placeholder = structuredWorkChat
        ? "Message Codex..."
        : continuingNative
        ? "Message the active native session..."
        : "Ask, plan, or describe a task...";
    }

    async function loadSessions() {
      const params = new URLSearchParams();
      const q = byId("session-search").value.trim();
      const workspace = byId("session-workspace-filter").value.trim();
      const harness = byId("session-harness-filter").value;
      if (q) params.set("q", q);
      if (workspace) params.set("workspace", workspace);
      if (!workspace && state.project && state.project.id) params.set("project_id", state.project.id);
      if (harness) params.set("harness_id", harness);
      if (byId("include-archived-checkbox").checked) params.set("include_archived", "true");
      const result = await getJson(`/api/sessions?${params.toString()}`);
      state.sessions = result.ok ? result.data.sessions || [] : [];
      renderSessions();
    }

    async function loadNativeSessions(sync, options = {}) {
      if (sync || options.resetVisible) resetNativeVisibleLimit();
      const showAllWorkspaces = byId("native-all-workspaces-checkbox").checked;
      const workspace = showAllWorkspaces ? "" : byId("session-workspace-filter").value.trim() || byId("workspace-input").value.trim();
      const includeExternal = true;
      if (sync) {
        const payload = {
          workspace: showAllWorkspaces ? null : workspace || null,
          include_external: includeExternal
        };
        const synced = await getJson("/api/native/sessions/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!synced.ok) {
          state.nativeSessions = [];
          renderNativeSessions(synced.data.detail || "Native history sync failed.");
          if (options.openModal) openNativeHistory(false);
          return;
        }
        const errors = Array.isArray(synced.data.errors) ? synced.data.errors : [];
        if (errors.length) {
          setText("native-status", `Native sync completed with ${errors.length} warning${errors.length === 1 ? "" : "s"}.`);
        }
      }
      const params = new URLSearchParams({ include_external: "true" });
      if (!showAllWorkspaces && workspace) params.set("workspace", workspace);
      if (!showAllWorkspaces && !workspace && state.project && state.project.id) params.set("project_id", state.project.id);
      const result = await getJson(`/api/native/sessions?${params.toString()}`);
      if (!result.ok) {
        state.nativeSessions = [];
        renderNativeSessions(result.data.detail || "Native history unavailable.");
        if (options.openModal) openNativeHistory(false);
        return;
      }
      state.nativeSessions = result.data.sessions || [];
      renderNativeSessions();
      if (options.openModal) openNativeHistory(false);
    }

    function renderSessions() {
      const list = byId("session-list");
      list.textContent = "";
      byId("session-count").textContent = String(state.sessions.length);
      if (!state.sessions.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No sessions";
        list.appendChild(empty);
        return;
      }
      const groups = groupSessions(state.sessions);
      for (const [label, sessions] of groups) {
        if (!sessions.length) continue;
        const title = document.createElement("div");
        title.className = "group-title";
        title.textContent = label;
        list.appendChild(title);
        for (const session of sessions) {
          const row = document.createElement("div");
          row.className = `session-row${session.id === state.currentSessionId ? " active" : ""}`;
          const displayTitle = compactSessionTitle(session.title || "Untitled session");
          row.innerHTML = `
            <div class="session-row-content">
              <div class="session-title" title="${escapeHtml(session.title || "Untitled session")}">${escapeHtml(displayTitle)}</div>
              <div class="session-meta">
                <span>${escapeHtml(session.default_harness_id || "")}</span>
                <span>${escapeHtml(session.default_api_mode || "")}</span>
                <span>${escapeHtml(session.last_run_status || "new")}</span>
              </div>
            </div>
            <div class="session-row-actions"></div>
          `;
          row.addEventListener("click", () => loadSession(session.id));
          const actions = row.querySelector(".session-row-actions");
          actions.appendChild(sessionRowActionButton(
            session.archived ? "Unarchive" : "Archive",
            session.archived ? "unarchive" : "archive",
            () => archiveSessionFromList(session)
          ));
          actions.appendChild(sessionRowActionButton(
            "Delete",
            "delete",
            () => deleteSessionFromList(session)
          ));
          list.appendChild(row);
        }
      }
    }

    function compactSessionTitle(value) {
      const title = String(value || "Untitled session").replace(/^\s*[#>*-]+\s*/, "").replace(/\s+/g, " ").trim();
      if (title.length <= 40) return title || "Untitled session";
      let candidate = title.slice(0, 37).trimEnd();
      const wordBoundary = candidate.lastIndexOf(" ");
      if (wordBoundary >= 24) candidate = candidate.slice(0, wordBoundary);
      return `${candidate.replace(/[.,:;!?]+$/, "")}...`;
    }

    function sessionRowActionButton(label, action, handler) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `session-row-action ${action}`;
      button.setAttribute("aria-label", `${label} session`);
      button.title = label;
      button.innerHTML = action === "delete"
        ? '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3m-9 0 1 14h10l1-14M10 11v6m4-6v6"/></svg>'
        : '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16v13H4zM3 4h18v3H3zm6 8h6"/></svg>';
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        handler();
      });
      return button;
    }

    async function archiveSessionFromList(session) {
      const result = await getJson(`/api/sessions/${encodeURIComponent(session.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived: !session.archived })
      });
      if (!result.ok) {
        setText("model-status", result.data.detail || "Session archive failed.");
        return;
      }
      if (state.currentBundle && state.currentSessionId === session.id) {
        state.currentBundle.session = result.data.session;
        renderAll();
      }
      await loadSessions();
    }

    async function deleteSessionFromList(session) {
      if (!window.confirm(`Delete \"${compactSessionTitle(session.title)}\" permanently?`)) return;
      const result = await getJson(`/api/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
      if (!result.ok) {
        setText("model-status", result.data.detail || "Session delete failed.");
        return;
      }
      if (state.currentSessionId === session.id) clearCurrentSession();
      await loadSessions();
    }

    function renderNativeSessions(error) {
      const list = byId("native-session-list");
      list.textContent = "";
      byId("native-count").textContent = String(state.nativeSessions.length);
      if (error) {
        setText("native-status", error);
        setText("native-modal-status", error);
      } else {
        const status = state.nativeSessions.length ? "Native history loaded" : "No native sessions cached";
        setText("native-status", status);
        setText("native-modal-status", status);
      }
      const visibleLimit = Math.min(state.nativeVisibleLimit, state.nativeSessions.length);
      setText("native-page-status", `Showing ${visibleLimit} of ${state.nativeSessions.length}`);
      const loadMoreButton = byId("load-more-native-button");
      loadMoreButton.disabled = !state.nativeSessions.length || visibleLimit >= state.nativeSessions.length;
      loadMoreButton.textContent = visibleLimit >= state.nativeSessions.length ? "All loaded" : "Load 5 more";
      if (!state.nativeSessions.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = error || "No native sessions";
        list.appendChild(empty);
        return;
      }
      const groups = groupByHarness(state.nativeSessions.slice(0, visibleLimit));
      for (const [harnessId, sessions] of groups) {
        const title = document.createElement("div");
        title.className = "group-title sidebar-heading";
        title.textContent = harnessTitle(harnessId);
        list.appendChild(title);
        for (const ref of sessions) {
          list.appendChild(nativeSessionRow(ref));
        }
      }
    }

    function nativeSessionRow(ref) {
      const row = document.createElement("div");
      row.className = `native-session-row${ref.id === state.selectedNativeRefId ? " active" : ""}`;
      const status = nativeStatusLabel(ref.status);
      row.innerHTML = `
        <div class="session-title">${escapeHtml(ref.title || "Untitled native session")}</div>
        <div class="session-meta">
          <span>${escapeHtml(ref.harness_id || "")}</span>
          <span>${escapeHtml(status)}</span>
          <span>${escapeHtml(ref.can_resume ? "resumable" : ref.can_import ? "importable" : "readonly")}</span>
        </div>
        <div class="badge-row">
          ${nativeBadge(ref.status)}
          ${ref.can_resume ? '<span class="badge ok">resumable</span>' : ''}
          ${ref.can_import ? '<span class="badge info">importable</span>' : ''}
        </div>
      `;
      row.addEventListener("click", () => selectNativeSession(ref.id));
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      actions.appendChild(nativeActionButton("Preview", () => previewNativeSession(ref.id), !ref.can_preview));
      actions.appendChild(nativeActionButton("Import", () => importNativeSession(ref.id), !ref.can_import));
      actions.appendChild(nativeActionButton("Link to current chat", () => linkNativeSession(ref.id), !state.currentSessionId));
      actions.appendChild(nativeActionButton("Resume native", () => resumeNativeSession(ref.id), !ref.can_resume));
      row.appendChild(actions);
      return row;
    }

    function resetNativeVisibleLimit() {
      state.nativeVisibleLimit = NATIVE_SESSION_PAGE_SIZE;
    }

    function loadMoreNativeSessions() {
      state.nativeVisibleLimit = Math.min(
        state.nativeVisibleLimit + NATIVE_SESSION_PAGE_SIZE,
        state.nativeSessions.length
      );
      renderNativeSessions();
    }

    function openNativeHistory(resetVisible = true) {
      if (resetVisible) resetNativeVisibleLimit();
      state.nativeModalOpen = true;
      byId("native-history-modal").hidden = false;
      renderNativeSessions();
      byId("close-native-history-button").focus();
    }

    function closeNativeHistory() {
      state.nativeModalOpen = false;
      byId("native-history-modal").hidden = true;
    }

    function nativeActionButton(label, handler, disabled) {
      const button = document.createElement("button");
      button.className = "secondary";
      button.type = "button";
      button.textContent = label;
      button.disabled = Boolean(disabled);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        closeNativeHistory();
        handler();
      });
      return button;
    }

    function groupSessions(sessions) {
      const today = new Date();
      const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const buckets = new Map([
        ["Pinned", []],
        ["Today", []],
        ["Yesterday", []],
        ["Previous 7 days", []],
        ["Older", []]
      ]);
      for (const session of sessions) {
        if (session.pinned) {
          buckets.get("Pinned").push(session);
          continue;
        }
        const updated = new Date(session.updated_at);
        const days = Math.floor((startToday - new Date(updated.getFullYear(), updated.getMonth(), updated.getDate())) / 86400000);
        const label = days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days" : "Older";
        buckets.get(label).push(session);
      }
      return [...buckets.entries()];
    }

    function groupByHarness(refs) {
      const buckets = new Map();
      for (const ref of refs) {
        const harnessId = ref.harness_id || "unknown";
        if (!buckets.has(harnessId)) buckets.set(harnessId, []);
        buckets.get(harnessId).push(ref);
      }
      return [...buckets.entries()];
    }

    function harnessTitle(harnessId) {
      const item = state.harnesses.find((entry) => entry.spec && entry.spec.id === harnessId);
      return item && item.spec && item.spec.title ? item.spec.title : harnessId;
    }

    function nativeStatusLabel(status) {
      const value = String(status || "readonly");
      if (value === "managed_native") return "managed";
      if (value === "external_native") return "external";
      return value;
    }

    function nativeBadge(status) {
      const label = nativeStatusLabel(status);
      const className = label === "managed" || label === "linked" || label === "imported" ? "ok" : label === "external" ? "warn" : "info";
      return `<span class="badge ${className}">${escapeHtml(label)}</span>`;
    }

    function selectNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const ref = state.nativeSessions.find((item) => item.id === refId);
      setNativeSummary(ref ? pretty(ref) : "No native session selected.");
      renderNativeSessions();
      showTab("native");
    }

    async function previewNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const result = await getJson(`/api/native/sessions/${encodeURIComponent(refId)}/preview`);
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native preview failed.");
        showTab("native");
        return;
      }
      state.nativePreview = result.data;
      setNativeSummary(pretty(result.data));
      renderNativeSessions();
      showTab("native");
    }

    async function importNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const result = await getJson(`/api/native/sessions/${encodeURIComponent(refId)}/import`, { method: "POST" });
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native import failed.");
        showTab("native");
        return;
      }
      setNativeSummary(pretty(result.data));
      if (result.data.session && result.data.session.id) {
        await loadSession(result.data.session.id);
      }
      await loadNativeSessions(false);
      showTab("native");
    }

    async function linkNativeSession(refId) {
      state.selectedNativeRefId = refId;
      if (!state.currentSessionId) {
        setNativeSummary("Select a GPT2Giga chat before linking a native session.");
        showTab("native");
        return;
      }
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/native/link`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ native_ref_id: refId })
      });
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native link failed.");
        showTab("native");
        return;
      }
      setNativeSummary(pretty(result.data));
      await loadSession(state.currentSessionId);
      showTab("native");
    }

    async function resumeNativeSession(refId) {
      state.selectedNativeRefId = refId;
      const ref = state.nativeSessions.find((item) => item.id === refId);
      if (!ref) return;
      if (!(await ensureSessionForNative({
        harness_id: ref.harness_id,
        model: byId("model-input").value.trim() || null,
        api_mode: currentApiMode(),
        mode: byId("mode-select").value,
        workspace: ref.workspace || byId("workspace-input").value.trim() || null
      }))) return;
      setNativeSummary("Resuming native session...");
      showTab("native");
      setInspectorOpen(true);
      const result = await getJson("/api/native/processes/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.currentSessionId,
          action: "resume",
          native_ref_id: refId,
          workspace: ref.workspace || byId("workspace-input").value.trim() || null
        })
      });
      if (!result.ok) {
        setNativeSummary(result.data.detail || "Native resume failed.");
        return;
      }
      setActiveNativeProcess(result.data.process || null, result.data);
      await loadSession(state.currentSessionId);
      showTab("native");
    }

    async function loadSession(sessionId, options = {}) {
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}`);
      if (!result.ok) return;
      state.currentSessionId = sessionId;
      state.selectedRunId = options.runId || null;
      state.currentBundle = result.data;
      await loadAttachments(sessionId);
      applySessionDefaults(result.data.session || {});
      persistProjectState({ last_selected_session: sessionId });
      restoreTerminalPartialDrafts();
      renderAll();
      resumeActiveHeadlessRun();
      restoreActiveNativeProcess();
      setSidebarOpen(false);
      if (options.syncRoute !== false) {
        syncBrowserRoute(options.area || "work", options.runId || sessionId);
      } else {
        syncNavigation();
      }
      await loadSessions();
    }

    async function loadRun(runId, options = {}) {
      const result = await getJson(`/api/runs/${encodeURIComponent(runId)}`);
      if (!result.ok || !result.data.session) return false;
      const sessionId = result.data.session.id;
      state.currentSessionId = sessionId;
      state.selectedRunId = runId;
      state.currentBundle = result.data;
      await loadAttachments(sessionId);
      applySessionDefaults(result.data.session);
      persistProjectState({ last_selected_session: sessionId });
      restoreTerminalPartialDrafts();
      renderAll();
      resumeActiveHeadlessRun();
      restoreActiveNativeProcess();
      setSidebarOpen(false);
      if (options.syncRoute !== false) syncBrowserRoute("runs", runId);
      else syncNavigation();
      await loadSessions();
      return true;
    }

    async function loadAttachments(sessionId) {
      if (!sessionId) {
        state.attachments = [];
        renderAttachments();
        return;
      }
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}/attachments`);
      state.attachments = result.ok && Array.isArray(result.data.attachments) ? result.data.attachments : [];
      renderAttachments();
    }

    async function ensureSessionForAttachments() {
      if (state.currentSessionId) return true;
      const result = await getJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildSessionDefaults())
      });
      if (!result.ok || !result.data.session) {
        setText("attachment-status", result.data.detail || "Attachment session failed.");
        return false;
      }
      await loadSession(result.data.session.id);
      return true;
    }

    async function attachFiles(files, source) {
      const fileList = Array.from(files || []).filter(Boolean);
      if (!fileList.length) return;
      if (!(await ensureSessionForAttachments())) return;
      setText("attachment-status", `Uploading ${fileList.length}...`);
      for (const file of fileList) {
        try {
          const dataBase64 = await readFileAsBase64(file);
          const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/attachments`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              filename: file.name || "clipboard-image.png",
              mime_type: file.type || null,
              data_base64: dataBase64,
              source
            })
          });
          if (result.ok && result.data.attachment) {
            state.attachments.push(result.data.attachment);
          } else {
            setText("attachment-status", result.data.detail || "Attachment upload failed.");
          }
        } catch (error) {
          setText("attachment-status", "Attachment upload failed.");
        }
      }
      renderAttachments();
      await loadSessions();
    }

    function readFileAsBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const value = String(reader.result || "");
          resolve(value.includes(",") ? value.split(",", 2)[1] : value);
        };
        reader.onerror = () => reject(reader.error || new Error("file read failed"));
        reader.readAsDataURL(file);
      });
    }

    async function removeAttachment(attachmentId) {
      const result = await getJson(`/api/attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" });
      if (!result.ok) {
        setText("attachment-status", result.data.detail || "Attachment delete failed.");
        return;
      }
      state.attachments = state.attachments.filter((attachment) => attachment.id !== attachmentId);
      renderAttachments();
    }

    async function searchWorkspaceFiles() {
      const query = currentFileMentionQuery();
      state.fileMentionQuery = query;
      if (query == null) {
        hideWorkspaceFileMenu();
        return;
      }
      const workspace = byId("workspace-input").value.trim() || ".";
      const params = new URLSearchParams({ workspace, q: query, limit: "20" });
      const result = await getJson(`/api/workspace/tree?${params.toString()}`);
      if (state.fileMentionQuery !== query) return;
      if (!result.ok) {
        renderWorkspaceFileMenu([], result.data.detail || "Workspace search failed.");
        return;
      }
      renderWorkspaceFileMenu(result.data.files || [], "");
    }

    function currentFileMentionQuery() {
      const input = byId("prompt-input");
      const beforeCursor = input.value.slice(0, input.selectionStart || 0);
      const match = beforeCursor.match(/(?:^|\\s)@([^\\s@]*)$/);
      return match ? match[1] : null;
    }

    function renderWorkspaceFileMenu(files, error) {
      const menu = byId("workspace-file-menu");
      menu.textContent = "";
      if (error) {
        const item = document.createElement("button");
        item.className = "workspace-file-option";
        item.type = "button";
        item.disabled = true;
        item.textContent = error;
        menu.appendChild(item);
        menu.hidden = false;
        return;
      }
      if (!files.length) {
        hideWorkspaceFileMenu();
        return;
      }
      for (const file of files) {
        const item = document.createElement("button");
        item.className = "workspace-file-option";
        item.type = "button";
        item.textContent = `${file.path} (${formatBytes(file.size_bytes || 0)})`;
        item.addEventListener("click", () => attachWorkspaceFile(file.path));
        menu.appendChild(item);
      }
      menu.hidden = false;
    }

    function hideWorkspaceFileMenu() {
      const menu = byId("workspace-file-menu");
      if (menu) {
        menu.textContent = "";
        menu.hidden = true;
      }
    }

    async function attachWorkspaceFile(path) {
      if (!(await ensureSessionForAttachments())) return;
      const workspace = byId("workspace-input").value.trim() || ".";
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/attachments/workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace, path })
      });
      if (!result.ok || !result.data.attachment) {
        setText("attachment-status", result.data.detail || "Workspace attachment failed.");
        return;
      }
      state.attachments.push(result.data.attachment);
      replaceCurrentFileMention(path);
      hideWorkspaceFileMenu();
      renderAttachments();
      await loadSessions();
    }

    function replaceCurrentFileMention(path) {
      const input = byId("prompt-input");
      const start = input.selectionStart || 0;
      const beforeCursor = input.value.slice(0, start);
      const afterCursor = input.value.slice(input.selectionEnd || start);
      const replaced = beforeCursor.replace(/(?:^|\\s)@([^\\s@]*)$/, (match) => {
        const prefix = match.startsWith("@") ? "" : match.slice(0, 1);
        return `${prefix}@${path} `;
      });
      input.value = replaced + afterCursor;
      input.focus();
      input.selectionStart = input.selectionEnd = replaced.length;
    }

    function renderAttachments() {
      const list = byId("attachment-list");
      if (!list) return;
      list.textContent = "";
      if (!state.attachments.length) {
        setText("attachment-status", "No attachments");
        scheduleRouteRecommendation();
        return;
      }
      setText("attachment-status", `${state.attachments.length} attachment${state.attachments.length === 1 ? "" : "s"}`);
      for (const attachment of state.attachments) {
        const card = document.createElement("div");
        card.className = "attachment-card";
        const warning = attachmentWarning(attachment);
        card.innerHTML = `
          <span class="attachment-name">${escapeHtml(attachment.filename || attachment.id)}</span>
          <span class="badge info">${escapeHtml(attachment.kind || "attachment")}</span>
          <span class="status-line">${escapeHtml(attachment.mime_type || "")} ${escapeHtml(formatBytes(attachment.size_bytes || 0))}</span>
          ${warning ? `<span class="badge warn">${escapeHtml(warning)}</span>` : ""}
        `;
        const remove = document.createElement("button");
        remove.className = "attachment-remove";
        remove.type = "button";
        remove.textContent = "x";
        remove.addEventListener("click", () => removeAttachment(attachment.id));
        card.appendChild(remove);
        list.appendChild(card);
      }
      scheduleRouteRecommendation();
    }

    function attachmentWarning(attachment) {
      const harnessId = currentHarnessId();
      const supported = attachment.supported_by || {};
      if (Object.prototype.hasOwnProperty.call(supported, harnessId) && !supported[harnessId]) {
        const warning = (attachment.warnings || []).find((item) => String(item).startsWith(`${harnessId} `));
        return warning || `${harnessId} does not accept this attachment`;
      }
      if (attachment.kind === "image" && harnessId === "gemini-cli") {
        return "path reference only";
      }
      return "";
    }

    function formatBytes(value) {
      const bytes = Number(value) || 0;
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    function applySessionDefaults(session) {
      if (session.default_harness_id) selectHarness(session.default_harness_id);
      byId("model-input").value = session.default_model || state.defaults.default_model || "";
      renderModelList();
      const mode = session.default_api_mode || state.defaults.default_api_mode || "v2";
      byId(`api-mode-${mode}`).checked = true;
      byId("mode-select").value = session.default_mode || "plan";
      byId("workspace-input").value = session.workspace || "";
      updateRouteNote();
    }

    function applyRunDefaults(payload) {
      if (payload.harness_id) selectHarness(payload.harness_id);
      byId("model-input").value = payload.model || state.defaults.default_model || "";
      renderModelList();
      const mode = payload.api_mode || state.defaults.default_api_mode || "v2";
      byId(`api-mode-${mode}`).checked = true;
      byId("mode-select").value = payload.mode || "plan";
      byId("workspace-input").value = payload.workspace || "";
      applyBuiltinTools(payload.builtin_tools || []);
      updateRouteNote();
    }

    async function newChat() {
      const payload = buildSessionDefaults();
      const result = await getJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (result.ok) {
        byId("prompt-input").value = "";
        state.attachments = [];
        renderAttachments();
        await loadSession(result.data.session.id);
      }
    }

    function buildSessionDefaults() {
      return {
        harness_id: currentHarnessId(),
        model: byId("model-input").value.trim() || null,
        api_mode: currentApiMode(),
        mode: byId("mode-select").value,
        workspace_policy: byId("workspace-policy-select").value || "auto",
        workspace: byId("workspace-input").value.trim() || null
      };
    }

    function buildPayload() {
      const payload = {
        ...buildSessionDefaults(),
        prompt: byId("prompt-input").value,
        capability: byId("capability-select").value || "chat_completions",
        invocation_mode: currentInvocationMode(),
        permission_profile: byId("permission-profile-select").value || "interactive",
        stream: usesStructuredWorkChat() ? true : byId("stream-checkbox").checked,
        dry_run: byId("dry-run-checkbox").checked
      };
      const builtinTools = selectedBuiltinTools();
      if (builtinTools.length) payload.builtin_tools = builtinTools;
      const attachmentIds = state.attachments.map((attachment) => attachment.id).filter(Boolean);
      if (attachmentIds.length) payload.attachment_ids = attachmentIds;
      return payload;
    }

    function buildArenaPayload() {
      return {
        prompt: byId("arena-prompt-input").value,
        harness_ids: arenaSelectedHarnessIds(),
        model: byId("arena-model-input").value.trim() || null,
        api_mode: byId("arena-api-mode-select").value || "v2",
        mode: byId("arena-mode-select").value || "plan",
        workspace_policy: byId("arena-workspace-policy-select").value || "auto",
        workspace: byId("arena-workspace-input").value.trim() || null,
        session_id: null
      };
    }

    function buildRecommendationPayload() {
      const attachments = state.attachments.map((attachment) => ({
        id: attachment.id,
        kind: attachment.kind,
        filename: attachment.filename,
        mime_type: attachment.mime_type,
        size_bytes: attachment.size_bytes,
        workspace_path: attachment.workspace_path || null,
        source: attachment.source || null,
        metadata: attachment.metadata || {}
      }));
      return {
        prompt: byId("prompt-input").value,
        mode: byId("mode-select").value,
        workspace: byId("workspace-input").value.trim() || null,
        current_harness_id: currentHarnessId(),
        attachments,
        selected_files: attachments.map((attachment) => attachment.workspace_path).filter(Boolean)
      };
    }

    function scheduleRouteRecommendation() {
      if (state.routeRecommendationTimer) clearTimeout(state.routeRecommendationTimer);
      state.routeRecommendationTimer = window.setTimeout(refreshRouteRecommendation, 250);
    }

    async function refreshRouteRecommendation() {
      if (!state.harnesses.length) return;
      const payload = buildRecommendationPayload();
      if (!payload.prompt.trim() && !payload.attachments.length && !payload.workspace) {
        state.routeRecommendation = null;
        renderRouteRecommendation(null);
        return;
      }
      const result = await getJson("/api/route/recommendation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!result.ok || !result.data.recommendation) {
        state.routeRecommendation = null;
        setText("route-recommendation-badge", "Recommended: unavailable");
        byId("route-recommendation-badge").className = "badge warn";
        setText("route-recommendation-reasons", result.data.detail || "Recommendation failed.");
        byId("apply-route-recommendation-button").disabled = true;
        renderHarnessCards();
        return;
      }
      state.routeRecommendation = result.data.recommendation;
      renderRouteRecommendation(state.routeRecommendation);
    }

    function renderRouteRecommendation(recommendation) {
      const badge = byId("route-recommendation-badge");
      const applyButton = byId("apply-route-recommendation-button");
      if (!recommendation) {
        badge.className = "badge info";
        badge.textContent = "Recommended: pending";
        setText("route-recommendation-reasons", "Type a prompt or attach context to refresh the recommendation.");
        applyButton.disabled = true;
        renderHarnessCards();
        return;
      }
      const current = recommendation.harness_id === currentHarnessId()
        && recommendation.mode === byId("mode-select").value
        && recommendation.invocation_mode === currentInvocationMode();
      badge.className = current ? "badge ok" : "badge info";
      const confidence = Math.round(Number(recommendation.confidence || 0) * 100);
      badge.textContent = `Recommended: ${harnessTitle(recommendation.harness_id)} (${confidence}%)`;
      const reasons = Array.isArray(recommendation.reasons) ? recommendation.reasons : [];
      const warnings = Array.isArray(recommendation.warnings) ? recommendation.warnings : [];
      const lines = [
        ...reasons.map((reason) => `- ${reason}`),
        ...warnings.map((warning) => `! ${warning}`)
      ];
      setText("route-recommendation-reasons", lines.join("\\n") || "No recommendation details.");
      applyButton.disabled = current;
      renderHarnessCards();
    }

    function applyRouteRecommendation() {
      const recommendation = state.routeRecommendation;
      if (!recommendation || !recommendation.harness_id) return;
      selectHarness(recommendation.harness_id);
      if (recommendation.mode && byId("mode-select").querySelector(`option[value="${recommendation.mode}"]`)) {
        byId("mode-select").value = recommendation.mode;
      }
      if (recommendation.invocation_mode) {
        byId("invocation-select").value = recommendation.invocation_mode;
      }
      updateHarnessDrivenControls();
      renderRouteRecommendation(recommendation);
      persistProjectState();
    }

    function renderPresetButtons() {
      const list = byId("preset-list");
      list.textContent = "";
      const presets = Array.isArray(state.projectPresets) ? state.projectPresets : [];
      setText("preset-status", presets.length ? `Presets: ${presets.length}` : "Presets: none");
      if (!presets.length) {
        const empty = document.createElement("span");
        empty.className = "status-line";
        empty.textContent = "No project presets configured.";
        list.appendChild(empty);
        return;
      }
      for (const preset of presets) {
        const button = document.createElement("button");
        button.className = "secondary preset-button";
        button.type = "button";
        button.textContent = preset.title || preset.name;
        button.title = preset.name || preset.title || "preset";
        button.addEventListener("click", () => applyPreset(preset.name));
        list.appendChild(button);
      }
    }

    async function applyPreset(presetName) {
      if (!presetName || !state.project || !state.project.root) return;
      const result = await getJson(`/api/project/presets/${encodeURIComponent(presetName)}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: state.project.root,
          user_prompt: byId("prompt-input").value,
          selected_files: selectedWorkspaceFiles(),
          last_run_diff: currentLastDiff()
        })
      });
      const body = result.data || {};
      if (!result.ok || !body.preset) {
        setText("preset-status", body.detail || "Preset failed.");
        return;
      }
      const preset = body.preset;
      if (preset.harness) selectHarness(preset.harness);
      if (preset.model) {
        byId("model-input").value = preset.model;
        renderModelList();
      }
      if (preset.api_mode) {
        const apiMode = byId(`api-mode-${preset.api_mode}`);
        if (apiMode) apiMode.checked = true;
      }
      if (preset.mode && byId("mode-select").querySelector(`option[value="${preset.mode}"]`)) {
        byId("mode-select").value = preset.mode;
      }
      if (preset.invocation_mode) byId("invocation-select").value = preset.invocation_mode;
      if (preset.workspace_policy && byId("workspace-policy-select").querySelector(`option[value="${preset.workspace_policy}"]`)) {
        byId("workspace-policy-select").value = preset.workspace_policy;
      }
      byId("prompt-input").value = preset.prompt || "";
      updateHeaderBadges();
      updateRouteNote();
      updateHarnessDrivenControls();
      scheduleRouteRecommendation();
      persistProjectState();
      const warnings = Array.isArray(preset.warnings) && preset.warnings.length ? ` (${preset.warnings.length} warning)` : "";
      setText("preset-status", `Preset: ${preset.title || preset.name}${warnings}`);
    }

    async function loadMemory() {
      if (!state.project || !state.project.root) {
        state.projectMemory = [];
        state.memoryError = null;
        renderMemoryPanel();
        return;
      }
      const result = await getJson(`/api/project/memory?workspace=${encodeURIComponent(state.project.root)}&include_disabled=true`);
      if (!result.ok) {
        state.projectMemory = [];
        state.memoryError = result.data.detail || "Memory unavailable";
        renderMemoryPanel();
        return;
      }
      state.projectMemory = Array.isArray(result.data.memories) ? result.data.memories : [];
      state.memoryError = null;
      renderMemoryPanel();
    }

    async function addMemoryFromInput() {
      if (!state.project || !state.project.root) return;
      const text = byId("memory-input").value.trim();
      if (!text) return;
      const result = await getJson("/api/project/memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: state.project.root,
          text,
          tags: memoryTagsFromInput(),
          source_session_id: state.currentSessionId || null,
          source_run_id: currentRun() && currentRun().id ? currentRun().id : null
        })
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory add failed.";
        renderMemoryPanel();
        return;
      }
      byId("memory-input").value = "";
      byId("memory-tags-input").value = "";
      await loadMemory();
      showTab("memory");
    }

    async function rememberLastMessage() {
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      const message = [...messages].reverse().find((item) => item.content);
      if (!message) return;
      byId("memory-input").value = message.content || "";
      byId("memory-tags-input").value = "message";
      await addMemoryFromInput();
    }

    async function setMemoryEnabled(memoryId, enabled) {
      if (!state.project || !state.project.root || !memoryId) return;
      const result = await getJson(`/api/project/memory/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, enabled })
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory update failed.";
        renderMemoryPanel();
        return;
      }
      await loadMemory();
    }

    async function editMemory(memoryId) {
      const memory = state.projectMemory.find((item) => item.id === memoryId);
      if (!memory || !state.project || !state.project.root) return;
      const text = window.prompt("Edit memory", memory.text || "");
      if (text == null) return;
      const result = await getJson(`/api/project/memory/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, text })
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory edit failed.";
        renderMemoryPanel();
        return;
      }
      await loadMemory();
    }

    async function deleteMemory(memoryId) {
      if (!state.project || !state.project.root || !memoryId) return;
      const params = new URLSearchParams({ workspace: state.project.root });
      const result = await getJson(`/api/project/memory/${encodeURIComponent(memoryId)}?${params.toString()}`, {
        method: "DELETE"
      });
      if (!result.ok) {
        state.memoryError = result.data.detail || "Memory delete failed.";
        renderMemoryPanel();
        return;
      }
      await loadMemory();
    }

    function memoryTagsFromInput() {
      return byId("memory-tags-input").value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function renderMemoryPanel() {
      const list = byId("memory-list");
      if (!list) return;
      list.textContent = "";
      const memories = Array.isArray(state.projectMemory) ? state.projectMemory : [];
      const enabledCount = memories.filter((memory) => memory.enabled !== false).length;
      setText("memory-status", state.memoryError || (memories.length ? `Memory: ${enabledCount}/${memories.length} enabled` : "Memory: none"));
      byId("remember-message-button").disabled = !lastPromotableMessage();
      if (state.memoryError) {
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = state.memoryError;
        list.appendChild(error);
        return;
      }
      if (!memories.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No project memory saved.";
        list.appendChild(empty);
        return;
      }
      for (const memory of memories) {
        list.appendChild(memoryCard(memory));
      }
    }

    function memoryCard(memory) {
      const card = document.createElement("div");
      card.className = "tool-profile-card";
      const tags = Array.isArray(memory.tags) && memory.tags.length ? memory.tags.join(", ") : "untagged";
      const enabled = memory.enabled !== false;
      card.innerHTML = `
        <div class="tool-profile-title">
          <span>${escapeHtml(memory.id || "memory")}</span>
          <span class="${enabled ? "badge ok" : "badge"}">${enabled ? "enabled" : "disabled"}</span>
          <span class="badge info">${escapeHtml(tags)}</span>
        </div>
        <div class="details">${escapeHtml(memory.text || "")}</div>
      `;
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      actions.appendChild(memoryActionButton(enabled ? "Disable" : "Enable", () => setMemoryEnabled(memory.id, !enabled)));
      actions.appendChild(memoryActionButton("Edit", () => editMemory(memory.id)));
      actions.appendChild(memoryActionButton("Delete", () => deleteMemory(memory.id), "danger"));
      card.appendChild(actions);
      return card;
    }

    function memoryActionButton(label, handler, className = "secondary") {
      const button = document.createElement("button");
      button.className = className;
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    }

    function lastPromotableMessage() {
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      return [...messages].reverse().find((item) => item.content);
    }

    async function loadTools() {
      if (!state.project || !state.project.root) {
        state.toolProfiles = [];
        state.toolSyncPreview = null;
        state.toolError = null;
        renderToolsPanel();
        return;
      }
      const result = await getJson(`/api/tools?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        state.toolProfiles = [];
        state.toolSyncPreview = null;
        state.toolError = result.data.detail || "Tools unavailable";
        renderToolsPanel();
        return;
      }
      state.toolProfiles = Array.isArray(result.data.profiles) ? result.data.profiles : [];
      state.toolSyncPreview = null;
      state.toolError = null;
      renderToolsPanel();
    }

    async function syncTools() {
      if (!state.project || !state.project.root) return;
      setText("tools-status", "Tools: dry-run syncing");
      const result = await getJson("/api/tools/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: state.project.root, dry_run: true })
      });
      if (!result.ok) {
        setText("tools-status", result.data.detail || "Tool sync failed.");
        return;
      }
      state.toolSyncPreview = result.data;
      state.toolProfiles = Array.isArray(result.data.profiles) ? result.data.profiles : state.toolProfiles;
      renderToolsPanel();
      showTab("tools");
    }

    function renderToolsPanel() {
      const list = byId("tool-profile-list");
      if (!list) return;
      list.textContent = "";
      const run = currentRun();
      const metadata = run && run.metadata && typeof run.metadata === "object" ? run.metadata : {};
      const bindings = Array.isArray(metadata.tool_profile_bindings)
        ? metadata.tool_profile_bindings
        : Array.isArray(metadata.tool_profiles) ? metadata.tool_profiles : [];
      setText("tools-status", bindings.length ? `Run tools: ${bindings.length}` : "Run tools: none");
      const summary = document.createElement("div");
      summary.className = "status-line";
      summary.textContent = bindings.length
        ? `Recorded bindings: ${bindings.join(", ")}`
        : "No MCP/tool bindings were recorded for this run.";
      list.appendChild(summary);
      setText("tool-sync-preview", "Open Tools for connection health, schemas, policies, compatibility, and probe history.");
    }

    function toolProfileCard(item) {
      const profile = item.profile || {};
      const card = document.createElement("div");
      card.className = "tool-profile-card";
      const title = document.createElement("div");
      title.className = "tool-profile-title";
      title.innerHTML = `
        <span>${escapeHtml(profile.title || item.name || "tool")}</span>
        <span class="${toolStatusBadgeClass(profile.enabled ? "ready" : "disabled")}">${escapeHtml(profile.enabled ? "enabled" : "disabled")}</span>
        <span class="badge info">${escapeHtml(profile.kind || "mcp")}</span>
      `;
      card.appendChild(title);
      if (profile.description) {
        const description = document.createElement("div");
        description.className = "details";
        description.textContent = profile.description;
        card.appendChild(description);
      }
      const statuses = document.createElement("div");
      statuses.className = "tool-profile-statuses";
      for (const status of item.harnesses || []) {
        const badge = document.createElement("span");
        badge.className = toolStatusBadgeClass(status.status);
        badge.title = status.reason || "";
        badge.textContent = `${harnessTitle(status.harness_id)}: ${status.status}`;
        statuses.appendChild(badge);
      }
      card.appendChild(statuses);
      const warnings = [
        ...(Array.isArray(item.warnings) ? item.warnings : []),
        ...(item.harnesses || []).flatMap((status) => Array.isArray(status.warnings) ? status.warnings : [])
      ];
      if (warnings.length) {
        const warning = document.createElement("div");
        warning.className = "warning";
        warning.textContent = warnings.join(" ");
        card.appendChild(warning);
      }
      return card;
    }

    function toolStatusBadgeClass(status) {
      if (status === "ready") return "badge ok";
      if (status === "disabled") return "badge";
      if (status === "missing" || status === "unsupported") return "badge warn";
      return "badge info";
    }

    async function loadEvals() {
      if (!state.project || !state.project.root) {
        state.evalSpecs = [];
        state.evalRuns = [];
        state.evalErrors = [];
        state.currentEvalRun = null;
        state.evalError = null;
        renderEvalsPanel();
        return;
      }
      const result = await getJson(`/api/evals?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        state.evalSpecs = [];
        state.evalRuns = [];
        state.evalErrors = [];
        state.currentEvalRun = null;
        state.evalError = result.data.detail || "Evals unavailable";
        renderEvalsPanel();
        return;
      }
      state.evalSpecs = Array.isArray(result.data.specs) ? result.data.specs : [];
      state.evalRuns = Array.isArray(result.data.runs) ? result.data.runs : [];
      state.evalErrors = Array.isArray(result.data.errors) ? result.data.errors : [];
      state.currentEvalRun = state.currentEvalRun || state.evalRuns[0] || null;
      state.evalError = null;
      renderEvalsPanel();
    }

    async function runSelectedEval() {
      const select = byId("eval-spec-select");
      const evalName = select && select.value ? select.value : "";
      if (!evalName || !state.project || !state.project.root) return;
      setText("evals-status", "Evals: running");
      const result = await getJson(`/api/evals/${encodeURIComponent(evalName)}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: state.project.root,
          harness_ids: evalHarnessOverride(),
          model: byId("model-input").value.trim() || null,
          api_mode: selectedApiMode(),
          mode: byId("mode-select").value,
          workspace_policy: byId("workspace-policy-select").value,
          dry_run: byId("dry-run-checkbox").checked
        })
      });
      if (!result.ok || !result.data.eval_run) {
        state.evalError = result.data.detail || `Eval failed with HTTP ${result.status}`;
        renderEvalsPanel();
        showTab("evals");
        return;
      }
      state.currentEvalRun = result.data.eval_run;
      state.evalRuns = [result.data.eval_run, ...state.evalRuns.filter((item) => item.id !== result.data.eval_run.id)];
      state.evalError = null;
      renderEvalsPanel();
      showTab("evals");
    }

    function evalHarnessOverride() {
      const input = byId("eval-harness-input");
      if (!input || !input.value.trim()) return [];
      return input.value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function renderEvalsPanel() {
      const select = byId("eval-spec-select");
      const list = byId("eval-spec-list");
      if (!select || !list) return;
      const selected = select.value;
      select.textContent = "";
      list.textContent = "";
      const specs = Array.isArray(state.evalSpecs) ? state.evalSpecs : [];
      const errors = Array.isArray(state.evalErrors) ? state.evalErrors : [];
      const run = state.currentEvalRun || state.evalRuns[0] || null;
      const statusText = state.evalError
        || (specs.length ? `Evals: ${specs.length} spec${specs.length === 1 ? "" : "s"}` : "Evals: none");
      setText("evals-status", statusText);
      byId("run-eval-button").disabled = !specs.length;
      if (!specs.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No eval specs";
        select.appendChild(option);
      }
      for (const spec of specs) {
        const option = document.createElement("option");
        option.value = spec.name || "";
        option.textContent = `${spec.name || "eval"} (${spec.case_count || 0})`;
        select.appendChild(option);
      }
      if (selected && Array.from(select.options).some((option) => option.value === selected)) {
        select.value = selected;
      }
      if (state.evalError) {
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = state.evalError;
        list.appendChild(error);
      }
      for (const errorItem of errors) {
        const error = document.createElement("div");
        error.className = "warning";
        error.textContent = `${errorItem.path || "eval"}: ${errorItem.message || "parse failed"}`;
        list.appendChild(error);
      }
      if (!specs.length && !errors.length && !state.evalError) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No project eval specs found under .giga/evals.";
        list.appendChild(empty);
      }
      for (const spec of specs) {
        list.appendChild(evalSpecCard(spec));
      }
      setText("eval-scorecard", run ? evalRunScorecard(run) : "No eval run selected.");
    }

    function evalSpecCard(spec) {
      const card = document.createElement("div");
      card.className = "tool-profile-card";
      const harnesses = Array.isArray(spec.harnesses) && spec.harnesses.length ? spec.harnesses.join(", ") : "echo";
      card.innerHTML = `
        <div class="tool-profile-title">
          <span>${escapeHtml(spec.name || "eval")}</span>
          <span class="badge info">${escapeHtml(String(spec.case_count || 0))} cases</span>
          <span class="badge info">${escapeHtml(harnesses)}</span>
        </div>
        <div class="details">${escapeHtml(spec.description || spec.path || "")}</div>
      `;
      return card;
    }

    function evalRunScorecard(run) {
      const summary = run.summary || {};
      const lines = [
        `Eval: ${run.spec_name || ""} (${run.id || ""})`,
        `Status: ${run.status || "unknown"}`,
        `Score: ${summary.passed || 0}/${summary.total || 0} passed, ${summary.failed || 0} failed, ${summary.errors || 0} errors`,
        `Session: ${run.session_id || "-"}`,
        ""
      ];
      const results = Array.isArray(run.results) ? run.results : [];
      for (const item of results) {
        lines.push(`${item.case_id || "case"} / ${item.harness_id || "harness"}: ${item.status || "unknown"} (${Number(item.score || 0).toFixed(2)})`);
        const checks = Array.isArray(item.checks) ? item.checks : [];
        for (const check of checks) {
          lines.push(`  - ${check.passed ? "pass" : "fail"} ${check.type || "check"}: ${check.message || ""}`);
        }
        if (item.error) lines.push(`  error: ${item.error}`);
      }
      return lines.join("\\n");
    }

    function selectedWorkspaceFiles() {
      return state.attachments
        .map((attachment) => attachment.workspace_path)
        .filter(Boolean);
    }

    async function confirmRunPreflight(payload) {
      const result = await getJson("/api/preflight/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          session_id: state.currentSessionId || null
        })
      });
      const body = result.data || {};
      if (!result.ok || !body.preflight) {
        setText("run-panel", body.detail || `Preflight failed with HTTP ${result.status}`);
        showTab("run");
        return false;
      }
      const report = body.preflight;
      state.pendingPreflight = report;
      state.pendingPreflightPayload = payload;
      if (!Array.isArray(report.findings) || !report.findings.length) return true;
      return openPreflightModal(report, payload);
    }

    function openPreflightModal(report, payload) {
      renderPreflightModal(report, payload);
      byId("preflight-modal").hidden = false;
      state.preflightModalOpen = true;
      return new Promise((resolve) => {
        state.preflightDecisionResolver = resolve;
      });
    }

    function closePreflightModal(allowRun = false) {
      byId("preflight-modal").hidden = true;
      state.preflightModalOpen = false;
      const resolver = state.preflightDecisionResolver;
      state.preflightDecisionResolver = null;
      if (resolver) resolver(Boolean(allowRun));
    }

    function renderPreflightModal(report, payload) {
      const findings = Array.isArray(report.findings) ? report.findings : [];
      const hardBlock = report.hard_block === true || findings.some((finding) => finding.severity === "block");
      setText("preflight-status", hardBlock ? "Hard block: remove blocked context first" : `${findings.length} warning${findings.length === 1 ? "" : "s"}`);
      setText("preflight-footer-status", hardBlock ? "Blocked findings cannot be continued." : "Only warning-level findings can continue.");
      byId("continue-preflight-button").hidden = hardBlock;
      byId("continue-preflight-button").disabled = hardBlock;
      setText("preflight-budget", preflightBudgetText(report.context_budget || {}));
      const list = byId("preflight-finding-list");
      list.textContent = "";
      for (const finding of findings) {
        list.appendChild(preflightFindingCard(finding));
      }
      if (!findings.length) {
        const empty = document.createElement("div");
        empty.className = "status-line";
        empty.textContent = "No preflight findings.";
        list.appendChild(empty);
      }
      setText("raw-request-panel", pretty({ ...payload, preflight: report }));
    }

    function preflightFindingCard(finding) {
      const card = document.createElement("div");
      card.className = "preflight-finding";
      const badgeClass = finding.severity === "block" ? "badge error" : finding.severity === "warning" ? "badge warn" : "badge info";
      card.innerHTML = `
        <div class="tool-profile-title">
          <span class="${badgeClass}">${escapeHtml(finding.severity || "info")}</span>
          <span>${escapeHtml(finding.message || finding.code || "Preflight finding")}</span>
        </div>
        <div class="details">${escapeHtml(finding.subject || finding.workspace_path || finding.code || "")}</div>
      `;
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      const allowedActions = Array.isArray(finding.actions) ? finding.actions : [];
      if (finding.attachment_id && allowedActions.includes("exclude_attachment")) {
        actions.appendChild(preflightActionButton("Exclude file", () => excludePreflightAttachment(finding.attachment_id)));
      }
      if (finding.attachment_id && finding.workspace_path && allowedActions.includes("send_path_only")) {
        actions.appendChild(preflightActionButton("Send path only", () => sendPreflightPathOnly(finding.attachment_id, finding.workspace_path)));
      }
      if (actions.childNodes.length) card.appendChild(actions);
      return card;
    }

    function preflightActionButton(label, handler) {
      const button = document.createElement("button");
      button.className = "secondary";
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    }

    function excludePreflightAttachment(attachmentId) {
      state.attachments = state.attachments.filter((attachment) => attachment.id !== attachmentId);
      renderAttachments();
      scheduleRouteRecommendation();
      closePreflightModal(false);
    }

    function sendPreflightPathOnly(attachmentId, workspacePath) {
      state.attachments = state.attachments.filter((attachment) => attachment.id !== attachmentId);
      const prompt = byId("prompt-input");
      const line = `Reference path only: @${workspacePath}`;
      prompt.value = prompt.value.trim() ? `${prompt.value.trim()}\\n\\n${line}` : line;
      renderAttachments();
      scheduleRouteRecommendation();
      closePreflightModal(false);
    }

    function preflightBudgetText(budget) {
      const lines = [
        `Estimated tokens: ${budget.total_estimated_tokens || 0}`,
        `Prompt: ${budget.prompt_tokens || 0} tokens / ${budget.prompt_chars || 0} chars`,
        `Project memory: ${budget.project_memory_count || 0} entries / ${budget.project_memory_tokens || 0} tokens`,
        `Previous chat: ${budget.included_previous_message_count || 0}/${budget.previous_message_count || 0} messages / ${budget.previous_message_tokens || 0} tokens`,
        `Attachments: ${budget.attached_file_count || 0} files / ${formatBytes(budget.attached_file_bytes || 0)} / ${budget.attachment_tokens || 0} estimated tokens`,
        `Images: ${budget.image_count || 0} / ${formatBytes(budget.image_bytes || 0)}`
      ];
      const warnings = Array.isArray(budget.truncation_warnings) ? budget.truncation_warnings : [];
      if (warnings.length) {
        lines.push("");
        lines.push("Truncation warnings:");
        for (const warning of warnings) lines.push(`- ${warning}`);
      }
      return lines.join("\\n");
    }

    function currentLastDiff() {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      for (let index = runs.length - 1; index >= 0; index -= 1) {
        const run = runs[index] || {};
        const metadata = run.metadata || {};
        if (metadata.diff) return String(metadata.diff);
      }
      return "";
    }

    async function runHarness(delivery = "queue") {
      const payload = buildPayload();
      if (!payload.prompt.trim()) return;
      if (!(await confirmRunPreflight(payload))) return;
      setAdvancedSettings(false);
      if (!(await retireLegacyNativeProcessForStructuredChat())) return;
      if (activeNativeConversation()) {
        await continueNativeConversation(payload);
        return;
      }
      if (state.activeHeadlessRun && state.activeHeadlessRun.id) {
        await queueHeadlessMessage(payload, { interrupt: delivery === "interrupt" });
        return;
      }
      if (payload.invocation_mode === "native" && currentHarnessSupportsNative()) {
        await startNativeProcess(payload);
        return;
      }
      await startHeadlessStream(payload);
    }

    async function loadArenaCenter(options = {}) {
      const hydrateControls = options.hydrateControls !== false;
      let result;
      if (state.currentArena && state.currentArena.id) {
        result = await getJson(`/api/arena/runs/${encodeURIComponent(state.currentArena.id)}`);
      } else {
        const params = new URLSearchParams({ limit: "1" });
        const workspace = state.project && state.project.root ? state.project.root : byId("arena-workspace-input").value.trim();
        if (workspace) params.set("workspace", workspace);
        result = await getJson(`/api/arena/runs?${params.toString()}`);
      }
      if (!result.ok) {
        setText("arena-center-status", result.data.detail || "Arena history is unavailable.");
        return false;
      }
      const arena = result.data.arena || (Array.isArray(result.data.arenas) ? result.data.arenas[0] : null);
      if (!arena) {
        state.currentArena = null;
        renderArenaCenter(null);
        updateArenaStatus(null);
        stopArenaRefresh();
        return true;
      }
      state.currentArena = arena;
      if (hydrateControls) applyArenaToControls(arena);
      renderArenaCenter(arena);
      updateArenaStatus(arena);
      scheduleArenaRefresh(arena);
      return true;
    }

    async function runArena() {
      const payload = buildArenaPayload();
      if (!payload.prompt.trim()) {
        setText("arena-center-status", "Enter a prompt to compare responses.");
        byId("arena-prompt-input").focus();
        return;
      }
      if (!payload.harness_ids.length) {
        setText("arena-center-status", "Select at least one response format.");
        return;
      }
      state.lastPayload = payload;
      setText("arena-center-status", "Starting comparison...");
      setText("arena-results-status", `${payload.harness_ids.length} responses requested.`);
      setText("arena-panel", "Arena is starting...");
      byId("arena-compare-button").disabled = true;
      byId("arena-compare-button").textContent = "Comparing...";
      try {
        const result = await getJson("/api/arena/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const body = result.data || {};
        if (!result.ok || !body.arena) {
          setText("arena-panel", body.detail || `Arena failed with HTTP ${result.status}`);
          setText("arena-center-status", "Comparison failed.");
          setText("arena-results-status", body.detail || `HTTP ${result.status}`);
          return;
        }
        state.currentArena = body.arena;
        renderArenaCenter(state.currentArena);
        updateArenaStatus(state.currentArena);
        scheduleArenaRefresh(state.currentArena);
      } finally {
        byId("arena-compare-button").disabled = false;
        byId("arena-compare-button").textContent = "Compare responses";
      }
    }

    async function startHeadlessStream(payload) {
      state.lastPayload = payload;
      closeHeadlessEventSource();
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      renderDiffInspector(null);
      renderPrInspector(null);
      setText("run-panel", "Queueing durable run...");
      renderEvents([]);
      setHeadlessRunning(true);
      try {
        const url = state.currentSessionId ? `/api/sessions/${encodeURIComponent(state.currentSessionId)}/run/start` : "/api/sessions/run/start";
        const result = await getJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const body = result.data || {};
        if (!result.ok || !body.run) {
          setText("raw-response-panel", pretty(body));
          setText("run-panel", body.detail || `Stream start failed with HTTP ${result.status}`);
          setHeadlessRunning(false);
          return;
        }
        state.currentSessionId = body.session && body.session.id ? body.session.id : state.currentSessionId;
        state.activeHeadlessRun = body.run;
        ensureLiveRun(body.run.id, body.run);
        if (state.currentSessionId) {
          await loadSession(state.currentSessionId);
          applyRunDefaults(payload);
          persistProjectState({ last_selected_session: state.currentSessionId });
        }
        clearAcceptedComposer();
        setHeadlessRunning(true);
        const initialEvents = Array.isArray(body.events) ? body.events : [];
        for (const event of [...eventsForRun(body.run.id), ...initialEvents]) consumeLiveEvent(event);
        renderLiveDraft(body.run.id);
        renderRunSummary(runForId(body.run.id) || body.run, state.currentBundle && state.currentBundle.events ? state.currentBundle.events : initialEvents);
        if (body.job && body.job.status === "waiting_approval") {
          setHeadlessRunning(false);
          await loadApprovals();
          syncBrowserRoute("approvals", null);
          await applyCurrentRoute();
          return;
        }
        openHeadlessEventStream(body.run.id);
      } catch (error) {
        setText("run-panel", "Stream start failed.");
        setHeadlessRunning(false);
      }
    }

    function clearAcceptedComposer() {
      byId("prompt-input").value = "";
      state.attachments = [];
      renderAttachments();
      scheduleRouteRecommendation();
    }

    async function queueHeadlessMessage(payload, options = {}) {
      const activeRun = state.activeHeadlessRun || {};
      if (!state.currentSessionId || !activeRun.id) return;
      const interrupt = options.interrupt === true;
      byId("run-button").disabled = true;
      byId("interrupt-run-button").disabled = true;
      if (interrupt) {
        setText("run-panel", "Requesting stop before queueing the next message...");
        const stopped = await getJson(`/api/runs/${encodeURIComponent(activeRun.id)}/cancel`, {
          method: "POST"
        });
        if (!stopped.ok) {
          setText("run-panel", stopped.data.detail || "Interrupt failed.");
          setHeadlessRunning(true);
          return;
        }
      } else {
        setText("run-panel", "Queueing the next message...");
      }
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}/run/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const body = result.data || {};
      if (!result.ok || !body.run) {
        setText("run-panel", body.detail || `Queue failed with HTTP ${result.status}`);
        setHeadlessRunning(true);
        return;
      }
      state.lastPayload = payload;
      await loadSession(state.currentSessionId, { syncRoute: false });
      clearAcceptedComposer();
      setText(
        "run-panel",
        interrupt
          ? "Interrupt requested. The message will run after the current operation stops."
          : "Message queued. It will run after earlier turns finish."
      );
      if (body.job && body.job.status === "waiting_approval") await loadApprovals();
      setHeadlessRunning(Boolean(state.activeHeadlessRun));
    }

    function openHeadlessEventStream(runId) {
      if (state.headlessEventSource && state.headlessEventSourceRunId === runId) return;
      closeHeadlessEventSource();
      if (!window.EventSource) {
        setText("run-panel", "This browser does not support EventSource.");
        setHeadlessRunning(false);
        return;
      }
      const lastEventId = latestEventIdForRun(runId);
      const query = lastEventId ? `?after_id=${encodeURIComponent(lastEventId)}` : "";
      const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events/stream${query}`);
      state.headlessEventSource = source;
      state.headlessEventSourceRunId = runId;
      source.onmessage = (event) => {
        if (!state.activeHeadlessRun || state.activeHeadlessRun.id !== runId) return;
        let payload = {};
        try {
          payload = JSON.parse(event.data || "{}");
        } catch (error) {
          payload = { type: "warning", message: "Invalid event payload", payload: {} };
        }
        appendStreamEvent(payload);
        if (payload.type === "run_finished") {
          finishHeadlessStream(runId);
        }
      };
      source.onerror = () => {
        const run = state.activeHeadlessRun || {};
        if (run.id === runId && ["succeeded", "failed", "canceled"].includes(run.status)) {
          finishHeadlessStream(runId);
        }
      };
    }

    function appendStreamEvent(event) {
      if (!state.currentBundle) state.currentBundle = { events: [], runs: [] };
      if (!Array.isArray(state.currentBundle.events)) state.currentBundle.events = [];
      const exists = event.id && state.currentBundle.events.some((item) => item.id === event.id);
      if (!exists) state.currentBundle.events.push(event);
      const draft = consumeLiveEvent(event);
      renderEvents(state.currentBundle.events);
      if (event.type === "run_finished" && event.payload && event.payload.status) {
        state.activeHeadlessRun = {
          ...(state.activeHeadlessRun || {}),
          status: event.payload.status
        };
      }
      if (draft) {
        renderLiveDraft(draft.runId);
        renderRunSummary(runForId(draft.runId) || state.activeHeadlessRun, state.currentBundle.events);
      }
      if (event.type === "error" || event.type === "run_canceled") showTab("events");
    }

    async function finishHeadlessStream(runId) {
      if (!runId || !state.activeHeadlessRun || state.activeHeadlessRun.id !== runId) return;
      const draft = state.liveRuns.get(runId);
      closeHeadlessEventSource();
      state.activeHeadlessRun = null;
      setHeadlessRunning(false);
      if (state.currentSessionId) {
        await loadSession(state.currentSessionId);
        await loadSessions();
      }
      if (!preserveTerminalPartialDraft(draft)) {
        state.liveRuns.delete(runId);
        renderMessages();
      }
    }

    function closeHeadlessEventSource() {
      if (state.headlessEventSource) {
        state.headlessEventSource.close();
        state.headlessEventSource = null;
      }
      state.headlessEventSourceRunId = null;
    }

    function setHeadlessRunning(running) {
      const active = running && Boolean(state.activeHeadlessRun && state.activeHeadlessRun.id);
      byId("run-button").parentElement.classList.toggle("headless-running", active);
      byId("run-button").disabled = running && !active;
      if (active) byId("run-button").textContent = "Queue";
      else if (running) byId("run-button").textContent = "Starting...";
      else updateHarnessDrivenControls();
      byId("interrupt-run-button").hidden = !active;
      byId("interrupt-run-button").disabled = !active;
      byId("cancel-run-button").hidden = !active;
      byId("cancel-run-button").disabled = !active;
    }

    async function cancelHeadlessRun() {
      const run = state.activeHeadlessRun || {};
      if (!run.id) return;
      byId("cancel-run-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/cancel`, {
        method: "POST"
      });
      if (!result.ok) {
        appendStreamEvent({
          type: "error",
          message: result.data.detail || "Cancel failed.",
          payload: { status: result.status }
        });
        byId("cancel-run-button").disabled = false;
        return;
      }
      setText("run-panel", "Stop requested. The current operation may finish; no next step will start.");
    }

    async function startNativeProcess(payload) {
      if (!(await ensureSessionForNative(payload))) return;
      state.lastPayload = payload;
      setText("raw-request-panel", pretty(payload));
      setText("raw-response-panel", "{}");
      setText("command-panel", commandPreview(payload));
      setNativeSummary("Starting native process...");
      byId("run-button").disabled = true;
      byId("run-button").textContent = "Starting...";
      const pendingApproval = state.pendingNativeApproval;
      const reusePendingApproval = pendingApproval
        && pendingApproval.prompt === payload.prompt
        && pendingApproval.harnessId === payload.harness_id;
      const promptIdempotencyKey = reusePendingApproval
        ? pendingApproval.idempotencyKey
        : window.crypto && typeof window.crypto.randomUUID === "function"
          ? `native_prompt_${window.crypto.randomUUID()}`
          : `native_prompt_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      try {
        const result = await getJson("/api/native/processes/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: state.currentSessionId,
            action: "start",
            idempotency_key: promptIdempotencyKey,
            harness_id: payload.harness_id,
            prompt: payload.prompt,
            model: payload.model,
            api_mode: payload.api_mode,
            mode: payload.mode,
            workspace_policy: payload.workspace_policy || "auto",
            permission_profile: payload.permission_profile || "interactive",
            workspace: payload.workspace,
            attachment_ids: payload.attachment_ids || []
          })
        });
        if (!result.ok) {
          setNativeSummary(result.data.detail || `Native start failed with HTTP ${result.status}`);
          return;
        }
        if (result.data.approval_required) {
          const approval = result.data.approval || {};
          state.pendingNativeApproval = {
            idempotencyKey: promptIdempotencyKey,
            prompt: payload.prompt,
            harnessId: payload.harness_id
          };
          setNativeSummary(`Native start is waiting for Approval Center (${approval.id || "pending"}). Approve it, then submit the same prompt again.`);
          await loadApprovals();
          return;
        }
        state.pendingNativeApproval = null;
        setActiveNativeProcess(result.data.process || null, result.data);
        state.attachments = [];
        byId("prompt-input").value = "";
        renderAttachments();
        if (state.currentSessionId) await loadSession(state.currentSessionId);
      } finally {
        byId("run-button").disabled = false;
        updateHarnessDrivenControls();
      }
    }

    function activeNativeConversation() {
      const process = state.activeNativeProcess || {};
      if (currentInvocationMode() !== "native") return null;
      if (!process.id || process.status !== "running") return null;
      if (!state.currentSessionId || process.session_id !== state.currentSessionId) return null;
      return process;
    }

    function legacyNativeProcessForStructuredChat() {
      const process = state.activeNativeProcess || {};
      if (!usesStructuredWorkChat()) return null;
      if (!process.id || process.status !== "running") return null;
      if (process.harness_id !== "codex-cli" || process.session_id !== state.currentSessionId) return null;
      return process;
    }

    async function retireLegacyNativeProcessForStructuredChat() {
      const process = legacyNativeProcessForStructuredChat();
      if (!process) return true;
      stopNativePolling();
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}`, { method: "DELETE" });
      if (!result.ok) {
        setStatus(result.data.detail || "Could not switch the terminal session to structured chat.", "error");
        return false;
      }
      if (result.data.run) syncNativeRunInBundle(result.data.run);
      state.activeNativeProcess = result.data.process || { ...process, status: "stopped" };
      resetNativeTrustPrompt();
      renderNativeTerminalStatus(state.activeNativeProcess.status);
      setNativeSummary(pretty(result.data));
      return true;
    }

    async function continueNativeConversation(payload) {
      const prompt = payload.prompt.trim();
      if (!prompt || !activeNativeConversation()) return;
      byId("run-button").disabled = true;
      byId("run-button").textContent = "Sending...";
      state.nativePollBurstUntil = Date.now() + NATIVE_POLL_BURST_MS;
      try {
        const result = await sendNativeProcessInput(prompt, prompt, true);
        if (!result.ok) {
          setStatus(result.data.detail || "Native input failed.", "error");
          return;
        }
        if (result.data.process) state.activeNativeProcess = result.data.process;
        beginNativeResponseStream();
        if (result.data.message && state.currentBundle) {
          const messages = Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
          if (!messages.some((message) => message.id === result.data.message.id)) {
            state.currentBundle.messages = [...messages, result.data.message];
          }
        }
        byId("prompt-input").value = "";
        state.attachments = [];
        renderAttachments();
        renderMessages();
        await pollNativeOutput();
      } finally {
        byId("run-button").disabled = false;
        updateHarnessDrivenControls();
      }
    }

    async function ensureSessionForNative(payload) {
      if (state.currentSessionId) return true;
      const result = await getJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!result.ok || !result.data.session) {
        setNativeSummary(result.data.detail || "Native session creation failed.");
        return false;
      }
      state.currentSessionId = result.data.session.id;
      await loadSession(state.currentSessionId);
      return true;
    }

    function renderAll() {
      renderMessages();
      renderInspector();
      renderSessions();
      renderMemoryPanel();
      renderToolsPanel();
      renderEvalsPanel();
      syncNavigation();
    }

    function normalizeMessageRole(value) {
      const role = String(value || "assistant").toLowerCase();
      return ["user", "assistant", "error", "tool"].includes(role) ? role : "assistant";
    }

    function isChatNearBottom() {
      const panel = byId("output-panel");
      return panel.scrollHeight - panel.scrollTop - panel.clientHeight < 96;
    }

    function scrollChatToBottom() {
      const panel = byId("output-panel");
      requestAnimationFrame(() => {
        panel.scrollTop = panel.scrollHeight;
      });
    }

    function runForId(runId) {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      return runs.find((run) => run.id === runId) || null;
    }

    function eventsForRun(runId) {
      const events = state.currentBundle && Array.isArray(state.currentBundle.events) ? state.currentBundle.events : [];
      return events.filter((event) => event.run_id === runId || (!event.run_id && state.activeHeadlessRun && state.activeHeadlessRun.id === runId));
    }

    function eventTimestamp(value) {
      const timestamp = Date.parse(value || "");
      return Number.isFinite(timestamp) ? timestamp : null;
    }

    function executionMessagesForRun(runId, messages) {
      return messages
        .filter((message) => message.run_id === runId && ["assistant", "error"].includes(message.role))
        .sort((left, right) => (eventTimestamp(left.created_at) || 0) - (eventTimestamp(right.created_at) || 0));
    }

    function eventsForMessage(message, messages) {
      const events = message.run_id ? eventsForRun(message.run_id) : [];
      if (!message.run_id || !["assistant", "error"].includes(message.role)) return [];
      const executionMessages = executionMessagesForRun(message.run_id, messages);
      if (executionMessages.length <= 1) return events;
      const index = executionMessages.findIndex((item) => item.id === message.id);
      if (index === -1) return [];
      const upperBound = eventTimestamp(message.created_at);
      const lowerBound = index > 0 ? eventTimestamp(executionMessages[index - 1].created_at) : null;
      return events.filter((event) => {
        const timestamp = eventTimestamp(event.created_at);
        if (timestamp == null || upperBound == null) return index === executionMessages.length - 1;
        return timestamp <= upperBound && (lowerBound == null || timestamp > lowerBound);
      });
    }

    function eventsAfterLatestMessage(runId, messages) {
      const executionMessages = executionMessagesForRun(runId, messages);
      const latest = executionMessages.length ? executionMessages[executionMessages.length - 1] : null;
      const lowerBound = latest ? eventTimestamp(latest.created_at) : null;
      return eventsForRun(runId).filter((event) => {
        const timestamp = eventTimestamp(event.created_at);
        return lowerBound == null || timestamp == null || timestamp > lowerBound;
      });
    }

    function activeHeadlessRunFromBundle(bundle = state.currentBundle) {
      const runs = bundle && Array.isArray(bundle.runs) ? bundle.runs : [];
      const headless = runs.filter((run) => run.invocation_mode !== "native");
      return headless.find((run) => run.status === "running")
        || headless.find((run) => run.status === "queued")
        || null;
    }

    function queuedHeadlessTurns(bundle = state.currentBundle) {
      const runs = bundle && Array.isArray(bundle.runs) ? bundle.runs : [];
      const messages = bundle && Array.isArray(bundle.messages) ? bundle.messages : [];
      const prompts = new Map();
      for (const message of messages) {
        if (message.role === "user" && message.run_id && !prompts.has(message.run_id)) {
          prompts.set(message.run_id, message.content || "Queued message");
        }
      }
      return runs
        .filter((run) => run.invocation_mode !== "native" && run.status === "queued")
        .map((run) => ({ run, prompt: prompts.get(run.id) || "Queued message" }));
    }

    function renderComposerQueue() {
      const queue = byId("composer-queue");
      const turns = queuedHeadlessTurns();
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      const hasRunningTurn = runs.some((run) => run.invocation_mode !== "native" && run.status === "running");
      queue.replaceChildren();
      queue.hidden = turns.length === 0;
      for (const [index, turn] of turns.entries()) {
        const card = document.createElement("article");
        card.className = "composer-queue-card";
        card.dataset.runId = turn.run.id;

        const heading = document.createElement("div");
        heading.className = "composer-queue-heading";
        const prompt = document.createElement("strong");
        prompt.textContent = String(turn.prompt).replace(/\s+/g, " ").trim();
        prompt.title = turn.prompt;
        const position = document.createElement("span");
        position.className = "composer-queue-position";
        position.textContent = turns.length === 1 ? "Queued" : `${index + 1} of ${turns.length}`;
        heading.append(prompt, position);

        const status = document.createElement("small");
        status.textContent = index === 0
          ? hasRunningTurn ? "Waiting for the current turn to finish" : "Waiting to start"
          : "Waiting behind earlier queued messages";
        card.append(heading, status);
        queue.appendChild(card);
      }
    }

    function latestEventIdForRun(runId) {
      const events = eventsForRun(runId);
      const latest = [...events].reverse().find((event) => event && event.id);
      return latest ? latest.id : null;
    }

    function resumeActiveHeadlessRun() {
      const run = activeHeadlessRunFromBundle();
      const previousRunId = state.activeHeadlessRun && state.activeHeadlessRun.id;
      if (!run) {
        if (previousRunId || state.headlessEventSource) closeHeadlessEventSource();
        state.activeHeadlessRun = null;
        setHeadlessRunning(false);
        return;
      }
      if (previousRunId && previousRunId !== run.id) closeHeadlessEventSource();
      state.activeHeadlessRun = run;
      const draft = ensureLiveRun(run.id, run);
      draft.status = run.status;
      for (const event of eventsForRun(run.id)) consumeLiveEvent(event);
      setHeadlessRunning(true);
      renderLiveDraft(run.id);
      renderRunSummary(run, eventsForRun(run.id));
      openHeadlessEventStream(run.id);
    }

    function restoreTerminalPartialDrafts() {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      for (const run of runs) {
        if (!["failed", "canceled"].includes(run.status)) continue;
        const events = eventsForRun(run.id);
        const hasPartialText = events.some((event) => event.type === "message_delta" && liveDelta(event));
        if (!hasPartialText) {
          state.liveRuns.delete(run.id);
          continue;
        }
        const draft = ensureLiveRun(run.id, run);
        for (const event of events) consumeLiveEvent(event);
        draft.status = run.status;
      }
    }

    function finiteToken(value) {
      if (value == null || value === "") return null;
      const number = Number(value);
      return Number.isFinite(number) && number >= 0 ? Math.round(number) : null;
    }

    function normalizeUsage(value) {
      if (!value || typeof value !== "object") return null;
      const source = value.usage && typeof value.usage === "object" ? value.usage : value;
      const inputTokens = finiteToken(source.input_tokens != null ? source.input_tokens : source.prompt_tokens);
      const outputTokens = finiteToken(source.output_tokens != null ? source.output_tokens : source.completion_tokens);
      let totalTokens = finiteToken(source.total_tokens);
      if (totalTokens == null && inputTokens != null && outputTokens != null) totalTokens = inputTokens + outputTokens;
      if (inputTokens == null && outputTokens == null && totalTokens == null) return null;
      return {
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: totalTokens
      };
    }

    function mergeUsage(current, update) {
      const previous = normalizeUsage(current) || {
        input_tokens: null,
        output_tokens: null,
        total_tokens: null
      };
      const next = normalizeUsage(update);
      if (!next) return normalizeUsage(previous);
      const inputTokens = next.input_tokens != null ? next.input_tokens : previous.input_tokens;
      const outputTokens = next.output_tokens != null ? next.output_tokens : previous.output_tokens;
      let totalTokens = next.total_tokens != null ? next.total_tokens : previous.total_tokens;
      if (
        inputTokens != null
        && outputTokens != null
        && (next.total_tokens == null || totalTokens == null)
      ) {
        totalTokens = inputTokens + outputTokens;
      }
      return normalizeUsage({
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        total_tokens: totalTokens
      });
    }

    function usageFromEvents(events) {
      let usage = null;
      for (const event of events || []) {
        if (event.type !== "usage") continue;
        usage = mergeUsage(usage, event.payload || {});
      }
      return usage;
    }

    function usageForMessage(message, run, events) {
      const metadata = message && message.metadata && typeof message.metadata === "object" ? message.metadata : {};
      const runMetadata = run && run.metadata && typeof run.metadata === "object" ? run.metadata : {};
      return mergeUsage(
        mergeUsage(usageFromEvents(events || []), runMetadata.usage),
        metadata.usage
      );
    }

    function tokenChip(label, value) {
      if (value == null) return null;
      const chip = document.createElement("span");
      chip.className = "token-chip";
      const name = document.createElement("strong");
      name.textContent = label;
      chip.appendChild(name);
      chip.appendChild(document.createTextNode(String(value)));
      return chip;
    }

    function appendUsageChips(parent, usage) {
      const normalized = normalizeUsage(usage);
      if (!normalized) return;
      const row = document.createElement("div");
      row.className = "usage-row";
      for (const chip of [
        tokenChip("Input", normalized.input_tokens),
        tokenChip("Output", normalized.output_tokens),
        tokenChip("Total", normalized.total_tokens)
      ]) {
        if (chip) row.appendChild(chip);
      }
      if (row.childElementCount) parent.appendChild(row);
    }

    function isSafeMarkdownHref(value) {
      const href = String(value || "").trim();
      if (!href || /[\u0000-\u001f\u007f]/.test(href) || href.startsWith("//") || href.includes("\\")) return false;
      const explicitScheme = href.match(/^([A-Za-z][A-Za-z0-9+.-]*):/);
      if (explicitScheme) {
        return ["http:", "https:", "mailto:"].includes(`${explicitScheme[1].toLowerCase()}:`);
      }
      try {
        const resolved = new URL(href, window.location.href);
        return ["http:", "https:"].includes(resolved.protocol) && resolved.origin === window.location.origin;
      } catch (error) {
        return false;
      }
    }

    function parseMarkdownLink(source, start) {
      if (source[start] !== "[" || (start > 0 && source[start - 1] === "!")) return null;
      let labelEnd = -1;
      for (let cursor = start + 1; cursor < source.length - 1; cursor += 1) {
        if (source[cursor] === "\\") {
          cursor += 1;
          continue;
        }
        if (source[cursor] === "]" && source[cursor + 1] === "(") {
          labelEnd = cursor;
          break;
        }
      }
      if (labelEnd < 0) return null;
      let targetEnd = -1;
      let depth = 0;
      let inAngleTarget = false;
      for (let cursor = labelEnd + 2; cursor < source.length; cursor += 1) {
        const character = source[cursor];
        if (character === "\\") {
          cursor += 1;
          continue;
        }
        if (cursor === labelEnd + 2 && character === "<") inAngleTarget = true;
        if (inAngleTarget) {
          if (character === ">") inAngleTarget = false;
          continue;
        }
        if (character === "(") depth += 1;
        if (character === ")" && depth > 0) depth -= 1;
        else if (character === ")") {
          targetEnd = cursor;
          break;
        }
      }
      if (targetEnd < 0) return null;
      const label = source.slice(start + 1, labelEnd);
      const rawTarget = source.slice(labelEnd + 2, targetEnd).trim();
      const targetMatch = rawTarget.match(/^(<[^>]+>|\S+?)(?:\s+["']([^"']*)["'])?$/);
      if (!targetMatch) return null;
      const href = targetMatch[1].startsWith("<") ? targetMatch[1].slice(1, -1) : targetMatch[1];
      if (!isSafeMarkdownHref(href)) return null;
      return {
        end: targetEnd + 1,
        label,
        href,
        title: targetMatch[2] || ""
      };
    }

    function parseLocalFilePath(source, start) {
      if (source[start] !== "/") return null;
      const previous = start > 0 ? source[start - 1] : " ";
      if (!/[\s(\[{]/.test(previous)) return null;
      const match = source.slice(start).match(/^\/[^\s<>\[\]{}"'`]+/);
      if (!match) return null;
      const path = match[0].replace(/[.,;:!?]+$/, "");
      if (!/^\/(?:[^/\s]+\/)+[^/\s]+\.[A-Za-z0-9]{1,12}$/.test(path)) return null;
      const params = new URLSearchParams({ path });
      if (state.project && state.project.root) params.set("workspace", state.project.root);
      return {
        end: start + path.length,
        path,
        href: `/api/files/preview?${params.toString()}`
      };
    }

    function sourceLinkFromLine(line) {
      const match = markdownListMatch(line, false);
      if (!match) return null;
      const link = parseMarkdownLink(match[1].trim(), 0);
      if (!link || link.end !== match[1].trim().length) return null;
      return link;
    }

    function appendSourcesBlock(parent, lines, start) {
      const links = [];
      let index = start + 1;
      while (index < lines.length) {
        const link = sourceLinkFromLine(lines[index]);
        if (!link) break;
        links.push(link);
        index += 1;
      }
      if (!links.length) return null;

      const section = document.createElement("section");
      section.className = "markdown-sources";
      const header = document.createElement("div");
      header.className = "markdown-sources-header";
      const title = document.createElement("strong");
      title.textContent = "Sources";
      const count = document.createElement("span");
      count.textContent = String(links.length);
      header.append(title, count);
      const list = document.createElement("ul");
      for (const source of links) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.setAttribute("href", source.href);
        link.setAttribute("target", "_blank");
        link.setAttribute("rel", "noopener noreferrer");
        const label = document.createElement("span");
        appendInlineMarkdown(label, source.label);
        const domain = document.createElement("small");
        try {
          domain.textContent = new URL(source.href, window.location.href).hostname;
        } catch (error) {
          domain.textContent = source.href;
        }
        const arrow = document.createElement("span");
        arrow.className = "markdown-source-arrow";
        arrow.textContent = "↗";
        link.append(label, domain, arrow);
        item.appendChild(link);
        list.appendChild(item);
      }
      section.append(header, list);
      parent.appendChild(section);
      return index;
    }

    function appendInlineMarkdown(parent, value) {
      const source = String(value == null ? "" : value);
      let index = 0;
      let buffer = "";
      const flush = () => {
        if (!buffer) return;
        parent.appendChild(document.createTextNode(buffer));
        buffer = "";
      };
      while (index < source.length) {
        if (source[index] === "\\" && index + 1 < source.length) {
          buffer += source[index + 1];
          index += 2;
          continue;
        }
        if (source[index] === "`") {
          let ticks = 1;
          while (source[index + ticks] === "`") ticks += 1;
          const marker = "`".repeat(ticks);
          const closing = source.indexOf(marker, index + ticks);
          if (closing >= 0) {
            flush();
            const code = document.createElement("code");
            code.textContent = source.slice(index + ticks, closing).replace(/^ | $/g, "");
            parent.appendChild(code);
            index = closing + ticks;
            continue;
          }
        }
        const parsedLink = parseMarkdownLink(source, index);
        if (parsedLink) {
          flush();
          const link = document.createElement("a");
          link.setAttribute("href", parsedLink.href);
          link.setAttribute("target", "_blank");
          link.setAttribute("rel", "noopener noreferrer");
          if (parsedLink.title) link.setAttribute("title", parsedLink.title);
          appendInlineMarkdown(link, parsedLink.label);
          parent.appendChild(link);
          index = parsedLink.end;
          continue;
        }
        const localFile = parseLocalFilePath(source, index);
        if (localFile) {
          flush();
          const link = document.createElement("a");
          link.className = "markdown-file-link";
          link.setAttribute("href", localFile.href);
          link.setAttribute("target", "_blank");
          link.setAttribute("rel", "noopener noreferrer");
          link.setAttribute("title", `Preview ${localFile.path}`);
          link.textContent = localFile.path;
          parent.appendChild(link);
          index = localFile.end;
          continue;
        }
        const strongMarker = source.startsWith("**", index) ? "**" : source.startsWith("__", index) ? "__" : null;
        if (strongMarker) {
          const closing = source.indexOf(strongMarker, index + 2);
          if (closing > index + 2) {
            flush();
            const strong = document.createElement("strong");
            appendInlineMarkdown(strong, source.slice(index + 2, closing));
            parent.appendChild(strong);
            index = closing + 2;
            continue;
          }
        }
        if (source[index] === "*" || source[index] === "_") {
          const marker = source[index];
          const previous = index > 0 ? source[index - 1] : " ";
          const next = source[index + 1] || " ";
          const insideWord = marker === "_" && /[A-Za-z0-9]/.test(previous) && /[A-Za-z0-9]/.test(next);
          const closing = insideWord ? -1 : source.indexOf(marker, index + 1);
          if (closing > index + 1) {
            flush();
            const emphasis = document.createElement("em");
            appendInlineMarkdown(emphasis, source.slice(index + 1, closing));
            parent.appendChild(emphasis);
            index = closing + 1;
            continue;
          }
        }
        buffer += source[index];
        index += 1;
      }
      flush();
    }

    function markdownListMatch(line, ordered) {
      return ordered ? line.match(/^\s*\d+[.)]\s+(.+)$/) : line.match(/^\s*[-+*]\s+(.+)$/);
    }

    function isMarkdownBlockStart(line) {
      return /^#{1,6}\s+/.test(line) || /^```/.test(line) || /^>\s?/.test(line) || Boolean(markdownListMatch(line, false)) || Boolean(markdownListMatch(line, true));
    }

    function normalizeMarkdownFenceLines(value) {
      const lines = String(value == null ? "" : value).replace(/\r\n?/g, "\n").split("\n");
      const normalized = [];
      let inFence = false;
      for (const line of lines) {
        if (!inFence) {
          const prefixedFence = line.match(/^(.*\S)[ \t]+```([A-Za-z0-9_-]+)(?:[ \t]+(.*))?$/);
          const compactFence = line.match(/^```([A-Za-z0-9_-]+)[ \t]+(.+)$/);
          if (prefixedFence && line.indexOf("```") === line.lastIndexOf("```")) {
            normalized.push(prefixedFence[1], `\`\`\`${prefixedFence[2]}`);
            if (prefixedFence[3]) normalized.push(prefixedFence[3]);
            inFence = true;
            continue;
          }
          if (compactFence && line.indexOf("```") === line.lastIndexOf("```")) {
            normalized.push(`\`\`\`${compactFence[1]}`, compactFence[2]);
            inFence = true;
            continue;
          }
          normalized.push(line);
          if (/^```[A-Za-z0-9_-]*\s*$/.test(line)) inFence = true;
          continue;
        }

        const suffixedFence = line.match(/^(.*\S)[ \t]+```\s*$/);
        if (suffixedFence) normalized.push(suffixedFence[1], "```");
        else normalized.push(line);
        if (/^```\s*$/.test(line) || suffixedFence) inFence = false;
      }
      return normalized;
    }

    function appendMarkdownBlocks(parent, lines) {
      let index = 0;
      while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) {
          index += 1;
          continue;
        }
        if (/^sources:\s*$/i.test(line.trim())) {
          const nextIndex = appendSourcesBlock(parent, lines, index);
          if (nextIndex != null) {
            index = nextIndex;
            continue;
          }
        }
        const fence = line.match(/^```([A-Za-z0-9_-]*)\s*$/);
        if (fence) {
          const codeLines = [];
          index += 1;
          while (index < lines.length && !/^```\s*$/.test(lines[index])) {
            codeLines.push(lines[index]);
            index += 1;
          }
          if (index < lines.length) index += 1;
          const wrapper = document.createElement("div");
          wrapper.className = "code-block";
          const header = document.createElement("div");
          header.className = "code-block-header";
          const language = document.createElement("span");
          language.textContent = fence[1] || "text";
          const copy = document.createElement("button");
          copy.className = "code-block-copy";
          copy.type = "button";
          copy.textContent = "Copy";
          copy.setAttribute("aria-label", `Copy ${fence[1] || "text"} code`);
          header.append(language, copy);
          const pre = document.createElement("pre");
          const code = document.createElement("code");
          if (fence[1]) code.className = `language-${fence[1]}`;
          code.textContent = codeLines.join("\n");
          pre.appendChild(code);
          copy.addEventListener("click", async () => {
            try {
              await navigator.clipboard.writeText(code.textContent || "");
              copy.textContent = "Copied";
              setTimeout(() => { copy.textContent = "Copy"; }, 1200);
            } catch (error) {
              copy.textContent = "Unavailable";
            }
          });
          wrapper.append(header, pre);
          parent.appendChild(wrapper);
          continue;
        }
        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
          const node = document.createElement(`h${heading[1].length}`);
          appendInlineMarkdown(node, heading[2]);
          parent.appendChild(node);
          index += 1;
          continue;
        }
        if (/^>\s?/.test(line)) {
          const quoteLines = [];
          while (index < lines.length && /^>\s?/.test(lines[index])) {
            quoteLines.push(lines[index].replace(/^>\s?/, ""));
            index += 1;
          }
          const quote = document.createElement("blockquote");
          appendMarkdownBlocks(quote, quoteLines);
          parent.appendChild(quote);
          continue;
        }
        const unordered = markdownListMatch(line, false);
        const ordered = markdownListMatch(line, true);
        if (unordered || ordered) {
          const isOrdered = Boolean(ordered);
          const list = document.createElement(isOrdered ? "ol" : "ul");
          while (index < lines.length) {
            const itemMatch = markdownListMatch(lines[index], isOrdered);
            if (!itemMatch) break;
            const parts = [itemMatch[1]];
            index += 1;
            while (index < lines.length && /^\s{2,}\S/.test(lines[index]) && !markdownListMatch(lines[index], isOrdered)) {
              parts.push(lines[index].trim());
              index += 1;
            }
            const item = document.createElement("li");
            appendInlineMarkdown(item, parts.join(" "));
            list.appendChild(item);
          }
          parent.appendChild(list);
          continue;
        }
        const paragraphLines = [line.trim()];
        index += 1;
        while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines[index])) {
          paragraphLines.push(lines[index].trim());
          index += 1;
        }
        const paragraph = document.createElement("p");
        appendInlineMarkdown(paragraph, paragraphLines.join(" "));
        parent.appendChild(paragraph);
      }
    }

    function renderMarkdownInto(node, value) {
      const fragment = document.createDocumentFragment();
      const lines = normalizeMarkdownFenceLines(value);
      appendMarkdownBlocks(fragment, lines);
      node.replaceChildren(fragment);
    }

    function eventToolPayload(event) {
      const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
      const toolCall = payload.tool_call && typeof payload.tool_call === "object" ? payload.tool_call : {};
      const delta = payload.delta && typeof payload.delta === "object" ? payload.delta : {};
      return { ...payload, ...toolCall, ...delta };
    }

    function toolValueText(value) {
      if (value == null) return "";
      if (typeof value === "string") return value;
      try {
        return JSON.stringify(value, null, 2);
      } catch (error) {
        return String(value);
      }
    }

    function toolEventId(event, payload, tools) {
      const value = payload.call_id != null ? payload.call_id : payload.tool_call_id != null ? payload.tool_call_id : payload.id != null ? payload.id : payload.index != null ? payload.index : payload.name;
      if (value != null && String(value)) return String(value);
      const existing = [...tools.values()].find((tool) => tool.status === "running");
      return existing ? existing.id : `tool-${tools.size + 1}`;
    }

    function normalizedToolStatus(value, fallback) {
      const status = String(value || fallback || "running").toLowerCase();
      if (["failed", "error", "canceled", "cancelled"].includes(status)) return "failed";
      if (["requested", "completed", "succeeded", "running"].includes(status)) return status;
      return fallback || "running";
    }

    function applyToolEvent(tools, event) {
      if (!event || !["tool_call_started", "tool_call_delta", "tool_call_finished"].includes(event.type)) return;
      const payload = eventToolPayload(event);
      const id = toolEventId(event, payload, tools);
      const current = tools.get(id) || {
        id,
        name: "tool",
        status: "running",
        arguments: "",
        output: "",
        duration_ms: null,
        seconds_left: null,
        parentToolCallId: "",
        subagentId: "",
        subagentType: "",
        subagentDescription: "",
        subagentDepth: null
      };
      const functionPayload = payload.function && typeof payload.function === "object" ? payload.function : {};
      const name = payload.name || functionPayload.name;
      if (name) current.name = String(name);
      if (payload.parent_tool_call_id != null) current.parentToolCallId = String(payload.parent_tool_call_id);
      if (payload.subagent_id != null) current.subagentId = String(payload.subagent_id);
      if (payload.subagent_type != null) current.subagentType = String(payload.subagent_type);
      if (payload.subagent_description != null) current.subagentDescription = String(payload.subagent_description);
      if (payload.subagent_depth != null) current.subagentDepth = finiteToken(payload.subagent_depth);
      const completeArguments = payload.arguments != null ? payload.arguments : payload.input != null ? payload.input : functionPayload.arguments;
      const argumentDelta = payload.arguments_delta != null ? payload.arguments_delta : payload.input_delta;
      if (event.type === "tool_call_delta" && argumentDelta != null) {
        current.arguments += toolValueText(argumentDelta);
      } else if (completeArguments != null) {
        current.arguments = toolValueText(completeArguments);
      }
      const outputDelta = payload.output_delta != null ? payload.output_delta : payload.result_delta;
      const completeOutput = payload.output != null ? payload.output : payload.result != null ? payload.result : payload.error;
      if (event.type === "tool_call_delta" && (outputDelta != null || completeOutput != null)) {
        current.output += toolValueText(outputDelta != null ? outputDelta : completeOutput);
      }
      if (event.type === "tool_call_finished" && completeOutput != null) current.output = toolValueText(completeOutput);
      if (event.type === "tool_call_finished") {
        current.status = normalizedToolStatus(payload.status, payload.error ? "failed" : "completed");
        current.duration_ms = finiteToken(payload.duration_ms);
        current.seconds_left = null;
      } else {
        current.status = normalizedToolStatus(payload.status, current.status || "running");
        if (payload.seconds_left != null) current.seconds_left = finiteToken(payload.seconds_left);
      }
      tools.set(id, current);
    }

    function toolsFromEvents(events) {
      const tools = new Map();
      for (const event of events || []) applyToolEvent(tools, event);
      return tools;
    }

    function applyGeneratedFileEvent(files, event) {
      if (!event || event.type !== "generated_file") return;
      const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
      const previewUrl = typeof payload.preview_url === "string" ? payload.preview_url : "";
      if (!previewUrl.startsWith("/api/files/generated/")) return;
      const id = String(payload.file_id || payload.id || previewUrl);
      files.set(id, {
        id,
        filename: String(payload.filename || "Generated image"),
        mime_type: String(payload.mime_type || "image/jpeg"),
        preview_url: previewUrl,
        size_bytes: finiteToken(payload.size_bytes)
      });
    }

    function generatedFilesFromEvents(events) {
      const files = new Map();
      for (const event of events || []) applyGeneratedFileEvent(files, event);
      return files;
    }

    function planPayloadFromTool(tool) {
      const name = String(tool && tool.name || "").toLowerCase();
      if (!(name === "update_plan" || name.endsWith("__update_plan") || name.endsWith(".update_plan"))) return null;
      let payload = tool.arguments;
      if (typeof payload === "string") {
        try {
          payload = JSON.parse(payload);
        } catch (error) {
          return null;
        }
      }
      if (!payload || typeof payload !== "object" || !Array.isArray(payload.plan)) return null;
      const items = payload.plan.flatMap((item) => {
        if (!item || typeof item !== "object" || typeof item.step !== "string" || !item.step.trim()) return [];
        const rawStatus = String(item.status || "pending").toLowerCase();
        const status = ["pending", "in_progress", "completed"].includes(rawStatus) ? rawStatus : "pending";
        return [{ step: item.step.trim(), status }];
      });
      if (!items.length) return null;
      return {
        explanation: typeof payload.explanation === "string" ? payload.explanation.trim() : "",
        items
      };
    }

    function planProgressText(plan) {
      const completed = plan.items.filter((item) => item.status === "completed").length;
      return `${completed}/${plan.items.length} complete`;
    }

    function latestPlanFromTools(tools) {
      let latest = null;
      for (const tool of tools ? tools.values() : []) {
        const plan = planPayloadFromTool(tool);
        if (plan) latest = { plan, tool };
      }
      return latest;
    }

    function appendPlanBody(details, plan, tool) {
      const body = document.createElement("div");
      body.className = "tool-call-body plan-body";
      const progressRow = document.createElement("div");
      progressRow.className = "plan-progress-row";
      const progress = document.createElement("progress");
      const completed = plan.items.filter((item) => item.status === "completed").length;
      progress.max = plan.items.length;
      progress.value = completed;
      progress.setAttribute("aria-label", planProgressText(plan));
      const progressText = document.createElement("span");
      progressText.textContent = planProgressText(plan);
      progressRow.append(progress, progressText);
      body.appendChild(progressRow);
      if (plan.explanation) {
        const explanation = document.createElement("p");
        explanation.className = "plan-explanation";
        explanation.textContent = plan.explanation;
        body.appendChild(explanation);
      }
      const list = document.createElement("ol");
      list.className = "plan-list";
      for (const item of plan.items) {
        const row = document.createElement("li");
        row.className = `plan-item ${item.status}`;
        const marker = document.createElement("span");
        marker.className = "plan-item-marker";
        marker.textContent = item.status === "completed" ? "✓" : item.status === "in_progress" ? "●" : "○";
        marker.setAttribute("aria-hidden", "true");
        const step = document.createElement("span");
        step.className = "plan-item-step";
        step.textContent = item.step;
        const status = document.createElement("span");
        status.className = "plan-item-status";
        status.textContent = item.status.replace("_", " ");
        row.append(marker, step, status);
        list.appendChild(row);
      }
      body.appendChild(list);
      if (tool.status === "failed") {
        const failure = document.createElement("div");
        failure.className = "plan-failure";
        failure.textContent = tool.output || "No failure details were reported by the harness.";
        body.appendChild(failure);
      }
      details.appendChild(body);
    }

    function toolCard(tool, messageKey) {
      const plan = planPayloadFromTool(tool);
      const details = document.createElement("details");
      details.className = `tool-call-card${plan ? " plan-card" : ""}${tool.subagentId ? " subagent-tool" : ""}`;
      const expansionKey = `${messageKey || "run"}:${tool.id}`;
      const rememberedOpen = state.toolCallExpansion.get(expansionKey);
      details.open = rememberedOpen == null
        ? Boolean(plan) || tool.status === "running" || tool.status === "failed" || tool.status === "requested"
        : rememberedOpen;
      details.addEventListener("toggle", () => {
        state.toolCallExpansion.set(expansionKey, details.open);
      });
      const summary = document.createElement("summary");
      const dot = document.createElement("span");
      dot.className = `tool-status-dot ${tool.status || "running"}`;
      const title = document.createElement("span");
      title.className = "tool-call-title";
      const name = document.createElement("span");
      name.className = "tool-call-name";
      name.textContent = plan ? "Plan" : tool.name || "tool";
      title.appendChild(name);
      if (tool.subagentType) {
        const origin = document.createElement("span");
        origin.className = "tool-call-origin";
        origin.textContent = `${tool.subagentType} subagent`;
        if (tool.subagentDescription) origin.title = tool.subagentDescription;
        title.appendChild(origin);
      }
      const status = document.createElement("span");
      status.className = "tool-call-status";
      status.textContent = plan
        ? planProgressText(plan)
        : tool.seconds_left != null && tool.status === "running"
          ? `${tool.status} · ${tool.seconds_left}s left`
          : tool.duration_ms != null
            ? `${tool.status} · ${tool.duration_ms} ms`
            : tool.status || "running";
      summary.append(dot, title, status);
      details.appendChild(summary);
      if (plan) {
        appendPlanBody(details, plan, tool);
      } else if (tool.arguments || tool.output || tool.status === "failed") {
        const body = document.createElement("div");
        body.className = "tool-call-body";
        const failureOutput = tool.status === "failed" && !tool.output
          ? "No failure details were reported by the harness."
          : tool.output;
        for (const [label, text] of [["Input", tool.arguments], [tool.status === "failed" ? "Failure reason" : "Output", failureOutput]]) {
          if (!text) continue;
          const section = document.createElement("div");
          section.className = "tool-call-section";
          const heading = document.createElement("span");
          heading.textContent = label;
          const pre = document.createElement("pre");
          pre.textContent = text;
          section.append(heading, pre);
          body.appendChild(section);
        }
        details.appendChild(body);
      }
      return details;
    }

    function currentSessionPlan() {
      const liveDrafts = [...state.liveRuns.values()].filter((draft) => draft.sessionId === state.currentSessionId);
      const live = liveDrafts.length ? latestPlanFromTools(liveDrafts[liveDrafts.length - 1].tools) : null;
      if (live) return live;
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      const run = runs.length ? runs[runs.length - 1] : null;
      return run ? latestPlanFromTools(toolsFromEvents(eventsForRun(run.id))) : null;
    }

    function renderCurrentPlan() {
      const panel = byId("current-plan");
      if (!panel) return;
      const current = currentSessionPlan();
      panel.replaceChildren();
      panel.hidden = !current;
      if (!current) return;
      const details = document.createElement("details");
      details.className = "current-plan-details";
      details.open = panel.dataset.collapsed !== "true";
      details.addEventListener("toggle", () => {
        panel.dataset.collapsed = details.open ? "false" : "true";
      });
      const summary = document.createElement("summary");
      const title = document.createElement("span");
      title.className = "current-plan-title";
      title.textContent = "Current plan";
      const progress = document.createElement("span");
      progress.className = "current-plan-count";
      progress.textContent = planProgressText(current.plan);
      summary.append(title, progress);
      details.appendChild(summary);
      appendPlanBody(details, current.plan, current.tool);
      panel.appendChild(details);
    }

    function appendToolCards(parent, tools, messageKey) {
      if (!tools || !tools.size) return;
      const stack = document.createElement("div");
      stack.className = "tool-call-stack";
      const label = document.createElement("div");
      label.className = "execution-rail-label";
      label.textContent = `Tool calls · ${tools.size}`;
      stack.appendChild(label);
      for (const tool of tools.values()) stack.appendChild(toolCard(tool, messageKey));
      parent.appendChild(stack);
    }

    function appendGeneratedFiles(parent, files) {
      if (!files || !files.size) return;
      const stack = document.createElement("div");
      stack.className = "generated-file-stack";
      for (const file of files.values()) {
        const figure = document.createElement("figure");
        figure.className = "generated-file-card";
        const link = document.createElement("a");
        link.href = file.preview_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = `Open ${file.filename}`;
        const image = document.createElement("img");
        image.src = file.preview_url;
        image.alt = file.filename || "Generated image";
        image.loading = "lazy";
        link.appendChild(image);
        const caption = document.createElement("figcaption");
        caption.textContent = file.size_bytes != null
          ? `${file.filename} · ${formatBytes(file.size_bytes)}`
          : file.filename;
        figure.append(link, caption);
        stack.appendChild(figure);
      }
      parent.appendChild(stack);
    }

    function appendExecutionOutput(parent, draft) {
      if (!draft || (!draft.stdout && !draft.stderr)) return;
      const stack = document.createElement("div");
      stack.className = "execution-output-stack";
      const label = document.createElement("div");
      label.className = "execution-rail-label";
      label.textContent = "Process output";
      stack.appendChild(label);
      const tool = {
        name: "stdout / stderr",
        status: ["failed", "canceled"].includes(draft.status) ? "failed" : ["running", "queued"].includes(draft.status) ? "running" : "succeeded",
        arguments: draft.stdout || "",
        output: draft.stderr || "",
        duration_ms: null
      };
      stack.appendChild(toolCard(tool));
      parent.appendChild(stack);
    }

    function messageHeader(message, liveStatus) {
      const header = document.createElement("div");
      header.className = "message-header";
      const meta = document.createElement("div");
      meta.className = "message-meta";
      for (const value of [message.role, message.harness_id, message.api_mode]) {
        if (!value) continue;
        const item = document.createElement("span");
        item.textContent = String(value);
        meta.appendChild(item);
      }
      header.appendChild(meta);
      if (liveStatus) {
        const status = document.createElement("span");
        const terminal = ["succeeded", "failed", "canceled"].includes(liveStatus);
        status.className = `live-status${liveStatus === "failed" || liveStatus === "canceled" ? " failed" : terminal ? " complete" : ""}`;
        status.textContent = liveStatus === "succeeded" ? "Complete" : liveStatus === "canceled" ? "Canceled" : liveStatus === "failed" ? "Failed" : liveStatus === "queued" ? "Queued" : "Streaming";
        header.appendChild(status);
      }
      return header;
    }

    function appendAttachmentChips(parent, attachments) {
      if (!attachments || !attachments.length) return;
      const row = document.createElement("div");
      row.className = "attachment-chip-row";
      for (const attachment of attachments) {
        const chip = document.createElement("span");
        chip.className = "badge attachment-chip";
        chip.textContent = attachment.filename || attachment.id || "attachment";
        row.appendChild(chip);
      }
      parent.appendChild(row);
    }

    function buildMessageNode(message, options = {}) {
      const role = normalizeMessageRole(message.role);
      const item = document.createElement("article");
      item.className = `message ${role}`;
      if (message.run_id) item.dataset.runId = message.run_id;
      if (options.live) item.dataset.liveRunId = message.run_id;
      item.appendChild(messageHeader({ ...message, role }, options.liveStatus || null));
      const content = document.createElement("div");
      content.className = "message-content markdown-body";
      const liveNonterminal = options.live && !["succeeded", "failed", "canceled"].includes(options.liveStatus);
      if (message.content) {
        renderMarkdownInto(content, message.content);
      } else if (liveNonterminal) {
        const waiting = document.createElement("p");
        waiting.className = "hint";
        waiting.textContent = "Waiting for model output…";
        content.appendChild(waiting);
      }
      if (liveNonterminal) {
        const cursor = document.createElement("span");
        cursor.className = "live-cursor";
        cursor.setAttribute("aria-hidden", "true");
        const last = content.lastElementChild;
        if (last) last.appendChild(cursor);
        else content.appendChild(cursor);
      }
      item.appendChild(content);
      appendToolCards(item, options.tools || new Map(), message.id || message.run_id);
      appendGeneratedFiles(item, options.generatedFiles || new Map());
      appendExecutionOutput(item, options.draft || null);
      appendUsageChips(item, options.usage || null);
      const attachments = message.metadata && Array.isArray(message.metadata.attachments) ? message.metadata.attachments : [];
      appendAttachmentChips(item, attachments);
      return item;
    }

    function ensureLiveRun(runId, seed = {}) {
      if (!runId) return null;
      let draft = state.liveRuns.get(runId);
      if (!draft) {
        draft = {
          runId,
          sessionId: seed.session_id || state.currentSessionId,
          harnessId: seed.harness_id || currentHarnessId(),
          model: seed.model || byId("model-input").value.trim(),
          apiMode: seed.api_mode || currentApiMode(),
          text: "",
          stdout: "",
          stderr: "",
          tools: new Map(),
          generatedFiles: new Map(),
          usage: null,
          status: seed.status || "running",
          hasMessageDelta: false,
          eventIds: new Set()
        };
        state.liveRuns.set(runId, draft);
      } else {
        draft.sessionId = seed.session_id || draft.sessionId;
        draft.harnessId = seed.harness_id || draft.harnessId;
        draft.model = seed.model || draft.model;
        draft.apiMode = seed.api_mode || draft.apiMode;
      }
      return draft;
    }

    function liveDelta(event) {
      const payload = event && event.payload && typeof event.payload === "object" ? event.payload : {};
      const value = payload.delta != null ? payload.delta : payload.text_delta != null ? payload.text_delta : payload.text != null ? payload.text : payload.content != null ? payload.content : payload.chunk;
      return typeof value === "string" ? value : "";
    }

    function consumeLiveEvent(event) {
      const activeRun = state.activeHeadlessRun || {};
      const runId = event.run_id || activeRun.id;
      const draft = ensureLiveRun(runId, activeRun);
      if (!draft) return null;
      if (!draft.eventIds) draft.eventIds = new Set();
      if (event.id && draft.eventIds.has(event.id)) return draft;
      if (event.id) draft.eventIds.add(event.id);
      const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
      if (event.type === "run_started") {
        draft.status = "running";
      } else if (event.type === "message_delta") {
        draft.text += liveDelta(event);
        draft.hasMessageDelta = true;
      } else if (event.type === "stdout_delta") {
        draft.stdout += liveDelta(event);
      } else if (event.type === "stderr_delta") {
        draft.stderr += liveDelta(event);
      } else if (["tool_call_started", "tool_call_delta", "tool_call_finished"].includes(event.type)) {
        applyToolEvent(draft.tools, event);
      } else if (event.type === "generated_file") {
        applyGeneratedFileEvent(draft.generatedFiles, event);
      } else if (event.type === "usage") {
        draft.usage = mergeUsage(draft.usage, payload);
      } else if (event.type === "message_completed" && !draft.text) {
        const completeText = payload.content != null ? payload.content : payload.text;
        if (typeof completeText === "string") draft.text = completeText;
      } else if (event.type === "error") {
        draft.status = "failed";
        if (event.message) draft.stderr += `${event.message}\\n`;
      } else if (event.type === "run_canceled") {
        draft.status = "canceled";
      } else if (event.type === "run_finished") {
        draft.status = String(payload.status || "succeeded");
      }
      return draft;
    }

    function persistedMessageForRun(runId) {
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      return messages.find((message) => message.run_id === runId && ["assistant", "error"].includes(message.role));
    }

    function preserveTerminalPartialDraft(draft) {
      if (!draft || !["failed", "canceled"].includes(draft.status) || !draft.text.trim()) return false;
      const persisted = persistedMessageForRun(draft.runId);
      return !persisted || String(persisted.content || "").trim() !== draft.text.trim();
    }

    function liveMessageNode(draft) {
      return buildMessageNode(
        {
          role: "assistant",
          run_id: draft.runId,
          content: draft.text,
          harness_id: draft.harnessId,
          api_mode: draft.apiMode,
          metadata: {}
        },
        {
          live: true,
          liveStatus: draft.status,
          tools: draft.tools,
          generatedFiles: draft.generatedFiles,
          usage: draft.usage,
          draft
        }
      );
    }

    function findLiveMessageNode(runId) {
      return [...byId("message-list").children].find((node) => node.dataset && node.dataset.liveRunId === runId) || null;
    }

    function renderLiveDraft(runId) {
      const draft = state.liveRuns.get(runId);
      if (!draft || draft.sessionId !== state.currentSessionId) return;
      const existing = findLiveMessageNode(runId);
      if (persistedMessageForRun(runId) && !preserveTerminalPartialDraft(draft)) {
        if (existing) existing.remove();
        state.liveRuns.delete(runId);
        return;
      }
      const shouldStick = isChatNearBottom();
      const replacement = liveMessageNode(draft);
      if (existing) existing.replaceWith(replacement);
      else byId("message-list").appendChild(replacement);
      renderCurrentPlan();
      document.body.classList.remove("new-session");
      if (shouldStick) scrollChatToBottom();
    }

    function renderMessages() {
      const list = byId("message-list");
      const panel = byId("output-panel");
      const session = state.currentBundle && state.currentBundle.session ? state.currentBundle.session : null;
      const sessionChanged = state.renderedSessionId !== (session && session.id);
      const shouldStick = sessionChanged || panel.scrollHeight === 0 || isChatNearBottom();
      list.replaceChildren();
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      const latestMessageIdsByRun = new Map();
      for (const message of messages) {
        if (message.run_id && ["assistant", "error"].includes(message.role)) {
          latestMessageIdsByRun.set(message.run_id, message.id);
        }
      }
      const persistedRunIds = new Set();
      const renderedPartialDrafts = new Set();
      for (const message of messages) {
        const run = message.run_id ? runForId(message.run_id) : null;
        const events = eventsForMessage(message, messages);
        const executionMessage = ["assistant", "error"].includes(message.role);
        const latestExecutionMessage = executionMessage && latestMessageIdsByRun.get(message.run_id) === message.id;
        const tools = executionMessage ? toolsFromEvents(events) : new Map();
        const generatedFiles = executionMessage ? generatedFilesFromEvents(events) : new Map();
        const usage = executionMessage ? usageForMessage(message, run, events) : null;
        if (message.run_id && executionMessage) {
          persistedRunIds.add(message.run_id);
          const draft = state.liveRuns.get(message.run_id);
          if (latestExecutionMessage && preserveTerminalPartialDraft(draft)) {
            list.appendChild(liveMessageNode(draft));
            renderedPartialDrafts.add(message.run_id);
          }
        }
        const queuedStatus = message.role === "user" && run && run.status === "queued" ? "queued" : null;
        list.appendChild(buildMessageNode(message, { tools, generatedFiles, usage, liveStatus: queuedStatus }));
      }
      for (const [runId, draft] of [...state.liveRuns.entries()]) {
        if (renderedPartialDrafts.has(runId)) continue;
        if (persistedRunIds.has(runId) && !preserveTerminalPartialDraft(draft)) {
          state.liveRuns.delete(runId);
          continue;
        }
        if (draft.sessionId === (session && session.id)) list.appendChild(liveMessageNode(draft));
      }
      appendNativeStreamingMessage(list, messages);
      orderMessagesByRun(list);
      const hasVisibleMessages = list.childElementCount > 0;
      document.body.classList.toggle("new-session", !hasVisibleMessages);
      if (!hasVisibleMessages) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "New session";
        list.appendChild(empty);
      }
      state.renderedSessionId = session && session.id;
      renderComposerQueue();
      renderCurrentPlan();
      if (shouldStick) scrollChatToBottom();
    }

    function orderMessagesByRun(list) {
      const runs = state.currentBundle && Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      const order = new Map(runs.map((run, index) => [run.id, index]));
      const nodes = [...list.children];
      const originalOrder = new Map(nodes.map((node, index) => [node, index]));
      nodes.sort((left, right) => {
        const leftRun = left.dataset.runId;
        const rightRun = right.dataset.runId;
        const leftIndex = leftRun && order.has(leftRun) ? order.get(leftRun) : -1;
        const rightIndex = rightRun && order.has(rightRun) ? order.get(rightRun) : -1;
        return leftIndex - rightIndex || originalOrder.get(left) - originalOrder.get(right);
      });
      for (const node of nodes) list.appendChild(node);
    }

    function runStatusBadgeClass(status) {
      if (status === "succeeded") return "badge ok";
      if (["failed", "canceled"].includes(status)) return "badge error";
      if (["running", "queued"].includes(status)) return "badge warn";
      return "badge info";
    }

    function runDuration(run) {
      if (!run || !run.started_at) return "-";
      if (["running", "queued"].includes(run.status)) return "running";
      const started = Date.parse(run.started_at);
      const finished = Date.parse(run.finished_at || run.updated_at || "");
      if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return run.status === "running" ? "running" : "-";
      const milliseconds = finished - started;
      return milliseconds < 1000 ? `${milliseconds} ms` : `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0)} s`;
    }

    function appendRunSummaryField(grid, label, value) {
      const field = document.createElement("div");
      field.className = "run-summary-field";
      const name = document.createElement("span");
      name.textContent = label;
      const content = document.createElement("strong");
      content.textContent = value == null || value === "" ? "-" : String(value);
      content.title = content.textContent;
      field.append(name, content);
      grid.appendChild(field);
    }

    function renderRunSummary(run, allEvents) {
      const panel = byId("run-panel");
      panel.replaceChildren();
      if (!run) {
        panel.textContent = "No run selected.";
        return;
      }
      const events = (allEvents || []).filter((event) => !event.run_id || event.run_id === run.id);
      const draft = state.liveRuns.get(run.id) || null;
      const effectiveStatus = draft ? draft.status : run.status || "unknown";
      const displayStatus = effectiveStatus === "running" && run.invocation_mode === "native"
        ? "active"
        : effectiveStatus;
      const metadata = run.metadata && typeof run.metadata === "object" ? run.metadata : {};
      const usage = mergeUsage(
        mergeUsage(usageFromEvents(events), metadata.usage),
        draft && draft.usage
      );
      const tools = draft && draft.tools && draft.tools.size ? draft.tools : toolsFromEvents(events);
      const header = document.createElement("div");
      header.className = "run-summary-header";
      const title = document.createElement("div");
      title.className = "run-summary-title";
      const harness = document.createElement("strong");
      harness.textContent = run.harness_id || "Harness run";
      const identifier = document.createElement("span");
      identifier.textContent = run.id || "";
      title.append(harness, identifier);
      const status = document.createElement("span");
      status.className = runStatusBadgeClass(effectiveStatus);
      status.textContent = displayStatus;
      header.append(title, status);
      panel.appendChild(header);
      const grid = document.createElement("div");
      grid.className = "run-summary-grid";
      appendRunSummaryField(grid, "Model", run.model || "default");
      appendRunSummaryField(grid, "Route", run.api_mode ? `/${run.api_mode}` : "-");
      appendRunSummaryField(grid, "Mode", run.mode || "-");
      appendRunSummaryField(grid, "Invocation", run.invocation_mode || "headless");
      appendRunSummaryField(
        grid,
        "Duration",
        displayStatus === "active" ? "active" : runDuration({ ...run, status: effectiveStatus })
      );
      appendRunSummaryField(grid, "Workspace", run.workspace || "current");
      panel.appendChild(grid);
      appendUsageChips(panel, usage);
      const footer = document.createElement("div");
      footer.className = "run-summary-footer";
      const deltaCount = events.filter((event) => ["message_delta", "stdout_delta", "stderr_delta"].includes(event.type)).length;
      for (const value of [`${events.length} events`, `${deltaCount} deltas`, `${tools.size} tool calls`]) {
        const item = document.createElement("span");
        item.textContent = value;
        footer.appendChild(item);
      }
      panel.appendChild(footer);
    }

    function renderInspector() {
      const bundle = state.currentBundle || {};
      const session = bundle.session || null;
      const runs = Array.isArray(bundle.runs) ? bundle.runs : [];
      const events = Array.isArray(bundle.events) ? bundle.events : [];
      const rawRequests = Array.isArray(bundle.raw_requests) ? bundle.raw_requests : [];
      const rawResponses = Array.isArray(bundle.raw_responses) ? bundle.raw_responses : [];
      const run = runs[runs.length - 1] || null;
      setText("selected-session-line", session ? `${session.title} - ${session.id}` : "No session selected");
      renderRunSummary(run, events);
      void loadWorkAgentTeam(run);
      renderArenaCenter(state.currentArena);
      renderEvents(events);
      setText("raw-request-panel", rawRequests.length ? pretty(rawRequests[rawRequests.length - 1].payload) : "{}");
      setText("raw-response-panel", rawResponses.length ? pretty(rawResponses[rawResponses.length - 1].payload) : "{}");
      setText("command-panel", run && run.command && run.command.length ? run.command.join(" ") : commandPreview(state.lastPayload));
      renderDiffInspector(run);
      renderPrInspector(run);
      renderProvenanceInspector(run);
      renderEditorInspector(run);
      setText("attachments-panel", run ? attachmentInspectorText(run, rawRequests[rawRequests.length - 1]) : "No attachments selected.");
      setNativeSummary(nativeInspectorText(bundle));
      setText("storage-panel", pretty(bundle.storage || {}));
      byId("pin-session-button").textContent = session && session.pinned ? "Unpin" : "Pin";
      byId("archive-session-button").textContent = session && session.archived ? "Unarchive" : "Archive";
    }

    function renderArenaCenter(arena) {
      const panel = byId("arena-panel");
      if (!panel) return;
      panel.textContent = "";
      if (!arena || !arena.id) {
        panel.textContent = "No comparison yet.";
        return;
      }
      const header = document.createElement("div");
      header.className = "arena-run-summary";
      header.innerHTML = `
        <div class="badge-row">
          <span class="badge info">Arena</span>
          <span class="badge ${arena.status === "succeeded" ? "ok" : arena.status === "partial" ? "warn" : arena.status === "failed" ? "warn" : "info"}">${escapeHtml(arena.status || "unknown")}</span>
        </div>
        <p class="arena-run-prompt">${escapeHtml(arena.prompt || "")}</p>
        <div class="session-meta">
          <span>${escapeHtml(arena.id)}</span>
          <span>${escapeHtml(arena.harness_ids ? arena.harness_ids.join(", ") : "")}</span>
        </div>
      `;
      panel.appendChild(header);
      const children = Array.isArray(arena.child_runs) ? arena.child_runs : [];
      if (!children.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "Arena is waiting for child runs.";
        panel.appendChild(empty);
        return;
      }
      const grid = document.createElement("div");
      grid.className = "arena-grid";
      for (const child of children) {
        const card = document.createElement("article");
        card.className = "arena-card";
        const message = child.message && child.message.content ? child.message.content : child.result_text || child.error || "No output";
        const runLink = child.run_id
          ? `<a class="secondary link-button" href="/runs/${encodeURIComponent(child.run_id)}">Open run</a>`
          : "";
        card.innerHTML = `
          <div class="arena-card-header">
            <div>
              <h4>${escapeHtml(child.harness_id || "harness")}</h4>
              <div class="session-meta">
                <span>${escapeHtml(child.run_id || "no run")}</span>
                <span>${escapeHtml(String(child.event_count || 0))} events</span>
              </div>
            </div>
            <div class="badge-row">
              <span class="badge ${child.status === "succeeded" ? "ok" : child.status === "running" || child.status === "queued" ? "info" : "warn"}">${escapeHtml(child.status || "unknown")}</span>
              ${runLink}
            </div>
          </div>
          <pre>${escapeHtml(message)}</pre>
        `;
        grid.appendChild(card);
      }
      panel.appendChild(grid);
    }

    function renderDiffInspector(run) {
      const metadata = run && run.metadata ? run.metadata : {};
      const execution = metadata.workspace_execution || {};
      const patch = execution.patch || metadata.diff || "";
      const changedFiles = Array.isArray(execution.changed_files) ? execution.changed_files : [];
      const untrackedFiles = Array.isArray(execution.untracked_files) ? execution.untracked_files : [];
      const lines = [];
      if (run && run.id) lines.push(`Run: ${run.id}`);
      if (execution.policy) lines.push(`Policy: ${execution.policy}`);
      if (execution.requested_policy && execution.requested_policy !== execution.policy) {
        lines.push(`Requested: ${execution.requested_policy}`);
      }
      if (execution.base_branch) lines.push(`Base branch: ${execution.base_branch}`);
      if (execution.base_commit) lines.push(`Base commit: ${execution.base_commit}`);
      if (execution.worktree_path) lines.push(`Worktree: ${execution.worktree_path}`);
      if (execution.applied_at) lines.push(`Applied: ${execution.applied_at}`);
      if (execution.discarded_at) lines.push(`Discarded: ${execution.discarded_at}`);
      if (execution.fallback_reason) lines.push(`Fallback: ${execution.fallback_reason}`);
      if (changedFiles.length) lines.push(`Changed files: ${changedFiles.join(", ")}`);
      if (untrackedFiles.length) lines.push(`Untracked files: ${untrackedFiles.join(", ")}`);
      const summary = lines.length ? lines.join("\\n") : "No run selected.";
      setText("diff-text", `${summary}\\n\\n${patch || "No diff captured."}`);
      const canApply = Boolean(run && run.id && execution.policy === "worktree" && patch && patch !== "No diff captured." && !execution.truncated && !execution.applied_at && !execution.discarded_at);
      const canDiscard = Boolean(run && run.id && execution.policy === "worktree" && !execution.discarded_at);
      byId("apply-run-diff-button").disabled = !canApply;
      byId("apply-branch-input").disabled = !canApply;
      byId("discard-run-worktree-button").disabled = !canDiscard;
      byId("open-run-worktree-button").disabled = !(run && run.id && execution.worktree_path);
      byId("open-run-terminal-button").disabled = !(run && run.id && execution.worktree_path);
    }

    function renderPrInspector(run) {
      const artifact = prArtifactFromRun(run);
      const execution = run && run.metadata ? (run.metadata.workspace_execution || {}) : {};
      const canCreateBranch = Boolean(run && run.id && artifact && artifact.patch && artifact.patch !== "No diff captured." && execution.policy === "worktree" && !execution.truncated && !execution.applied_at && !execution.discarded_at);
      if (!artifact) {
        setText("pr-text", "No PR artifact.");
        byId("pr-branch-input").disabled = true;
        byId("copy-pr-title-button").disabled = true;
        byId("copy-pr-body-button").disabled = true;
        byId("copy-pr-patch-button").disabled = true;
        byId("create-pr-branch-button").disabled = true;
        return;
      }
      if (run && byId("pr-branch-input").dataset.runId !== run.id) {
        byId("pr-branch-input").value = artifact.branch_name_suggestion || "";
        byId("pr-branch-input").dataset.runId = run.id;
      }
      const lines = [
        `Title:\\n${artifact.title || ""}`,
        `Branch:\\n${artifact.applied_branch || artifact.branch_name_suggestion || ""}`,
        `Body:\\n${artifact.body || ""}`,
        `Changed files:\\n${(artifact.changed_files || []).join("\\n") || "None"}`,
        `Patch:\\n${artifact.patch || "No patch captured."}`
      ];
      setText("pr-text", lines.join("\\n\\n"));
      byId("pr-branch-input").disabled = !canCreateBranch;
      byId("copy-pr-title-button").disabled = !(artifact.title || "").trim();
      byId("copy-pr-body-button").disabled = !(artifact.body || "").trim();
      byId("copy-pr-patch-button").disabled = !(artifact.patch || "").trim();
      byId("create-pr-branch-button").disabled = !canCreateBranch;
    }

    function renderProvenanceInspector(run) {
      const hasRun = Boolean(run && run.id);
      byId("refresh-provenance-button").disabled = !hasRun;
      byId("replay-run-button").disabled = !hasRun;
      byId("fork-run-button").disabled = !hasRun;
      byId("promote-agent-button").disabled = !hasRun;
      byId("promote-workflow-button").disabled = !hasRun;
      byId("promote-eval-button").disabled = !hasRun;
      if (!hasRun) {
        setText("provenance-text", "No provenance selected.");
        return;
      }
      const provenance = run.metadata && run.metadata.provenance ? run.metadata.provenance : null;
      if (!provenance) {
        setText("provenance-text", `Run: ${run.id}\\nProvenance snapshot is not stored yet. Refresh provenance to reconstruct it from session records.`);
        return;
      }
      setText("provenance-text", pretty(provenance));
    }

    function renderEditorInspector(run) {
      const workspace = state.project && state.project.root ? state.project.root : byId("workspace-input").value.trim();
      const runWorkspace = editorWorkspaceFromRun(run);
      const patch = editorPatchFromRun(run);
      const hasSession = Boolean(state.currentBundle && state.currentBundle.session && state.currentBundle.session.id);
      const hasRun = Boolean(run && run.id);
      byId("open-editor-workspace-button").disabled = !workspace;
      byId("open-editor-run-button").disabled = !runWorkspace;
      byId("open-editor-diff-button").disabled = !(hasRun && patch && patch !== "No diff captured.");
      byId("open-editor-terminal-button").disabled = !runWorkspace;
      byId("open-editor-file-button").disabled = !workspace;
      byId("copy-session-open-command-button").disabled = !hasSession;
      byId("copy-run-open-command-button").disabled = !hasRun;
      const lines = [
        `Project workspace: ${workspace || "-"}`,
        `Run workspace: ${runWorkspace || "-"}`,
        `Run diff: ${patch && patch !== "No diff captured." ? "available" : "unavailable"}`,
        "Editor and terminal commands come from [editor] in .giga/harness.toml."
      ];
      setText("editor-text", lines.join("\\n"));
    }

    function editorWorkspaceFromRun(run) {
      if (!run || !run.id) return "";
      const execution = run.metadata && run.metadata.workspace_execution ? run.metadata.workspace_execution : {};
      return execution.worktree_path || execution.effective_workspace || execution.source_workspace || run.workspace || "";
    }

    function editorPatchFromRun(run) {
      if (!run || !run.id) return "";
      const metadata = run.metadata || {};
      const execution = metadata.workspace_execution || {};
      return execution.patch || metadata.diff || "";
    }

    function prArtifactFromRun(run) {
      if (!run || !run.id) return null;
      const metadata = run.metadata || {};
      if (metadata.pr_artifact) return metadata.pr_artifact;
      const execution = metadata.workspace_execution || {};
      const patch = execution.patch || metadata.diff || "";
      const changedFiles = Array.isArray(execution.changed_files) ? execution.changed_files : [];
      if (!patch && !changedFiles.length) return null;
      const title = changedFiles.length ? `Update ${changedFiles[0]}` : `Update from ${run.id}`;
      const changeLines = changedFiles.map((item) => "- Updated `" + item + "`").join("\\n") || "- No changed files captured.";
      return {
        run_id: run.id,
        session_id: run.session_id,
        title,
        body: "## Summary\\n- Generated from stored harness run.\\n\\n## Changes\\n" + changeLines + "\\n\\n## Tests\\n```text\\nNot recorded.\\n```",
        patch,
        changed_files: changedFiles,
        untracked_files: Array.isArray(execution.untracked_files) ? execution.untracked_files : [],
        branch_name_suggestion: `giga/${String(title).toLowerCase().replace(/[^a-z0-9._/-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48) || run.id}`
      };
    }

    function currentRun() {
      const bundle = state.currentBundle || {};
      const runs = Array.isArray(bundle.runs) ? bundle.runs : [];
      if (state.selectedRunId) {
        const selected = runs.find((run) => run.id === state.selectedRunId);
        if (selected) return selected;
      }
      return runs[runs.length - 1] || null;
    }

    async function refreshRunDiff(runId) {
      const result = await getJson(`/api/runs/${encodeURIComponent(runId)}/diff`);
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Diff request failed with HTTP ${result.status}`);
        return null;
      }
      const run = result.data.run || null;
      renderDiffInspector(run);
      return run;
    }

    async function applyRunDiff() {
      const run = currentRun();
      if (!run || !run.id) return;
      const branchName = byId("apply-branch-input").value.trim();
      byId("apply-run-diff-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ branch_name: branchName || null })
      });
      if (result.data.approval_required) {
        setText("model-status", "Apply is waiting for approval.");
        await loadApprovals();
        syncBrowserRoute("approvals", null);
        await applyCurrentRoute();
        renderDiffInspector(run);
        return;
      }
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Apply failed with HTTP ${result.status}`);
        renderDiffInspector(run);
        return;
      }
      setText("model-status", "Applied run diff.");
      if (state.currentSessionId) await loadSession(state.currentSessionId);
      await refreshRunDiff(run.id);
      renderPrInspector(currentRun());
    }

    async function discardRunWorktree() {
      const run = currentRun();
      if (!run || !run.id) return;
      byId("discard-run-worktree-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/discard`, {
        method: "POST"
      });
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Discard failed with HTTP ${result.status}`);
        renderDiffInspector(run);
        return;
      }
      setText("model-status", "Discarded run worktree.");
      if (state.currentSessionId) await loadSession(state.currentSessionId);
      await refreshRunDiff(run.id);
      renderPrInspector(currentRun());
    }

    async function openRunWorktree() {
      const run = currentRun();
      if (!run || !run.id) return;
      const workspace = editorWorkspaceFromRun(run);
      if (!workspace) return;
      const result = await getJson("/api/editor/open-workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace })
      });
      if (!result.ok) {
        setText("diff-text", result.data.detail || `Open worktree failed with HTTP ${result.status}`);
        setText("editor-text", result.data.detail || `Open worktree failed with HTTP ${result.status}`);
        return;
      }
      setText("model-status", `Opened editor for ${result.data.editor.target_path}.`);
      setText("editor-text", pretty(result.data.editor));
      showTab("editor");
      await refreshRunDiff(run.id);
    }

    async function openEditorWorkspace(useRunWorkspace = false) {
      const run = currentRun();
      const workspace = useRunWorkspace ? editorWorkspaceFromRun(run) : (state.project && state.project.root ? state.project.root : byId("workspace-input").value.trim());
      if (!workspace) return;
      const result = await getJson("/api/editor/open-workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace })
      });
      renderEditorResult(result, "Open workspace failed");
    }

    async function openEditorFile() {
      const path = byId("open-editor-file-input").value.trim();
      const workspace = state.project && state.project.root ? state.project.root : byId("workspace-input").value.trim();
      if (!path || !workspace) return;
      const result = await getJson("/api/editor/open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace, path })
      });
      renderEditorResult(result, "Open file failed");
    }

    async function openEditorDiff() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson("/api/editor/open-diff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: run.id })
      });
      renderEditorResult(result, "Open diff failed");
    }

    async function openRunTerminal() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson("/api/editor/open-terminal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: run.id })
      });
      renderEditorResult(result, "Open terminal failed");
    }

    function renderEditorResult(result, fallback) {
      if (!result.ok) {
        setText("editor-text", result.data.detail || `${fallback} with HTTP ${result.status}`);
        showTab("editor");
        return;
      }
      const editor = result.data.editor || {};
      setText("editor-text", pretty(editor));
      setText("model-status", editor.executed ? `Opened ${editor.kind || "launcher"} for ${editor.target_path}.` : editor.command_display || "Editor command ready.");
      showTab("editor");
    }

    function copySessionOpenCommand() {
      const session = state.currentBundle && state.currentBundle.session ? state.currentBundle.session : null;
      if (!session || !session.id) return;
      const url = new URL(`/work/${encodeURIComponent(session.id)}`, window.location.origin);
      copyText(url.toString(), "Copied session deep link.");
    }

    function copyRunOpenCommand() {
      const run = currentRun();
      if (!run || !run.id) return;
      const url = new URL(`/runs/${encodeURIComponent(run.id)}`, window.location.origin);
      copyText(url.toString(), "Copied run deep link.");
    }

    async function createPrBranch() {
      const run = currentRun();
      if (!run || !run.id) return;
      const branchName = byId("pr-branch-input").value.trim();
      byId("create-pr-branch-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/branch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ branch_name: branchName || null })
      });
      if (result.data.approval_required) {
        setText("model-status", "Branch creation is waiting for approval.");
        await loadApprovals();
        syncBrowserRoute("approvals", null);
        await applyCurrentRoute();
        renderPrInspector(run);
        return;
      }
      if (!result.ok) {
        setText("pr-text", result.data.detail || `Branch creation failed with HTTP ${result.status}`);
        renderPrInspector(run);
        return;
      }
      setText("model-status", `Created branch ${result.data.branch_name}.`);
      if (state.currentSessionId) await loadSession(state.currentSessionId);
      renderPrInspector(currentRun());
      showTab("pr");
    }

    function copyCurrentPrField(field, status) {
      const artifact = prArtifactFromRun(currentRun());
      if (!artifact) return;
      copyText(artifact[field] || "", status);
    }

    async function refreshRunProvenance() {
      const run = currentRun();
      if (!run || !run.id) return;
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/provenance`);
      if (!result.ok) {
        setText("provenance-text", result.data.detail || `Provenance failed with HTTP ${result.status}`);
        showTab("provenance");
        return;
      }
      const provenance = result.data.provenance || {};
      setText("provenance-text", pretty(provenance));
      if (run.metadata) run.metadata.provenance = provenance;
      showTab("provenance");
    }

    async function replayCurrentRun() {
      const run = currentRun();
      if (!run || !run.id) return;
      byId("replay-run-button").disabled = true;
      setText("provenance-text", `Replaying ${run.id}...`);
      showTab("provenance");
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream: false })
      });
      if (!result.ok) {
        setText("provenance-text", result.data.detail || `Replay failed with HTTP ${result.status}`);
        renderProvenanceInspector(run);
        return;
      }
      state.currentSessionId = result.data.session && result.data.session.id ? result.data.session.id : state.currentSessionId;
      state.currentBundle = result.data;
      state.attachments = [];
      byId("prompt-input").value = "";
      renderAll();
      renderAttachments();
      await loadSessions();
      setText("model-status", "Replayed run.");
      showTab("run");
    }

    async function previewRunPromotion(kind) {
      const run = currentRun();
      if (!run) return;
      const suggested = `${kind}-${String(run.harness_id || "run").replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}-${String(run.id).slice(-8).toLowerCase()}`;
      state.promotionDraft = { runId: run.id, kind };
      byId("promotion-target-id").value = suggested;
      byId("promotion-review-content").value = "";
      byId("promotion-review-content").hidden = true;
      byId("apply-promotion-button").disabled = true;
      setText("promotion-review-meta", `Choose the project ${kind} id, then generate and review YAML before applying.`);
      byId("promotion-review").hidden = false;
      showTab("provenance");
    }

    async function generateRunPromotion() {
      const pending = state.promotionDraft;
      if (!pending) return;
      const targetId = byId("promotion-target-id").value.trim();
      if (!targetId) return setText("promotion-review-meta", "Project artifact id is required.");
      const result = await getJson(`/api/runs/${encodeURIComponent(pending.runId)}/promotions/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: pending.kind, target_id: targetId })
      });
      if (!result.ok) {
        setText("provenance-text", result.data.detail || `Promotion preview failed with HTTP ${result.status}`);
        showTab("provenance");
        return;
      }
      state.promotionDraft = { runId: pending.runId, ...result.data.promotion };
      byId("promotion-review-content").value = state.promotionDraft.content || "";
      byId("promotion-review-content").hidden = false;
      byId("apply-promotion-button").disabled = false;
      setText("promotion-review-meta", `${state.promotionDraft.relative_path} · review required · ${(state.promotionDraft.warnings || []).join(" ")}`);
      byId("promotion-review").hidden = false;
      setText("provenance-text", state.promotionDraft.redacted_diff || "New project file has no diff.");
      showTab("provenance");
    }

    async function applyRunPromotion() {
      const draft = state.promotionDraft;
      if (!draft) return;
      byId("apply-promotion-button").disabled = true;
      const result = await getJson(`/api/runs/${encodeURIComponent(draft.runId)}/promotions/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: draft.kind,
          target_id: draft.target_id,
          content: draft.content,
          source_hash: draft.source_hash,
          review_token: draft.review_token
        })
      });
      byId("apply-promotion-button").disabled = false;
      if (!result.ok) return setText("provenance-text", result.data.detail || `Promotion apply failed with HTTP ${result.status}`);
      setText("provenance-text", `Saved ${result.data.relative_path}\nSource: ${String(result.data.source_hash || "").slice(0, 12)}\nPlugin/skill export was not performed.`);
      byId("promotion-review").hidden = true;
      state.promotionDraft = null;
    }

    function cancelRunPromotion() {
      state.promotionDraft = null;
      byId("promotion-review").hidden = true;
    }

    async function forkCurrentRun() {
      const run = currentRun();
      if (!run || !run.id) return;
      byId("fork-run-button").disabled = true;
      setText("provenance-text", `Forking ${run.id}...`);
      showTab("provenance");
      const result = await getJson(`/api/runs/${encodeURIComponent(run.id)}/fork`, {
        method: "POST"
      });
      if (!result.ok || !result.data.session) {
        setText("provenance-text", result.data.detail || `Fork failed with HTTP ${result.status}`);
        renderProvenanceInspector(run);
        return;
      }
      await loadSession(result.data.session.id);
      await loadSessions();
      setText("model-status", "Forked run into a new chat.");
      showTab("run");
    }

    function nativeTrustDecisionRecorded(bundle, processId) {
      const events = bundle && Array.isArray(bundle.events) ? bundle.events : [];
      let terminalText = "";
      for (const event of events) {
        const payload = event && event.payload ? event.payload : {};
        if (payload.process_id !== processId) continue;
        if (event.type === "terminal_output") {
          terminalText = `${terminalText}${payload.text || ""}`.slice(-10000);
          continue;
        }
        if (event.type !== "terminal_input" || !["1", "2"].includes(String(payload.text || "").trim())) continue;
        const compact = terminalText.toLowerCase().replace(/[^a-z0-9]+/g, "");
        if (
          compact.includes("doyoutrustthecontentsofthisdirectory") &&
          compact.includes("yescontinue") &&
          compact.includes("noquit")
        ) {
          return true;
        }
      }
      return false;
    }

    function activeNativeProcessFromBundle(bundle) {
      const runs = bundle && Array.isArray(bundle.runs) ? bundle.runs : [];
      const links = bundle && Array.isArray(bundle.native_links) ? bundle.native_links : [];
      const runsById = new Map(runs.map((run) => [run.id, run]));
      for (let index = links.length - 1; index >= 0; index -= 1) {
        const link = links[index] || {};
        const metadata = link.metadata || {};
        const run = runsById.get(metadata.run_id);
        if (!metadata.native_process_id || metadata.process_status !== "running") continue;
        if (!run || run.status !== "running" || run.invocation_mode !== "native") continue;
        const process = {
          id: metadata.native_process_id,
          harness_id: link.harness_id || run.harness_id,
          session_id: link.session_id || run.session_id,
          run_id: metadata.run_id,
          status: "running",
          cwd: link.workspace || run.workspace || null,
          native_home: metadata.native_home || null,
          metadata: { reconnected: true }
        };
        if (nativeTrustDecisionRecorded(bundle, process.id)) rememberNativeTrustDecision(process.id);
        return process;
      }
      return null;
    }

    function restoreActiveNativeProcess() {
      const candidate = activeNativeProcessFromBundle(state.currentBundle);
      if (candidate && state.activeNativeProcess && state.activeNativeProcess.id === candidate.id) return;
      if (candidate) {
        setActiveNativeProcess(candidate, { process: candidate, reconnected: true });
        return;
      }
      if (state.activeNativeProcess && state.activeNativeProcess.session_id !== state.currentSessionId) {
        stopNativeOutputTransport();
        state.activeNativeProcess = null;
        state.nativeOutputCursor = 0;
        state.nativeTerminalText = "";
        finishNativeResponseStream();
        resetNativeTrustPrompt();
        renderNativeTerminalStatus("idle");
        setNativeSummary(nativeInspectorText(state.currentBundle));
        setText("native-terminal-output", "Terminal output will appear here.");
      }
    }

    function nativeInspectorText(bundle) {
      if (state.nativePreview) return pretty(state.nativePreview);
      if (state.activeNativeProcess) return pretty(state.activeNativeProcess);
      const links = bundle && Array.isArray(bundle.native_links) ? bundle.native_links : [];
      if (!links.length) return "No native session selected.";
      return pretty({ native_links: links });
    }

    function setNativeSummary(value) {
      setText("native-process-summary", value);
    }

    function setActiveNativeProcess(process, payload) {
      stopNativeOutputTransport();
      resetNativeTrustPrompt();
      state.activeNativeProcess = process;
      state.nativeOutputCursor = 0;
      state.nativeTerminalText = "";
      state.nativeStreamingActive = Boolean(
        process
        && ["claude-code", "gemini-cli"].includes(process.harness_id)
        && !(payload && payload.reconnected)
      );
      state.nativeStreamingText = "";
      state.nativePollBurstUntil = Date.now() + NATIVE_POLL_BURST_MS;
      setNativeSummary(pretty(payload || process || {}));
      setText("native-terminal-output", "Terminal output will appear here.");
      renderNativeTerminalStatus();
      renderNativeStreamingDraft();
      if (process && process.id) {
        startNativeOutputTransport();
        startNativeResizeObserver();
      }
    }

    function renderNativeTerminalStatus(status) {
      const process = state.activeNativeProcess || {};
      const effectiveStatus = status || process.status || "idle";
      const displayStatus = effectiveStatus === "running" ? "active" : effectiveStatus;
      const badge = byId("native-terminal-status");
      badge.className = effectiveStatus === "running" ? "badge ok" : effectiveStatus === "idle" ? "badge info" : "badge warn";
      badge.textContent = `Native: ${displayStatus}`;
      const running = effectiveStatus === "running";
      byId("stop-native-process-button").disabled = !process.id || !running;
      byId("poll-native-output-button").disabled = !process.id;
      updateHarnessDrivenControls();
    }

    function syncNativeRunInBundle(run) {
      if (!run || !state.currentBundle) return;
      const runs = Array.isArray(state.currentBundle.runs) ? state.currentBundle.runs : [];
      const index = runs.findIndex((item) => item.id === run.id);
      state.currentBundle.runs = index === -1
        ? [...runs, run]
        : runs.map((item, itemIndex) => itemIndex === index ? run : item);
    }

    function syncNativeMessagesInBundle(messages) {
      if (!state.currentBundle || !Array.isArray(messages) || !messages.length) return false;
      const current = Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      const byMessageId = new Map(current.map((message) => [message.id, message]));
      let changed = false;
      for (const message of messages) {
        if (!message || !message.id) continue;
        const previous = byMessageId.get(message.id);
        if (!previous || JSON.stringify(previous) !== JSON.stringify(message)) changed = true;
        byMessageId.set(message.id, message);
      }
      if (!changed) return false;
      state.currentBundle.messages = [...byMessageId.values()];
      return true;
    }

    function syncNativeEventsInBundle(events) {
      if (!state.currentBundle || !Array.isArray(events) || !events.length) return false;
      const current = Array.isArray(state.currentBundle.events) ? state.currentBundle.events : [];
      const byEventId = new Map(current.map((event) => [event.id, event]));
      let changed = false;
      for (const event of events) {
        if (!event || !event.id) continue;
        const previous = byEventId.get(event.id);
        if (!previous || JSON.stringify(previous) !== JSON.stringify(event)) changed = true;
        byEventId.set(event.id, event);
      }
      if (!changed) return false;
      state.currentBundle.events = [...byEventId.values()];
      return true;
    }

    function nativeStreamingMessageNode(messages) {
      const process = state.activeNativeProcess || {};
      if (
        !state.nativeStreamingActive
        || !["claude-code", "gemini-cli"].includes(process.harness_id)
        || !process.run_id
      ) return null;
      const events = eventsAfterLatestMessage(process.run_id, messages);
      const node = buildMessageNode(
        {
          id: `native-stream:${process.id}`,
          role: "assistant",
          run_id: process.run_id,
          content: state.nativeStreamingText,
          harness_id: process.harness_id,
          api_mode: process.api_mode || currentApiMode(),
          metadata: {}
        },
        {
          live: true,
          liveStatus: "running",
          tools: toolsFromEvents(events)
        }
      );
      node.dataset.nativeStreamingProcessId = process.id;
      return node;
    }

    function appendNativeStreamingMessage(list, messages) {
      const node = nativeStreamingMessageNode(messages);
      if (node) list.appendChild(node);
    }

    function renderNativeStreamingDraft() {
      const list = byId("message-list");
      if (!list) return;
      const existing = list.querySelector("[data-native-streaming-process-id]");
      const messages = state.currentBundle && Array.isArray(state.currentBundle.messages) ? state.currentBundle.messages : [];
      const replacement = nativeStreamingMessageNode(messages);
      if (existing && replacement) existing.replaceWith(replacement);
      else if (existing) existing.remove();
      else if (replacement) list.appendChild(replacement);
      if (replacement && isChatNearBottom()) scrollChatToBottom();
    }

    function beginNativeResponseStream() {
      const process = state.activeNativeProcess || {};
      if (!["claude-code", "gemini-cli"].includes(process.harness_id)) return;
      state.nativeTerminalText = "";
      state.nativeStreamingActive = true;
      state.nativeStreamingText = "";
      renderNativeStreamingDraft();
    }

    function finishNativeResponseStream() {
      state.nativeStreamingActive = false;
      state.nativeStreamingText = "";
    }

    function geminiStreamingTextFromTerminal(value) {
      const lines = String(value || "").replace(/\r/g, "").split("\n");
      let promptIndex = -1;
      for (let index = 0; index < lines.length; index += 1) {
        if (/^\s*>\s+\S/.test(lines[index])) promptIndex = index;
      }
      if (promptIndex === -1) return "";
      let responseIndex = -1;
      for (let index = promptIndex + 1; index < lines.length; index += 1) {
        if (/^\s*✦(?:\s|$)/.test(lines[index])) {
          responseIndex = index;
          break;
        }
      }
      if (responseIndex === -1) return "";
      const response = [];
      for (let index = responseIndex; index < lines.length; index += 1) {
        const line = lines[index];
        if (index > responseIndex && /^\s*>\s*$/.test(line)) break;
        response.push(index === responseIndex ? line.replace(/^\s*✦\s?/, "") : line.replace(/^ {2}/, ""));
      }
      return response.join("\n").trim();
    }

    function updateNativeStreamingFromTerminal() {
      const process = state.activeNativeProcess || {};
      if (!state.nativeStreamingActive || process.harness_id !== "gemini-cli") return false;
      const candidate = geminiStreamingTextFromTerminal(state.nativeTerminalText);
      if (!candidate || candidate === state.nativeStreamingText) return false;
      if (state.nativeStreamingText && candidate.length < state.nativeStreamingText.length) return false;
      state.nativeStreamingText = candidate;
      return true;
    }

    async function consumeNativeOutputPayload(body, processId) {
      const process = state.activeNativeProcess || {};
      if (!process.id || (processId && process.id !== processId)) return;
      state.nativeOutputCursor = body.cursor || state.nativeOutputCursor;
      const outputs = Array.isArray(body.outputs) ? body.outputs : [];
      let nativeStreamChanged = false;
      for (const output of outputs) {
        nativeStreamChanged = appendNativeTerminal(output.text || "") || nativeStreamChanged;
      }
      if (outputs.length) state.nativePollBurstUntil = Date.now() + NATIVE_POLL_BURST_MS;
      const status = body.status || (body.run && body.run.status) || "running";
      state.activeNativeProcess = { ...process, status, exit_code: body.exit_code };
      if (body.run) {
        syncNativeRunInBundle(body.run);
        renderInspector();
      }
      const nativeMessages = Array.isArray(body.messages) ? body.messages : [];
      const nativeEvents = Array.isArray(body.events) ? body.events : [];
      const currentMessageIds = new Set(
        state.currentBundle && Array.isArray(state.currentBundle.messages)
          ? state.currentBundle.messages.map((message) => message.id)
          : []
      );
      const hasNewAssistantMessage = nativeMessages.some(
        (message) => message && ["assistant", "error"].includes(message.role) && !currentMessageIds.has(message.id)
      );
      const messagesChanged = syncNativeMessagesInBundle(nativeMessages);
      const eventsChanged = syncNativeEventsInBundle(nativeEvents);
      if (hasNewAssistantMessage) {
        finishNativeResponseStream();
      }
      if (messagesChanged || eventsChanged) {
        renderMessages();
      } else if (nativeStreamChanged) {
        renderNativeStreamingDraft();
      }
      renderNativeTerminalStatus(status);
      if (status !== "running") {
        const hadNativeStream = state.nativeStreamingActive;
        finishNativeResponseStream();
        if (hadNativeStream && !messagesChanged && !eventsChanged) renderNativeStreamingDraft();
        stopNativeOutputTransport();
        resetNativeTrustPrompt();
      } else if (!state.nativeEventSource) {
        scheduleNativePoll(Date.now() < state.nativePollBurstUntil ? NATIVE_ACTIVE_POLL_MS : NATIVE_IDLE_POLL_MS);
      }
      if (body.run) setNativeSummary(pretty({ process: state.activeNativeProcess, run: body.run }));
      maybeShowNativeTrustPrompt();
      if (
        status !== "running"
        && state.currentSessionId
        && state.currentSessionId === (body.run && body.run.session_id || process.session_id)
      ) {
        await loadSession(state.currentSessionId, {
          runId: state.selectedRunId,
          syncRoute: false
        });
      }
    }

    async function pollNativeOutput() {
      const process = state.activeNativeProcess || {};
      if (!process.id) {
        renderNativeTerminalStatus("idle");
        return;
      }
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}/output?cursor=${state.nativeOutputCursor}`);
      if (!result.ok) {
        appendNativeTerminalLine(result.data.detail || "Native output polling failed.");
        stopNativePolling();
        renderNativeTerminalStatus("error");
        return;
      }
      await consumeNativeOutputPayload(result.data || {}, process.id);
    }

    function startNativeOutputTransport() {
      const process = state.activeNativeProcess || {};
      if (!process.id) return;
      stopNativePolling();
      if (!window.EventSource) {
        scheduleNativePoll(0);
        return;
      }
      openNativeOutputStream(process.id);
    }

    function openNativeOutputStream(processId) {
      closeNativeOutputStream();
      const query = `?cursor=${encodeURIComponent(state.nativeOutputCursor)}`;
      const source = new EventSource(`/api/native/processes/${encodeURIComponent(processId)}/output/stream${query}`);
      state.nativeEventSource = source;
      state.nativeEventSourceProcessId = processId;
      state.nativeStreamFailures = 0;
      source.onmessage = async (event) => {
        if (state.nativeEventSource !== source || state.nativeEventSourceProcessId !== processId) return;
        state.nativeStreamFailures = 0;
        let payload = {};
        try {
          payload = JSON.parse(event.data || "{}");
        } catch (error) {
          appendNativeTerminalLine("Native output stream returned an invalid event.");
          return;
        }
        await consumeNativeOutputPayload(payload, processId);
      };
      source.onerror = () => {
        if (state.nativeEventSource !== source || state.nativeEventSourceProcessId !== processId) return;
        const process = state.activeNativeProcess || {};
        if (process.id !== processId || process.status !== "running") {
          closeNativeOutputStream();
          return;
        }
        state.nativeStreamFailures += 1;
        if (state.nativeStreamFailures < NATIVE_STREAM_FAILURE_LIMIT) return;
        closeNativeOutputStream();
        scheduleNativePoll(NATIVE_ACTIVE_POLL_MS);
      };
    }

    function closeNativeOutputStream() {
      if (state.nativeEventSource) state.nativeEventSource.close();
      state.nativeEventSource = null;
      state.nativeEventSourceProcessId = null;
      state.nativeStreamFailures = 0;
    }

    function maybeShowNativeTrustPrompt() {
      const process = state.activeNativeProcess || {};
      if (usesStructuredWorkChat() && process.harness_id === "codex-cli") return;
      if (!process.id || process.harness_id !== "codex-cli" || process.status !== "running") return;
      if (state.nativeTrustResolvedProcessIds.has(process.id)) return;
      const compact = state.nativeTerminalText.toLowerCase().replace(/[^a-z0-9]+/g, "");
      if (!compact.includes("doyoutrustthecontentsofthisdirectory")) return;
      if (!compact.includes("yescontinue") || !compact.includes("noquit")) return;
      state.nativeTrustPromptProcessId = process.id;
      setText(
        "native-trust-workspace",
        process.cwd || (state.currentBundle && state.currentBundle.session && state.currentBundle.session.workspace) || "Current workspace"
      );
      setText("native-trust-status", "Choose whether Codex should continue.");
      byId("native-trust-yes-button").disabled = false;
      byId("native-trust-no-button").disabled = false;
      byId("native-trust-prompt").hidden = false;
      showTab("native");
      setInspectorOpen(true);
    }

    function resetNativeTrustPrompt() {
      state.nativeTrustPromptProcessId = null;
      const prompt = byId("native-trust-prompt");
      if (prompt) prompt.hidden = true;
    }

    async function respondToNativeTrust(allowed) {
      const process = state.activeNativeProcess || {};
      if (!process.id || state.nativeTrustPromptProcessId !== process.id) return;
      byId("native-trust-yes-button").disabled = true;
      byId("native-trust-no-button").disabled = true;
      setText("native-trust-status", allowed ? "Continuing Codex…" : "Stopping Codex…");
      const result = await sendNativeProcessInput(allowed ? "1\r" : "2\r");
      if (!result.ok) {
        setText("native-trust-status", result.data.detail || "Could not send the trust decision.");
        byId("native-trust-yes-button").disabled = false;
        byId("native-trust-no-button").disabled = false;
        return;
      }
      rememberNativeTrustDecision(process.id);
      resetNativeTrustPrompt();
      if (result.data.process) state.activeNativeProcess = result.data.process;
      await pollNativeOutput();
    }

    async function sendNativeProcessInput(data, message = null, submit = false) {
      const process = state.activeNativeProcess || {};
      if (!process.id) return { ok: false, data: { detail: "Native process is unavailable." } };
      const body = { data };
      if (message) body.message = message;
      if (submit) body.submit = true;
      return getJson(`/api/native/processes/${encodeURIComponent(process.id)}/input`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
    }

    async function stopNativeProcess() {
      const process = state.activeNativeProcess || {};
      if (!process.id) return;
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}`, { method: "DELETE" });
      if (!result.ok) {
        appendNativeTerminalLine(result.data.detail || "Native stop failed.");
        return;
      }
      if (result.data.process) state.activeNativeProcess = result.data.process;
      setNativeSummary(pretty(result.data));
      await pollNativeOutput();
    }

    function stopNativePolling() {
      if (state.nativePollTimer) {
        window.clearTimeout(state.nativePollTimer);
        state.nativePollTimer = null;
      }
    }

    function scheduleNativePoll(delay) {
      stopNativePolling();
      state.nativePollTimer = window.setTimeout(() => {
        state.nativePollTimer = null;
        pollNativeOutput();
      }, delay);
    }

    function stopNativeOutputTransport() {
      closeNativeOutputStream();
      stopNativePolling();
      stopNativeResizeObserver();
    }

    function nativeTerminalDimensions() {
      const terminal = byId("native-terminal-output");
      if (!terminal || terminal.clientWidth <= 0 || terminal.clientHeight <= 0) {
        return { rows: 24, columns: 80 };
      }
      const style = window.getComputedStyle(terminal);
      const fontSize = Number.parseFloat(style.fontSize) || 12;
      const lineHeight = Number.parseFloat(style.lineHeight) || fontSize * 1.4;
      const horizontalPadding = (Number.parseFloat(style.paddingLeft) || 0) + (Number.parseFloat(style.paddingRight) || 0);
      const verticalPadding = (Number.parseFloat(style.paddingTop) || 0) + (Number.parseFloat(style.paddingBottom) || 0);
      const rows = Math.max(NATIVE_MIN_ROWS, Math.min(NATIVE_MAX_ROWS, Math.floor((terminal.clientHeight - verticalPadding) / lineHeight)));
      const columns = Math.max(NATIVE_MIN_COLUMNS, Math.min(NATIVE_MAX_COLUMNS, Math.floor((terminal.clientWidth - horizontalPadding) / (fontSize * 0.62))));
      return { rows, columns };
    }

    async function resizeNativeTerminal() {
      const process = state.activeNativeProcess || {};
      if (!process.id || process.status !== "running" || process.transport === "pipes") return;
      const size = nativeTerminalDimensions();
      if (
        state.nativeTerminalSize
        && state.nativeTerminalSize.rows === size.rows
        && state.nativeTerminalSize.columns === size.columns
      ) return;
      const result = await getJson(`/api/native/processes/${encodeURIComponent(process.id)}/resize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(size)
      });
      if (!result.ok) {
        stopNativeResizeObserver();
        return;
      }
      state.nativeTerminalSize = size;
    }

    function scheduleNativeResize() {
      if (state.nativeResizeTimer) window.clearTimeout(state.nativeResizeTimer);
      state.nativeResizeTimer = window.setTimeout(() => {
        state.nativeResizeTimer = null;
        resizeNativeTerminal();
      }, NATIVE_RESIZE_DELAY_MS);
    }

    function startNativeResizeObserver() {
      stopNativeResizeObserver();
      const process = state.activeNativeProcess || {};
      if (!process.id || process.status !== "running" || process.transport === "pipes") return;
      state.nativeTerminalSize = null;
      if (window.ResizeObserver) {
        state.nativeResizeObserver = new ResizeObserver(scheduleNativeResize);
        state.nativeResizeObserver.observe(byId("native-terminal-output"));
      }
      scheduleNativeResize();
    }

    function stopNativeResizeObserver() {
      if (state.nativeResizeTimer) window.clearTimeout(state.nativeResizeTimer);
      state.nativeResizeTimer = null;
      if (state.nativeResizeObserver) state.nativeResizeObserver.disconnect();
      state.nativeResizeObserver = null;
      state.nativeTerminalSize = null;
    }

    function clearNativeTerminal() {
      state.nativeTerminalText = "";
      finishNativeResponseStream();
      renderNativeStreamingDraft();
      setText("native-terminal-output", "Terminal output will appear here.");
      resetNativeTrustPrompt();
    }

    function appendNativeTerminal(text) {
      const raw = String(text || "");
      if (raw.includes("\x1B[2J") || raw.includes("\x1B[3J")) {
        state.nativeTerminalText = "";
      }
      const clean = stripAnsi(raw);
      state.nativeTerminalText += clean;
      if (state.nativeTerminalText.length > NATIVE_TERMINAL_CHAR_LIMIT) {
        state.nativeTerminalText = state.nativeTerminalText.slice(-NATIVE_TERMINAL_CHAR_LIMIT);
      }
      setText("native-terminal-output", state.nativeTerminalText || "Terminal output will appear here.");
      return updateNativeStreamingFromTerminal();
    }

    function appendNativeTerminalLine(text) {
      appendNativeTerminal(`${text}\\n`);
    }

    function stripAnsi(text) {
      return String(text || "")
        .replace(/\x1B\][^\x07]*(?:\x07|\x1B\\)/g, "")
        .replace(/\x1B\[[0-?]*[ -/]*[@-~]/g, "")
        .replace(/\x1B[()][0-2A-Z0-9]/g, "");
    }

    function renderEvents(events) {
      const panel = byId("events-panel");
      panel.textContent = "";
      if (!events || !events.length) {
        panel.textContent = "No events yet.";
        return;
      }
      for (const event of events) {
        const row = document.createElement("div");
        row.className = "event-row";
        row.innerHTML = `
          <div class="badge-row">
            <span class="badge info">${escapeHtml(event.type || "event")}</span>
            <span class="hint">${escapeHtml(event.created_at || "")}</span>
          </div>
          <div>${escapeHtml(event.message || "")}</div>
          <pre>${escapeHtml(pretty(event.payload || {}))}</pre>
        `;
        panel.appendChild(row);
      }
    }

    function attachmentInspectorText(run, rawRequest) {
      const metadata = run && run.metadata ? run.metadata : {};
      const requestPayload = rawRequest && rawRequest.payload ? rawRequest.payload : {};
      const attachments = Array.isArray(metadata.attachments) ? metadata.attachments : Array.isArray(requestPayload.attachments) ? requestPayload.attachments : [];
      const renderPlan = metadata.attachment_render_plan || requestPayload.attachment_render_plan || null;
      if (!attachments.length && !renderPlan) return "No attachments selected.";
      const lines = [];
      if (attachments.length) {
        lines.push("Attachments");
        for (const attachment of attachments) {
          lines.push(`- ${attachment.filename || attachment.id} [${attachment.kind || "attachment"}] ${attachment.mime_type || ""} ${formatBytes(attachment.size_bytes || 0)}`);
          if (attachment.workspace_path) lines.push(`  workspace: @${attachment.workspace_path}`);
          if (attachment.source) lines.push(`  source: ${attachment.source}`);
        }
      }
      if (renderPlan) {
        lines.push("");
        lines.push("Render plan");
        const metadata = renderPlan.metadata || {};
        if (metadata.transport) lines.push(`transport: ${metadata.transport}`);
        if (Array.isArray(renderPlan.warnings) && renderPlan.warnings.length) {
          lines.push("warnings:");
          for (const warning of renderPlan.warnings) lines.push(`- ${warning}`);
        }
        if (renderPlan.prompt_prefix) lines.push(`prompt_prefix:\\n${renderPlan.prompt_prefix}`);
        if (Array.isArray(renderPlan.cli_args) && renderPlan.cli_args.length) {
          lines.push(`cli_args: ${renderPlan.cli_args.join(" ")}`);
        }
        if (Array.isArray(renderPlan.content_parts) && renderPlan.content_parts.length) {
          lines.push(`content_parts: ${renderPlan.content_parts.length}`);
        }
        lines.push("");
        lines.push("render_plan_json:");
        lines.push(pretty(renderPlan));
      }
      return lines.join("\\n");
    }

    async function patchCurrentSession(patch) {
      if (!state.currentSessionId) return;
      const result = await getJson(`/api/sessions/${encodeURIComponent(state.currentSessionId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      });
      if (result.ok) await loadSession(state.currentSessionId);
    }

    async function deleteCurrentSession() {
      if (!state.currentSessionId) return;
      const title = state.currentBundle && state.currentBundle.session ? state.currentBundle.session.title : "this session";
      if (!window.confirm(`Delete \"${compactSessionTitle(title)}\" permanently?`)) return;
      const sessionId = state.currentSessionId;
      const result = await getJson(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
      if (result.ok) {
        clearCurrentSession();
        await loadSessions();
      }
    }

    function clearCurrentSession() {
      state.currentSessionId = null;
      state.currentBundle = null;
      state.attachments = [];
      renderAttachments();
      renderAll();
      persistProjectState({ last_selected_session: null });
      syncBrowserRoute("work", null);
    }

    function renameCurrentSession() {
      if (!state.currentBundle || !state.currentBundle.session) return;
      const title = window.prompt("Rename session", state.currentBundle.session.title || "");
      if (title != null) patchCurrentSession({ title });
    }

    function currentHarnessId() {
      return byId("harness-select").value || "echo";
    }

    function currentHarnessSupportsNative() {
      const spec = state.selectedHarness && state.selectedHarness.spec ? state.selectedHarness.spec : {};
      return spec.supports_native_sessions === true;
    }

    function currentInvocationMode() {
      return byId("invocation-select").value || "headless";
    }

    function currentApiMode() {
      return byId("api-mode-v1").checked ? "v1" : "v2";
    }

    function updateRouteNote() {
      setText("route-note", `Current route: /${currentApiMode()}/chat/completions`);
      updateBuiltinToolControls();
      updateHeaderBadges();
    }

    function updateHeaderBadges() {
      const model = byId("model-input").value.trim() || "unset";
      setText("current-model-badge", `Model: ${model}`);
      setText("current-route-badge", `Route: /${currentApiMode()}/chat/completions`);
    }

    async function persistProjectState(patch = {}) {
      if (state.applyingProjectState || !state.project || !state.project.root) return;
      const payload = {
        workspace: state.project.root,
        last_harness: currentHarnessId(),
        last_model: byId("model-input").value.trim() || null,
        last_api_mode: currentApiMode(),
        last_run_mode: byId("mode-select").value,
        last_invocation_mode: currentInvocationMode(),
        last_selected_session: state.currentSessionId || null,
        ...patch
      };
      const result = await getJson("/api/project/state", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (result.ok) state.projectState = result.data.state || state.projectState;
    }

    function commandPreview(payload) {
      if (!payload) return "No command yet.";
      const args = ["giga", "harness", "run", payload.harness_id || "echo", "--api-mode", payload.api_mode || "v2"];
      if (payload.invocation_mode === "native") args.push("--native");
      if (payload.model) args.push("--model", payload.model);
      args.push("--prompt", payload.prompt || "");
      const command = args.map(shellQuote).join(" ");
      if (payload.stream) {
        return `# Non-streaming CLI preview: giga harness run has no --stream flag\n${command}`;
      }
      return command;
    }

    function curlPreview() {
      const payload = state.lastPayload || buildPayload();
      if (payload.harness_id !== "direct-chat") return "curl is only available for direct-chat.";
      const body = {
        model: payload.model || state.defaults.default_model || "GigaChat",
        messages: [{ role: "user", content: payload.prompt || "" }],
        stream: Boolean(payload.stream)
      };
      if (Array.isArray(payload.builtin_tools) && payload.builtin_tools.length) {
        body.tools = payload.builtin_tools.map((type) => ({ type }));
      }
      const url = `${state.defaults.proxy_url || "http://127.0.0.1:8090"}/${payload.api_mode || "v2"}/chat/completions`;
      const args = [
        payload.stream ? "curl -sS -N" : "curl -sS",
        shellQuote(url),
        "-H",
        shellQuote("Content-Type: application/json")
      ];
      if (payload.stream) args.push("-H", shellQuote("Accept: text/event-stream"));
      args.push(
        "-H",
        shellQuote("Authorization: Bearer <GPT2GIGA_API_KEY>"),
        "-d",
        shellQuote(JSON.stringify(body))
      );
      return args.join(" ");
    }

    async function copyText(text, status) {
      try {
        await navigator.clipboard.writeText(text);
        setText("model-status", status);
      } catch (error) {
        setText("model-status", "Clipboard unavailable.");
      }
    }

    function showTab(name) {
      for (const tab of document.querySelectorAll(".tab")) {
        tab.classList.toggle("active", tab.dataset.tab === name);
      }
      for (const panel of document.querySelectorAll(".tab-panel")) {
        panel.classList.remove("active");
      }
      const panelId = name === "run" ? "run-panel" : `${name}-panel`;
      const panel = byId(panelId);
      if (panel) panel.classList.add("active");
    }

    function setInspectorOpen(open) {
      document.body.classList.toggle("inspector-open", open);
      byId("details-toggle-button").setAttribute("aria-expanded", open ? "true" : "false");
      if (open) setSidebarOpen(false);
    }

    function setSidebarOpen(open) {
      document.body.classList.toggle("sidebar-open", open);
      byId("session-drawer-button").setAttribute("aria-expanded", open ? "true" : "false");
    }

    function prepareAdvancedPanel() {
      const grid = document.querySelector(".quick-config");
      const panel = document.createElement("div");
      panel.id = "advanced-settings-panel";
      panel.className = "advanced-panel";
      panel.hidden = true;
      for (const control of Array.from(grid.querySelectorAll(".advanced-control"))) {
        panel.appendChild(control);
      }
      grid.appendChild(panel);
      byId("advanced-settings-button").setAttribute("aria-controls", panel.id);
    }

    function setAdvancedSettings(open) {
      const grid = document.querySelector(".quick-config");
      grid.classList.toggle("advanced-open", open);
      byId("advanced-settings-button").setAttribute("aria-expanded", open ? "true" : "false");
      byId("advanced-settings-panel").hidden = !open;
    }

    function toggleAdvancedSettings() {
      const grid = document.querySelector(".quick-config");
      setAdvancedSettings(!grid.classList.contains("advanced-open"));
    }

    function resetComposer() {
      byId("prompt-input").value = "";
      byId("dry-run-checkbox").checked = false;
      byId("stream-checkbox").checked = false;
      closeHeadlessEventSource();
      setHeadlessRunning(false);
      state.attachments = [];
      renderAttachments();
    }

    function shellQuote(value) {
      const text = String(value == null ? "" : value);
      if (/^[A-Za-z0-9_./:=@-]+$/.test(text)) return text;
      return `'${text.replace(/'/g, "'\\\\''")}'`;
    }

    function bindTabEvents() {
      for (const tabs of document.querySelectorAll(".tabs")) {
        tabs.addEventListener("click", (event) => {
          const tab = event.target && event.target.closest ? event.target.closest(".tab") : null;
          if (tab && tabs.contains(tab)) showTab(tab.dataset.tab);
        });
      }
    }

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    async function loadScheduledCenter(scheduleId = null) {
      if (!state.project || !state.project.root) return false;
      setText("scheduled-status", "Refreshing schedules and attention...");
      const result = await getJson(`/api/automation?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) {
        setText("scheduled-status", result.data.detail || "Scheduled Automation is unavailable.");
        return false;
      }
      state.schedules = Array.isArray(result.data.schedules) ? result.data.schedules : [];
      state.scheduleHistory = Array.isArray(result.data.history) ? result.data.history : [];
      state.scheduleWorker = result.data.worker || {};
      state.attentionItems = result.data.attention && Array.isArray(result.data.attention.items) ? result.data.attention.items : [];
      state.selectedScheduleId = scheduleId || state.selectedScheduleId;
      const unread = Number(result.data.attention && result.data.attention.unread || 0);
      const badge = byId("attention-count");
      badge.hidden = unread < 1;
      badge.textContent = String(unread);
      byId("scheduled-worker").className = `badge ${state.scheduleWorker.online ? "ok" : "warn"}`;
      setText("scheduled-worker", `Worker: ${state.scheduleWorker.online ? `${state.scheduleWorker.count} online` : "offline"}`);
      setText("scheduled-status", `${state.schedules.length} schedules · ${unread} unread · immutable history retained`);
      setText("attention-status", `${unread} unread · approvals, failed jobs, and schedule findings`);
      renderScheduledCenter();
      notifyAttentionItems();
      return true;
    }

    async function loadAttentionBadge() {
      if (!state.project || !state.project.root) return false;
      const result = await getJson(`/api/attention?workspace=${encodeURIComponent(state.project.root)}`);
      if (!result.ok) return false;
      state.attentionItems = Array.isArray(result.data.items) ? result.data.items : [];
      const badge = byId("attention-count");
      badge.hidden = Number(result.data.unread || 0) < 1;
      badge.textContent = String(result.data.unread || 0);
      notifyAttentionItems();
      return true;
    }

    function renderScheduledCenter() {
      renderScheduleList();
      renderScheduleCalendar();
      renderScheduleHistory();
      renderAttentionInbox();
      for (const button of document.querySelectorAll("[data-scheduled-view]")) {
        button.classList.toggle("active", button.dataset.scheduledView === state.scheduledView);
      }
      byId("schedule-list").hidden = state.scheduledView !== "list";
      byId("schedule-calendar").hidden = state.scheduledView !== "calendar";
      byId("schedule-history").hidden = state.scheduledView !== "history";
    }

    function renderScheduleList() {
      const list = byId("schedule-list");
      list.textContent = "";
      for (const item of state.schedules) {
        const definition = item.definition || {};
        const scheduleState = item.state || {};
        const scheduleId = definition.id || scheduleState.schedule_id;
        const status = scheduleState.status || "paused";
        const target = definition.target || {};
        const cadence = definition.cadence || {};
        const tested = scheduleState.tested_hash && scheduleState.tested_hash === definition.source_hash;
        const archived = status === "archived";
        const card = document.createElement("article");
        card.className = "schedule-card";
        if (scheduleId === state.selectedScheduleId) card.classList.add("active");
        card.innerHTML = `<div class="schedule-card-header"><div><strong>${escapeHtml(definition.title || scheduleId)}</strong><div class="schedule-card-meta">${escapeHtml(scheduleId)} · ${escapeHtml(target.kind || "target")}:${escapeHtml(target.id || "unknown")}</div></div><span class="runs-status ${status === "active" ? "completed" : status === "needs_attention" ? "failed" : "blocked"}">${escapeHtml(status)}</span></div><div class="schedule-card-meta"><span>Next: ${escapeHtml(scheduleState.next_run_at || "not scheduled")}</span><span>Last: ${escapeHtml(scheduleState.last_status || "never")} ${scheduleState.last_error ? `· ${escapeHtml(scheduleState.last_error)}` : ""}</span><span>Version: ${escapeHtml(String(definition.source_hash || scheduleState.definition_hash || "").slice(0, 12))} · ${escapeHtml(cadence.kind || "unknown")} · ${escapeHtml(cadence.timezone || scheduleState.timezone || "UTC")}</span><span>Workspace: dedicated worktree · Policy: ${definition.workspace_policy === "worktree" ? "isolated" : "blocked"} · Test gate: ${tested ? "passed" : "required"}</span></div>`;
        if (!archived) {
          const actions = document.createElement("div");
          actions.className = "schedule-card-actions";
          for (const [label, action, className, disabled] of [
            ["Edit", "edit", "secondary", false],
            ["Test now", "test-now", "secondary", false],
            [status === "active" ? "Pause" : "Enable", status === "active" ? "pause" : "enable", "", status !== "active" && (!tested || !state.scheduleWorker.online)],
            ["Run now", "run-now", "secondary", !tested],
            ["Archive", "archive", "danger", false]
          ]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = className;
            button.textContent = label;
            button.disabled = Boolean(disabled);
            if (disabled && action === "enable") button.title = tested ? "Start the local worker first" : "Run Test now successfully for this exact version first";
            button.addEventListener("click", () => action === "edit" ? openScheduleWizard(item) : scheduleAction(scheduleId, action));
            actions.appendChild(button);
          }
          card.appendChild(actions);
        }
        card.addEventListener("click", (event) => {
          if (event.target.closest("button")) return;
          state.selectedScheduleId = scheduleId;
          syncBrowserRoute("scheduled", scheduleId);
          renderScheduleList();
        });
        list.appendChild(card);
      }
      if (!state.schedules.length) list.innerHTML = '<div class="status-line">No schedules yet. Create one to make repeatable work visible here.</div>';
    }

    function renderScheduleCalendar() {
      const calendar = byId("schedule-calendar");
      calendar.textContent = "";
      const entries = [];
      for (const item of state.schedules) {
        for (const occurrence of item.preview || []) {
          if (occurrence.utc) entries.push({ ...occurrence, schedule: item.definition.title || item.definition.id });
        }
      }
      entries.sort((left, right) => String(left.utc).localeCompare(String(right.utc)));
      for (const entry of entries.slice(0, 60)) {
        const row = document.createElement("article");
        row.className = "calendar-item";
        row.innerHTML = `<strong>${escapeHtml(entry.schedule)}</strong><div class="schedule-card-meta"><span>${escapeHtml(entry.utc)}</span><span>${escapeHtml(entry.local)} · ${escapeHtml(entry.status)}</span></div>`;
        calendar.appendChild(row);
      }
      if (!entries.length) calendar.innerHTML = '<div class="status-line">No upcoming occurrences.</div>';
    }

    function renderScheduleHistory() {
      const history = byId("schedule-history");
      history.textContent = "";
      for (const occurrence of state.scheduleHistory) {
        const row = document.createElement("article");
        row.className = "history-item";
        row.innerHTML = `<div class="attention-item-header"><strong>${escapeHtml(occurrence.schedule_id)}</strong><span class="runs-status ${occurrence.status === "succeeded" ? "completed" : occurrence.status}">${escapeHtml(occurrence.status)}</span></div><div class="schedule-card-meta"><span>${escapeHtml(occurrence.trigger)} · ${escapeHtml(occurrence.scheduled_for)}</span><span>${escapeHtml(occurrence.error_summary || occurrence.run_id || occurrence.job_id || "Audit record")}</span></div>`;
        history.appendChild(row);
      }
      if (!state.scheduleHistory.length) history.innerHTML = '<div class="status-line">No occurrence history yet.</div>';
    }

    function renderAttentionInbox() {
      const list = byId("attention-list");
      list.textContent = "";
      for (const item of state.attentionItems) {
        const card = document.createElement("article");
        card.className = `attention-item ${item.severity || "warning"}${item.read ? " read" : ""}`;
        card.innerHTML = `<div class="attention-item-header"><strong>${escapeHtml(item.title)}</strong><span class="badge ${item.read ? "" : "warn"}">${item.read ? "read" : "unread"}</span></div><div class="attention-item-meta"><span>${escapeHtml(item.summary)}</span><span>${escapeHtml(item.created_at)}</span></div>`;
        const actions = document.createElement("div");
        actions.className = "schedule-card-actions";
        const open = document.createElement("button");
        open.type = "button";
        open.className = "secondary";
        open.textContent = "Review";
        open.addEventListener("click", async () => {
          await markAttentionRead([item.id], true);
          window.location.assign(item.href);
        });
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "secondary";
        toggle.textContent = item.read ? "Mark unread" : "Mark read";
        toggle.addEventListener("click", () => markAttentionRead([item.id], !item.read));
        actions.append(open, toggle);
        card.appendChild(actions);
        list.appendChild(card);
      }
      if (!state.attentionItems.length) list.innerHTML = '<div class="status-line">Nothing needs attention.</div>';
      byId("mark-attention-read-button").disabled = !state.attentionItems.some((item) => !item.read);
    }

    async function markAttentionRead(itemIds, read) {
      if (!itemIds.length) return;
      const result = await getJson("/api/attention/read", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item_ids: itemIds, read }) });
      if (!result.ok) return setText("attention-status", result.data.detail || "Could not update inbox.");
      await loadScheduledCenter(state.selectedScheduleId);
    }

    async function scheduleAction(scheduleId, action) {
      if (action === "archive") {
        const result = await getJson(`/api/schedules/${encodeURIComponent(scheduleId)}?workspace=${encodeURIComponent(state.project.root)}`, { method: "DELETE" });
        if (!result.ok) return setText("scheduled-status", result.data.detail || "Archive failed.");
      } else {
        const result = await getJson(`/api/schedules/${encodeURIComponent(scheduleId)}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workspace: state.project.root }) });
        if (!result.ok) return setText("scheduled-status", result.data.detail || `${action} failed.`);
        if (result.data.approval_required) {
          setText("scheduled-status", `${action} is waiting in Approval Center.`);
          return syncBrowserRoute("approvals", null);
        }
      }
      await loadScheduledCenter(scheduleId);
    }

    function openScheduleWizard(item = null) {
      const definition = item && item.definition || {};
      const target = definition.target || {};
      const cadence = definition.cadence || {};
      byId("schedule-wizard-title").textContent = definition.id ? "Edit schedule" : "New schedule";
      byId("schedule-id-input").value = definition.id || "";
      byId("schedule-id-input").disabled = Boolean(definition.id);
      byId("schedule-title-input").value = definition.title || "";
      byId("schedule-target-kind").value = target.kind || "agent";
      byId("schedule-target-id").value = target.id || "";
      byId("schedule-cadence-kind").value = cadence.kind || "once";
      byId("schedule-start-at").value = String(cadence.start_at || new Date(Date.now() + 3600000).toISOString()).slice(0, 16);
      byId("schedule-timezone").value = cadence.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      byId("schedule-interval").value = cadence.interval_seconds || 86400;
      byId("schedule-rrule").value = cadence.rrule || "FREQ=DAILY";
      byId("schedule-destination").value = definition.destination || "new_task";
      byId("schedule-session-id").value = definition.session_id || "";
      byId("schedule-concurrency").value = definition.max_concurrency || 1;
      byId("schedule-overlap").value = definition.overlap_policy || "skip";
      byId("schedule-misfire").value = definition.misfire_policy || "skip";
      byId("schedule-attempts").value = definition.max_attempts || 1;
      byId("schedule-timeout").value = definition.timeout_seconds || 3600;
      byId("schedule-notifications").checked = Boolean(definition.notifications && definition.notifications.desktop);
      setText("schedule-form-status", "Saving pauses the definition and invalidates its previous Test now grant.");
      byId("schedule-preview").textContent = "Preview upcoming occurrences before saving.";
      byId("schedule-wizard").showModal();
    }

    function scheduleFormPayload() {
      return {
        workspace: state.project.root,
        id: byId("schedule-id-input").value.trim(),
        title: byId("schedule-title-input").value.trim(),
        target: { kind: byId("schedule-target-kind").value, id: byId("schedule-target-id").value.trim() },
        cadence: { kind: byId("schedule-cadence-kind").value, timezone: byId("schedule-timezone").value.trim(), start_at: byId("schedule-start-at").value, interval_seconds: Number(byId("schedule-interval").value), rrule: byId("schedule-rrule").value.trim() },
        destination: byId("schedule-destination").value,
        session_id: byId("schedule-session-id").value.trim() || null,
        workspace_policy: "worktree",
        max_concurrency: Number(byId("schedule-concurrency").value),
        overlap_policy: byId("schedule-overlap").value,
        misfire_policy: byId("schedule-misfire").value,
        max_attempts: Number(byId("schedule-attempts").value),
        timeout_seconds: Number(byId("schedule-timeout").value),
        notifications: { desktop: byId("schedule-notifications").checked }
      };
    }

    async function previewSchedule() {
      const result = await getJson("/api/schedules/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(scheduleFormPayload()) });
      if (!result.ok) return setText("schedule-form-status", result.data.detail || "Preview failed.");
      byId("schedule-preview").textContent = pretty(result.data.occurrences);
      setText("schedule-form-status", `Valid exact hash ${String(result.data.definition.source_hash).slice(0, 12)} · no files changed`);
    }

    async function saveSchedule() {
      const payload = scheduleFormPayload();
      const editing = byId("schedule-id-input").disabled;
      const url = editing ? `/api/schedules/${encodeURIComponent(payload.id)}` : "/api/schedules";
      const result = await getJson(url, { method: editing ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!result.ok) return setText("schedule-form-status", result.data.detail || "Save failed.");
      if (result.data.approval_required) {
        byId("schedule-wizard").close();
        return syncBrowserRoute("approvals", null);
      }
      byId("schedule-wizard").close();
      state.selectedScheduleId = payload.id;
      syncBrowserRoute("scheduled", payload.id);
      await loadScheduledCenter(payload.id);
    }

    async function configureDesktopNotifications() {
      if (!("Notification" in window)) return setText("scheduled-status", "Desktop notifications are not supported by this browser.");
      const permission = await Notification.requestPermission();
      state.desktopNotificationsEnabled = permission === "granted";
      byId("notification-button").textContent = `Desktop alerts: ${permission === "granted" ? "on" : "off"}`;
    }

    function notifyAttentionItems() {
      const enabled = state.desktopNotificationsEnabled;
      byId("notification-button").textContent = `Desktop alerts: ${enabled ? "on" : "off"}`;
      if (!enabled || !("Notification" in window) || Notification.permission !== "granted") return;
      for (const item of state.attentionItems) {
        if (item.read || !item.desktop_notification || state.notifiedAttentionIds.has(item.id)) continue;
        const notification = new Notification(item.title, { body: item.summary, tag: item.id });
        notification.onclick = () => window.location.assign(item.href);
        state.notifiedAttentionIds.add(item.id);
      }
    }

    function bindEvents() {
      if (state.eventsBound) return;
      state.eventsBound = true;
      bindTabEvents();
      bindPrimaryNavigation();
      const composer = byId("composer");
      byId("details-toggle-button").addEventListener("click", () => setInspectorOpen(true));
      byId("close-inspector-button").addEventListener("click", () => setInspectorOpen(false));
      byId("inspector-backdrop").addEventListener("click", () => setInspectorOpen(false));
      byId("session-drawer-button").addEventListener("click", () => setSidebarOpen(true));
      byId("sidebar-backdrop").addEventListener("click", () => setSidebarOpen(false));
      byId("advanced-settings-button").addEventListener("click", toggleAdvancedSettings);
      for (const example of document.querySelectorAll(".example-prompt")) {
        example.addEventListener("click", () => {
          byId("prompt-input").value = example.textContent.trim();
          byId("prompt-input").focus();
          scheduleRouteRecommendation();
        });
      }
      byId("refresh-health-button").addEventListener("click", refreshHealth);
      byId("refresh-models-button").addEventListener("click", loadModels);
      byId("refresh-runs-center-button").addEventListener("click", () => loadRunsCenter());
      byId("refresh-approvals-button").addEventListener("click", () => loadApprovals());
      byId("refresh-scheduled-button").addEventListener("click", () => loadScheduledCenter(state.selectedScheduleId));
      byId("new-schedule-button").addEventListener("click", () => openScheduleWizard());
      byId("notification-button").addEventListener("click", configureDesktopNotifications);
      byId("mark-attention-read-button").addEventListener("click", () => markAttentionRead(state.attentionItems.filter((item) => !item.read).map((item) => item.id), true));
      byId("preview-schedule-button").addEventListener("click", previewSchedule);
      byId("save-schedule-button").addEventListener("click", saveSchedule);
      byId("close-schedule-wizard").addEventListener("click", () => byId("schedule-wizard").close());
      for (const button of document.querySelectorAll("[data-scheduled-view]")) {
        button.addEventListener("click", () => {
          state.scheduledView = button.dataset.scheduledView || "list";
          renderScheduledCenter();
        });
      }
      byId("load-more-runs-button").addEventListener("click", () => loadRunsCenter({ append: true }));
      byId("load-older-trace-button").addEventListener("click", () => loadRunsTrace(true));
      byId("runs-open-task-button").addEventListener("click", () => runCenterAction("open_task"));
      byId("runs-cancel-button").addEventListener("click", () => runCenterAction("cancel"));
      byId("runs-retry-button").addEventListener("click", () => runCenterAction("retry"));
      byId("runs-open-worktree-button").addEventListener("click", () => runCenterAction("open_worktree"));
      byId("runs-inspect-artifact-button").addEventListener("click", () => runCenterAction("inspect_artifact"));
      for (const filter of document.querySelectorAll("[data-run-status]")) {
        filter.addEventListener("click", async () => {
          state.runsCenterStatus = filter.dataset.runStatus || "";
          for (const button of document.querySelectorAll("[data-run-status]")) {
            button.classList.toggle("active", button === filter);
          }
          state.runsCenterSelected = null;
          closeRunsCenterEventStream();
          renderRunsCenterSelection();
          syncBrowserRoute("runs", null);
          await loadRunsCenter();
        });
      }
      for (const filter of document.querySelectorAll("[data-approval-status]")) {
        filter.addEventListener("click", async () => {
          state.approvalsStatus = filter.dataset.approvalStatus || "";
          for (const button of document.querySelectorAll("[data-approval-status]")) {
            button.classList.toggle("active", button === filter);
          }
          await loadApprovals();
        });
      }
      byId("init-project-button").addEventListener("click", initProject);
      byId("new-chat-button").addEventListener("click", newChat);
      byId("add-memory-button").addEventListener("click", addMemoryFromInput);
      byId("remember-message-button").addEventListener("click", rememberLastMessage);
      byId("refresh-evals-button").addEventListener("click", loadEvals);
      byId("refresh-evaluate-button").addEventListener("click", loadEvaluateCenter);
      byId("run-evaluate-button").addEventListener("click", runEvaluateMatrix);
      byId("cancel-evaluate-button").addEventListener("click", cancelEvaluateRun);
      byId("pin-evaluate-baseline-button").addEventListener("click", pinEvaluateBaseline);
      byId("refresh-tools-center-button").addEventListener("click", loadToolsCenter);
      byId("preview-tool-config-button").addEventListener("click", previewManagedToolConfig);
      byId("apply-tool-config-button").addEventListener("click", applyManagedToolConfig);
      byId("rollback-tool-config-button").addEventListener("click", rollbackManagedToolConfig);
      byId("tool-config-harness-select").addEventListener("change", () => {
        state.managedToolConfigPlan = null;
        byId("apply-tool-config-button").disabled = true;
        byId("tool-config-diff-panel").hidden = true;
      });
      byId("refresh-agents-button").addEventListener("click", loadAgentsCenter);
      byId("validate-agent-button").addEventListener("click", previewAgent);
      byId("apply-agent-button").addEventListener("click", applyAgent);
      byId("duplicate-agent-button").addEventListener("click", duplicateAgent);
      byId("run-agent-button").addEventListener("click", runSelectedAgent);
      byId("refresh-workflows-button").addEventListener("click", () => loadWorkflowsCenter(state.selectedWorkflow && state.selectedWorkflow.workflow.id));
      byId("create-workflow-template-button").addEventListener("click", () => importWorkflow(null, byId("workflow-template-select").value));
      byId("import-workflow-button").addEventListener("click", () => {
        const content = window.prompt("Paste workflow YAML");
        if (content) importWorkflow(content, null);
      });
      byId("validate-workflow-button").addEventListener("click", validateWorkflowSource);
      byId("save-workflow-button").addEventListener("click", saveSelectedWorkflow);
      byId("duplicate-workflow-button").addEventListener("click", duplicateSelectedWorkflow);
      byId("add-workflow-step-button").addEventListener("click", () => addWorkflowStepRow());
      byId("run-eval-button").addEventListener("click", runSelectedEval);
      byId("harness-select").addEventListener("change", (event) => {
        selectHarness(event.target.value);
        renderRouteRecommendation(state.routeRecommendation);
      });
      byId("arena-harness-options").addEventListener("change", (event) => {
        if (!event.target.matches('input[name="arena-harness"]')) return;
        state.arenaSelectionTouched = true;
        updateArenaSelectionUi();
      });
      byId("arena-select-all-button").addEventListener("click", () => selectAllArenaHarnesses(true));
      byId("arena-clear-button").addEventListener("click", () => selectAllArenaHarnesses(false));
      byId("invocation-select").addEventListener("change", () => {
        updateHarnessDrivenControls();
        persistProjectState();
      });
      byId("sync-native-button").addEventListener("click", () => loadNativeSessions(true, { openModal: true, resetVisible: true }));
      byId("open-native-history-button").addEventListener("click", () => openNativeHistory(true));
      byId("load-more-native-button").addEventListener("click", loadMoreNativeSessions);
      byId("close-native-history-button").addEventListener("click", closeNativeHistory);
      byId("native-history-modal").addEventListener("click", (event) => {
        if (event.target === byId("native-history-modal")) closeNativeHistory();
      });
      byId("preflight-modal").addEventListener("click", (event) => {
        if (event.target === byId("preflight-modal")) closePreflightModal(false);
      });
      byId("close-preflight-button").addEventListener("click", () => closePreflightModal(false));
      byId("continue-preflight-button").addEventListener("click", () => closePreflightModal(true));
      byId("auth-form").addEventListener("submit", authenticateBrowser);
      window.addEventListener("popstate", () => applyCurrentRoute());
      window.addEventListener("resize", () => {
        syncNavigation();
        scheduleNativeResize();
      });
      window.addEventListener("beforeunload", stopNativeOutputTransport);
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && state.nativeModalOpen) closeNativeHistory();
        if (event.key === "Escape" && state.preflightModalOpen) closePreflightModal(false);
        if (event.key === "Escape" && document.body.classList.contains("inspector-open")) setInspectorOpen(false);
        if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) setSidebarOpen(false);
      });
      byId("native-all-workspaces-checkbox").addEventListener("change", () => loadNativeSessions(false, { resetVisible: true }));
      byId("poll-native-output-button").addEventListener("click", pollNativeOutput);
      byId("native-terminal-diagnostics").addEventListener("toggle", scheduleNativeResize);
      byId("native-trust-yes-button").addEventListener("click", () => respondToNativeTrust(true));
      byId("native-trust-no-button").addEventListener("click", () => respondToNativeTrust(false));
      byId("stop-native-process-button").addEventListener("click", stopNativeProcess);
      byId("clear-native-terminal-button").addEventListener("click", clearNativeTerminal);
      byId("api-mode-v1").addEventListener("change", () => { updateRouteNote(); loadModels(); persistProjectState(); });
      byId("api-mode-v2").addEventListener("change", () => { updateRouteNote(); loadModels(); persistProjectState(); });
      byId("mode-select").addEventListener("change", () => {
        persistProjectState();
        scheduleRouteRecommendation();
      });
      byId("workspace-policy-select").addEventListener("change", () => persistProjectState());
      byId("workspace-input").addEventListener("input", scheduleRouteRecommendation);
      byId("workspace-input").addEventListener("change", () => {
        persistProjectState();
        scheduleRouteRecommendation();
      });
      byId("model-menu-button").addEventListener("click", toggleModelList);
      byId("model-input").addEventListener("focus", openModelList);
      byId("model-input").addEventListener("input", () => {
        updateHeaderBadges();
        openModelList();
      });
      byId("model-input").addEventListener("change", () => persistProjectState());
      byId("model-input").addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeModelList();
        if (event.key === "ArrowDown") {
          event.preventDefault();
          openModelList();
          const first = byId("model-list").querySelector(".model-option:not(.empty)");
          if (first) first.focus();
        }
      });
      byId("model-list").addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          closeModelList();
          byId("model-input").focus();
        }
      });
      document.addEventListener("click", (event) => {
        if (!byId("model-picker").contains(event.target)) closeModelList();
      });
      byId("run-button").addEventListener("click", runHarness);
      byId("arena-compare-button").addEventListener("click", runArena);
      byId("interrupt-run-button").addEventListener("click", () => runHarness("interrupt"));
      byId("cancel-run-button").addEventListener("click", cancelHeadlessRun);
      byId("apply-route-recommendation-button").addEventListener("click", applyRouteRecommendation);
      byId("apply-run-diff-button").addEventListener("click", applyRunDiff);
      byId("discard-run-worktree-button").addEventListener("click", discardRunWorktree);
      byId("open-run-worktree-button").addEventListener("click", openRunWorktree);
      byId("open-run-terminal-button").addEventListener("click", openRunTerminal);
      byId("copy-pr-title-button").addEventListener("click", () => copyCurrentPrField("title", "Copied PR title."));
      byId("copy-pr-body-button").addEventListener("click", () => copyCurrentPrField("body", "Copied PR body."));
      byId("copy-pr-patch-button").addEventListener("click", () => copyCurrentPrField("patch", "Copied PR patch."));
      byId("create-pr-branch-button").addEventListener("click", createPrBranch);
      byId("refresh-provenance-button").addEventListener("click", refreshRunProvenance);
      byId("replay-run-button").addEventListener("click", replayCurrentRun);
      byId("fork-run-button").addEventListener("click", forkCurrentRun);
      byId("promote-agent-button").addEventListener("click", () => previewRunPromotion("agent"));
      byId("promote-workflow-button").addEventListener("click", () => previewRunPromotion("workflow"));
      byId("promote-eval-button").addEventListener("click", () => previewRunPromotion("eval"));
      byId("preview-promotion-button").addEventListener("click", generateRunPromotion);
      byId("apply-promotion-button").addEventListener("click", applyRunPromotion);
      byId("cancel-promotion-button").addEventListener("click", cancelRunPromotion);
      byId("open-editor-workspace-button").addEventListener("click", () => openEditorWorkspace(false));
      byId("open-editor-run-button").addEventListener("click", () => openEditorWorkspace(true));
      byId("open-editor-diff-button").addEventListener("click", openEditorDiff);
      byId("open-editor-terminal-button").addEventListener("click", openRunTerminal);
      byId("open-editor-file-button").addEventListener("click", openEditorFile);
      byId("copy-session-open-command-button").addEventListener("click", copySessionOpenCommand);
      byId("copy-run-open-command-button").addEventListener("click", copyRunOpenCommand);
      byId("reset-button").addEventListener("click", resetComposer);
      byId("attach-file-button").addEventListener("click", () => byId("attachment-file-input").click());
      byId("attachment-file-input").addEventListener("change", (event) => {
        attachFiles(event.target.files, "upload");
        event.target.value = "";
      });
      composer.addEventListener("dragenter", (event) => {
        event.preventDefault();
        composer.classList.add("drag-over");
      });
      composer.addEventListener("dragover", (event) => {
        event.preventDefault();
        composer.classList.add("drag-over");
      });
      composer.addEventListener("dragleave", (event) => {
        if (!composer.contains(event.relatedTarget)) composer.classList.remove("drag-over");
      });
      composer.addEventListener("drop", (event) => {
        event.preventDefault();
        composer.classList.remove("drag-over");
        attachFiles(event.dataTransfer.files, "upload");
      });
      byId("copy-cli-button").addEventListener("click", () => copyText(commandPreview(state.lastPayload || buildPayload()), "Copied CLI command."));
      byId("copy-curl-button").addEventListener("click", () => copyText(curlPreview(), "Copied curl command."));
      byId("session-search").addEventListener("input", loadSessions);
      byId("session-workspace-filter").addEventListener("change", loadSessions);
      byId("session-harness-filter").addEventListener("change", loadSessions);
      byId("include-archived-checkbox").addEventListener("change", loadSessions);
      byId("rename-session-button").addEventListener("click", renameCurrentSession);
      byId("pin-session-button").addEventListener("click", () => {
        const pinned = !(state.currentBundle && state.currentBundle.session && state.currentBundle.session.pinned);
        patchCurrentSession({ pinned });
      });
      byId("archive-session-button").addEventListener("click", () => {
        const archived = !(state.currentBundle && state.currentBundle.session && state.currentBundle.session.archived);
        patchCurrentSession({ archived });
      });
      byId("delete-session-button").addEventListener("click", deleteCurrentSession);
      byId("prompt-input").addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          runHarness();
        }
        if (event.key === "Escape") hideWorkspaceFileMenu();
      });
      byId("prompt-input").addEventListener("input", () => {
        searchWorkspaceFiles();
        scheduleRouteRecommendation();
      });
      byId("prompt-input").addEventListener("paste", (event) => {
        const items = event.clipboardData && event.clipboardData.items ? Array.from(event.clipboardData.items) : [];
        const files = items
          .filter((item) => item.kind === "file")
          .map((item) => item.getAsFile())
          .filter((file) => file && String(file.type || "").startsWith("image/"));
        if (files.length) attachFiles(files, "paste");
      });
      byId("arena-prompt-input").addEventListener("keydown", (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
          event.preventDefault();
          runArena();
        }
      });
    }

    function bindPrimaryNavigation() {
      for (const link of document.querySelectorAll(".primary-nav-link")) {
        link.addEventListener("click", (event) => {
          if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          const target = new URL(link.href, window.location.href);
          if (target.origin !== window.location.origin) return;
          event.preventDefault();
          window.history.pushState({}, "", `${target.pathname}${target.search}${target.hash}`);
          syncNavigation();
          void applyCurrentRoute();
        });
      }
    }

    async function authenticateBrowser(event) {
      event.preventDefault();
      const input = byId("auth-token-input");
      const token = input.value;
      if (!token) {
        setText("auth-status", "Enter the bootstrap token.");
        return;
      }
      setText("auth-status", "Authenticating...");
      const result = await getJson("/auth/session", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      });
      input.value = "";
      if (!result.ok) {
        setText("auth-status", result.data.detail || "Authentication failed.");
        return;
      }
      byId("auth-modal").hidden = true;
      await boot();
    }

    function clearRouteSelection() {
      closeHeadlessEventSource();
      closeRunsCenterEventStream();
      state.currentSessionId = null;
      state.selectedRunId = null;
      state.currentBundle = null;
      state.attachments = [];
      renderAttachments();
      renderAll();
    }

    async function applyCurrentRoute() {
      const routeKey = `${window.location.pathname}${window.location.search}`;
      if (state.routeLoadedKey === routeKey) return true;
      if (state.routeLoadKey === routeKey && state.routeLoadPromise) return state.routeLoadPromise;
      const promise = loadCurrentRoute();
      state.routeLoadKey = routeKey;
      state.routeLoadPromise = promise;
      try {
        const loaded = await promise;
        if (loaded) state.routeLoadedKey = routeKey;
        return loaded;
      } finally {
        if (state.routeLoadPromise === promise) {
          state.routeLoadKey = null;
          state.routeLoadPromise = null;
        }
      }
    }

    async function loadCurrentRoute() {
      const route = currentRoute();
      syncNavigation();
      if (route.area === "work" && route.id) {
        closeRunsCenterEventStream();
        await loadSession(route.id, { syncRoute: false });
        return true;
      }
      if (route.area === "arena") {
        closeRunsCenterEventStream();
        return loadArenaCenter({ hydrateControls: !state.currentArena });
      }
      if (route.area === "runs" && route.id) {
        await loadRunsCenter();
        const item = await resolveRunsCenterItem(route.id);
        if (item) await selectRunsCenterItem(item, { syncRoute: false });
        else setText("runs-center-status", "Run deep link was not found.");
        return true;
      }
      if (route.area === "runs") {
        closeRunsCenterEventStream();
        state.runsCenterSelected = null;
        state.runsTraceNodes = [];
        state.runsTraceCursor = null;
        renderRunsCenterSelection();
        await loadRunsCenter();
        return true;
      }
      if (route.area === "approvals") {
        closeRunsCenterEventStream();
        await loadApprovals();
        return true;
      }
      if (route.area === "tools") {
        closeRunsCenterEventStream();
        await loadToolsCenter();
        return true;
      }
      if (route.area === "agents") {
        closeRunsCenterEventStream();
        await loadAgentsCenter();
        return true;
      }
      if (route.area === "workflows") {
        closeRunsCenterEventStream();
        await loadWorkflowsCenter(route.id);
        return true;
      }
      if (route.area === "evaluate") {
        closeRunsCenterEventStream();
        await loadEvaluateCenter();
        return true;
      }
      if (route.area === "scheduled") {
        closeRunsCenterEventStream();
        await loadScheduledCenter(route.id);
        return true;
      }
      if (route.area === "work") {
        clearRouteSelection();
        syncNavigation();
        return true;
      }
      syncNavigation();
      return false;
    }

    async function boot() {
      if (!state.eventsBound) prepareAdvancedPanel();
      bindEvents();
      renderNativeTerminalStatus("idle");
      const defaults = await loadDefaults();
      if (!defaults.ok) {
        byId("auth-modal").hidden = false;
        setText("auth-status", defaults.data.detail || "A browser session is required.");
        byId("auth-token-input").focus();
        return;
      }
      byId("auth-modal").hidden = true;
      await loadProject();
      const secondaryLoads = Promise.all([
        loadMemory(),
        loadTools(),
        loadEvals(),
        loadHarnesses(),
        refreshHealth(),
        loadModels(),
        loadApprovals(),
        loadAttentionBadge()
      ]);
      const route = currentRoute();
      if ((route.area === "work" && !route.id) || route.area === "legacy") await loadSessions();
      const routed = await applyCurrentRoute();
      if (!routed && !state.currentSessionId && state.projectState && state.projectState.last_selected_session) {
        await loadSession(state.projectState.last_selected_session);
      }
      renderAll();
      await secondaryLoads;
    }

    boot();
