import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import {
  type AttachmentUploadResponse,
  deleteCockpit,
  type EventProjection,
  type EventPayloadResponse,
  fetchCockpit,
  mutateCockpit,
  patchCockpit,
  type RunStartResponse,
  type SessionSummary,
  type TokenUsageProjection,
} from "../api";
import { MessageMarkdown } from "../message-markdown";
import { generatedImageProjection } from "../generated-image";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import {
  requestKeys,
  refreshSessionAfterRunStart,
  harnessesOptions,
  modelsOptions,
  sessionAttachmentsOptions,
  sessionEventsOptions,
  sessionIndexOptions,
  sessionMessagesOptions,
  sessionOverviewOptions,
  sessionRunsOptions,
  runsCenterOptions,
} from "../request-graph";
import {
  formatTimestamp,
  latestRun,
  runStage,
  sessionGroups,
  shortId,
  type RunStage,
} from "../surface-model";
import { useRunEventStream } from "../stream-store";
import {
  projectToolPayload,
  projectWorkbenchStream,
  type WorkbenchPlanItem,
  type WorkbenchToolActivity,
  workbenchRunActive,
} from "../workbench-model";

const layoutKey = "gpt2giga.cockpit-v2.workbench-layout.v1";
const runPreferencesKey = "gpt2giga.cockpit-v2.run-preferences.v1";
const sessionTitleModel = "GigaChat-3-Lightning";
const reasoningModel = "GigaChat-2-Reasoning";
type SessionAction = "archive" | "delete";
type RunConfig = { apiMode: string; harnessId: string; mode: string; model: string };
type ReasoningEffort = "high" | "low" | "medium";
type AdvancedRunConfig = {
  capability: string;
  dryRun: boolean;
  invocationMode: string;
  permissionProfile: string;
  stream: boolean;
  workspacePolicy: string;
};

const builtinToolLabels: Record<string, string> = {
  code_interpreter: "Code interpreter",
  image_generate: "Image generation",
  model_3d_generate: "3D generation",
  url_content_extraction: "URL content",
  web_search: "Web search",
};
const emptyStringList: readonly string[] = [];
const activeRunStatusGroups = new Set(["approval-needed", "blocked", "queued", "running"]);
const terminalRunStatusGroups = new Set(["canceled", "completed", "failed"]);

type CompletionNotice = {
  id: string;
  sessionId: string;
  status: string;
  title: string;
};

