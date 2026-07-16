import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  ArenaChildProjection,
  ArenaProjectionResponse,
  ArenaVerdict,
  HarnessOption,
  WorkspaceFileCandidate,
} from "../api";
import { mutateCockpit } from "../api";
import {
  arenaElapsedMs,
  arenaClosedStreamStatus,
  arenaSelectionError,
  arenaStatusFromChildren,
  arenaTerminalStatus,
  arenaTokenUsage,
  projectArenaStream,
  reconcileArenaTerminalEvent,
} from "../arena-model";
import { MessageMarkdown } from "../message-markdown";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import {
  harnessesOptions,
  requestKeys,
} from "../request-graph";
import {
  arenaDetailOptions,
  arenaWorkspaceFilesOptions,
  evaluationSurfaceOptions,
  remainingRequestKeys,
} from "../remaining-request-graph";
import { useRunEventStream } from "../stream-store";
import { activeAtQuery, consumeAtQuery } from "../workbench-execution";

const activeStatuses = new Set(["queued", "running", "retry_wait"]);
const verdicts: readonly ArenaVerdict[] = [
  "a_better",
  "b_better",
  "tie",
  "both_failed",
];

export function ArenaWorkspace({ selectedId }: { selectedId: string | undefined }) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const history = useQuery(evaluationSurfaceOptions());
  const harnesses = useQuery(harnessesOptions());
  const detail = useQuery({
    ...arenaDetailOptions(selectedId ?? "pending"),
    enabled: selectedId !== undefined,
  });
  const [selectedHarnesses, setSelectedHarnesses] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [caret, setCaret] = useState(0);
  const [selectedFiles, setSelectedFiles] = useState<WorkspaceFileCandidate[]>([]);
  const [fileSelection, setFileSelection] = useState(0);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const atQuery = activeAtQuery(prompt, caret);
  const deferredFileQuery = useDeferredValue(atQuery?.query ?? "");
  const files = useQuery({
    ...arenaWorkspaceFilesOptions(deferredFileQuery),
    enabled: atQuery !== null,
  });

  useEffect(() => {
    if (selectedHarnesses.length > 0 || harnesses.data === undefined) return;
    setSelectedHarnesses(
      harnesses.data.harnesses
        .filter((item) => item.availability?.status !== "unavailable")
        .slice(0, 2)
        .map((item) => item.spec.id),
    );
  }, [harnesses.data, selectedHarnesses.length]);

  const create = useMutation({
    mutationFn: () =>
      mutateCockpit<ArenaProjectionResponse>("/api/arena/runs", {
        api_mode: "v2",
        harness_ids: selectedHarnesses,
        mode: "plan",
        prompt: prompt.trim(),
        workspace: ".",
        workspace_paths: selectedFiles.map((item) => item.path),
      }),
    onSuccess: async (response) => {
      const { arena } = response;
      setPrompt("");
      setSelectedFiles([]);
      queryClient.setQueryData(remainingRequestKeys.arena(arena.id), response);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: remainingRequestKeys.evaluation() }),
        queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
      ]);
      await navigate({
        search: { selected: arena.id },
        to: "/cockpit-v2/evaluation/arena",
      });
    },
  });
  const followUp = useMutation({
    mutationFn: () => {
      if (selectedId === undefined) throw new Error("Select an arena first");
      return mutateCockpit<ArenaProjectionResponse>(
        `/api/arena/runs/${encodeURIComponent(selectedId)}/turns`,
        {
          prompt: prompt.trim(),
          workspace_paths: selectedFiles.map((item) => item.path),
        },
      );
    },
    onSuccess: async ({ arena }) => {
      setPrompt("");
      setSelectedFiles([]);
      queryClient.setQueryData(remainingRequestKeys.arena(arena.id), { arena });
      await queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() });
    },
  });

  const selectionError = arenaSelectionError(
    selectedHarnesses,
    harnesses.data?.harnesses ?? [],
    selectedFiles.length > 0,
  );
  const canSubmit = prompt.trim().length > 0 && (
    selectedId === undefined ? selectionError === null : true
  );
  const submit = () => {
    if (!canSubmit) return;
    if (selectedId === undefined) create.mutate();
    else followUp.mutate();
  };
  const chooseFile = (file: WorkspaceFileCandidate) => {
    setSelectedFiles((current) =>
      current.some((item) => item.path === file.path) ? current : [...current, file],
    );
    if (atQuery !== null) setPrompt((current) => consumeAtQuery(current, atQuery));
    setFileSelection(0);
    requestAnimationFrame(() => composerRef.current?.focus());
  };

  return (
    <div className="arena-workspace">
      <header className="arena-header">
        <div>
          <span className="section-kicker">{message(locale, "arenaWorkspace")}</span>
          <h1>{message(locale, "arenaCompareTitle")}</h1>
          <p>{message(locale, "arenaCompareDescription")}</p>
        </div>
        {selectedId === undefined ? null : (
          <button
            className="primary-button"
            onClick={() => {
              void navigate({ search: {}, to: "/cockpit-v2/evaluation/arena" });
            }}
            type="button"
          >
            {message(locale, "newArena")}
          </button>
        )}
      </header>
      <nav className="arena-history" aria-label={message(locale, "previousArenas")}>
        <span>{message(locale, "previousArenas")}</span>
        {(history.data?.arenas ?? []).slice(0, 12).map((item) => (
          <Link
            aria-current={selectedId === item.id ? "page" : undefined}
            className={selectedId === item.id ? "active" : ""}
            key={item.id}
            search={{ selected: item.id }}
            to="/cockpit-v2/evaluation/arena"
          >
            {item.id.slice(-8)} · {item.harnessCount}
          </Link>
        ))}
      </nav>

      {selectedId === undefined ? (
        <ArenaSetup
          harnesses={harnesses.data?.harnesses ?? []}
          selected={selectedHarnesses}
          onChange={setSelectedHarnesses}
        />
      ) : detail.isPending ? (
        <div className="arena-loading" aria-busy="true">{message(locale, "loading")}</div>
      ) : detail.isError || detail.data === undefined ? (
        <div className="error-state">{message(locale, "boundedDataUnavailable")}</div>
      ) : (
        <ArenaDetail response={detail.data} />
      )}

      <SharedComposer
        atQueryOpen={atQuery !== null}
        canSubmit={canSubmit}
        caret={caret}
        error={
          create.error?.message ?? followUp.error?.message ??
          (selectedId === undefined ? selectionError : null)
        }
        fileSelection={fileSelection}
        files={files.data?.files ?? []}
        pending={create.isPending || followUp.isPending}
        prompt={prompt}
        selectedFiles={selectedFiles}
        textareaRef={composerRef}
        onCaret={setCaret}
        onChooseFile={chooseFile}
        onFileSelection={setFileSelection}
        onPrompt={setPrompt}
        onRemoveFile={(path) =>
          setSelectedFiles((current) => current.filter((item) => item.path !== path))
        }
        onSubmit={submit}
        submitKey={selectedId === undefined ? "startArena" : "sendToAll"}
      />
    </div>
  );
}

