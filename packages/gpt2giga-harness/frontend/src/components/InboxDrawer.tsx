import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { mutateCockpit } from "../api";
import {
  approvalDecisionPayload,
  decisionLabelKey,
  enabledApprovalOptions,
} from "../approval-ux";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import {
  approvalsOptions,
  attentionOptions,
  requestKeys,
} from "../request-graph";
import { formatTimestamp, statusTone } from "../surface-model";

export type InboxKind = "approvals" | "attention";

const CommitApprovalPreview = lazy(async () => {
  const module = await import("../inspectors/InspectorFrame");
  return { default: module.CommitApprovalPreview };
});

const PushApprovalPreview = lazy(async () => {
  const module = await import("../inspectors/InspectorFrame");
  return { default: module.PushApprovalPreview };
});

const PullRequestApprovalPreview = lazy(async () => {
  const module = await import("../inspectors/InspectorFrame");
  return { default: module.PullRequestApprovalPreview };
});

export default function InboxDrawer({
  kind,
  onClose,
}: {
  kind: InboxKind;
  onClose: () => void;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const approvals = useQuery(approvalsOptions());
  const attention = useQuery(attentionOptions());
  const approvalDecision = useMutation({
    mutationFn: ({
      approvalId,
      option,
    }: {
      approvalId: string;
      option: ReturnType<typeof enabledApprovalOptions>[number];
    }) =>
      mutateCockpit(
        `/api/approvals/${encodeURIComponent(approvalId)}/decision`,
        approvalDecisionPayload(option),
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: requestKeys.approvals() }),
        queryClient.invalidateQueries({ queryKey: requestKeys.attention() }),
        queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() }),
      ]);
    },
  });
  const attentionRead = useMutation({
    mutationFn: (itemIds: string[]) =>
      mutateCockpit("/api/attention/read", { item_ids: itemIds, read: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: requestKeys.attention() });
    },
  });

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside
        aria-label={message(locale, kind)}
        aria-modal="true"
        className="inbox-drawer"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="drawer-heading">
          <div>
            <p className="section-kicker">{message(locale, "globalInbox")}</p>
            <h2>{message(locale, kind)}</h2>
          </div>
          <button aria-label={message(locale, "close")} onClick={onClose} type="button">
            ×
          </button>
        </div>
        {kind === "approvals" ? (
          <div className="inbox-list">
            {approvals.isPending ? <InboxLoading locale={locale} /> : null}
            {approvals.isError ? <InboxError locale={locale} /> : null}
            {approvals.data?.approvals.length === 0 ? (
              <div className="empty-state">{message(locale, "noItems")}</div>
            ) : null}
            {approvals.data?.approvals.map((approval) => (
              <article className="inbox-item" key={approval.id}>
                <div className="inbox-item-heading">
                  <strong>{approval.action}</strong>
                  <span className={`status-label ${statusTone(approval.status)}`}>
                    {approval.status}
                  </span>
                </div>
                <p>{approval.reason ?? approval.policy_source}</p>
                {approval.ux === undefined ? null : (
                  <>
                    <div className={`approval-risk ${approval.ux.risk}`}>
                      {message(locale, "risk")} · {approval.ux.risk}
                    </div>
                    <dl className="compact-fields approval-scope">
                      <div>
                        <dt>{message(locale, "target")}</dt>
                        <dd>
                          {approval.ux.target.kind}
                          {Object.keys(approval.ux.target.fields).length === 0
                            ? ""
                            : ` · ${Object.values(approval.ux.target.fields).join(" · ")}`}
                        </dd>
                      </div>
                      <div>
                        <dt>{message(locale, "scope")}</dt>
                        <dd>
                          {approval.ux.scope.session_id === null
                            ? message(locale, "operationScope")
                            : message(locale, "sessionScope")}
                        </dd>
                      </div>
                      <div>
                        <dt>{message(locale, "sourcePolicy")}</dt>
                        <dd>{approval.ux.policy_source}</dd>
                      </div>
                      <div>
                        <dt>{message(locale, "previewDigest")}</dt>
                        <dd><code>{approval.ux.preview_sha256.slice(0, 12)}</code></dd>
                      </div>
                    </dl>
                    <details className="approval-explanation">
                      <summary>{message(locale, "whyThisDecision")}</summary>
                      <p>{approval.ux.why}</p>
                      <p>{message(locale, "consequence")} · {approval.ux.consequence}</p>
                      <p>{message(locale, "whatChanged")} · {approval.ux.what_changed}</p>
                    </details>
                    {approval.ux.protected ? (
                      <div className="error-state" role="alert">
                        {message(locale, "protectedAuthorityBlocked")}
                      </div>
                    ) : null}
                  </>
                )}
                <dl className="compact-fields">
                  <div><dt>{message(locale, "owner")}</dt><dd>{approval.enforcement_owner}</dd></div>
                  <div><dt>{message(locale, "run")}</dt><dd>{approval.run_id ?? "—"}</dd></div>
                  <div><dt>{message(locale, "created")}</dt><dd>{formatTimestamp(approval.created_at, locale)}</dd></div>
                </dl>
                {approval.action === "git.commit" && (
                  <Suspense fallback={null}>
                    <CommitApprovalPreview preview={approval.preview} />
                  </Suspense>
                )}
                {approval.action === "git.push" && (
                  <Suspense fallback={null}>
                    <PushApprovalPreview preview={approval.preview} />
                  </Suspense>
                )}
                {approval.action === "github.pull_request.create" && (
                  <Suspense fallback={null}>
                    <PullRequestApprovalPreview preview={approval.preview} />
                  </Suspense>
                )}
                {approval.status === "pending" ? (
                  <div className="decision-actions">
                    {enabledApprovalOptions(approval).map((option) => (
                      <button
                        className={
                          option.decision === "deny" ? "danger-button" : "primary-button"
                        }
                        disabled={approvalDecision.isPending}
                        key={`${option.decision}-${option.lifetime}`}
                        onClick={() =>
                          approvalDecision.mutate({ approvalId: approval.id, option })
                        }
                        type="button"
                      >
                        {message(locale, decisionLabelKey(option.decision))}
                      </button>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <div className="inbox-list">
            {attention.isPending ? <InboxLoading locale={locale} /> : null}
            {attention.isError ? <InboxError locale={locale} /> : null}
            {attention.data?.items.length === 0 ? (
              <div className="empty-state">{message(locale, "nothingNeedsAttention")}</div>
            ) : null}
            {attention.data?.items.map((item) => (
              <article className={item.read ? "inbox-item read" : "inbox-item"} key={item.id}>
                <div className="inbox-item-heading">
                  <strong>{item.title}</strong>
                  <span className={`status-label ${statusTone(item.severity)}`}>
                    {item.read ? "read" : "unread"}
                  </span>
                </div>
                <p>{item.summary}</p>
                <div className="inbox-item-actions">
                  {item.href.startsWith("/runs/") ? (
                    <Link
                      onClick={onClose}
                      params={{ runId: item.href.slice("/runs/".length) }}
                      to="/cockpit-v2/runs/$runId"
                    >
                      {message(locale, "openRun")}
                    </Link>
                  ) : null}
                  {!item.read ? (
                    <button
                      disabled={attentionRead.isPending}
                      onClick={() => attentionRead.mutate([item.id])}
                      type="button"
                    >
                      {message(locale, "markRead")}
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}

function InboxLoading({ locale }: { locale: "en" | "ru" }) {
  return <div className="skeleton-block" aria-label={message(locale, "loading")} />;
}

function InboxError({ locale }: { locale: "en" | "ru" }) {
  return <div className="error-state" role="alert">{message(locale, "inboxUnavailable")}</div>;
}