export function WorkbenchSurface() {
  const params = useParams({ strict: false });
  const sessionId =
    "sessionId" in params && typeof params.sessionId === "string"
      ? params.sessionId
      : undefined;
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [leftWidth, setLeftWidth] = useState(() => loadWidth("left", 264));
  const [rightWidth, setRightWidth] = useState(() => loadWidth("right", 320));
  const [prompt, setPrompt] = useState("");
  const rememberedRunPreferences = useMemo(loadRunPreferences, []);
  const [runConfig, setRunConfig] = useState<RunConfig>(rememberedRunPreferences.config);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>(
    rememberedRunPreferences.reasoningEffort,
  );
  const [advancedConfig, setAdvancedConfig] = useState<AdvancedRunConfig>({
    capability: "chat_completions",
    dryRun: false,
    invocationMode: "headless",
    permissionProfile: "interactive",
    stream: true,
    workspacePolicy: "auto",
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [builtinTools, setBuiltinTools] = useState<string[]>([]);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [startedRuns, setStartedRuns] = useState<Record<string, string>>({});
  const [unreadSessionIds, setUnreadSessionIds] = useState<Set<string>>(() => new Set());
  const [completionNotices, setCompletionNotices] = useState<CompletionNotice[]>([]);
  const previousRunStatuses = useRef(new Map<string, string>());
  const [sessionConfirmation, setSessionConfirmation] = useState<{
    action: SessionAction;
    id: string;
    title: string;
  } | null>(null);

  const index = useQuery(sessionIndexOptions());
  const runsCenter = useQuery({
    ...runsCenterOptions(),
    refetchInterval: 1_000,
  });
  const harnesses = useQuery(harnessesOptions());
  const models = useQuery(modelsOptions(runConfig.apiMode));
  const overview = useQuery({
    ...sessionOverviewOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const messages = useQuery({
    ...sessionMessagesOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const runs = useQuery({
    ...sessionRunsOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const attachments = useQuery({
    ...sessionAttachmentsOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const events = useQuery({
    ...sessionEventsOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const retainedLatestRun = latestRun(runs.data?.runs ?? []);
  const selectedRunId =
    sessionId === undefined ? retainedLatestRun?.id : startedRuns[sessionId] ?? retainedLatestRun?.id;
  const locallyStartedRunSelected =
    sessionId !== undefined && startedRuns[sessionId] === selectedRunId;
  const stream = useRunEventStream(selectedRunId, 0, !locallyStartedRunSelected);

  useEffect(() => {
    localStorage.setItem(
      layoutKey,
      JSON.stringify({ left: leftWidth, right: rightWidth }),
    );
  }, [leftWidth, rightWidth]);

  useEffect(() => {
    localStorage.setItem(
      runPreferencesKey,
      JSON.stringify({ ...runConfig, reasoningEffort }),
    );
  }, [reasoningEffort, runConfig]);

  useEffect(() => {
    const session = overview.data?.session;
    if (session === undefined) return;
    setRunConfig((current) => ({
      apiMode: session.default_api_mode ?? current.apiMode,
      harnessId: session.default_harness_id ?? current.harnessId,
      mode: session.default_mode ?? current.mode,
      model: session.default_model ?? current.model,
    }));
  }, [
    overview.data?.session.default_api_mode,
    overview.data?.session.default_harness_id,
    overview.data?.session.default_mode,
    overview.data?.session.default_model,
    overview.data?.session.id,
  ]);

  useEffect(() => {
    if (runConfig.model || models.isPending) return;
    const selectedModel = models.isSuccess && models.data.models.length > 0
      ? preferredModel(models.data.models)
      : sessionTitleModel;
    setRunConfig((current) => current.model ? current : { ...current, model: selectedModel });
  }, [models.data?.models, models.isPending, models.isSuccess, runConfig.model]);

  const createSession = useMutation({
    mutationFn: () =>
      mutateCockpit<{ session: SessionSummary }>("/api/sessions", {
        api_mode: runConfig.apiMode,
        harness_id: runConfig.harnessId,
        mode: runConfig.mode,
        model: runConfig.model || null,
        workspace: ".",
      }),
    onSuccess: ({ session }) => {
      setPrompt("");
      setBuiltinTools([]);
      void navigate({
        params: { sessionId: session.id },
        to: "/cockpit-v2/work/$sessionId",
      });
      void queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() });
    },
  });

  const startRun = useMutation({
    mutationFn: () => {
      const session = overview.data?.session;
      if (sessionId === undefined || session === undefined) {
        throw new Error("Session is not selected");
      }
      return mutateCockpit<RunStartResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/run/start`,
        {
          api_mode: runConfig.apiMode,
          attachment_ids: attachments.data?.attachments.map((attachment) => attachment.id) ?? [],
          builtin_tools: runConfig.apiMode === "v2" ? builtinTools : [],
          capability: advancedConfig.capability,
          dry_run: advancedConfig.dryRun,
          extra: {
            generate_session_title: session.title === "Untitled session",
            session_title_model: sessionTitleModel,
            ...(isReasoningModel(runConfig.model)
              ? { agent_adapter_options: { reasoning_effort: reasoningEffort } }
              : {}),
          },
          harness_id: runConfig.harnessId,
          invocation_mode: advancedConfig.invocationMode,
          mode: runConfig.mode,
          model: runConfig.model.trim() || null,
          permission_profile: advancedConfig.permissionProfile,
          prompt: prompt.trim(),
          stream: advancedConfig.stream,
          workspace: session.workspace_bound ? undefined : ".",
          workspace_policy: advancedConfig.workspacePolicy,
        },
      );
    },
    onSuccess: async ({ run }) => {
      setStartedRuns((current) => ({ ...current, [run.session_id]: run.id }));
      previousRunStatuses.current.set(run.id, run.status);
      await refreshSessionAfterRunStart(queryClient, run.session_id);
      setPrompt("");
    },
  });

  const saveRunConfig = useMutation({
    mutationFn: (values: Readonly<Record<string, unknown>>) => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      return patchCockpit<{ session: SessionSummary }>(
        `/api/sessions/${encodeURIComponent(sessionId)}`,
        values,
      );
    },
    onSuccess: ({ session }) => {
      queryClient.setQueryData(
        requestKeys.sessionOverview(session.id),
        (current: typeof overview.data) => current === undefined ? current : { ...current, session },
      );
      void queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() });
    },
  });

  const uploadFiles = useMutation({
    mutationFn: async ({ files, source }: { files: File[]; source: string }) => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      return Promise.all(files.map(async (file) => mutateCockpit<AttachmentUploadResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/attachments`,
        {
          data_base64: await fileToBase64(file),
          filename: file.name || `pasted-${Date.now()}.png`,
          mime_type: file.type || "application/octet-stream",
          source,
        },
      )));
    },
    onSuccess: async () => {
      if (sessionId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: requestKeys.sessionAttachments(sessionId) });
      }
    },
  });

  const removeAttachment = useMutation({
    mutationFn: (attachmentId: string) =>
      deleteCockpit(`/api/attachments/${encodeURIComponent(attachmentId)}`),
    onSuccess: async () => {
      if (sessionId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: requestKeys.sessionAttachments(sessionId) });
      }
    },
  });

  const cancelRun = useMutation({
    mutationFn: (runId: string) =>
      mutateCockpit(`/api/runs/${encodeURIComponent(runId)}/cancel`),
    onSuccess: async () => {
      if (sessionId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: requestKeys.sessionScope(sessionId) });
      }
      await queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() });
    },
  });

  const changeSession = useMutation({
    mutationFn: ({ action, id }: { action: SessionAction; id: string }) =>
      action === "archive"
        ? patchCockpit(`/api/sessions/${encodeURIComponent(id)}`, { archived: true })
        : deleteCockpit(`/api/sessions/${encodeURIComponent(id)}`),
    onSuccess: async (_, { id }) => {
      setSessionConfirmation(null);
      setStartedRuns((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      await navigate({ to: "/cockpit-v2/work" });
      queryClient.removeQueries({ queryKey: requestKeys.sessionScope(id) });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() }),
        queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
      ]);
    },
  });

  const filteredSessions = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase(locale);
    const items = index.data?.sessions ?? [];
    return needle
      ? items.filter((session) => session.title.toLocaleLowerCase(locale).includes(needle))
      : items;
  }, [index.data?.sessions, locale, search]);

  const latestRunStateBySession = useMemo(() => {
    const states = new Map<string, { runId: string; status: string }>();
    for (const item of runsCenter.data?.runs ?? []) {
      if (!states.has(item.session_id)) {
        states.set(item.session_id, { runId: item.run_id, status: item.status_group });
      }
    }
    return states;
  }, [runsCenter.data?.runs]);

  const layoutStyle = {
    gridTemplateColumns: `${leftOpen ? `${leftWidth}px 8px` : "44px"} minmax(360px, 1fr) ${rightOpen ? `8px ${rightWidth}px` : "44px"}`,
  };
  const stage = runStage(retainedLatestRun);
  const selectedHarness = harnesses.data?.harnesses.find(
    (harness) => harness.spec.id === runConfig.harnessId,
  );
  const supportedBuiltinTools = selectedHarness?.spec.supported_builtin_tools ?? emptyStringList;
  const builtinToolsAvailable =
    runConfig.apiMode === "v2" &&
    advancedConfig.invocationMode === "headless" &&
    supportedBuiltinTools.length > 0;
  const modelSuggestions = models.data?.models ?? [];
  const streamPresentation = useMemo(
    () => projectWorkbenchStream(
      stream.events,
      messages.data?.messages ?? [],
      selectedRunId,
    ),
    [messages.data?.messages, selectedRunId, stream.events],
  );
  const selectedRunHasRetainedResponse = useMemo(
    () => hasRetainedResponse(messages.data?.messages ?? [], selectedRunId),
    [messages.data?.messages, selectedRunId],
  );
  const streamedEventIds = new Set(
    stream.events.map((event) => event.id),
  );
  const retainedGeneratedEvents = (events.data?.events ?? []).filter(
    (event) => event.type === "generated_file" && !streamedEventIds.has(event.id),
  );
  const retainedPlanEvent = (events.data?.events ?? []).filter(
    (event) => event.run_id === selectedRunId && event.type === "plan_updated",
  ).at(-1);
  const retainedToolEvents = (events.data?.events ?? []).filter(
    (event) =>
      event.run_id === selectedRunId &&
      event.type === "tool_call_finished" &&
      !streamedEventIds.has(event.id),
  );
  if (retainedPlanEvent !== undefined && !streamedEventIds.has(retainedPlanEvent.id)) {
    retainedToolEvents.unshift(retainedPlanEvent);
  }
  const locallyStartedRunId = sessionId === undefined ? undefined : startedRuns[sessionId];
  const selectedRunActive = workbenchRunActive(
    retainedLatestRun,
    selectedRunId,
    locallyStartedRunId,
    streamPresentation.terminalEvent,
  );

  useEffect(() => {
    const supported = new Set(supportedBuiltinTools);
    setBuiltinTools((current) => current.filter((tool) => supported.has(tool)));
    const capabilities = selectedHarness?.spec.capabilities ?? [];
    if (capabilities.length > 0 && !capabilities.includes(advancedConfig.capability)) {
      setAdvancedConfig((current) => ({ ...current, capability: capabilities[0] ?? "chat_completions" }));
    }
  }, [advancedConfig.capability, runConfig.harnessId, supportedBuiltinTools, selectedHarness?.spec.capabilities]);

  useEffect(() => {
    if (sessionId !== undefined && streamPresentation.terminalEvent !== null) {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: requestKeys.sessionScope(sessionId) }),
        queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() }),
        queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
      ]);
    }
  }, [queryClient, sessionId, streamPresentation.terminalEvent?.id]);

  useEffect(() => {
    if (sessionId === undefined) return;
    setUnreadSessionIds((current) => {
      if (!current.has(sessionId)) return current;
      const next = new Set(current);
      next.delete(sessionId);
      return next;
    });
  }, [sessionId]);

  useEffect(() => {
    const items = runsCenter.data?.runs;
    if (items === undefined) return;
    const previous = previousRunStatuses.current;
    const completed: CompletionNotice[] = [];
    for (const item of items) {
      const prior = previous.get(item.run_id);
      previous.set(item.run_id, item.status_group);
      if (
        prior !== undefined &&
        activeRunStatusGroups.has(prior) &&
        terminalRunStatusGroups.has(item.status_group) &&
        item.session_id !== sessionId
      ) {
        completed.push({
          id: item.run_id,
          sessionId: item.session_id,
          status: item.status_group,
          title: item.session_title,
        });
      }
    }
    if (completed.length === 0) return;
    setUnreadSessionIds((current) => {
      const next = new Set(current);
      for (const item of completed) next.add(item.sessionId);
      return next;
    });
    setCompletionNotices((current) => [...current, ...completed].slice(-3));
    for (const item of completed) {
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification(item.title, {
          body: message(locale, item.status === "completed" ? "backgroundRunCompleted" : "backgroundRunFailed"),
          tag: item.id,
        });
      }
    }
    void queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() });
  }, [locale, queryClient, runsCenter.data?.runs, sessionId]);
  const setConfig = <Key extends keyof RunConfig>(
    key: Key,
    value: RunConfig[Key],
    persistKey?: string,
  ) => {
    setRunConfig((current) => ({ ...current, [key]: value }));
    if (persistKey !== undefined) saveRunConfig.mutate({ [persistKey]: value || null });
  };

  return (
    <div className="workbench-layout" style={layoutStyle}>
      {leftOpen ? (
        <aside className="session-navigator" aria-label={message(locale, "allSessions")}>
          <div className="panel-heading">
            <div>
              <span className="section-kicker">{message(locale, "workbench")}</span>
              <h1>{message(locale, "allSessions")}</h1>
            </div>
            <button
              aria-label={message(locale, "collapse")}
              onClick={() => setLeftOpen(false)}
              type="button"
            >
              ‹
            </button>
          </div>
          <button
            className="new-session-button"
            disabled={createSession.isPending || !runConfig.model}
            onClick={() => createSession.mutate()}
            type="button"
          >
            <span aria-hidden="true">＋</span>
            {message(locale, "newSession")}
          </button>
          <label className="search-control">
            <span className="sr-only">{message(locale, "searchSessions")}</span>
            <span aria-hidden="true">⌕</span>
            <input
              onChange={(event) => setSearch(event.target.value)}
              placeholder={message(locale, "searchSessions")}
              type="search"
              value={search}
            />
          </label>
          <div className="list-toolbar">
            <span>{message(locale, "groupByProject")}</span>
            <span>{filteredSessions.length}</span>
          </div>
          <nav className="session-list" aria-label={message(locale, "allSessions")}>
            {index.isPending ? <ListSkeleton rows={6} /> : null}
            {index.isError ? <ReadError locale={locale} /> : null}
            {index.isSuccess && filteredSessions.length === 0 ? (
              <div className="empty-state">{message(locale, "emptySessions")}</div>
            ) : null}
            {sessionGroups(filteredSessions).map((group) => (
              <section className="project-group" key={group.projectId}>
                <h2>{group.projectId === "unbound" ? message(locale, "localSessions") : group.projectId}</h2>
                {group.sessions.map((session) => {
                  const runState = latestRunStateBySession.get(session.id);
                  const running = runState !== undefined && activeRunStatusGroups.has(runState.status);
                  const unread = unreadSessionIds.has(session.id);
                  return (
                    <Link
                      className={[
                        "session-row",
                        session.id === sessionId ? "selected" : "",
                        running ? "running" : "",
                        unread ? "unread" : "",
                      ].filter(Boolean).join(" ")}
                      key={session.id}
                      onClick={() => {
                        setUnreadSessionIds((current) => {
                          if (!current.has(session.id)) return current;
                          const next = new Set(current);
                          next.delete(session.id);
                          return next;
                        });
                      }}
                      params={{ sessionId: session.id }}
                      to="/cockpit-v2/work/$sessionId"
                    >
                      <strong>{session.title}</strong>
                      <span>
                        {session.default_harness_id ?? "echo"} · {session.default_api_mode ?? "v2"}
                      </span>
                      {running ? (
                        <span aria-label={message(locale, "running")} className="session-status-icon running-spinner" />
                      ) : unread ? (
                        <span aria-label={message(locale, "unreadSession")} className="session-status-icon unread-dot" />
                      ) : (
                        <time>{formatTimestamp(session.updated_at, locale)}</time>
                      )}
                    </Link>
                  );
                })}
              </section>
            ))}
          </nav>
        </aside>
      ) : (
        <button className="panel-restore" onClick={() => setLeftOpen(true)} type="button">
          <span>›</span><span>{message(locale, "restore")}</span>
        </button>
      )}
      {leftOpen ? (
        <ResizeHandle
          label="Resize session navigator"
          onReset={() => setLeftWidth(264)}
          onResize={(delta) => setLeftWidth((value) => clamp(value + delta, 220, 360))}
        />
      ) : null}

      <main className="work-canvas">
        {sessionId === undefined ? (
          <div className="empty-work-canvas">
            <h1>{message(locale, "workbench")}</h1>
            <p>{message(locale, "selectSession")}</p>
          </div>
        ) : overview.isPending ? (
          <ListSkeleton rows={5} />
        ) : overview.isError ? (
          <ReadError locale={locale} />
        ) : (
          <>
            <header className="work-header">
              <div>
                <p className="section-kicker">{message(locale, "session")} · {shortId(sessionId)}</p>
                <h1>{overview.data?.session.title}</h1>
                <span>
                  {runConfig.model || "GigaChat"} · /{runConfig.apiMode} · {runConfig.harnessId}
                </span>
              </div>
              <div className="work-header-actions">
                {selectedRunId === undefined ? null : (
                  <Link params={{ runId: selectedRunId }} to="/cockpit-v2/runs/$runId">
                    {message(locale, "openRun")} ↗
                  </Link>
                )}
                <button
                  disabled={changeSession.isPending}
                  onClick={() => {
                    changeSession.reset();
                    setSessionConfirmation({
                      action: "archive",
                      id: sessionId,
                      title: overview.data?.session.title ?? sessionId,
                    });
                  }}
                  type="button"
                >
                  {message(locale, "archiveSession")}
                </button>
                <button
                  className="danger-button"
                  disabled={changeSession.isPending}
                  onClick={() => {
                    changeSession.reset();
                    setSessionConfirmation({
                      action: "delete",
                      id: sessionId,
                      title: overview.data?.session.title ?? sessionId,
                    });
                  }}
                  type="button"
                >
                  {message(locale, "deleteSession")}
                </button>
              </div>
            </header>
            <section className="message-region" aria-label={message(locale, "sessionMessages")}>
              {messages.isPending ? <ListSkeleton rows={4} /> : null}
              {messages.isError ? <ReadError locale={locale} /> : null}
              {messages.data?.messages.length === 0 ? (
                <div className="empty-state">{message(locale, "emptyMessages")}</div>
              ) : null}
              {messages.data?.messages.map((item) => (
                <Fragment key={item.id}>
                  {(item.role === "assistant" || item.role === "error") && item.run_id
                    ? retainedToolEvents
                        .filter((event) => event.run_id === item.run_id)
                        .map((event) => (
                          <RetainedToolActivity event={event} key={event.id} locale={locale} />
                        ))
                    : null}
                  {(item.role === "assistant" || item.role === "error") && item.run_id === selectedRunId ? (
                    <>
                      {!item.reasoning?.text && streamPresentation.reasoningText ? (
                        <ReasoningDisclosure text={streamPresentation.reasoningText} locale={locale} />
                      ) : null}
                      {streamPresentation.plan.length > 0 ? (
                        <PlanCard items={streamPresentation.plan} locale={locale} />
                      ) : null}
                      {streamPresentation.toolActivities.map((activity) => (
                        <ToolActivityCard activity={activity} key={activity.id} locale={locale} />
                      ))}
                    </>
                  ) : null}
                  <article className={`message-entry ${item.role}`}>
                    <div>
                      <strong>{item.role}</strong>
                      <span className="message-header-meta">
                        <TokenUsage usage={item.usage} />
                        <time>{formatTimestamp(item.created_at, locale)}</time>
                      </span>
                    </div>
                    {item.reasoning?.text ? (
                      <ReasoningDisclosure text={item.reasoning.text} locale={locale} />
                    ) : null}
                    <MessageMarkdown source={item.content.text} />
                    {item.content.truncated ? <span>{message(locale, "boundedPreview")}</span> : null}
                  </article>
                </Fragment>
              ))}
              {retainedGeneratedEvents.map((event) => (
                <GeneratedFilePreview eventId={event.id} key={event.id} payloadUrl={event.payload_url} />
              ))}
              {!selectedRunHasRetainedResponse && streamPresentation.reasoningText ? (
                <ReasoningDisclosure text={streamPresentation.reasoningText} locale={locale} />
              ) : null}
              {!selectedRunHasRetainedResponse && streamPresentation.plan.length > 0 ? (
                <PlanCard items={streamPresentation.plan} locale={locale} />
              ) : null}
              {!selectedRunHasRetainedResponse
                ? streamPresentation.toolActivities.map((activity) => (
                    <ToolActivityCard activity={activity} key={activity.id} locale={locale} />
                  ))
                : null}
              {streamPresentation.assistantText ? (
                <article className="message-entry assistant" key={`live-${selectedRunId}`}>
                  <div>
                    <strong>assistant</strong>
                    <TokenUsage usage={streamPresentation.usage} />
                  </div>
                  <MessageMarkdown source={streamPresentation.assistantText} />
                </article>
              ) : null}
              {streamPresentation.generatedFiles.map((event) => (
                <GeneratedImageCard key={event.id} payload={event.payload} />
              ))}
            </section>
            <form
              className={[
                "composer",
                draggingFiles ? "dragging-files" : "",
                modelMenuOpen || plusMenuOpen ? "popover-open" : "",
              ].filter(Boolean).join(" ")}
              onDragEnter={(event) => {
                event.preventDefault();
                setDraggingFiles(true);
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setDraggingFiles(false);
                }
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                setDraggingFiles(false);
                const files = Array.from(event.dataTransfer.files);
                if (files.length > 0) uploadFiles.mutate({ files, source: "drop" });
              }}
              onSubmit={(event) => {
                event.preventDefault();
                if (prompt.trim() && !startRun.isPending) startRun.mutate();
              }}
            >
              {attachments.data?.attachments.length ? (
                <div className="attachment-chips" aria-label={message(locale, "attachedFiles")}>
                  {attachments.data.attachments.map((attachment) => (
                    <span className="attachment-chip" key={attachment.id}>
                      <span aria-hidden="true">{attachment.mime_type?.startsWith("image/") ? "▧" : "◇"}</span>
                      <span title={attachment.filename}>{attachment.filename}</span>
                      <small>{formatBytes(attachment.size_bytes)}</small>
                      <button
                        aria-label={`${message(locale, "removeAttachment")} ${attachment.filename}`}
                        disabled={removeAttachment.isPending}
                        onClick={() => removeAttachment.mutate(attachment.id)}
                        type="button"
                      >×</button>
                    </span>
                  ))}
                </div>
              ) : null}
              <textarea
                aria-label={message(locale, "composerPlaceholder")}
                disabled={startRun.isPending}
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && prompt.trim()) {
                    event.preventDefault();
                    startRun.mutate();
                  }
                }}
                onPaste={(event) => {
                  const files = Array.from(event.clipboardData.files);
                  if (files.length > 0) uploadFiles.mutate({ files, source: "paste" });
                }}
                placeholder={message(locale, "composerPlaceholder")}
                rows={4}
                value={prompt}
              />
              {modelMenuOpen && modelSuggestions.length > 0 ? (
                <div
                  className="model-suggestions"
                  onMouseDown={(event) => event.preventDefault()}
                  role="listbox"
                >
                  {modelSuggestions.map((model) => (
                    <button
                      aria-selected={model === runConfig.model}
                      key={model}
                      onClick={() => {
                        setConfig("model", model);
                        setModelMenuOpen(false);
                        saveRunConfig.mutate({ default_model: model });
                      }}
                      role="option"
                      type="button"
                    >{model}</button>
                  ))}
                </div>
              ) : null}
              {advancedOpen ? (
                <section className="advanced-composer-panel" aria-label={message(locale, "advancedSettings")}>
                  <div className="advanced-panel-heading">
                    <div>
                      <strong>{message(locale, "advancedSettings")}</strong>
                      <span>{message(locale, "advancedSettingsHint")}</span>
                    </div>
                    <button aria-label={message(locale, "close")} onClick={() => setAdvancedOpen(false)} type="button">×</button>
                  </div>
                  <div className="advanced-config-grid">
                    <label>
                      <span>{message(locale, "invocation")}</span>
                      <select
                        onChange={(event) => setAdvancedConfig((current) => ({ ...current, invocationMode: event.target.value }))}
                        value={advancedConfig.invocationMode}
                      >
                        <option value="headless">headless</option>
                        <option disabled={selectedHarness?.spec.supports_native_sessions !== true} value="native">native</option>
                      </select>
                    </label>
                    <label>
                      <span>{message(locale, "capability")}</span>
                      <select
                        onChange={(event) => setAdvancedConfig((current) => ({ ...current, capability: event.target.value }))}
                        value={advancedConfig.capability}
                      >
                        {(selectedHarness?.spec.capabilities ?? ["chat_completions"]).map((capability) => (
                          <option key={capability} value={capability}>{capability}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>{message(locale, "workspacePolicy")}</span>
                      <select
                        onChange={(event) => setAdvancedConfig((current) => ({ ...current, workspacePolicy: event.target.value }))}
                        value={advancedConfig.workspacePolicy}
                      >
                        <option value="auto">auto</option>
                        <option value="current">current</option>
                        <option value="worktree">worktree</option>
                        <option value="temp_copy">temp copy</option>
                      </select>
                    </label>
                    <label>
                      <span>{message(locale, "permissionProfile")}</span>
                      <select
                        onChange={(event) => setAdvancedConfig((current) => ({ ...current, permissionProfile: event.target.value }))}
                        value={advancedConfig.permissionProfile}
                      >
                        <option value="interactive">interactive</option>
                        <option value="review_every_action">review every action</option>
                      </select>
                    </label>
                  </div>
                  <div className="advanced-switches">
                    <label><input checked={advancedConfig.dryRun} onChange={(event) => setAdvancedConfig((current) => ({ ...current, dryRun: event.target.checked }))} type="checkbox" /> dry run</label>
                    <label><input checked={advancedConfig.stream} onChange={(event) => setAdvancedConfig((current) => ({ ...current, stream: event.target.checked }))} type="checkbox" /> stream</label>
                  </div>
                  <fieldset className="builtin-tools-panel">
                    <legend>{message(locale, "builtinTools")}</legend>
                    <div>
                      {Object.entries(builtinToolLabels).map(([tool, label]) => (
                        <label className="builtin-tool-choice" key={tool}>
                          <input
                            checked={builtinTools.includes(tool)}
                            disabled={!builtinToolsAvailable || !supportedBuiltinTools.includes(tool)}
                            onChange={(event) => setBuiltinTools((current) => event.target.checked
                              ? [...current, tool]
                              : current.filter((item) => item !== tool))}
                            type="checkbox"
                          />
                          <span>{label}</span>
                        </label>
                      ))}
                    </div>
                    <p>
                      {builtinToolsAvailable
                        ? message(locale, "builtinToolsHint")
                        : message(locale, "builtinToolsUnavailable")}
                    </p>
                  </fieldset>
                </section>
              ) : null}
              <div className="composer-footer">
                <div className="composer-footer-left">
                  <div className="composer-controls" aria-label={message(locale, "runConfiguration")}>
                    <input
                      className="sr-only"
                      multiple
                      onChange={(event) => {
                        const files = Array.from(event.target.files ?? []);
                        if (files.length > 0) uploadFiles.mutate({ files, source: "upload" });
                        event.target.value = "";
                      }}
                      ref={fileInputRef}
                      type="file"
                    />
                    <div className="plus-menu-wrapper">
                      <button
                        aria-expanded={plusMenuOpen}
                        aria-label={message(locale, "moreComposerActions")}
                        className="attach-button"
                        disabled={uploadFiles.isPending}
                        onClick={() => setPlusMenuOpen((open) => !open)}
                        title={message(locale, "moreComposerActions")}
                        type="button"
                      >
                        <span aria-hidden="true">＋</span>
                      </button>
                      {plusMenuOpen ? (
                        <div className="plus-menu" role="menu">
                          <button onClick={() => { setPlusMenuOpen(false); fileInputRef.current?.click(); }} role="menuitem" type="button">
                            <span aria-hidden="true">◇</span>
                            <span><strong>{message(locale, "attachFiles")}</strong><small>{message(locale, "attachFilesHint")}</small></span>
                          </button>
                          <button onClick={() => { setPlusMenuOpen(false); setAdvancedOpen(true); }} role="menuitem" type="button">
                            <span aria-hidden="true">✦</span>
                            <span><strong>{message(locale, "builtinTools")}</strong><small>{message(locale, "builtinToolsMenuHint")}</small></span>
                          </button>
                        </div>
                      ) : null}
                    </div>
                    <label className="compact-control">
                      <span>{message(locale, "harness")}</span>
                      <select
                        aria-label={message(locale, "harness")}
                        onChange={(event) => setConfig("harnessId", event.target.value, "default_harness_id")}
                        value={runConfig.harnessId}
                      >
                        {harnesses.data?.harnesses.map((harness) => (
                          <option
                            disabled={harness.availability?.status === "unavailable"}
                            key={harness.spec.id}
                            value={harness.spec.id}
                          >
                            {harness.spec.title || harness.spec.id}
                          </option>
                        )) ?? <option value={runConfig.harnessId}>{runConfig.harnessId}</option>}
                      </select>
                    </label>
                    <label className="compact-control api-control">
                      <span>{message(locale, "apiMode")}</span>
                      <select
                        aria-label={message(locale, "apiMode")}
                        disabled={selectedHarness?.spec.supports_api_mode_selection === false}
                        onChange={(event) => setConfig("apiMode", event.target.value, "default_api_mode")}
                        value={runConfig.apiMode}
                      >
                        <option value="v2">/v2</option>
                        <option value="v1">/v1</option>
                      </select>
                    </label>
                    <div className="compact-control model-control">
                      <span>{message(locale, "model")}</span>
                      <div
                        className="model-picker"
                        onBlur={(event) => {
                          if (!event.currentTarget.contains(event.relatedTarget)) {
                            setModelMenuOpen(false);
                            saveRunConfig.mutate({ default_model: runConfig.model.trim() || null });
                          }
                        }}
                      >
                        <button
                          aria-label={message(locale, "model")}
                          aria-expanded={modelMenuOpen}
                          aria-haspopup="listbox"
                          className="model-select-button"
                          disabled={selectedHarness?.spec.supports_model_selection === false}
                          onClick={() => setModelMenuOpen((open) => !open)}
                          type="button"
                        >
                          <span>{runConfig.model || sessionTitleModel}</span>
                          <span aria-hidden="true">⌄</span>
                        </button>
                      </div>
                    </div>
                    {isReasoningModel(runConfig.model) ? (
                      <label className="compact-control reasoning-control">
                        <span>{message(locale, "reasoning")}</span>
                        <select
                          aria-label={message(locale, "reasoning")}
                          onChange={(event) => setReasoningEffort(event.target.value as ReasoningEffort)}
                          value={reasoningEffort}
                        >
                          <option value="low">low</option>
                          <option value="medium">medium</option>
                          <option value="high">high</option>
                        </select>
                      </label>
                    ) : null}
                    <label className="compact-control mode-control">
                      <span>{message(locale, "mode")}</span>
                      <select
                        aria-label={message(locale, "mode")}
                        onChange={(event) => setConfig("mode", event.target.value, "default_mode")}
                        value={runConfig.mode}
                      >
                        <option value="plan">plan</option>
                        <option value="read">read</option>
                        <option value="edit">edit</option>
                      </select>
                    </label>
                    <button
                      aria-expanded={advancedOpen}
                      className={builtinTools.length > 0 ? "advanced-button active" : "advanced-button"}
                      onClick={() => setAdvancedOpen((open) => !open)}
                      type="button"
                    >
                      {message(locale, "advanced")}{builtinTools.length > 0 ? ` · ${builtinTools.length}` : ""}
                    </button>
                  </div>
                  <span className={`stream-indicator ${stream.status}`}>
                    {uploadFiles.isPending ? message(locale, "uploadingFiles") : stream.status.replaceAll("_", " ")}
                  </span>
                </div>
                {selectedRunActive && selectedRunId !== undefined ? (
                  <button
                    className="danger-button"
                    disabled={cancelRun.isPending}
                    onClick={() => cancelRun.mutate(selectedRunId)}
                    type="button"
                  >
                    {message(locale, "cancelRun")}
                  </button>
                ) : (
                  <button className="primary-button" disabled={!prompt.trim() || startRun.isPending} type="submit">
                    {message(locale, "runTask")}
                  </button>
                )}
              </div>
              {startRun.isError || uploadFiles.isError || removeAttachment.isError || saveRunConfig.isError ? (
                <div className="error-state" role="alert">
                  {String(startRun.error ?? uploadFiles.error ?? removeAttachment.error ?? saveRunConfig.error)}
                </div>
              ) : null}
            </form>
          </>
        )}
      </main>

      {rightOpen ? (
        <>
          <ResizeHandle
            label="Resize run inspector"
            onReset={() => setRightWidth(320)}
            onResize={(delta) => setRightWidth((value) => clamp(value - delta, 280, 420))}
          />
          <aside className="run-readiness" aria-label={message(locale, "readiness")}>
            <div className="panel-heading">
              <div>
                <span className="section-kicker">{message(locale, "readiness")}</span>
                <h2>{message(locale, "startReady")}</h2>
              </div>
              <button aria-label={message(locale, "collapse")} onClick={() => setRightOpen(false)} type="button">×</button>
            </div>
            <div className="readiness-callout success">
              <strong>{message(locale, "ready")}</strong>
              <span>{message(locale, "fastApiAuthority")}</span>
            </div>
            <section className="inspector-section">
              <h3>{message(locale, "executionPlan")}</h3>
              <dl className="plan-fields">
                <div><dt>{message(locale, "mode")}</dt><dd>{runConfig.mode}</dd></div>
                <div><dt>{message(locale, "workspacePolicy")}</dt><dd>{message(locale, "workspacePolicyValue")}</dd></div>
                <div><dt>{message(locale, "route")}</dt><dd>{runConfig.model || "GigaChat"} · /{runConfig.apiMode}</dd></div>
                <div><dt>{message(locale, "harness")}</dt><dd>{runConfig.harnessId}</dd></div>
              </dl>
            </section>
            <Progression current={stage} locale={locale} />
            <section className="inspector-section next-actions">
              <h3>{message(locale, "nextActions")}</h3>
              {selectedRunId === undefined ? (
                <span className="muted-copy">{message(locale, "runTask")}</span>
              ) : (
                <>
                  <Link params={{ runId: selectedRunId }} to="/cockpit-v2/runs/$runId">{message(locale, "reviewDiff")} <span>›</span></Link>
                  <button onClick={() => openInbox("approvals")} type="button">{message(locale, "requestApproval")} <span>›</span></button>
                  <Link params={{ runId: selectedRunId }} to="/cockpit-v2/runs/$runId">{message(locale, "apply")} <span>›</span></Link>
                  <Link params={{ runId: selectedRunId }} to="/cockpit-v2/runs/$runId">{message(locale, "promote")} <span>›</span></Link>
                </>
              )}
            </section>
          </aside>
        </>
      ) : (
        <button className="panel-restore right" onClick={() => setRightOpen(true)} type="button">
          <span>‹</span><span>{message(locale, "restore")}</span>
        </button>
      )}
      {sessionConfirmation === null ? null : (
        <SessionConfirmationDialog
          action={sessionConfirmation.action}
          error={changeSession.isError}
          locale={locale}
          onCancel={() => {
            if (!changeSession.isPending) setSessionConfirmation(null);
          }}
          onConfirm={() => changeSession.mutate(sessionConfirmation)}
          pending={changeSession.isPending}
          title={sessionConfirmation.title}
        />
      )}
      <div aria-live="polite" className="completion-notices">
        {completionNotices.map((notice) => (
          <button
            className={notice.status === "completed" ? "completion-notice" : "completion-notice failed"}
            key={notice.id}
            onClick={() => {
              setCompletionNotices((current) => current.filter((item) => item.id !== notice.id));
              void navigate({ params: { sessionId: notice.sessionId }, to: "/cockpit-v2/work/$sessionId" });
            }}
            type="button"
          >
            <span aria-hidden="true">{notice.status === "completed" ? "✓" : "!"}</span>
            <span><strong>{notice.title}</strong><small>{message(locale, notice.status === "completed" ? "backgroundRunCompleted" : "backgroundRunFailed")}</small></span>
          </button>
        ))}
      </div>
    </div>
  );
}