function ArenaSetup({
  harnesses,
  selected,
  onChange,
}: {
  harnesses: readonly HarnessOption[];
  selected: readonly string[];
  onChange: (ids: string[]) => void;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  return (
    <section className="arena-setup">
      <div>
        <span className="section-kicker">{message(locale, "selectHarnesses")}</span>
        <h2>{message(locale, "arenaColumns")}</h2>
        <p>{message(locale, "arenaHarnessHint")}</p>
      </div>
      <div className="arena-harness-grid">
        {harnesses.map((item) => {
          const checked = selected.includes(item.spec.id);
          const unavailable = item.availability?.status === "unavailable";
          return (
            <label className={checked ? "selected" : ""} key={item.spec.id}>
              <input
                checked={checked}
                disabled={unavailable || (!checked && selected.length >= 4)}
                onChange={() =>
                  onChange(
                    checked
                      ? selected.filter((id) => id !== item.spec.id)
                      : [...selected, item.spec.id],
                  )
                }
                type="checkbox"
              />
              <strong>{item.spec.title ?? item.spec.id}</strong>
              <span>{item.spec.id}</span>
              <small>{unavailable ? item.availability?.reason : message(locale, "independentChat")}</small>
            </label>
          );
        })}
      </div>
    </section>
  );
}

function ArenaDetail({ response }: { response: ArenaProjectionResponse }) {
  const { arena } = response;
  const queryClient = useQueryClient();
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const [note, setNote] = useState(arena.metadata.verdict_note ?? "");
  const [streamStatuses, setStreamStatuses] = useState<Record<string, string>>({});
  const recordStreamStatus = useCallback((runId: string, status: string) => {
    setStreamStatuses((current) =>
      current[runId] === status ? current : { ...current, [runId]: status },
    );
  }, []);
  const arenaStatus = arenaStatusFromChildren(
    arena.child_runs.map((child) => {
      const run = child.runs?.at(-1) ?? child.run;
      return (run === undefined ? undefined : streamStatuses[run.id]) ?? child.status;
    }),
  );
  const verdict = useMutation({
    mutationFn: (value: ArenaVerdict) =>
      mutateCockpit<ArenaProjectionResponse>(
        `/api/arena/runs/${encodeURIComponent(arena.id)}/verdict`,
        { note, verdict: value },
      ),
    onSuccess: ({ arena: updated }) =>
      queryClient.setQueryData(remainingRequestKeys.arena(updated.id), { arena: updated }),
  });
  return (
    <>
      <div className="arena-identity-strip">
        <strong>{arena.prompt}</strong>
        <span>{arena.child_runs.length} {message(locale, "independentChats")}</span>
        <span>{message(locale, "turns")}: {(arena.metadata.turn_count ?? 0) + 1}</span>
        <span className={`status-label ${arenaStatus === "succeeded" ? "success" : "warning"}`}>{arenaStatus}</span>
      </div>
      <div className="arena-chat-grid" style={{ "--arena-columns": arena.child_runs.length } as React.CSSProperties}>
        {arena.child_runs.map((child) => (
          <ArenaChatColumn
            arenaId={arena.id}
            child={child}
            key={child.index}
            onTerminalStatus={recordStreamStatus}
          />
        ))}
      </div>
      <section className="arena-verdict">
        <div>
          <span className="section-kicker">{message(locale, "comparisonVerdict")}</span>
          <strong>{message(locale, "verdictEvidenceHint")}</strong>
        </div>
        <div className="arena-verdict-actions">
          {verdicts.map((value) => (
            <button
              className={arena.metadata.verdict === value ? "active" : ""}
              disabled={verdict.isPending}
              key={value}
              onClick={() => verdict.mutate(value)}
              type="button"
            >
              {message(locale, value)}
            </button>
          ))}
        </div>
        <input
          aria-label={message(locale, "optionalVerdictNote")}
          maxLength={2000}
          onChange={(event) => setNote(event.target.value)}
          placeholder={message(locale, "optionalVerdictNote")}
          value={note}
        />
      </section>
    </>
  );
}

function ArenaChatColumn({
  arenaId,
  child,
  onTerminalStatus,
}: {
  arenaId: string;
  child: ArenaChildProjection;
  onTerminalStatus: (runId: string, status: string) => void;
}) {
  const queryClient = useQueryClient();
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const run = child.runs?.at(-1) ?? child.run;
  const stream = useRunEventStream(run?.id, 0, true);
  const messages = child.messages ?? [];
  const projected = useMemo(
    () => projectArenaStream(messages, stream.events, run?.id),
    [messages, run?.id, stream.events],
  );
  const elapsed = useElapsed(run);
  const usage = arenaTokenUsage(messages, projected.usage);
  const runId = run?.id;
  const terminalStatus = arenaTerminalStatus(projected.terminalEvent) ??
    arenaClosedStreamStatus(
      stream.status,
      stream.events,
      projected.assistantText.length > 0 || messages.some(
        (item) => item.run_id === runId && item.role === "assistant",
      ),
    );
  const status = terminalStatus ?? child.status;
  useEffect(() => {
    if (runId === undefined || terminalStatus === null) return;
    if (projected.terminalEvent !== null) {
      queryClient.setQueryData<ArenaProjectionResponse>(
        remainingRequestKeys.arena(arenaId),
        (current) => reconcileArenaTerminalEvent(current, child.index, projected.terminalEvent!),
      );
    }
    onTerminalStatus(runId, terminalStatus);
    void queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() });
  }, [arenaId, child.index, onTerminalStatus, projected.terminalEvent, queryClient, runId, terminalStatus]);
  const cancel = useMutation({
    mutationFn: () => {
      if (run === undefined) throw new Error("Run is unavailable");
      return mutateCockpit(`/api/runs/${encodeURIComponent(run.id)}/cancel`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: remainingRequestKeys.arena(arenaId) }),
  });
  const retry = useMutation({
    mutationFn: () =>
      mutateCockpit<ArenaProjectionResponse>(
        `/api/arena/runs/${encodeURIComponent(arenaId)}/children/${child.index}/retry`,
      ),
    onSuccess: ({ arena }) =>
      queryClient.setQueryData(remainingRequestKeys.arena(arena.id), { arena }),
  });
  return (
    <article className="arena-chat-column">
      <header>
        <div><span>{String.fromCharCode(65 + child.index)}</span><div><strong>{child.harness_id}</strong><small>{run?.model ?? message(locale, "defaultRoute")}</small></div></div>
        <span className={`status-label ${status === "succeeded" ? "success" : activeStatuses.has(status) ? "warning" : "danger"}`}>{status}</span>
      </header>
      <div className="arena-chat-metrics">
        <span>{formatElapsed(elapsed)}</span>
        <span>{usage.total_tokens === undefined ? message(locale, "tokensUnavailable") : `${usage.total_tokens} ${message(locale, "tokens")}`}</span>
        <span>{stream.status.replaceAll("_", " ")}</span>
      </div>
      <div className="arena-chat-scroll" role="log" aria-live="polite">
        {messages.map((item) => (
          <div className={`arena-message ${item.role}`} key={item.id}>
            <span>{item.role}</span>
            {item.role === "assistant" ? <MessageMarkdown source={item.content} /> : <p>{item.content}</p>}
          </div>
        ))}
        {projected.toolActivities.map((activity) => (
          <div className="arena-activity" key={activity.id}>
            <span>{activity.status}</span><strong>{activity.label}</strong>
          </div>
        ))}
        {projected.assistantText ? (
          <div className="arena-message assistant streaming">
            <span>{message(locale, "assistant")}</span>
            <MessageMarkdown source={projected.assistantText} />
          </div>
        ) : null}
        {child.error ? <p className="mutation-error" role="alert">{child.error}</p> : null}
      </div>
      <footer>
        <button disabled={run === undefined || !activeStatuses.has(run.status) || cancel.isPending} onClick={() => cancel.mutate()} type="button">{message(locale, "cancel")}</button>
        <button disabled={run === undefined || activeStatuses.has(run.status) || retry.isPending} onClick={() => retry.mutate()} type="button">{message(locale, "retry")}</button>
        {run === undefined ? null : <Link params={{ runId: run.id }} to="/cockpit-v2/runs/$runId">{message(locale, "openRun")}</Link>}
      </footer>
    </article>
  );
}

