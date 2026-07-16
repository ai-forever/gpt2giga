import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { mutateCockpit, type ApprovalRequest, type TextProjection } from "../api";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import {
  requestKeys,
  runCenterSummaryOptions,
  runOverviewOptions,
  runProjectionOptions,
  runsCenterOptions,
  runTraceOptions,
} from "../request-graph";
import {
  formatDuration,
  formatTimestamp,
  pendingApproval,
  shortId,
  statusTone,
} from "../surface-model";
import { useRunEventStream } from "../stream-store";

type RunTab = "timeline" | "evidence" | "review" | "reuse";

interface DiffProjection {
  patch: TextProjection;
  changed_files: string[];
  can_apply: boolean;
  can_discard: boolean;
}

interface PromotionPreview {
  kind: string;
  target_id: string;
  content: string;
  source_hash: string;
  review_token: string;
  relative_path: string;
  redacted_diff: string;
}

export function RunsSurface() {
  const params = useParams({ strict: false });
  const routeRunId =
    "runId" in params && typeof params.runId === "string" ? params.runId : undefined;
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<RunTab>("timeline");
  const [branchName, setBranchName] = useState("");
  const [promotionKind, setPromotionKind] = useState("workflow");
  const [targetId, setTargetId] = useState("");
  const [promotion, setPromotion] = useState<PromotionPreview | null>(null);
  const [streamReset, setStreamReset] = useState(0);

  const runs = useQuery(runsCenterOptions());
  const selectedRunId = routeRunId ?? runs.data?.runs[0]?.run_id;
  const selectedListItem =
    runs.data?.runs.find((item) => item.run_id === selectedRunId) ?? null;
  const summary = useQuery({
    ...runCenterSummaryOptions(selectedRunId ?? "pending"),
    enabled: selectedRunId !== undefined,
  });
  const cockpitOverview = useQuery({
    ...runOverviewOptions(selectedRunId ?? "pending"),
    enabled: selectedRunId !== undefined,
  });
  const trace = useQuery({
    ...runTraceOptions(selectedRunId ?? "pending"),
    enabled: selectedRunId !== undefined && tab === "timeline",
  });
  const diff = useQuery({
    ...runProjectionOptions(selectedRunId ?? "pending", "diff"),
    enabled: selectedRunId !== undefined && tab === "review",
  });
  const report = useQuery({
    ...runProjectionOptions(selectedRunId ?? "pending", "report"),
    enabled: selectedRunId !== undefined && tab === "evidence",
  });
  const stream = useRunEventStream(selectedRunId, streamReset);
  const selected = summary.data?.run ?? selectedListItem;
  const currentApproval = pendingApproval(selected);

  const visibleRuns = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase(locale);
    const items = runs.data?.runs ?? [];
    if (!needle) return items;
    return items.filter((item) =>
      `${item.run_id} ${item.session_title}`.toLocaleLowerCase(locale).includes(needle),
    );
  }, [locale, runs.data?.runs, search]);

  const refreshSelected = async () => {
    if (selectedRunId === undefined) return;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
      queryClient.invalidateQueries({ queryKey: requestKeys.runScope(selectedRunId) }),
      queryClient.invalidateQueries({ queryKey: requestKeys.approvals() }),
    ]);
  };

  const approvalDecision = useMutation({
    mutationFn: ({ approval, decision }: { approval: ApprovalRequest; decision: string }) =>
      mutateCockpit(`/api/approvals/${encodeURIComponent(approval.id)}/decision`, {
        decision,
      }),
    onSuccess: refreshSelected,
  });
  const applyPatch = useMutation({
    mutationFn: () => {
      if (selectedRunId === undefined) throw new Error("Run is not selected");
      return mutateCockpit<Record<string, unknown>>(
        `/api/runs/${encodeURIComponent(selectedRunId)}/apply`,
        { branch_name: branchName.trim() || null },
      );
    },
    onSuccess: async (response) => {
      if (response.approval_required) openInbox("approvals");
      await refreshSelected();
    },
  });
  const previewPromotion = useMutation({
    mutationFn: () => {
      if (selectedRunId === undefined) throw new Error("Run is not selected");
      return mutateCockpit<{ promotion: PromotionPreview }>(
        `/api/runs/${encodeURIComponent(selectedRunId)}/promotions/preview`,
        { kind: promotionKind, target_id: targetId.trim() },
      );
    },
    onSuccess: ({ promotion: next }) => setPromotion(next),
  });
  const applyPromotion = useMutation({
    mutationFn: () => {
      if (selectedRunId === undefined || promotion === null) {
        throw new Error("Reviewed promotion is unavailable");
      }
      return mutateCockpit(`/api/runs/${encodeURIComponent(selectedRunId)}/promotions/apply`, {
        content: promotion.content,
        kind: promotion.kind,
        review_token: promotion.review_token,
        source_hash: promotion.source_hash,
        target_id: promotion.target_id,
      });
    },
    onSuccess: async () => {
      setPromotion(null);
      await refreshSelected();
    },
  });

  return (
    <div className="runs-layout">
      <aside className="runs-list-pane">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">{message(locale, "runsEyebrow")}</span>
            <h1>{message(locale, "runs")}</h1>
          </div>
          <span className="record-count">{visibleRuns.length}</span>
        </div>
        <label className="search-control">
          <span className="sr-only">{message(locale, "searchRuns")}</span>
          <span aria-hidden="true">⌕</span>
          <input
            onChange={(event) => setSearch(event.target.value)}
            placeholder={message(locale, "searchRuns")}
            type="search"
            value={search}
          />
        </label>
        <div className="filter-row" aria-label={message(locale, "runFilters")}>
          <button type="button">{message(locale, "status")}</button>
          <button type="button">{message(locale, "workflow")}</button>
          <button type="button">{message(locale, "harness")}</button>
          <button type="button">{message(locale, "owner")}</button>
        </div>
        <nav className="runs-list" aria-label={message(locale, "runs")}>
          {runs.isPending ? <ListSkeleton rows={7} /> : null}
          {runs.isError ? <ReadError locale={locale} /> : null}
          {runs.isSuccess && visibleRuns.length === 0 ? (
            <div className="empty-state">{message(locale, "emptyRuns")}</div>
          ) : null}
          {visibleRuns.map((item) => (
            <Link
              className={item.run_id === selectedRunId ? "run-row selected" : "run-row"}
              key={item.run_id}
              params={{ runId: item.run_id }}
              to="/cockpit-v2/runs/$runId"
            >
              <span className={`run-status-dot ${statusTone(item.status_group)}`} aria-hidden="true" />
              <div>
                <strong>{item.session_title}</strong>
                <span className="mono">{shortId(item.run_id)}</span>
                <span className={`status-copy ${statusTone(item.status_group)}`}>{item.status_group}</span>
              </div>
              <div className="run-row-meta">
                <span>{item.worker_id ?? message(locale, "unowned")}</span>
                <span>{item.run?.harness_id ?? "—"}</span>
                <span>{formatDuration(item.duration_ms)}</span>
              </div>
            </Link>
          ))}
        </nav>
      </aside>

      <main className="run-detail-pane">
        {selectedRunId === undefined ? (
          <div className="empty-work-canvas"><h1>{message(locale, "runs")}</h1><p>{message(locale, "selectRun")}</p></div>
        ) : summary.isPending ? (
          <ListSkeleton rows={7} />
        ) : summary.isError ? (
          <ReadError locale={locale} />
        ) : selected === null || selected === undefined ? null : (
          <>
            <header className="run-detail-header">
              <div>
                <div className="title-line">
                  <h1>{selected.session_title}</h1>
                  <code>{shortId(selected.run_id)}</code>
                  <span className={`status-label ${statusTone(selected.status_group)}`}>{selected.status_group}</span>
                </div>
                <span>{selected.run?.harness_id ?? message(locale, "harness")} · {selected.run?.model ?? message(locale, "defaultRoute")}</span>
              </div>
              <Link params={{ sessionId: selected.session_id }} to="/cockpit-v2/work/$sessionId">
                {message(locale, "workbench")} ↗
              </Link>
            </header>
            <dl className="ownership-strip">
              <OwnershipField label={message(locale, "session")} value={shortId(selected.session_id)} />
              <OwnershipField label={message(locale, "job")} value={shortId(selected.ownership.job_id)} />
              <OwnershipField label={message(locale, "attempt")} value={selected.ownership.attempt_number?.toString() ?? "—"} />
              <OwnershipField label={message(locale, "worker")} value={selected.ownership.worker_id ?? "—"} />
              <OwnershipField label={message(locale, "worktree")} value={selected.artifact_inventory.some((item) => item.type === "worktree") ? message(locale, "present") : message(locale, "missing")} />
            </dl>
            <div className="run-tabs" role="tablist">
              {(["timeline", "evidence", "review", "reuse"] as const).map((item) => (
                <button
                  aria-selected={tab === item}
                  className={tab === item ? "active" : ""}
                  key={item}
                  onClick={() => setTab(item)}
                  role="tab"
                  type="button"
                >
                  {message(locale, item)}
                </button>
              ))}
            </div>
            <div className="run-content-grid">
              <section className="run-tab-panel" role="tabpanel">
                {tab === "timeline" ? (
                  <TimelinePanel
                    locale={locale}
                    streamEvents={stream.events}
                    trace={trace.data?.nodes ?? []}
                  />
                ) : null}
                {tab === "evidence" ? (
                  <EvidencePanel
                    artifacts={cockpitOverview.data?.run.artifacts ?? []}
                    loading={cockpitOverview.isPending || report.isPending}
                    locale={locale}
                    report={report.data}
                  />
                ) : null}
                {tab === "review" ? (
                  <ReviewPanel
                    approval={currentApproval}
                    approvalPending={approvalDecision.isPending}
                    applyPending={applyPatch.isPending}
                    branchName={branchName}
                    diff={diff.data as DiffProjection | undefined}
                    locale={locale}
                    onApply={() => applyPatch.mutate()}
                    onBranchName={setBranchName}
                    onDecision={(decision) => {
                      if (currentApproval !== null) {
                        approvalDecision.mutate({ approval: currentApproval, decision });
                      }
                    }}
                  />
                ) : null}
                {tab === "reuse" ? (
                  <ReusePanel
                    applyPending={applyPromotion.isPending}
                    kind={promotionKind}
                    locale={locale}
                    onApply={() => applyPromotion.mutate()}
                    onKind={setPromotionKind}
                    onPreview={() => previewPromotion.mutate()}
                    onTargetId={setTargetId}
                    preview={promotion}
                    previewPending={previewPromotion.isPending}
                    targetId={targetId}
                  />
                ) : null}
              </section>
              <aside className="run-context-panel">
                {currentApproval === null ? (
                  <div className="context-callout">
                    <strong>{message(locale, "readiness")}</strong>
                    <span>{selected.explanations.find((item) => item.key === "policy")?.summary ?? message(locale, "ready")}</span>
                  </div>
                ) : (
                  <div className="context-callout warning">
                    <strong>{message(locale, "approvalRequired")}</strong>
                    <span>{currentApproval.action}</span>
                    <button onClick={() => openInbox("approvals")} type="button">{message(locale, "reviewApproval")}</button>
                  </div>
                )}
                <h3>{message(locale, "operationalTruth")}</h3>
                {selected.explanations.map((item) => (
                  <article className="explanation-row" key={item.key}>
                    <span className={`status-label ${statusTone(item.status)}`}>{item.status}</span>
                    <strong>{item.title}</strong>
                    <p>{item.summary}</p>
                  </article>
                ))}
                <div className={`stream-card ${stream.status}`}>
                  <strong>{stream.status.replaceAll("_", " ")}</strong>
                  <span>{stream.events.length} {message(locale, "boundedLiveEvents")}</span>
                  {stream.status === "resnapshot_required" ? (
                    <button onClick={() => setStreamReset((value) => value + 1)} type="button">
                      {message(locale, "resyncCursor")}
                    </button>
                  ) : null}
                </div>
              </aside>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function TimelinePanel({
  locale,
  streamEvents,
  trace,
}: {
  locale: "en" | "ru";
  streamEvents: ReturnType<typeof useRunEventStream>["events"];
  trace: Array<{ id: string; event_id?: string; title: string; kind: string; status?: string | null; created_at: string; duration_ms?: number | null }>;
}) {
  const liveIds = new Set(streamEvents.map((item) => item.id));
  const retained = trace.filter((item) => item.event_id === undefined || !liveIds.has(item.event_id));
  const rows = [
    ...retained.map((item) => ({
      created_at: item.created_at,
      duration: formatDuration(item.duration_ms ?? null),
      id: item.id,
      kind: item.kind,
      status: item.status ?? "retained",
      title: item.title,
    })),
    ...streamEvents.map((item) => ({
      created_at: item.created_at ?? "",
      duration: "live",
      id: item.id,
      kind: item.type,
      status: "live",
      title: item.message ?? item.type.replaceAll("_", " "),
    })),
  ].slice(-200);
  if (rows.length === 0) return <div className="empty-state">{message(locale, "noEvents")}</div>;
  return (
    <div className="timeline-list">
      {rows.map((item) => (
        <article className="timeline-row" key={item.id}>
          <span className={`timeline-dot ${statusTone(item.status)}`} aria-hidden="true" />
          <div><strong>{item.title}</strong><span>{item.kind}</span></div>
          <time>{formatTimestamp(item.created_at, locale)}</time>
          <span>{item.duration}</span>
          <button type="button">{message(locale, "inspect")}</button>
        </article>
      ))}
    </div>
  );
}

function EvidencePanel({
  artifacts,
  loading,
  locale,
  report,
}: {
  artifacts: Array<{ type: string; byte_count?: number | null }>;
  loading: boolean;
  locale: "en" | "ru";
  report: Record<string, unknown> | undefined;
}) {
  if (loading) return <ListSkeleton rows={4} />;
  return (
    <div className="evidence-panel">
      {artifacts.length === 0 ? <div className="empty-state">{message(locale, "noRetainedArtifacts")}</div> : null}
      {artifacts.map((artifact) => (
        <article className="artifact-row" key={artifact.type}>
          <strong>{artifact.type}</strong>
          <span>{artifact.byte_count === null || artifact.byte_count === undefined ? message(locale, "available") : `${artifact.byte_count.toLocaleString()} ${message(locale, "bytes")}`}</span>
        </article>
      ))}
      {report === undefined ? null : <pre className="retained-preview">{projectedText(report.report)}</pre>}
    </div>
  );
}

function ReviewPanel({
  approval,
  approvalPending,
  applyPending,
  branchName,
  diff,
  locale,
  onApply,
  onBranchName,
  onDecision,
}: {
  approval: ApprovalRequest | null;
  approvalPending: boolean;
  applyPending: boolean;
  branchName: string;
  diff: DiffProjection | undefined;
  locale: "en" | "ru";
  onApply: () => void;
  onBranchName: (value: string) => void;
  onDecision: (decision: string) => void;
}) {
  return (
    <div className="review-panel">
      {diff === undefined ? <ListSkeleton rows={4} /> : (
        <>
          <div className="review-summary">
            <strong>{message(locale, "reviewDiff")}</strong>
            <span>{diff.changed_files.length} {message(locale, "changedFiles")} · {diff.patch.byte_count.toLocaleString()} {message(locale, "bytes")}</span>
          </div>
          <pre className="diff-preview">{diff.patch.text || message(locale, "noPatchContent")}</pre>
        </>
      )}
      {approval === null ? null : (
        <section className="approval-block">
          <h3>{message(locale, "approvalBinding")}</h3>
          <dl className="compact-fields">
            <div><dt>{message(locale, "action")}</dt><dd>{approval.action}</dd></div>
            <div><dt>{message(locale, "owner")}</dt><dd>{approval.enforcement_owner}</dd></div>
            <div><dt>{message(locale, "policy")}</dt><dd>{approval.policy_source}</dd></div>
          </dl>
          <div className="decision-actions">
            <button className="danger-button" disabled={approvalPending} onClick={() => onDecision("deny")} type="button">{message(locale, "deny")}</button>
            <button className="primary-button" disabled={approvalPending} onClick={() => onDecision("allow_once")} type="button">{message(locale, "approveOnce")}</button>
          </div>
        </section>
      )}
      <label className="field-control">
        <span>{message(locale, "branchNameOptional")}</span>
        <input onChange={(event) => onBranchName(event.target.value)} value={branchName} />
      </label>
      <button className="primary-button" disabled={applyPending || diff === undefined || !diff.can_apply} onClick={onApply} type="button">
        {message(locale, "applyReviewedPatch")}
      </button>
    </div>
  );
}

function ReusePanel({
  applyPending,
  kind,
  locale,
  onApply,
  onKind,
  onPreview,
  onTargetId,
  preview,
  previewPending,
  targetId,
}: {
  applyPending: boolean;
  kind: string;
  locale: "en" | "ru";
  onApply: () => void;
  onKind: (value: string) => void;
  onPreview: () => void;
  onTargetId: (value: string) => void;
  preview: PromotionPreview | null;
  previewPending: boolean;
  targetId: string;
}) {
  return (
    <div className="reuse-panel">
      <p>{message(locale, "promotionSeparation")}</p>
      <div className="reuse-form">
        <label className="field-control"><span>{message(locale, "promotionKind")}</span><select onChange={(event) => onKind(event.target.value)} value={kind}><option value="workflow">workflow</option><option value="agent">agent</option><option value="eval">eval</option></select></label>
        <label className="field-control"><span>{message(locale, "targetId")}</span><input onChange={(event) => onTargetId(event.target.value)} value={targetId} /></label>
        <button disabled={previewPending || !targetId.trim()} onClick={onPreview} type="button">{message(locale, "previewPromotion")}</button>
      </div>
      {preview === null ? null : (
        <section className="promotion-review">
          <strong>{preview.relative_path}</strong>
          <pre>{preview.redacted_diff}</pre>
          <button className="primary-button" disabled={applyPending} onClick={onApply} type="button">{message(locale, "applyPromotion")}</button>
        </section>
      )}
    </div>
  );
}

function OwnershipField({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function ListSkeleton({ rows }: { rows: number }) {
  return <>{Array.from({ length: rows }, (_, index) => <div className="skeleton-row" key={index} />)}</>;
}

function ReadError({ locale }: { locale: "en" | "ru" }) {
  return <div className="error-state" role="alert">{message(locale, "boundedDataUnavailable")}</div>;
}

function projectedText(value: unknown): string {
  if (value !== null && typeof value === "object" && "text" in value) {
    return String((value as { text?: unknown }).text ?? "");
  }
  return JSON.stringify(value ?? {}, null, 2);
}

function openInbox(kind: "approvals" | "attention") {
  globalThis.dispatchEvent(new CustomEvent("cockpit:open-inbox", { detail: kind }));
}
