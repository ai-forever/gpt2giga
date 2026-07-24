import {
  type UseMutationResult,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Fragment, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  type AttachmentSummary,
  type AttachmentUploadResponse,
  deleteCockpit,
  type EnvironmentCommitApplyResponse,
  type EnvironmentCommitPreview,
  type EnvironmentCommitPreviewResponse,
  type EnvironmentPushApplyResponse,
  type EnvironmentPushPreview,
  type EnvironmentPushPreviewResponse,
  type EnvironmentPullRequestApplyResponse,
  type EnvironmentPullRequestPreview,
  type EnvironmentPullRequestPreviewResponse,
  type EventProjection,
  type EventPayloadResponse,
  fetchCockpit,
  type FullMessageResponse,
  mutateCockpit,
  patchCockpit,
  type RunPreflightResponse,
  type RunStartResponse,
  type SessionSummary,
  type TokenUsageProjection,
  withQuery,
} from "../api";
import { composerAttachments, isPreviewableImage } from "../attachment-model";
import { MessageMarkdown } from "../message-markdown";
import { generatedFileProjection } from "../generated-image";
import { projectEnvironment, type EnvironmentView } from "../environment-model";
import {
  latestEditableUserMessageId,
  projectActiveMessageTimeline,
  resolveMessageAction,
  timelineWhileEditing,
  type MessageActionKind,
  type ResolvedMessageAction,
} from "../message-actions";
import { message, type MessageKey } from "../messages";
import { usePreferences } from "../preferences-context";
import type { LocalePreference } from "../preferences";
import { integrationFlowOptions } from "../remaining-request-graph";
import {
  environmentOptions,
  requestKeys,
  refreshSessionAfterRunStart,
  refreshSessionRevision,
  harnessesOptions,
  modelsOptions,
  sessionAttachmentsOptions,
  sessionEventsOptions,
  sessionIndexOptions,
  sessionMessagesOptions,
  sessionOverviewOptions,
  sessionRunsOptions,
  settingsOptions,
  runsCenterOptions,
  workspaceFilesOptions,
} from "../request-graph";
import { observeNativeProcess } from "../native-process-stream";
import { observeSessionUpdates } from "../session-update-stream";
import {
  sessionCreationPayload,
  shouldAutomaticallyCreateSession,
  type SessionCreationIntent,
} from "../session-creation";
import {
  promptWithSkillMentions,
  skillMentionOptions,
  type SkillMention,
} from "../skill-mentions";
import {
  admittedBuiltinToolSelection,
  composerToolCatalog,
  type ComposerToolCategory,
  type ComposerToolOption,
} from "../tool-selection";
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
  nestWorkbenchToolActivities,
  projectToolPayload,
  projectWorkbenchStream,
  type WorkbenchPlanItem,
  type WorkbenchToolActivity,
  workbenchRunActive,
} from "../workbench-model";
import {
  activeAtQuery,
  admittedExecutionTransport,
  consumeAtQuery,
  harnessesForWorkbenchKind,
  legacyModeForProductSelection,
  normalizeProductSelection,
  permissionSimulationHighlights,
  resolveLegacyProductSelection,
  type ProductExecutionSelection,
  type WorkbenchKind,
} from "../workbench-execution";

const layoutKey = "gpt2giga.cockpit-v2.workbench-layout.v1";
const runPreferencesKey = "gpt2giga.cockpit-v2.run-preferences.v1";
const reasoningModel = "GigaChat-2-Reasoning";
type SessionAction = "archive" | "delete";
type MessageAction = {
  kind: MessageActionKind;
  messageId: string;
  role: "assistant" | "user";
};
type RunConfig = { apiMode: string; harnessId: string; mode: string; model: string };
type ReasoningEffort = "high" | "low" | "medium";
type AdvancedRunConfig = {
  dryRun: boolean;
  permissionProfile: string;
  workspacePolicy: string;
};

function ArchiveSessionIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 7h16M6 7v12h12V7M9 11h6" />
      <path d="M5 4h14v3H5z" />
    </svg>
  );
}

function DeleteSessionIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
    </svg>
  );
}

type StartResult =
  | { kind: "preview"; report: RunPreflightResponse["preflight"] }
  | { kind: "run"; run: RunStartResponse["run"] };