function RetainedToolActivity({
  event,
  locale,
}: {
  event: EventProjection;
  locale: "en" | "ru";
}) {
  const payload = useQuery({
    queryKey: [...requestKeys.root, "event-payload", event.id],
    queryFn: ({ signal }) => fetchCockpit<EventPayloadResponse>(event.payload_url, signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (!payload.isSuccess || payload.data.hidden) return null;
  const projection = projectToolPayload(payload.data.payload, event.id);
  if (projection.plan.length > 0) return <PlanCard items={projection.plan} locale={locale} />;
  return projection.activity === null
    ? null
    : <ToolActivityCard activity={projection.activity} locale={locale} />;
}

function ToolActivityCard({
  activity,
  locale,
}: {
  activity: WorkbenchToolActivity;
  locale: "en" | "ru";
}) {
  const complete = ["completed", "succeeded", "success"].includes(activity.status.toLowerCase());
  const failed = ["error", "failed"].includes(activity.status.toLowerCase());
  const result = formatToolResult(
    activity.result ?? (failed ? message(locale, "toolFailedNoDetails") : undefined),
  );
  return (
    <article className={failed ? "tool-activity-card failed" : "tool-activity-card"}>
      <div className="tool-activity-heading">
        <span aria-hidden="true">{complete ? "✓" : failed ? "!" : "◇"}</span>
        <div>
          <strong>{activity.label}</strong>
          <small>{message(locale, "toolActivity")} · {activity.status}</small>
        </div>
      </div>
      {result === null ? null : (
        <details>
          <summary>{message(locale, "toolResult")}</summary>
          <pre>{result}</pre>
        </details>
      )}
    </article>
  );
}

function ReasoningDisclosure({
  locale,
  text,
}: {
  locale: "en" | "ru";
  text: string;
}) {
  return (
    <details className="reasoning-disclosure">
      <summary>{message(locale, "reasoningTrace")}</summary>
      <p>{text}</p>
    </details>
  );
}

function TokenUsage({
  usage,
}: {
  usage: TokenUsageProjection | undefined;
}) {
  if (usage?.input_tokens === undefined && usage?.output_tokens === undefined) return null;
  return (
    <span className="token-usage">
      {usage.input_tokens === undefined ? null : `input ${usage.input_tokens}`}
      {usage.input_tokens !== undefined && usage.output_tokens !== undefined ? " · " : null}
      {usage.output_tokens === undefined ? null : `output ${usage.output_tokens}`}
    </span>
  );
}

function formatToolResult(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (!text) return null;
  return text.length > 16_384 ? `${text.slice(0, 16_384)}\n…` : text;
}

function hasRetainedResponse(
  messages: readonly { role: string; run_id?: string | null }[],
  runId: string | undefined,
): boolean {
  return runId !== undefined && messages.some(
    (item) => item.run_id === runId && (item.role === "assistant" || item.role === "error"),
  );
}

function PlanCard({ items, locale }: { items: readonly WorkbenchPlanItem[]; locale: "en" | "ru" }) {
  return (
    <section className="live-plan-card">
      <div>
        <strong>{message(locale, "planProgress")}</strong>
        <small>{items.filter((item) => item.status === "completed").length}/{items.length}</small>
      </div>
      <ol>
        {items.map((item, index) => (
          <li className={item.status} key={`${index}-${item.step}`}>
            <span aria-hidden="true">
              {item.status === "completed" ? "✓" : item.status === "in_progress" ? "●" : "○"}
            </span>
            <span>{item.step}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function GeneratedFilePreview({ eventId, payloadUrl }: { eventId: string; payloadUrl: string }) {
  const payload = useQuery({
    queryKey: [...requestKeys.root, "event-payload", eventId],
    queryFn: ({ signal }) => fetchCockpit<EventPayloadResponse>(payloadUrl, signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (payload.isPending) return <div className="generated-image-skeleton skeleton-row" />;
  if (payload.isError || payload.data.hidden) return null;
  return <GeneratedImageCard payload={payload.data.payload} />;
}

function loadRunPreferences(): { config: RunConfig; reasoningEffort: ReasoningEffort } {
  const fallback = {
    config: { apiMode: "v2", harnessId: "codex-cli", mode: "plan", model: "" },
    reasoningEffort: "medium" as const,
  };
  try {
    const stored = JSON.parse(localStorage.getItem(runPreferencesKey) ?? "null") as unknown;
    if (typeof stored !== "object" || stored === null || Array.isArray(stored)) return fallback;
    const value = stored as Record<string, unknown>;
    const effort = value.reasoningEffort;
    return {
      config: {
        apiMode: typeof value.apiMode === "string" ? value.apiMode : fallback.config.apiMode,
        harnessId: typeof value.harnessId === "string" ? value.harnessId : fallback.config.harnessId,
        mode: typeof value.mode === "string" ? value.mode : fallback.config.mode,
        model: typeof value.model === "string" ? value.model : fallback.config.model,
      },
      reasoningEffort:
        effort === "low" || effort === "high" || effort === "medium"
          ? effort
          : fallback.reasoningEffort,
    };
  } catch {
    return fallback;
  }
}

function preferredModel(models: readonly string[]): string {
  return models.find((model) => model !== "GigaChat") ?? models[0] ?? sessionTitleModel;
}

function isReasoningModel(model: string): boolean {
  return model === reasoningModel || model.startsWith(`${reasoningModel}:`);
}

function GeneratedImageCard({ payload }: { payload?: Readonly<Record<string, unknown>> }) {
  const image = generatedImageProjection(payload);
  if (image === null) return null;
  const size = image.sizeBytes === null ? null : formatBytes(image.sizeBytes);
  return (
    <article className="message-entry assistant generated-image-message">
      <div><strong>assistant · image generation</strong></div>
      <figure>
        <a href={image.previewUrl} rel="noreferrer" target="_blank">
          <img alt={image.filename} loading="lazy" src={image.previewUrl} />
        </a>
        <figcaption>{image.filename}{size === null ? "" : ` · ${size}`}</figcaption>
      </figure>
    </article>
  );
}

function SessionConfirmationDialog({
  action,
  error,
  locale,
  onCancel,
  onConfirm,
  pending,
  title,
}: {
  action: SessionAction;
  error: boolean;
  locale: "en" | "ru";
  onCancel: () => void;
  onConfirm: () => void;
  pending: boolean;
  title: string;
}) {
  const destructive = action === "delete";
  const headingId = "session-confirmation-heading";
  const descriptionId = "session-confirmation-description";
  return (
    <div className="dialog-backdrop" onClick={onCancel} role="presentation">
      <section
        aria-describedby={descriptionId}
        aria-labelledby={headingId}
        aria-modal="true"
        className="confirmation-dialog"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <span className="section-kicker">{message(locale, "sessionActions")}</span>
        <h2 id={headingId}>
          {message(locale, destructive ? "deleteSessionTitle" : "archiveSessionTitle")}
        </h2>
        <p id={descriptionId}>
          <strong>{title}</strong>
          <span>
            {message(
              locale,
              destructive ? "deleteSessionDescription" : "archiveSessionDescription",
            )}
          </span>
        </p>
        {error ? (
          <div className="mutation-error" role="alert">
            {message(locale, "sessionMutationFailed")}
          </div>
        ) : null}
        <div className="confirmation-actions">
          <button autoFocus disabled={pending} onClick={onCancel} type="button">
            {message(locale, "cancel")}
          </button>
          <button
            className={destructive ? "primary-danger-button" : "primary-button"}
            disabled={pending}
            onClick={onConfirm}
            type="button"
          >
            {message(locale, destructive ? "deleteSession" : "archiveSession")}
          </button>
        </div>
      </section>
    </div>
  );
}

function Progression({ current, locale }: { current: RunStage; locale: "en" | "ru" }) {
  const stages: Array<[RunStage, "stageRun" | "stageEvidence" | "stageReview" | "stageReuse"]> = [
    ["run", "stageRun"],
    ["evidence", "stageEvidence"],
    ["review", "stageReview"],
    ["reuse", "stageReuse"],
  ];
  const currentIndex = stages.findIndex(([stage]) => stage === current);
  return (
    <ol className="progression" aria-label="Work to reuse progression">
      {stages.map(([stage, key], index) => (
        <li className={index <= currentIndex ? "complete" : ""} key={stage}>
          <span>{index + 1}</span><strong>{message(locale, key)}</strong>
        </li>
      ))}
    </ol>
  );
}

function ResizeHandle({
  label,
  onReset,
  onResize,
}: {
  label: string;
  onReset: () => void;
  onResize: (delta: number) => void;
}) {
  return (
    <div
      aria-label={label}
      className="resize-handle"
      onDoubleClick={onReset}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onResize(-16);
        if (event.key === "ArrowRight") onResize(16);
        if (event.key === "Home") onReset();
      }}
      onPointerDown={(event) => {
        const start = event.clientX;
        let previous = start;
        const move = (moveEvent: PointerEvent) => {
          onResize(moveEvent.clientX - previous);
          previous = moveEvent.clientX;
        };
        const stop = () => {
          globalThis.removeEventListener("pointermove", move);
          globalThis.removeEventListener("pointerup", stop);
        };
        globalThis.addEventListener("pointermove", move);
        globalThis.addEventListener("pointerup", stop);
      }}
      role="separator"
      tabIndex={0}
    />
  );
}

function ListSkeleton({ rows }: { rows: number }) {
  return <>{Array.from({ length: rows }, (_, index) => <div className="skeleton-row" key={index} />)}</>;
}

function ReadError({ locale }: { locale: "en" | "ru" }) {
  return <div className="error-state" role="alert">{message(locale, "boundedDataUnavailable")}</div>;
}

function loadWidth(key: "left" | "right", fallback: number): number {
  try {
    const stored = JSON.parse(localStorage.getItem(layoutKey) ?? "{}") as Record<string, unknown>;
    return typeof stored[key] === "number" ? stored[key] : fallback;
  } catch {
    return fallback;
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function openInbox(kind: "approvals" | "attention") {
  globalThis.dispatchEvent(new CustomEvent("cockpit:open-inbox", { detail: kind }));
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("Could not read attachment"));
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.includes(",") ? result.slice(result.indexOf(",") + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