function SharedComposer({
  atQueryOpen,
  canSubmit,
  caret,
  error,
  fileSelection,
  files,
  pending,
  prompt,
  selectedFiles,
  textareaRef,
  onCaret,
  onChooseFile,
  onFileSelection,
  onPrompt,
  onRemoveFile,
  onSubmit,
  submitKey,
}: {
  atQueryOpen: boolean;
  canSubmit: boolean;
  caret: number;
  error: string | null;
  fileSelection: number;
  files: readonly WorkspaceFileCandidate[];
  pending: boolean;
  prompt: string;
  selectedFiles: readonly WorkspaceFileCandidate[];
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onCaret: (value: number) => void;
  onChooseFile: (file: WorkspaceFileCandidate) => void;
  onFileSelection: (value: number) => void;
  onPrompt: (value: string) => void;
  onRemoveFile: (path: string) => void;
  onSubmit: () => void;
  submitKey: "sendToAll" | "startArena";
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  return (
    <section className="arena-composer">
      <span className="section-kicker">{message(locale, "sharedTask")}</span>
      {selectedFiles.length > 0 ? <div className="arena-file-chips">{selectedFiles.map((file) => <button key={file.path} onClick={() => onRemoveFile(file.path)} type="button">@{file.path} ×</button>)}</div> : null}
      <div className="arena-composer-input">
        <textarea
          aria-label={message(locale, "sharedTask")}
          onChange={(event) => { onPrompt(event.target.value); onCaret(event.target.selectionStart); }}
          onClick={(event) => onCaret(event.currentTarget.selectionStart)}
          onKeyDown={(event) => {
            if (atQueryOpen && files.length > 0 && event.key === "ArrowDown") { event.preventDefault(); onFileSelection((fileSelection + 1) % files.length); }
            else if (atQueryOpen && files.length > 0 && event.key === "ArrowUp") { event.preventDefault(); onFileSelection((fileSelection - 1 + files.length) % files.length); }
            else if (atQueryOpen && files[fileSelection] !== undefined && (event.key === "Enter" || event.key === "Tab")) { event.preventDefault(); onChooseFile(files[fileSelection]!); }
            else if (!event.shiftKey && event.key === "Enter") { event.preventDefault(); onSubmit(); }
          }}
          placeholder={message(locale, "arenaPromptPlaceholder")}
          ref={textareaRef}
          value={prompt}
        />
        <button className="primary-button" disabled={!canSubmit || pending} onClick={onSubmit} type="button">{message(locale, submitKey)}</button>
      </div>
      {atQueryOpen ? <div className="arena-file-picker" role="listbox">{files.map((file, index) => <button aria-selected={index === fileSelection} className={index === fileSelection ? "active" : ""} key={file.path} onClick={() => onChooseFile(file)} role="option" type="button"><strong>{file.path}</strong><span>{file.kind} · {file.size_bytes} B</span></button>)}</div> : null}
      <small>{message(locale, "arenaAtHint")}</small>
      {error ? <p className="mutation-error" role="alert">{error}</p> : null}
      <span className="sr-only">{caret}</span>
    </section>
  );
}

function useElapsed(run: ArenaChildProjection["run"]): number | null {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (run === undefined || !activeStatuses.has(run.status)) return;
    const handle = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(handle);
  }, [run]);
  return arenaElapsedMs(run);
}

function formatElapsed(value: number | null): string {
  if (value === null) return "—";
  if (value < 60_000) return `${(value / 1000).toFixed(1)}s`;
  return `${Math.floor(value / 60_000)}m ${Math.floor((value % 60_000) / 1000)}s`;
}