const builtinToolLabels: Record<string, string> = {
  code_interpreter: "Code interpreter",
  image_generate: "Image generation",
  model_3d_generate: "3D generation",
  url_content_extraction: "URL content",
  web_search: "Web search",
};
const toolCategoryMessageKeys: Record<ComposerToolCategory, MessageKey> = {
  agent: "toolCategoryAgent",
  gigachat: "toolCategoryGigachat",
  mcp: "toolCategoryMcp",
  plugin: "toolCategoryPlugin",
  skill: "toolCategorySkill",
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

type ProviderHandoffPreview = {
  handoff: {
    command: string[];
    instruction: string;
    status: string;
  };
};

type EnvironmentCommitDraft = {
  authorEmail: string;
  authorName: string;
  message: string;
};

type EnvironmentCommitAction = {
  draft: EnvironmentCommitDraft;
  error: boolean;
  notice: string | null;
  pending: boolean;
  preview: EnvironmentCommitPreview | undefined;
  setField: (field: keyof EnvironmentCommitDraft, value: string) => void;
  submit: () => void;
};

type EnvironmentPushAction = {
  error: boolean;
  notice: string | null;
  pending: boolean;
  preview: EnvironmentPushPreview | undefined;
  result: EnvironmentPushApplyResponse["result"] | undefined;
  submit: () => void;
};

type EnvironmentPullRequestDraft = {
  baseBranch: string;
  body: string;
  title: string;
};

type EnvironmentPullRequestAction = {
  draft: EnvironmentPullRequestDraft;
  error: boolean;
  notice: string | null;
  pending: boolean;
  preview: EnvironmentPullRequestPreview | undefined;
  result: EnvironmentPullRequestApplyResponse["result"] | undefined;
  setField: (field: keyof EnvironmentPullRequestDraft, value: string) => void;
  submit: () => void;
};

function EnvironmentCard({
  className = "",
  environment,
  error,
  commitAction,
  pushAction,
  pullRequestAction,
  locale,
  pending,
}: {
  className?: string;
  environment: EnvironmentView | undefined;
  error: boolean;
  commitAction: EnvironmentCommitAction;
  pushAction: EnvironmentPushAction;
  pullRequestAction: EnvironmentPullRequestAction;
  locale: LocalePreference;
  pending: boolean;
}) {
  return (
    <section
      className={`inspector-section environment-card ${className}`.trim()}
      data-state={environment?.status ?? "unavailable"}
    >
      <div className="environment-heading">
        <h3>{message(locale, "environment")}</h3>
        <span>{environment?.status ?? "unavailable"}</span>
      </div>
      {environment === undefined ? (
        <span className={error ? "mutation-error" : "muted-copy"}>
          {pending ? "…" : message(locale, "environmentUnavailable")}
        </span>
      ) : (
        <dl className="plan-fields">
          <div><dt>{message(locale, "changes")}</dt><dd>{environment.changes}</dd></div>
          <div><dt>{message(locale, "worktree")}</dt><dd title={environment.worktree}>{environment.worktree}</dd></div>
          <div><dt>{message(locale, "environmentBranch")}</dt><dd>{environment.branch} · {environment.head}</dd></div>
          <div><dt>{message(locale, "environmentCommit")}</dt><dd>{environment.commit}</dd></div>
          <div><dt>{message(locale, "environmentPush")}</dt><dd>{environment.push}</dd></div>
          <div><dt>{message(locale, "environmentIssuePr")}</dt><dd>{environment.issuePr}</dd></div>
          <div><dt>{message(locale, "environmentGitHub")}</dt><dd>{environment.githubRepository} · {environment.githubStatus}</dd></div>
          <div><dt>{message(locale, "environmentGitHubChecks")}</dt><dd>{environment.githubChecks}</dd></div>
          <div><dt>{message(locale, "environmentGitHubActions")}</dt><dd>{environment.githubActions}</dd></div>
          <div><dt>{message(locale, "environmentCaptured")}</dt><dd>{formatTimestamp(environment.capturedAt, locale)}</dd></div>
        </dl>
      )}
      <form
        className="environment-commit-form"
        onSubmit={(event) => {
          event.preventDefault();
          commitAction.submit();
        }}
      >
        <label>
          <span>{locale === "ru" ? "Сообщение коммита" : "Commit message"}</span>
          <input
            disabled={environment?.commit !== "ready" || commitAction.pending}
            maxLength={4096}
            onChange={(event) => commitAction.setField("message", event.target.value)}
            required
            value={commitAction.draft.message}
          />
        </label>
        <div>
          <label>
            <span>{locale === "ru" ? "Имя автора" : "Author name"}</span>
            <input
              disabled={environment?.commit !== "ready" || commitAction.pending}
              maxLength={200}
              onChange={(event) => commitAction.setField("authorName", event.target.value)}
              required
              value={commitAction.draft.authorName}
            />
          </label>
          <label>
            <span>{locale === "ru" ? "Email автора" : "Author email"}</span>
            <input
              disabled={environment?.commit !== "ready" || commitAction.pending}
              maxLength={200}
              onChange={(event) => commitAction.setField("authorEmail", event.target.value)}
              required
              type="email"
              value={commitAction.draft.authorEmail}
            />
          </label>
        </div>
        <button
          className="primary-button"
          disabled={environment?.commit !== "ready" || commitAction.pending}
          type="submit"
        >
          {message(
            locale,
            commitAction.preview === undefined
              ? "environmentCommit"
              : "apply",
          )}
        </button>
        {commitAction.notice === null ? null : (
          <p className={commitAction.error ? "mutation-error" : "mutation-success"}>
            {commitAction.notice}
          </p>
        )}
      </form>
      <section className="environment-push-action">
        {pushAction.preview === undefined ? null : (
          <dl className="plan-fields">
            <div><dt>Remote</dt><dd>{pushAction.preview.remote}</dd></div>
            <div><dt>Upstream</dt><dd>{pushAction.preview.upstream ?? "new"}</dd></div>
            <div><dt>{locale === "ru" ? "Целевая ветка" : "Target branch"}</dt><dd>{pushAction.preview.target_branch}</dd></div>
            <div><dt>HEAD</dt><dd><code>{pushAction.preview.head.slice(0, 12)}</code></dd></div>
            <div><dt>Remote HEAD</dt><dd><code>{pushAction.preview.remote_head?.slice(0, 12) ?? "new"}</code></dd></div>
          </dl>
        )}
        <button
          className="primary-button"
          disabled={environment?.push !== "ready" || pushAction.pending}
          onClick={pushAction.submit}
          type="button"
        >
          {message(locale, pushAction.preview === undefined ? "environmentPush" : "apply")}
        </button>
        {pushAction.notice === null ? null : (
          <p className={pushAction.error ? "mutation-error" : "mutation-success"}>
            {pushAction.notice}
          </p>
        )}
        {pushAction.result === undefined ? null : (
          <div className="environment-push-links">
            <a href={pushAction.result.remote_commit_url} rel="noreferrer" target="_blank">
              {locale === "ru" ? "Удалённый коммит" : "Remote commit"}
            </a>
            <a href={pushAction.result.run_evidence_url} rel="noreferrer" target="_blank">
              {locale === "ru" ? "Проверки и запуски" : "Checks and runs"}
            </a>
          </div>
        )}
      </section>
      <form
        className="environment-pull-request-action"
        onSubmit={(event) => {
          event.preventDefault();
          pullRequestAction.submit();
        }}
      >
        <label>
          <span>{locale === "ru" ? "Заголовок pull request" : "Pull-request title"}</span>
          <input
            disabled={environment?.push !== "ready" || pullRequestAction.pending}
            maxLength={256}
            onChange={(event) => pullRequestAction.setField("title", event.target.value)}
            required
            value={pullRequestAction.draft.title}
          />
        </label>
        <label>
          <span>{locale === "ru" ? "Описание" : "Body"}</span>
          <textarea
            disabled={environment?.push !== "ready" || pullRequestAction.pending}
            maxLength={16384}
            onChange={(event) => pullRequestAction.setField("body", event.target.value)}
            value={pullRequestAction.draft.body}
          />
        </label>
        <label>
          <span>{locale === "ru" ? "Базовая ветка" : "Base branch"}</span>
          <input
            disabled={environment?.push !== "ready" || pullRequestAction.pending}
            maxLength={512}
            onChange={(event) => pullRequestAction.setField("baseBranch", event.target.value)}
            placeholder={locale === "ru" ? "по умолчанию" : "repository default"}
            value={pullRequestAction.draft.baseBranch}
          />
        </label>
        {pullRequestAction.preview === undefined ? null : (
          <dl className="plan-fields">
            <div><dt>{locale === "ru" ? "Репозиторий" : "Repository"}</dt><dd>{pullRequestAction.preview.repository.name_with_owner}</dd></div>
            <div><dt>{locale === "ru" ? "Исходная ветка" : "Source branch"}</dt><dd>{pullRequestAction.preview.source_branch}</dd></div>
            <div><dt>{locale === "ru" ? "Базовая ветка" : "Base branch"}</dt><dd>{pullRequestAction.preview.base_branch}</dd></div>
            <div><dt>HEAD</dt><dd><code>{pullRequestAction.preview.source_head.slice(0, 12)}</code></dd></div>
            <div><dt>Base HEAD</dt><dd><code>{pullRequestAction.preview.base_head.slice(0, 12)}</code></dd></div>
          </dl>
        )}
        <button
          className="primary-button"
          disabled={environment?.push !== "ready" || pullRequestAction.pending}
          type="submit"
        >
          {pullRequestAction.preview === undefined
            ? (locale === "ru" ? "Создать pull request" : "Create pull request")
            : message(locale, "apply")}
        </button>
        {pullRequestAction.notice === null ? null : (
          <p className={pullRequestAction.error ? "mutation-error" : "mutation-success"}>
            {pullRequestAction.notice}
          </p>
        )}
        {pullRequestAction.result === undefined ? null : (
          <div className="environment-push-links">
            <a href={pullRequestAction.result.pull_request_url} rel="noreferrer" target="_blank">PR #{pullRequestAction.result.number}</a>
            <a href={pullRequestAction.result.commit_url} rel="noreferrer" target="_blank">Commit</a>
            <a href={pullRequestAction.result.checks_url} rel="noreferrer" target="_blank">Checks</a>
            <a href={pullRequestAction.result.run_evidence_url} rel="noreferrer" target="_blank">Actions</a>
          </div>
        )}
      </form>
    </section>
  );
}

export function WorkbenchSurface() {
  const params = useParams({ strict: false });
  const routeSearch = useSearch({ strict: false });
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
  const [selectedSkills, setSelectedSkills] = useState<SkillMention[]>([]);
  const [environmentCommitDraft, setEnvironmentCommitDraft] = useState<EnvironmentCommitDraft>({
    authorEmail: "",
    authorName: "",
    message: "",
  });
  const [environmentCommitPreview, setEnvironmentCommitPreview] = useState<EnvironmentCommitPreview>();
  const [environmentCommitNotice, setEnvironmentCommitNotice] = useState<string | null>(null);
  const [environmentPushPreview, setEnvironmentPushPreview] = useState<EnvironmentPushPreview>();
  const [environmentPushResult, setEnvironmentPushResult] = useState<EnvironmentPushApplyResponse["result"]>();
  const [environmentPushNotice, setEnvironmentPushNotice] = useState<string | null>(null);
  const [environmentPullRequestDraft, setEnvironmentPullRequestDraft] = useState<EnvironmentPullRequestDraft>({
    baseBranch: "",
    body: "",
    title: "",
  });
  const [environmentPullRequestPreview, setEnvironmentPullRequestPreview] = useState<EnvironmentPullRequestPreview>();
  const [environmentPullRequestResult, setEnvironmentPullRequestResult] = useState<EnvironmentPullRequestApplyResponse["result"]>();
  const [environmentPullRequestNotice, setEnvironmentPullRequestNotice] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string>();
  const rememberedRunPreferences = useMemo(loadRunPreferences, []);
  const rememberedProductSelection = useMemo(
    () => resolveLegacyProductSelection(
      rememberedRunPreferences.config.mode,
      rememberedRunPreferences.config.harnessId === "direct-chat"
        ? "direct_chat"
        : "coding_agent",
    ),
    [rememberedRunPreferences],
  );
  const [runConfig, setRunConfig] = useState<RunConfig>(rememberedRunPreferences.config);
  const [productSelection, setProductSelection] = useState<ProductExecutionSelection>(
    rememberedProductSelection.selection,
  );
  const [legacyModeWarning, setLegacyModeWarning] = useState<string | null>(
    rememberedProductSelection.warning,
  );
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort>(
    rememberedRunPreferences.reasoningEffort,
  );
  const [advancedConfig, setAdvancedConfig] = useState<AdvancedRunConfig>({
    dryRun: false,
    permissionProfile: "interactive",
    workspacePolicy: "auto",
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [builtinTools, setBuiltinTools] = useState<string[]>([]);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [toolPickerOpen, setToolPickerOpen] = useState(false);
  const [toolSearch, setToolSearch] = useState("");
  const [draggingFiles, setDraggingFiles] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [composerCaret, setComposerCaret] = useState(0);
  const [atSelection, setAtSelection] = useState(0);
  const [previewReport, setPreviewReport] = useState<RunPreflightResponse["preflight"] | null>(null);
  const permissionHighlights = permissionSimulationHighlights(
    previewReport?.permission_simulation,
  );
  const [startedRuns, setStartedRuns] = useState<Record<string, string>>({});
  const [unreadSessionIds, setUnreadSessionIds] = useState<Set<string>>(() => new Set());
  const [completionNotices, setCompletionNotices] = useState<CompletionNotice[]>([]);
  const previousRunStatuses = useRef(new Map<string, string>());
  const settingsDefaultsApplied = useRef(false);
  const automaticSessionRequested = useRef(false);
  const [sessionConfirmation, setSessionConfirmation] = useState<{
    action: SessionAction;
    id: string;
    title: string;
  } | null>(null);

  const index = useQuery(sessionIndexOptions());
  const runsCenter = useQuery(runsCenterOptions());
  const harnesses = useQuery(harnessesOptions());
  const models = useQuery(modelsOptions(runConfig.apiMode));
  const settings = useQuery(settingsOptions());
  const integrations = useQuery(integrationFlowOptions());
  const overview = useQuery({
    ...sessionOverviewOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const environment = useQuery({
    ...environmentOptions(sessionId ?? "pending"),
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
  const atQuery = activeAtQuery(prompt, composerCaret);
  const deferredAtQuery = useDeferredValue(atQuery?.query ?? "");
  const workspaceFiles = useQuery({
    ...workspaceFilesOptions(sessionId ?? "pending", deferredAtQuery),
    enabled: sessionId !== undefined && atQuery !== null,
  });
  const availableSkillMentions = skillMentionOptions(
    integrations.data,
    runConfig.harnessId,
    deferredAtQuery,
  ).filter((skill) => !selectedSkills.some((selected) => selected.id === skill.id));
  const events = useQuery({
    ...sessionEventsOptions(sessionId ?? "pending"),
    enabled: sessionId !== undefined,
  });
  const activeMessages = useMemo(
    () => projectActiveMessageTimeline(messages.data?.messages ?? []),
    [messages.data?.messages],
  );
  const draftAttachments = useMemo(
    () => composerAttachments(
      attachments.data?.attachments ?? [],
      messages.data?.messages ?? [],
    ),
    [attachments.data?.attachments, messages.data?.messages],
  );
  const latestUserMessageId = latestEditableUserMessageId(activeMessages);
  const visibleMessages = useMemo(
    () => timelineWhileEditing(activeMessages, editingMessageId),
    [activeMessages, editingMessageId],
  );

  useEffect(() => {
    setEditingMessageId(undefined);
    setSelectedSkills([]);
  }, [sessionId]);

  useEffect(() => {
    if (settings.data === undefined || settingsDefaultsApplied.current) return;
    settingsDefaultsApplied.current = true;
    const defaults = settings.data.harness_defaults;
    if (sessionId === undefined) {
      setRunConfig({
        apiMode: defaults.default_api_mode,
        harnessId: defaults.default_harness_id,
        mode: defaults.mode,
        model: defaults.default_model ?? "",
      });
      setProductSelection({
        authority: defaults.authority,
        intent: defaults.task_intent,
        kind: defaults.default_harness_id === "direct-chat"
          ? "direct_chat"
          : "coding_agent",
      });
      setLegacyModeWarning(
        settings.data.harness_defaults.compatibility.mode?.warning ?? null,
      );
    }
    setAdvancedConfig((current) => ({
      ...current,
      permissionProfile: defaults.permission_profile,
      workspacePolicy: defaults.workspace_policy,
    }));
  }, [sessionId, settings.data]);
  const retainedLatestRun = latestRun(runs.data?.runs ?? []);
  const selectedRunId =
    sessionId === undefined ? retainedLatestRun?.id : startedRuns[sessionId] ?? retainedLatestRun?.id;
  const locallyStartedRunSelected =
    sessionId !== undefined && startedRuns[sessionId] === selectedRunId;
  const stream = useRunEventStream(selectedRunId, 0, !locallyStartedRunSelected);

  useEffect(() => {
    if (sessionId === undefined || typeof globalThis.EventSource !== "function") {
      return;
    }
    return observeSessionUpdates(sessionId, () => {
      void refreshSessionRevision(queryClient, sessionId);
    });
  }, [queryClient, sessionId]);

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
    setProductSelection((current) => {
      const retained = session.workbench_selection;
      if (retained !== undefined) {
        setLegacyModeWarning(retained.compatibility_warning);
        return {
          authority: retained.authority,
          intent: retained.intent,
          kind: retained.kind,
        };
      }
      const legacy = resolveLegacyProductSelection(
        session.default_mode,
        session.default_harness_id === "direct-chat"
          ? "direct_chat"
          : current.kind,
      );
      setLegacyModeWarning(legacy.warning);
      return legacy.selection;
    });
  }, [
    overview.data?.session.default_api_mode,
    overview.data?.session.default_harness_id,
    overview.data?.session.default_mode,
    overview.data?.session.default_model,
    overview.data?.session.id,
    overview.data?.session.workbench_selection,
  ]);

  useEffect(() => {
    if (models.isPending) return;
    const availableModels = models.data?.models ?? [];
    const selectedModel = models.isSuccess && availableModels.length > 0
      ? preferredModel(availableModels)
      : settings.data?.harness_defaults.default_model ?? "";
    setRunConfig((current) => {
      if (
        current.model &&
        (!models.isSuccess || availableModels.length === 0 || availableModels.includes(current.model))
      ) {
        return current;
      }
      return current.model === selectedModel ? current : { ...current, model: selectedModel };
    });
  }, [
    models.data?.models,
    models.isPending,
    models.isSuccess,
    runConfig.model,
    settings.data?.harness_defaults.default_model,
  ]);

  const createSession = useMutation({
    mutationFn: (intent: SessionCreationIntent) =>
      mutateCockpit<{ session: SessionSummary }>(
        "/api/sessions",
        sessionCreationPayload(intent),
      ),
    onSuccess: ({ session }) => {
      setPrompt("");
      setSelectedSkills([]);
      setBuiltinTools([]);
      void navigate({
        params: { sessionId: session.id },
        to: "/cockpit-v2/work/$sessionId",
      });
      void queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() });
    },
  });
  const environmentCommit = useMutation({
    mutationFn: async () => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      const preview = environmentCommitPreview ?? (
        await mutateCockpit<EnvironmentCommitPreviewResponse>(
          "/api/environment/commit/preview",
          {
            session_id: sessionId,
            message: environmentCommitDraft.message,
            author_name: environmentCommitDraft.authorName,
            author_email: environmentCommitDraft.authorEmail,
          },
        )
      ).preview;
      return mutateCockpit<EnvironmentCommitApplyResponse>(
        "/api/environment/commit/apply",
        { preview_id: preview.id, session_id: sessionId },
      );
    },
    onSuccess: async (response) => {
      if (response.result === undefined) {
        setEnvironmentCommitPreview(response.preview);
        setEnvironmentCommitNotice(
          locale === "ru"
            ? "Подтвердите точный коммит во Inbox и примените снова."
            : "Approve the exact commit in Inbox, then apply again.",
        );
        openInbox("approvals");
        return;
      }
      setEnvironmentCommitPreview(undefined);
      setEnvironmentCommitDraft((current) => ({ ...current, message: "" }));
      setEnvironmentCommitNotice(
        `${message(locale, "environmentCommit")}: ${response.result.commit_head.slice(0, 8)}`,
      );
      await queryClient.invalidateQueries({ queryKey: requestKeys.environment(sessionId ?? "pending") });
    },
  });
  const environmentPush = useMutation({
    mutationFn: async () => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      const preview = environmentPushPreview ?? (
        await mutateCockpit<EnvironmentPushPreviewResponse>(
          "/api/environment/push/preview",
          { session_id: sessionId },
        )
      ).preview;
      return mutateCockpit<EnvironmentPushApplyResponse>(
        "/api/environment/push/apply",
        { preview_id: preview.id, session_id: sessionId },
      );
    },
    onSuccess: async (response) => {
      if (response.result === undefined) {
        setEnvironmentPushPreview(response.preview);
        setEnvironmentPushResult(undefined);
        setEnvironmentPushNotice(
          locale === "ru"
            ? "Подтвердите точный push во Inbox и примените снова."
            : "Approve the exact push in Inbox, then apply again.",
        );
        openInbox("approvals");
        return;
      }
      setEnvironmentPushPreview(undefined);
      setEnvironmentPushResult(response.result);
      setEnvironmentPushNotice(
        `${message(locale, "environmentPush")}: ${response.result.commit_head.slice(0, 8)}`,
      );
      await queryClient.invalidateQueries({ queryKey: requestKeys.environment(sessionId ?? "pending") });
    },
  });
  const environmentPullRequest = useMutation({
    mutationFn: async () => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      const preview = environmentPullRequestPreview ?? (
        await mutateCockpit<EnvironmentPullRequestPreviewResponse>(
          "/api/environment/pull-request/preview",
          {
            session_id: sessionId,
            title: environmentPullRequestDraft.title,
            body: environmentPullRequestDraft.body,
            base_branch: environmentPullRequestDraft.baseBranch || undefined,
          },
        )
      ).preview;
      return mutateCockpit<EnvironmentPullRequestApplyResponse>(
        "/api/environment/pull-request/apply",
        { preview_id: preview.id, session_id: sessionId },
      );
    },
    onSuccess: async (response) => {
      if (response.result === undefined) {
        setEnvironmentPullRequestPreview(response.preview);
        setEnvironmentPullRequestResult(undefined);
        setEnvironmentPullRequestNotice(
          locale === "ru"
            ? "Подтвердите точный pull request во Inbox и примените снова."
            : "Approve the exact pull request in Inbox, then apply again.",
        );
        openInbox("approvals");
        return;
      }
      setEnvironmentPullRequestPreview(undefined);
      setEnvironmentPullRequestResult(response.result);
      setEnvironmentPullRequestNotice(`PR #${response.result.number}`);
      await queryClient.invalidateQueries({ queryKey: requestKeys.environment(sessionId ?? "pending") });
    },
  });
  const createSessionMutate = createSession.mutate;

  useEffect(() => {
    if (
      !shouldAutomaticallyCreateSession(sessionId, routeSearch)
      || automaticSessionRequested.current
    ) return;
    automaticSessionRequested.current = true;
    createSessionMutate({ kind: "backend-defaults" });
  }, [createSessionMutate, routeSearch, sessionId]);

  useEffect(() => {
    if (sessionId === undefined || !overview.isSuccess) return;
    const frame = requestAnimationFrame(() => composerRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [overview.isSuccess, sessionId]);

  const startRun = useMutation<StartResult>({
    mutationFn: async () => {
      const session = overview.data?.session;
      if (sessionId === undefined || session === undefined) {
        throw new Error("Session is not selected");
      }
      const payload = {
        api_mode: runConfig.apiMode,
        attachment_ids: draftAttachments.map((attachment) => attachment.id),
        authority: productSelection.authority,
        builtin_tools: admittedBuiltinTools,
        extra: {
          ...(editingMessageId === undefined ? {} : { edit_message_id: editingMessageId }),
          generate_session_title: session.title === "Untitled session",
          session_title_model:
            settings.data?.harness_defaults.default_title_model
            ?? (runConfig.model.trim() || undefined),
          ...(isReasoningModel(runConfig.model)
            ? { agent_adapter_options: { reasoning_effort: reasoningEffort } }
            : {}),
        },
        harness_id: runConfig.harnessId,
        model: runConfig.model.trim() || null,
        permission_profile: advancedConfig.permissionProfile,
        prompt: promptWithSkillMentions(
          prompt,
          selectedSkills,
          runConfig.harnessId,
        ),
        session_id: sessionId,
        task_intent: productSelection.intent,
        workbench_kind: productSelection.kind,
        workspace: session.workspace_bound ? undefined : ".",
        workspace_policy: advancedConfig.workspacePolicy,
      };
      if (advancedConfig.dryRun) {
        const response = await mutateCockpit<RunPreflightResponse>("/api/preflight/run", {
          ...payload,
          dry_run: true,
        });
        return { kind: "preview", report: response.preflight };
      }
      const response = await mutateCockpit<RunStartResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/run/start`,
        payload,
      );
      return { kind: "run", run: response.run };
    },
    onSuccess: async (result) => {
      if (result.kind === "preview") {
        setPreviewReport(result.report);
        return;
      }
      const { run } = result;
      setPreviewReport(null);
      setStartedRuns((current) => ({ ...current, [run.session_id]: run.id }));
      previousRunStatuses.current.set(run.id, run.status);
      await refreshSessionAfterRunStart(queryClient, run.session_id);
      setEditingMessageId(undefined);
      setPrompt("");
      setSelectedSkills([]);
    },
  });
  const messageAction = useMutation({
    mutationFn: async ({ kind, messageId }: MessageAction) => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      return resolveMessageAction(
        kind,
        async () => {
          const response = await fetchCockpit<FullMessageResponse>(
            `/api/cockpit/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}/content`,
          );
          return response.content;
        },
        async (content) => {
          if (typeof navigator.clipboard?.writeText !== "function") {
            throw new Error("Clipboard API is unavailable");
          }
          await navigator.clipboard.writeText(content);
        },
      );
    },
    onSuccess: ({ content, kind }, variables) => {
      if (kind !== "edit") return;
      setEditingMessageId(variables.messageId);
      setPrompt(content);
      setComposerCaret(content.length);
      setPreviewReport(null);
      requestAnimationFrame(() => {
        const composer = composerRef.current;
        composer?.focus();
        composer?.setSelectionRange(content.length, content.length);
        composer?.scrollIntoView({ block: "nearest" });
      });
    },
  });
  const openInProvider = useMutation({
    mutationFn: () => fetchCockpit<ProviderHandoffPreview>(withQuery(
      `/api/provider-handoffs/${encodeURIComponent(runConfig.harnessId)}/preview`,
      { action: "open_provider_ui", workspace: "." },
    )),
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

  const attachWorkspaceFile = useMutation({
    mutationFn: ({ path }: { path: string; token: { start: number; end: number } }) => {
      if (sessionId === undefined) throw new Error("Session is not selected");
      return mutateCockpit<AttachmentUploadResponse>(
        `/api/sessions/${encodeURIComponent(sessionId)}/attachments/workspace`,
        { path },
      );
    },
    onSuccess: async (_, { token }) => {
      const nextPrompt = consumeAtQuery(prompt, token);
      setPrompt(nextPrompt);
      setComposerCaret(nextPrompt.length);
      setAtSelection(0);
      if (sessionId !== undefined) {
        await queryClient.invalidateQueries({ queryKey: requestKeys.sessionAttachments(sessionId) });
      }
      requestAnimationFrame(() => composerRef.current?.focus());
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
    mutationFn: ({ nativeProcessId, runId }: { nativeProcessId?: string; runId: string }) =>
      nativeProcessId === undefined
        ? mutateCockpit(`/api/runs/${encodeURIComponent(runId)}/cancel`)
        : deleteCockpit(`/api/native/processes/${encodeURIComponent(nativeProcessId)}`),
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
      if (id === sessionId) {
        await navigate({
          replace: true,
          search: { fromSessionAction: true },
          to: "/cockpit-v2/work",
        });
      }
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
  const environmentView = environment.data === undefined
    ? undefined
    : projectEnvironment(environment.data, { failedRefresh: environment.isError });
  const environmentCommitAction: EnvironmentCommitAction = {
    draft: environmentCommitDraft,
    error: environmentCommit.isError,
    notice: environmentCommit.isError
      ? (environmentCommit.error instanceof Error ? environmentCommit.error.message : "Commit failed")
      : environmentCommitNotice,
    pending: environmentCommit.isPending,
    preview: environmentCommitPreview,
    setField: (field, value) => {
      setEnvironmentCommitDraft((current) => ({ ...current, [field]: value }));
      setEnvironmentCommitPreview(undefined);
      setEnvironmentCommitNotice(null);
      environmentCommit.reset();
    },
    submit: () => environmentCommit.mutate(),
  };
  const environmentPushAction: EnvironmentPushAction = {
    error: environmentPush.isError,
    notice: environmentPush.isError
      ? (environmentPush.error instanceof Error ? environmentPush.error.message : "Push failed")
      : environmentPushNotice,
    pending: environmentPush.isPending,
    preview: environmentPushPreview,
    result: environmentPushResult,
    submit: () => environmentPush.mutate(),
  };
  const environmentPullRequestAction: EnvironmentPullRequestAction = {
    draft: environmentPullRequestDraft,
    error: environmentPullRequest.isError,
    notice: environmentPullRequest.isError
      ? (environmentPullRequest.error instanceof Error
        ? environmentPullRequest.error.message
        : "Pull-request creation failed")
      : environmentPullRequestNotice,
    pending: environmentPullRequest.isPending,
    preview: environmentPullRequestPreview,
    result: environmentPullRequestResult,
    setField: (field, value) => {
      setEnvironmentPullRequestDraft((current) => ({ ...current, [field]: value }));
      setEnvironmentPullRequestPreview(undefined);
      setEnvironmentPullRequestNotice(null);
      environmentPullRequest.reset();
    },
    submit: () => environmentPullRequest.mutate(),
  };
  const selectedHarness = harnesses.data?.harnesses.find(
    (harness) => harness.spec.id === runConfig.harnessId,
  );
  const selectableHarnesses = harnessesForWorkbenchKind(
    harnesses.data?.harnesses ?? [],
    productSelection.kind,
  );
  const admittedTransport = admittedExecutionTransport(
    selectedHarness,
    productSelection.kind,
  );
  const selectedTransport = selectedHarness?.workbench_transport?.options.find(
    (option) => option.id === admittedTransport,
  );
  const selectedAdmission = selectedHarness?.workbench_admission?.modes.find(
    (mode) => mode.id === productSelection.kind,
  );
  const authorityLimitsChange =
    productSelection.intent === "change"
    && productSelection.authority === "read_only";
  const admissionStatus = selectedAdmission?.status === "blocked"
    ? "blocked"
    : selectedAdmission?.status === "degraded" || authorityLimitsChange
      ? "degraded"
      : "available";
  const admissionReasons = [
    ...(selectedAdmission?.why ?? []),
    ...(authorityLimitsChange
      ? ["change_intent_limited_by_read_only_authority"]
      : []),
  ];
  const providerHandoffActions = [
    ...(selectedHarness?.provider_handoff?.available_actions ?? []),
    ...(selectedHarness?.provider_handoff?.degraded_actions ?? []),
  ];
  const capabilityCopy = productSelection.kind === "coding_agent"
    ? { label: message(locale, "codingAgent"), detail: message(locale, "codingAgentHint") }
    : { label: message(locale, "directChat"), detail: message(locale, "directChatHint") };
  const supportedBuiltinTools = selectedHarness?.spec.supported_builtin_tools ?? emptyStringList;
  const builtinToolsAvailable =
    runConfig.apiMode === "v2" &&
    productSelection.kind === "direct_chat" &&
    supportedBuiltinTools.length > 0;
  const admittedBuiltinTools = useMemo(
    () => admittedBuiltinToolSelection(
      builtinTools,
      supportedBuiltinTools,
      runConfig.apiMode,
      productSelection.kind,
    ),
    [builtinTools, productSelection.kind, runConfig.apiMode, supportedBuiltinTools],
  );
  const toolSkillMentions = useMemo(
    () => skillMentionOptions(
      integrations.data,
      runConfig.harnessId,
      toolSearch,
    ),
    [integrations.data, runConfig.harnessId, toolSearch],
  );
  const toolGroups = useMemo(
    () => composerToolCatalog({
      apiMode: runConfig.apiMode,
      builtinTools: admittedBuiltinTools,
      harnessId: runConfig.harnessId,
      inventory: integrations.data,
      kind: productSelection.kind,
      query: toolSearch,
      selectedSkillIds: new Set(selectedSkills.map((skill) => skill.id)),
      skillMentions: toolSkillMentions,
      supportedBuiltinTools,
    }),
    [
      admittedBuiltinTools,
      integrations.data,
      productSelection.kind,
      runConfig.apiMode,
      runConfig.harnessId,
      selectedSkills,
      supportedBuiltinTools,
      toolSearch,
      toolSkillMentions,
    ],
  );
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
  const selectedRun = (runs.data?.runs ?? []).find((run) => run.id === selectedRunId);
  const selectedNativeProcessId =
    selectedRun?.native_process_id ?? undefined;

  useEffect(() => {
    const supported = new Set(supportedBuiltinTools);
    setBuiltinTools((current) => (
      builtinToolsAvailable
        ? current.filter((tool) => supported.has(tool))
        : []
    ));
    setProductSelection((current) => normalizeProductSelection(selectedHarness, current));
  }, [
    builtinToolsAvailable,
    runConfig.harnessId,
    selectedHarness,
    supportedBuiltinTools,
  ]);

  useEffect(() => {
    setAtSelection(0);
  }, [deferredAtQuery]);

  useEffect(() => {
    if (
      sessionId === undefined ||
      selectedNativeProcessId === undefined ||
      !selectedRunActive ||
      typeof globalThis.EventSource !== "function"
    ) {
      return;
    }
    let refreshScheduled = false;
    return observeNativeProcess(selectedNativeProcessId, () => {
      if (refreshScheduled) return;
      refreshScheduled = true;
      requestAnimationFrame(() => {
        refreshScheduled = false;
        void Promise.all([
          queryClient.invalidateQueries({ queryKey: requestKeys.sessionScope(sessionId) }),
          queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
        ]);
      });
    });
  }, [queryClient, selectedNativeProcessId, selectedRunActive, sessionId]);

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
  const updateProductSelection = (
    patch: Partial<ProductExecutionSelection>,
  ) => {
    const next = { ...productSelection, ...patch };
    setProductSelection(next);
    setLegacyModeWarning(null);
    setRunConfig((current) => ({
      ...current,
      mode: legacyModeForProductSelection(next),
    }));
    saveRunConfig.mutate({ workbench_selection: next });
  };
  const selectWorkbenchKind = (kind: WorkbenchKind) => {
    const compatibleHarnesses = harnessesForWorkbenchKind(
      harnesses.data?.harnesses ?? [],
      kind,
    ).filter(
      (harness) => harness.availability?.status !== "unavailable",
    );
    const preferredHarnessId =
      kind === "coding_agent" ? "codex-cli" : "direct-chat";
    const compatibleHarness =
      compatibleHarnesses?.find(
        (harness) => harness.spec.id === runConfig.harnessId,
      )
      ?? compatibleHarnesses?.find(
        (harness) => harness.spec.id === preferredHarnessId,
      )
      ?? compatibleHarnesses?.[0];
    setProductSelection((current) => ({ ...current, kind }));
    if (
      compatibleHarness !== undefined
      && compatibleHarness.spec.id !== runConfig.harnessId
    ) {
      setConfig(
        "harnessId",
        compatibleHarness.spec.id,
        "default_harness_id",
      );
    }
  };
  const workspaceFileCandidates = workspaceFiles.data?.files ?? [];
  const atCandidates = [
    ...availableSkillMentions.map((skill) => ({ kind: "skill" as const, skill })),
    ...workspaceFileCandidates.map((file) => ({ kind: "file" as const, file })),
  ];
  const chooseWorkspaceFile = (path: string) => {
    if (atQuery === null || attachWorkspaceFile.isPending) return;
    attachWorkspaceFile.mutate({ path, token: atQuery });
  };
  const chooseSkill = (skill: SkillMention) => {
    if (atQuery === null) return;
    const nextPrompt = consumeAtQuery(prompt, atQuery);
    setSelectedSkills((current) => [...current, skill]);
    setPrompt(nextPrompt);
    setComposerCaret(nextPrompt.length);
    setAtSelection(0);
    requestAnimationFrame(() => composerRef.current?.focus());
  };
  const chooseAtCandidate = (index: number) => {
    const candidate = atCandidates[index];
    if (candidate?.kind === "skill") chooseSkill(candidate.skill);
    if (candidate?.kind === "file") chooseWorkspaceFile(candidate.file.path);
  };
  const toggleComposerTool = (option: ComposerToolOption) => {
    if (!option.selectable || option.value === null) return;
    const value = option.value;
    if (option.category === "gigachat") {
      setBuiltinTools((current) => (
        current.includes(value)
          ? current.filter((tool) => tool !== value)
          : [...current, value]
      ));
      return;
    }
    const skill = toolSkillMentions.find((candidate) => candidate.id === value);
    if (skill === undefined) return;
    setSelectedSkills((current) => (
      current.some((candidate) => candidate.id === skill.id)
        ? current.filter((candidate) => candidate.id !== skill.id)
        : [...current, skill]
    ));
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
            onClick={() => createSession.mutate({
              config: { ...runConfig, productSelection },
              kind: "configured",
            })}
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
                    <div
                      className={[
                        "session-row",
                        session.id === sessionId ? "selected" : "",
                        running ? "running" : "",
                        unread ? "unread" : "",
                      ].filter(Boolean).join(" ")}
                      key={session.id}
                    >
                      <Link
                        className="session-row-link"
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
                      <div className="session-row-actions">
                        <button
                          aria-label={`${message(locale, "archiveSession")}: ${session.title}`}
                          disabled={changeSession.isPending}
                          onClick={() => {
                            changeSession.reset();
                            setSessionConfirmation({
                              action: "archive",
                              id: session.id,
                              title: session.title,
                            });
                          }}
                          title={message(locale, "archiveSession")}
                          type="button"
                        >
                          <ArchiveSessionIcon />
                        </button>
                        <button
                          aria-label={`${message(locale, "deleteSession")}: ${session.title}`}
                          className="danger"
                          disabled={changeSession.isPending}
                          onClick={() => {
                            changeSession.reset();
                            setSessionConfirmation({
                              action: "delete",
                              id: session.id,
                              title: session.title,
                            });
                          }}
                          title={message(locale, "deleteSession")}
                          type="button"
                        >
                          <DeleteSessionIcon />
                        </button>
                      </div>
                    </div>
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
            {routeSearch.fromSessionAction === true ? (
              <>
                <h1>{message(locale, "noSessionSelected")}</h1>
                <p>{message(locale, "noSessionSelectedDescription")}</p>
              </>
            ) : (
              <>
                <span className="opening-session-spinner" aria-hidden="true" />
                <h1>{message(locale, "openingSession")}</h1>
              </>
            )}
            {routeSearch.fromSessionAction !== true && createSession.isError ? (
              <button
                onClick={() => createSession.mutate({ kind: "backend-defaults" })}
                type="button"
              >
                {message(locale, "retry")}
              </button>
            ) : null}
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
            <EnvironmentCard
              className="mobile-environment"
              commitAction={environmentCommitAction}
              pushAction={environmentPushAction}
              pullRequestAction={environmentPullRequestAction}
              environment={environmentView}
              error={environment.isError}
              locale={locale}
              pending={environment.isPending}
            />
            <section className="message-region" aria-label={message(locale, "sessionMessages")}>
              {messages.isPending ? <ListSkeleton rows={4} /> : null}
              {messages.isError ? <ReadError locale={locale} /> : null}
              {messages.data !== undefined && visibleMessages.length === 0 ? (
                <div className="empty-state">{message(locale, "emptyMessages")}</div>
              ) : null}
              {visibleMessages.map((item) => (
                <Fragment key={item.id}>
                  {(item.role === "assistant" || item.role === "error") && item.run_id
                    ? (
                        <RetainedToolActivities
                          events={retainedToolEvents.filter((event) => event.run_id === item.run_id)}
                          locale={locale}
                        />
                      )
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
                    <header className="message-entry-header">
                      <span className="message-role">{item.role}</span>
                      <span className="message-header-meta">
                        <TokenUsage usage={item.usage} />
                        <time>{formatTimestamp(item.created_at, locale)}</time>
                        {item.role === "assistant" || item.role === "user" ? (
                          <MessageActions
                            canEdit={item.id === latestUserMessageId}
                            locale={locale}
                            messageId={item.id}
                            mutation={messageAction}
                            role={item.role}
                          />
                        ) : null}
                      </span>
                    </header>
                    {item.reasoning?.text ? (
                      <ReasoningDisclosure text={item.reasoning.text} locale={locale} />
                    ) : null}
                    {item.attachments && item.attachments.length > 0 ? (
                      <AttachmentGallery attachments={item.attachments} locale={locale} />
                    ) : null}
                    <MessageMarkdown source={item.content.text} />
                    {item.content.truncated ? <span>{message(locale, "boundedPreview")}</span> : null}
                  </article>
                </Fragment>
              ))}
              {messageAction.isError ? (
                <span className="error-state" role="alert">
                  {message(locale, "messageActionFailed")}
                </span>
              ) : null}
              <span className="sr-only" aria-live="polite">
                {messageAction.isSuccess
                  ? message(
                      locale,
                      messageAction.data.kind === "copy"
                        ? messageAction.variables.role === "user"
                          ? "userMessageCopied"
                          : "assistantMessageCopied"
                        : "userMessageLoaded",
                    )
                  : ""}
              </span>
              {retainedGeneratedEvents.map((event) => (
                <GeneratedFilePreview
                  eventId={event.id}
                  key={event.id}
                  locale={locale}
                  payloadUrl={event.payload_url}
                />
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
                  <header className="message-entry-header">
                    <span className="message-role">assistant</span>
                    <TokenUsage usage={streamPresentation.usage} />
                  </header>
                  <MessageMarkdown source={streamPresentation.assistantText} />
                </article>
              ) : null}
              {streamPresentation.generatedFiles.map((event) => (
                <GeneratedFileCard key={event.id} locale={locale} payload={event.payload} />
              ))}
            </section>
            <form
              className={[
                "composer",
                draggingFiles ? "dragging-files" : "",
                modelMenuOpen || plusMenuOpen || toolPickerOpen ? "popover-open" : "",
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
              {legacyModeWarning === null ? null : (
                <div className="preview-execution blocked" role="status">
                  <strong>{message(locale, "legacyModeWarningTitle")}</strong>
                  <span>{message(locale, "legacyModeWarning")}</span>
                </div>
              )}
              {previewReport === null ? null : (
                <div
                  className={previewReport.hard_block ? "preview-execution blocked" : "preview-execution"}
                  role="status"
                >
                  <strong>{message(locale, "previewExecutionResult")}</strong>
                  <span>
                    {previewReport.hard_block
                      ? message(locale, "previewExecutionBlocked")
                      : message(locale, "previewExecutionReady")}
                  </span>
                  <small>
                    {message(locale, "previewExecutionEvidence")} · {previewReport.findings.length} {message(locale, "previewFindings")}
                  </small>
                  {permissionHighlights === null ? null : (
                    <small className="permission-simulation-summary">
                      {message(locale, "permissionSimulation")} · {permissionHighlights.approvalCount} {message(locale, "approvalRequired")} · {permissionHighlights.unknownCount} {message(locale, "permissionSimulationUnknown")} · {message(locale, "permissionSimulationEvidence")} {permissionHighlights.evidence}
                    </small>
                  )}
                </div>
              )}
              {selectedSkills.length > 0 || admittedBuiltinTools.length > 0 ? (
                <div className="attachment-chips" aria-label={message(locale, "selectedTools")}>
                  {admittedBuiltinTools.map((tool) => (
                    <span className="attachment-chip tool-selection-chip" key={tool}>
                      <span aria-hidden="true">⌁</span>
                      <span>{builtinToolLabels[tool] ?? tool}</span>
                      <small>GigaChat</small>
                      <button
                        aria-label={`${message(locale, "removeTool")} ${builtinToolLabels[tool] ?? tool}`}
                        onClick={() => setBuiltinTools((current) => current.filter((item) => item !== tool))}
                        type="button"
                      >×</button>
                    </span>
                  ))}
                  {selectedSkills.map((skill) => (
                    <span className="attachment-chip skill-mention-chip" key={skill.id}>
                      <span aria-hidden="true">✦</span>
                      <span title={`${skill.source} · ${skill.nativeName}`}>{skill.mention}</span>
                      <small>{skill.source}</small>
                      <button
                        aria-label={`${message(locale, "removeTool")} ${skill.mention}`}
                        onClick={() => setSelectedSkills((current) => current.filter((item) => item.id !== skill.id))}
                        type="button"
                      >×</button>
                    </span>
                  ))}
                </div>
              ) : null}
              {draftAttachments.length > 0 ? (
                <AttachmentGallery
                  attachments={draftAttachments}
                  locale={locale}
                  onRemove={(attachmentId) => removeAttachment.mutate(attachmentId)}
                  removePending={removeAttachment.isPending}
                />
              ) : null}
              {toolPickerOpen ? (
                <section
                  aria-label={message(locale, "toolPickerTitle")}
                  className="composer-tool-picker"
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setToolPickerOpen(false);
                    }
                  }}
                  role="dialog"
                >
                  <header>
                    <div>
                      <strong>{message(locale, "toolPickerTitle")}</strong>
                      <span>{message(locale, "toolPickerHint")}</span>
                    </div>
                    <button
                      aria-label={message(locale, "close")}
                      onClick={() => setToolPickerOpen(false)}
                      type="button"
                    >×</button>
                  </header>
                  <label className="tool-picker-search">
                    <span className="sr-only">{message(locale, "searchTools")}</span>
                    <input
                      autoFocus
                      onChange={(event) => setToolSearch(event.target.value)}
                      placeholder={message(locale, "searchTools")}
                      type="search"
                      value={toolSearch}
                    />
                  </label>
                  <div className="tool-picker-results">
                    {toolGroups.length === 0 ? (
                      <p className="empty-state">{message(locale, "noToolsFound")}</p>
                    ) : toolGroups.map((group) => (
                      <section className="tool-picker-group" key={group.category}>
                        <h3>{message(locale, toolCategoryMessageKeys[group.category])}</h3>
                        <div>
                          {group.options.map((option) => (
                            <button
                              aria-disabled={!option.selectable}
                              aria-pressed={option.selectable ? option.selected : undefined}
                              className={[
                                "tool-picker-option",
                                option.selected ? "selected" : "",
                                option.selectable ? "" : "unavailable",
                              ].filter(Boolean).join(" ")}
                              key={option.id}
                              onClick={() => toggleComposerTool(option)}
                              type="button"
                            >
                              <span aria-hidden="true">{option.selected ? "✓" : option.selectable ? "+" : "·"}</span>
                              <span>
                                <strong>{option.label}</strong>
                                <small>{option.detail}</small>
                                {option.reason === null ? null : <em>{option.reason}</em>}
                              </span>
                            </button>
                          ))}
                        </div>
                      </section>
                    ))}
                  </div>
                </section>
              ) : null}
              <textarea
                aria-label={message(locale, "composerPlaceholder")}
                aria-controls={atQuery === null ? undefined : "workspace-file-picker"}
                aria-expanded={atQuery !== null}
                disabled={startRun.isPending}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  setComposerCaret(event.target.selectionStart);
                  setPreviewReport(null);
                }}
                onKeyDown={(event) => {
                  if (atQuery !== null && atCandidates.length > 0) {
                    if (event.key === "ArrowDown") {
                      event.preventDefault();
                      setAtSelection((current) => (current + 1) % atCandidates.length);
                      return;
                    }
                    if (event.key === "ArrowUp") {
                      event.preventDefault();
                      setAtSelection((current) => (current - 1 + atCandidates.length) % atCandidates.length);
                      return;
                    }
                    if (event.key === "Enter" && !event.metaKey && !event.ctrlKey) {
                      event.preventDefault();
                      chooseAtCandidate(atSelection);
                      return;
                    }
                  }
                  if (event.key === "Escape" && atQuery !== null) {
                    event.preventDefault();
                    setComposerCaret(atQuery.start);
                    return;
                  }
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
                ref={composerRef}
                rows={4}
                onSelect={(event) => setComposerCaret(event.currentTarget.selectionStart)}
                value={prompt}
              />
              {atQuery === null ? null : (
                <div className="workspace-file-picker" id="workspace-file-picker" role="listbox">
                  <div>
                    <strong>{locale === "ru" ? "Skills, плагины и файлы" : "Skills, plugins, and files"}</strong>
                    <small>
                      {locale === "ru"
                        ? "OpenAI bundled capabilities доступны здесь через @; для Codex Harness передаст нативный $-вызов."
                        : "OpenAI bundled capabilities are selectable with @; Harness sends Codex the native $ invocation."}
                    </small>
                  </div>
                  {availableSkillMentions.map((skill, index) => (
                    <button
                      aria-selected={index === atSelection}
                      className={index === atSelection ? "selected" : ""}
                      key={skill.id}
                      onClick={() => chooseSkill(skill)}
                      onMouseDown={(event) => event.preventDefault()}
                      role="option"
                      type="button"
                    >
                      <span>{skill.mention}</span>
                      <small>{skill.source} · Skill</small>
                    </button>
                  ))}
                  {workspaceFiles.isPending && workspaceFileCandidates.length === 0 ? (
                    <span className="muted-copy">{message(locale, "loading")}</span>
                  ) : workspaceFiles.isError ? (
                    <span className="error-state" role="alert">{String(workspaceFiles.error)}</span>
                  ) : workspaceFileCandidates.length === 0 && availableSkillMentions.length === 0 ? (
                    <span className="muted-copy">{message(locale, "noWorkspaceFiles")}</span>
                  ) : workspaceFileCandidates.map((file, index) => (
                    <button
                      aria-selected={index + availableSkillMentions.length === atSelection}
                      className={index + availableSkillMentions.length === atSelection ? "selected" : ""}
                      key={file.path}
                      onClick={() => chooseWorkspaceFile(file.path)}
                      onMouseDown={(event) => event.preventDefault()}
                      role="option"
                      type="button"
                    >
                      <span>@{file.path}</span>
                      <small>{file.kind} · {formatBytes(file.size_bytes)}</small>
                    </button>
                  ))}
                </div>
              )}
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
                    <div className="capability-summary">
                      <span>{message(locale, "advancedDiagnostics")}</span>
                      <strong>{message(locale, "whyThisMode")}</strong>
                      <small>{selectedTransport?.detail ?? message(locale, "fastApiAuthority")}</small>
                      <code>{admittedTransport}</code>
                      {admissionReasons.map((reason) => (
                        <small key={reason}>{reason.replaceAll("_", " ")}</small>
                      ))}
                    </div>
                    <div className="capability-summary">
                      <span>{message(locale, "capability")}</span>
                      <strong>{capabilityCopy.label}</strong>
                      <small>{capabilityCopy.detail}</small>
                    </div>
                    <label>
                      <span>{message(locale, "apiMode")}</span>
                      <select
                        disabled={selectedHarness?.spec.supports_api_mode_selection === false}
                        onChange={(event) => setConfig("apiMode", event.target.value, "default_api_mode")}
                        value={runConfig.apiMode}
                      >
                        <option value="v2">/v2</option>
                        <option value="v1">/v1</option>
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
                  <fieldset className="developer-options">
                    <legend>{message(locale, "developerOptions")}</legend>
                    <label>
                      <input checked={advancedConfig.dryRun} onChange={(event) => setAdvancedConfig((current) => ({ ...current, dryRun: event.target.checked }))} type="checkbox" />
                      <span><strong>{message(locale, "previewExecution")}</strong><small>{message(locale, "previewExecutionHint")}</small></span>
                    </label>
                  </fieldset>
                  <p className="runtime-owned-copy">{message(locale, "streamRuntimeOwned")}</p>
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
                          <button onClick={() => {
                            setPlusMenuOpen(false);
                            setToolPickerOpen(true);
                            setToolSearch("");
                          }} role="menuitem" type="button">
                            <span aria-hidden="true">✦</span>
                            <span><strong>{message(locale, "toolsAndIntegrations")}</strong><small>{message(locale, "toolPickerMenuHint")}</small></span>
                          </button>
                        </div>
                      ) : null}
                    </div>
                    <label className="compact-control">
                      <span>{message(locale, "taskType")}</span>
                      <select
                        aria-label={message(locale, "taskType")}
                        onChange={(event) => selectWorkbenchKind(
                          event.target.value as WorkbenchKind,
                        )}
                        value={productSelection.kind}
                      >
                        <option value="coding_agent">{message(locale, "codingAgent")}</option>
                        <option value="direct_chat">{message(locale, "directChat")}</option>
                      </select>
                    </label>
                    <label className="compact-control">
                      <span>{message(locale, "harness")}</span>
                      <select
                        aria-label={message(locale, "harness")}
                        onChange={(event) => setConfig("harnessId", event.target.value, "default_harness_id")}
                        value={runConfig.harnessId}
                      >
                        {selectableHarnesses.map((harness) => (
                          <option
                            disabled={harness.availability?.status === "unavailable"}
                            key={harness.spec.id}
                            value={harness.spec.id}
                          >
                            {harness.spec.title || harness.spec.id}
                          </option>
                        ))}
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
                          <span>{runConfig.model || message(locale, "noDefaultModel")}</span>
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
                      <span>{message(locale, "intent")}</span>
                      <select
                        aria-label={message(locale, "intent")}
                        onChange={(event) => updateProductSelection({
                          intent: event.target.value as ProductExecutionSelection["intent"],
                        })}
                        value={productSelection.intent}
                      >
                        <option value="ask">{message(locale, "ask")}</option>
                        <option value="review">{message(locale, "review")}</option>
                        <option value="change">{message(locale, "change")}</option>
                      </select>
                    </label>
                    <label className="compact-control mode-control">
                      <span>{message(locale, "authority")}</span>
                      <select
                        aria-label={message(locale, "authority")}
                        onChange={(event) => updateProductSelection({
                          authority: event.target.value as ProductExecutionSelection["authority"],
                        })}
                        value={productSelection.authority}
                      >
                        <option value="read_only">{message(locale, "readOnly")}</option>
                        <option value="workspace_write">{message(locale, "workspaceWrite")}</option>
                      </select>
                    </label>
                    <button
                      aria-expanded={advancedOpen}
                      className={advancedConfig.dryRun ? "advanced-button active" : "advanced-button"}
                      onClick={() => setAdvancedOpen((open) => !open)}
                      type="button"
                    >
                      {message(locale, "advanced")}
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
                    onClick={() => cancelRun.mutate({
                      nativeProcessId: selectedNativeProcessId,
                      runId: selectedRunId,
                    })}
                    type="button"
                  >
                    {message(locale, "cancelRun")}
                  </button>
                ) : (
                  <button className="primary-button" disabled={!prompt.trim() || startRun.isPending} type="submit">
                    {message(locale, advancedConfig.dryRun ? "previewExecution" : "runTask")}
                  </button>
                )}
              </div>
              {startRun.isError || uploadFiles.isError || attachWorkspaceFile.isError || removeAttachment.isError || saveRunConfig.isError ? (
                <div className="error-state" role="alert">
                  {String(startRun.error ?? uploadFiles.error ?? attachWorkspaceFile.error ?? removeAttachment.error ?? saveRunConfig.error)}
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
            <div className={selectedTransport?.status === "blocked" || admissionStatus === "blocked" || previewReport?.hard_block ? "readiness-callout blocked" : admissionStatus === "degraded" ? "readiness-callout degraded" : "readiness-callout success"}>
              <strong>{message(locale, selectedTransport?.status === "blocked" || admissionStatus === "blocked" || previewReport?.hard_block ? "blocked" : admissionStatus === "degraded" ? "degraded" : "ready")}</strong>
              <span>{selectedTransport?.detail ?? message(locale, "fastApiAuthority")}</span>
              {selectedTransport?.status === "blocked" && selectedTransport.remediation ? (
                <code>{selectedTransport.remediation}</code>
              ) : null}
            </div>
            <EnvironmentCard
              commitAction={environmentCommitAction}
              pushAction={environmentPushAction}
              pullRequestAction={environmentPullRequestAction}
              environment={environmentView}
              error={environment.isError}
              locale={locale}
              pending={environment.isPending}
            />
            <section className="inspector-section">
              <h3>{message(locale, "executionPlan")}</h3>
              <dl className="plan-fields">
                <div><dt>{message(locale, "taskType")}</dt><dd>{capabilityCopy.label}</dd></div>
                <div><dt>{message(locale, "intent")}</dt><dd>{message(locale, productSelection.intent)}</dd></div>
                <div><dt>{message(locale, "authority")}</dt><dd>{message(locale, productSelection.authority === "read_only" ? "readOnly" : "workspaceWrite")}</dd></div>
                <div><dt>{message(locale, "workspacePolicy")}</dt><dd>{message(locale, "workspacePolicyValue")}</dd></div>
                <div><dt>{message(locale, "route")}</dt><dd>{runConfig.model || "GigaChat"} · /{runConfig.apiMode}</dd></div>
                <div><dt>{message(locale, "harness")}</dt><dd>{runConfig.harnessId}</dd></div>
              </dl>
            </section>
            {selectedRun?.provider_session ? (
              <section className="inspector-section provider-session-card">
                <h3>{message(locale, "providerSession")}</h3>
                <dl className="plan-fields">
                  <div><dt>{message(locale, "structuredLink")}</dt><dd>{shortId(selectedRun.provider_session.link_id ?? "-")}</dd></div>
                  <div><dt>{message(locale, "session")}</dt><dd>{shortId(selectedRun.provider_session.external_session_id ?? "-")}</dd></div>
                  <div><dt>{message(locale, "status")}</dt><dd>{selectedRun.provider_session.recovery_state ?? "active"}</dd></div>
                  <div><dt>{message(locale, "connection")}</dt><dd>{selectedRun.provider_session.protocol ?? "structured"}</dd></div>
                </dl>
              </section>
            ) : null}
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
              {providerHandoffActions.includes("open_provider_ui") ? (
                <button disabled={openInProvider.isPending} onClick={() => openInProvider.mutate()} type="button">
                  {message(locale, "openProviderUi")} <span>↗</span>
                </button>
              ) : null}
              {openInProvider.data ? (
                <div className="provider-handoff-instruction" role="status">
                  <span>{openInProvider.data.handoff.instruction}</span>
                  {openInProvider.data.handoff.command.length > 0 ? <code>{openInProvider.data.handoff.command.join(" ")}</code> : null}
                </div>
              ) : null}
              {openInProvider.isError ? <span className="mutation-error">{openInProvider.error.message}</span> : null}
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

function RetainedToolActivities({
  events,
  locale,
}: {
  events: readonly EventProjection[];
  locale: "en" | "ru";
}) {
  const payloads = useQueries({
    queries: events.map((event) => ({
      queryKey: [...requestKeys.root, "event-payload", event.id],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        fetchCockpit<EventPayloadResponse>(event.payload_url, signal),
      staleTime: Number.POSITIVE_INFINITY,
    })),
  });
  const activities = new Map<string, WorkbenchToolActivity>();
  let plan: readonly WorkbenchPlanItem[] = [];
  payloads.forEach((payload, index) => {
    if (!payload.isSuccess || payload.data.hidden) return;
    const projection = projectToolPayload(payload.data.payload, events[index]?.id ?? `event-${index}`);
    if (projection.plan.length > 0) {
      plan = projection.plan;
    } else if (projection.activity !== null) {
      activities.set(projection.activity.id, projection.activity);
    }
  });
  const nestedActivities = nestWorkbenchToolActivities([...activities.values()]);
  return (
    <>
      {plan.length > 0 ? <PlanCard items={plan} locale={locale} /> : null}
      {nestedActivities.map((activity) => (
        <ToolActivityCard activity={activity} key={activity.id} locale={locale} />
      ))}
    </>
  );
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
    <article
      className={[
        "tool-activity-card",
        failed ? "failed" : "",
        activity.children?.length ? "has-children" : "",
      ].filter(Boolean).join(" ")}
    >
      <div className="tool-activity-heading">
        <span aria-hidden="true">{complete ? "✓" : failed ? "!" : "◇"}</span>
        <div>
          <strong>{activity.label}</strong>
          {activity.detail ? <span className="tool-activity-detail">{activity.detail}</span> : null}
          <small>{message(locale, "toolActivity")} · {activity.status}</small>
        </div>
      </div>
      {result === null ? null : (
        <details>
          <summary>{message(locale, "toolResult")}</summary>
          <pre>{result}</pre>
        </details>
      )}
      {activity.children?.length ? (
        <div className="nested-tool-activities" aria-label={message(locale, "toolActivity")}>
          {activity.children.map((child) => (
            <ToolActivityCard activity={child} key={child.id} locale={locale} />
          ))}
        </div>
      ) : null}
    </article>
  );
}

function MessageActions({
  canEdit,
  locale,
  messageId,
  mutation,
  role,
}: {
  canEdit: boolean;
  locale: "en" | "ru";
  messageId: string;
  mutation: UseMutationResult<ResolvedMessageAction, Error, MessageAction>;
  role: "assistant" | "user";
}) {
  return (
    <span className="message-actions">
      <MessageActionButton
        action="copy"
        locale={locale}
        messageId={messageId}
        mutation={mutation}
        role={role}
      />
      {canEdit ? (
        <MessageActionButton
          action="edit"
          locale={locale}
          messageId={messageId}
          mutation={mutation}
          role={role}
        />
      ) : null}
    </span>
  );
}

function MessageActionButton({
  action,
  locale,
  messageId,
  mutation,
  role,
}: {
  action: MessageActionKind;
  locale: "en" | "ru";
  messageId: string;
  mutation: UseMutationResult<ResolvedMessageAction, Error, MessageAction>;
  role: "assistant" | "user";
}) {
  const active = mutation.isPending
    && mutation.variables?.messageId === messageId
    && mutation.variables.kind === action;
  const succeeded = mutation.isSuccess
    && mutation.variables?.messageId === messageId
    && mutation.data.kind === action;
  const label = message(
    locale,
    action === "copy"
      ? role === "user" ? "copyUserMessage" : "copyAssistantMessage"
      : "editUserMessage",
  );
  return (
    <button
      aria-label={label}
      className={`message-action${succeeded ? " success" : ""}`}
      disabled={mutation.isPending}
      onClick={() => mutation.mutate({ kind: action, messageId, role })}
      title={label}
      type="button"
    >
      {active ? <span aria-hidden="true">…</span> : succeeded ? (
        <span aria-hidden="true">✓</span>
      ) : action === "copy" ? <CopyIcon /> : <EditIcon />}
    </button>
  );
}

function CopyIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <rect x="8" y="8" width="11" height="11" rx="2" />
      <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m4 20 4.2-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20Z" />
      <path d="m13.8 7.4 2.8 2.8" />
    </svg>
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

function AttachmentGallery({
  attachments,
  locale,
  onRemove,
  removePending = false,
}: {
  attachments: readonly AttachmentSummary[];
  locale: "en" | "ru";
  onRemove?: (attachmentId: string) => void;
  removePending?: boolean;
}) {
  const [activeAttachment, setActiveAttachment] = useState<AttachmentSummary | null>(null);

  useEffect(() => {
    if (activeAttachment === null) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActiveAttachment(null);
    };
    globalThis.addEventListener("keydown", closeOnEscape);
    return () => globalThis.removeEventListener("keydown", closeOnEscape);
  }, [activeAttachment]);

  return (
    <>
      <div className="attachment-gallery" aria-label={message(locale, "attachedFiles")}>
        {attachments.map((attachment) => (
          <div
            className={isPreviewableImage(attachment) ? "attachment-preview-card" : "attachment-file-card"}
            key={attachment.id}
          >
            {isPreviewableImage(attachment) ? (
              <button
                aria-label={`${message(locale, "openAttachment")} ${attachment.filename}`}
                className="attachment-preview-button"
                onClick={() => setActiveAttachment(attachment)}
                type="button"
              >
                <img alt="" src={attachment.url} />
                <span>
                  <strong>{attachment.filename}</strong>
                  <small>{formatBytes(attachment.size_bytes)}</small>
                </span>
              </button>
            ) : (
              <span className="attachment-file-copy">
                <span aria-hidden="true">◇</span>
                <span title={attachment.workspace_path ?? attachment.filename}>
                  <strong>
                    {attachment.workspace_path ? `@${attachment.workspace_path}` : attachment.filename}
                  </strong>
                  <small>{formatBytes(attachment.size_bytes)}</small>
                </span>
              </span>
            )}
            {onRemove === undefined ? null : (
              <button
                aria-label={`${message(locale, "removeAttachment")} ${attachment.filename}`}
                className="attachment-remove"
                disabled={removePending}
                onClick={() => onRemove(attachment.id)}
                type="button"
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>
      {activeAttachment !== null && isPreviewableImage(activeAttachment)
        ? createPortal(
            <div
              aria-label={`${message(locale, "attachmentPreview")}: ${activeAttachment.filename}`}
              aria-modal="true"
              className="attachment-lightbox"
              onClick={() => setActiveAttachment(null)}
              role="dialog"
            >
              <div className="attachment-lightbox-content" onClick={(event) => event.stopPropagation()}>
                <header>
                  <span>
                    <strong>{activeAttachment.filename}</strong>
                    <small>{formatBytes(activeAttachment.size_bytes)}</small>
                  </span>
                  <button
                    aria-label={message(locale, "closeAttachmentPreview")}
                    onClick={() => setActiveAttachment(null)}
                    type="button"
                  >
                    ×
                  </button>
                </header>
                <img alt={activeAttachment.filename} src={activeAttachment.url} />
                <a href={activeAttachment.url} rel="noreferrer" target="_blank">
                  {message(locale, "openOriginal")} ↗
                </a>
              </div>
            </div>,
            globalThis.document.body,
          )
        : null}
    </>
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

function GeneratedFilePreview({
  eventId,
  locale,
  payloadUrl,
}: {
  eventId: string;
  locale: "en" | "ru";
  payloadUrl: string;
}) {
  const payload = useQuery({
    queryKey: [...requestKeys.root, "event-payload", eventId],
    queryFn: ({ signal }) => fetchCockpit<EventPayloadResponse>(payloadUrl, signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (payload.isPending) return <div className="generated-image-skeleton skeleton-row" />;
  if (payload.isError || payload.data.hidden) return null;
  return <GeneratedFileCard locale={locale} payload={payload.data.payload} />;
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
  return models.find((model) => model !== "GigaChat") ?? models[0] ?? "";
}

function isReasoningModel(model: string): boolean {
  return model === reasoningModel || model.startsWith(`${reasoningModel}:`);
}

function GeneratedFileCard({
  locale,
  payload,
}: {
  locale: "en" | "ru";
  payload?: Readonly<Record<string, unknown>>;
}) {
  const [htmlPreviewOpen, setHtmlPreviewOpen] = useState(false);
  const file = generatedFileProjection(payload);
  if (file === null) return null;
  const size = file.sizeBytes === null ? null : formatBytes(file.sizeBytes);
  const downloadLabel = `${message(locale, "downloadFile")} ${file.filename}`;
  const htmlPreviewLabel = message(
    locale,
    htmlPreviewOpen ? "closeHtmlPreview" : "openHtmlPreview",
  );
  return (
    <article className={`message-entry assistant generated-file-message${file.isImage ? " image" : ""}`}>
      <header className="message-entry-header">
        <span className="message-role">
          assistant · {message(locale, file.isImage ? "generatedImage" : "generatedFile")}
        </span>
      </header>
      {file.isImage && file.previewUrl !== null ? (
        <figure>
          <a className="generated-file-preview" href={file.previewUrl} rel="noreferrer" target="_blank">
            <img alt={file.filename} loading="lazy" src={file.previewUrl} />
          </a>
          <figcaption>
            <span>{file.filename}{size === null ? "" : ` · ${size}`}</span>
            <DownloadFileLink
              downloadUrl={file.downloadUrl}
              filename={file.filename}
              label={downloadLabel}
            />
          </figcaption>
        </figure>
      ) : (
        <div className={`generated-document${file.htmlPreviewUrl === null ? "" : " html"}`}>
          <div className="generated-document-row">
            <span aria-hidden="true" className="generated-document-icon">◇</span>
            <span>
              <strong>{file.filename}</strong>
              <small>{file.mimeType}{size === null ? "" : ` · ${size}`}</small>
            </span>
            {file.htmlPreviewUrl === null ? null : (
              <button
                aria-expanded={htmlPreviewOpen}
                aria-label={htmlPreviewLabel}
                className="generated-file-preview-toggle"
                onClick={() => setHtmlPreviewOpen((open) => !open)}
                title={htmlPreviewLabel}
                type="button"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24">
                  <path d="M2.8 12s3.3-6 9.2-6 9.2 6 9.2 6-3.3 6-9.2 6-9.2-6-9.2-6Z" />
                  <circle cx="12" cy="12" r="2.6" />
                </svg>
              </button>
            )}
            <DownloadFileLink
              downloadUrl={file.downloadUrl}
              filename={file.filename}
              label={downloadLabel}
            />
          </div>
          {file.htmlPreviewUrl !== null && htmlPreviewOpen ? (
            <iframe
              className="generated-html-preview"
              referrerPolicy="no-referrer"
              sandbox="allow-same-origin allow-scripts"
              src={file.htmlPreviewUrl}
              title={`${message(locale, "generatedFile")}: ${file.filename}`}
            />
          ) : null}
        </div>
      )}
    </article>
  );
}

function DownloadFileLink({
  downloadUrl,
  filename,
  label,
}: {
  downloadUrl: string;
  filename: string;
  label: string;
}) {
  return (
    <a
      aria-label={label}
      className="generated-file-download"
      download={filename}
      href={downloadUrl}
      title={label}
    >
      <svg aria-hidden="true" viewBox="0 0 24 24">
        <path d="M12 3v12" />
        <path d="m7 10 5 5 5-5" />
        <path d="M5 20h14" />
      </svg>
    </a>
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
