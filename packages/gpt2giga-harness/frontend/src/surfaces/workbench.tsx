import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import {
  mutateCockpit,
  type RunStartResponse,
  type SessionSummary,
} from "../api";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import {
  requestKeys,
  sessionIndexOptions,
  sessionMessagesOptions,
  sessionOverviewOptions,
  sessionRunsOptions,
} from "../request-graph";
import {
  activeRun,
  formatTimestamp,
  latestRun,
  runStage,
  sessionGroups,
  shortId,
  type RunStage,
} from "../surface-model";
import { useRunEventStream } from "../stream-store";

const layoutKey = "gpt2giga.cockpit-v2.workbench-layout.v1";

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
  const [startedRun, setStartedRun] = useState<{ sessionId: string; runId: string } | null>(null);

  const index = useQuery(sessionIndexOptions());
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
  const retainedLatestRun = latestRun(runs.data?.runs ?? []);
  const selectedRunId =
    startedRun?.sessionId === sessionId ? startedRun?.runId : retainedLatestRun?.id;
  const stream = useRunEventStream(selectedRunId);

  useEffect(() => {
    localStorage.setItem(
      layoutKey,
      JSON.stringify({ left: leftWidth, right: rightWidth }),
    );
  }, [leftWidth, rightWidth]);

  const createSession = useMutation({
    mutationFn: () =>
      mutateCockpit<{ session: SessionSummary }>("/api/sessions", {
        api_mode: "v2",
        harness_id: "echo",
        mode: "plan",
        title: "New governed session",
      }),
    onSuccess: async ({ session }) => {
      await queryClient.invalidateQueries({ queryKey: requestKeys.sessionIndex() });
      await navigate({
        params: { sessionId: session.id },
        to: "/cockpit-v2/work/$sessionId",
      });
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
          api_mode: session.default_api_mode ?? "v2",
          capability: "chat_completions",
          harness_id: session.default_harness_id ?? "echo",
          invocation_mode: "headless",
          mode: session.default_mode ?? "plan",
          model: session.default_model ?? null,
          permission_profile: "interactive",
          prompt: prompt.trim(),
          stream: true,
          workspace_policy: "auto",
        },
      );
    },
    onSuccess: async ({ run }) => {
      setStartedRun({ runId: run.id, sessionId: run.session_id });
      setPrompt("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: requestKeys.sessionScope(run.session_id) }),
        queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
      ]);
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

  const filteredSessions = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase(locale);
    const items = index.data?.sessions ?? [];
    return needle
      ? items.filter((session) => session.title.toLocaleLowerCase(locale).includes(needle))
      : items;
  }, [index.data?.sessions, locale, search]);

  const layoutStyle = {
    gridTemplateColumns: `${leftOpen ? `${leftWidth}px 8px` : "44px"} minmax(360px, 1fr) ${rightOpen ? `8px ${rightWidth}px` : "44px"}`,
  };
  const stage = runStage(retainedLatestRun);

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
            disabled={createSession.isPending}
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
                {group.sessions.map((session) => (
                  <Link
                    className={session.id === sessionId ? "session-row selected" : "session-row"}
                    key={session.id}
                    params={{ sessionId: session.id }}
                    to="/cockpit-v2/work/$sessionId"
                  >
                    <strong>{session.title}</strong>
                    <span>
                      {session.default_harness_id ?? "echo"} · {session.default_api_mode ?? "v2"}
                    </span>
                    <time>{formatTimestamp(session.updated_at, locale)}</time>
                  </Link>
                ))}
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
                  {overview.data?.session.default_model ?? "GigaChat"} · /{overview.data?.session.default_api_mode ?? "v2"} · {overview.data?.session.default_harness_id ?? "echo"}
                </span>
              </div>
              {selectedRunId === undefined ? null : (
                <Link params={{ runId: selectedRunId }} to="/cockpit-v2/runs/$runId">
                  {message(locale, "openRun")} ↗
                </Link>
              )}
            </header>
            <section className="message-region" aria-label={message(locale, "sessionMessages")}>
              {messages.isPending ? <ListSkeleton rows={4} /> : null}
              {messages.isError ? <ReadError locale={locale} /> : null}
              {messages.data?.messages.length === 0 ? (
                <div className="empty-state">{message(locale, "emptyMessages")}</div>
              ) : null}
              {messages.data?.messages.map((item) => (
                <article className={`message-entry ${item.role}`} key={item.id}>
                  <div>
                    <strong>{item.role}</strong>
                    <time>{formatTimestamp(item.created_at, locale)}</time>
                  </div>
                  <p>{item.content.text}</p>
                  {item.content.truncated ? <span>{message(locale, "boundedPreview")}</span> : null}
                </article>
              ))}
              {stream.events.map((event) => (
                <article className="message-entry event" key={event.id}>
                  <div><strong>{event.type.replaceAll("_", " ")}</strong></div>
                  <p>{event.message ?? String(event.payload?.delta ?? "")}</p>
                </article>
              ))}
            </section>
            <form
              className="composer"
              onSubmit={(event) => {
                event.preventDefault();
                if (prompt.trim() && !startRun.isPending) startRun.mutate();
              }}
            >
              <textarea
                aria-label={message(locale, "composerPlaceholder")}
                disabled={startRun.isPending}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={message(locale, "composerPlaceholder")}
                rows={4}
                value={prompt}
              />
              <div className="composer-footer">
                <span className={`stream-indicator ${stream.status}`}>{stream.status.replaceAll("_", " ")}</span>
                {activeRun(retainedLatestRun) && selectedRunId !== undefined ? (
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
              {startRun.isError ? <div className="error-state" role="alert">{String(startRun.error)}</div> : null}
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
                <div><dt>{message(locale, "mode")}</dt><dd>{overview.data?.session.default_mode ?? "plan"}</dd></div>
                <div><dt>{message(locale, "workspacePolicy")}</dt><dd>{message(locale, "workspacePolicyValue")}</dd></div>
                <div><dt>{message(locale, "route")}</dt><dd>{overview.data?.session.default_model ?? "GigaChat"} · /{overview.data?.session.default_api_mode ?? "v2"}</dd></div>
                <div><dt>{message(locale, "harness")}</dt><dd>{overview.data?.session.default_harness_id ?? "echo"}</dd></div>
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
