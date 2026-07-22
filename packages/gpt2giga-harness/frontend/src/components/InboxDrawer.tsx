import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { mutateCockpit } from "../api";
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
    mutationFn: ({ approvalId, decision }: { approvalId: string; decision: string }) =>
      mutateCockpit(`/api/approvals/${encodeURIComponent(approvalId)}/decision`, {
        decision,
      }),
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
                {approval.status === "pending" ? (
                  <div className="decision-actions">
                    <button
                      className="danger-button"
                      disabled={approvalDecision.isPending}
                      onClick={() =>
                        approvalDecision.mutate({ approvalId: approval.id, decision: "deny" })
                      }
                      type="button"
                    >
                      {message(locale, "deny")}
                    </button>
                    <button
                      className="primary-button"
                      disabled={approvalDecision.isPending}
                      onClick={() =>
                        approvalDecision.mutate({ approvalId: approval.id, decision: "allow_once" })
                      }
                      type="button"
                    >
                      {message(locale, "approveOnce")}
                    </button>
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
