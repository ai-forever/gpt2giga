import type { ReactNode } from "react";

import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function InspectorFrame({
  children,
  locale,
  title,
}: {
  children: ReactNode;
  locale: LocalePreference;
  title: string;
}) {
  return (
    <section className="lazy-inspector" aria-label={title}>
      <div className="eyebrow">{message(locale, "lazyBoundary")}</div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}

export function CommitApprovalPreview({ preview }: { preview?: Record<string, unknown> }) {
  const author = preview?.author;
  const authorRecord = typeof author === "object" && author !== null
    ? author as Record<string, unknown>
    : {};
  const head = typeof preview?.head === "string" ? preview.head : "unborn";
  const diff = typeof preview?.diff_sha256 === "string" ? preview.diff_sha256 : "unavailable";
  return (
    <dl className="compact-fields commit-approval-preview">
      <div><dt>Author</dt><dd>{String(authorRecord.name ?? "unknown")} &lt;{String(authorRecord.email ?? "unknown")}&gt;</dd></div>
      <div><dt>Message</dt><dd>{String(preview?.message ?? "")}</dd></div>
      <div><dt>HEAD</dt><dd><code>{head}</code></dd></div>
      <div><dt>Diff</dt><dd><code>{diff}</code></dd></div>
    </dl>
  );
}

export function PushApprovalPreview({ preview }: { preview?: Record<string, unknown> }) {
  const permissions = preview?.permissions;
  const permissionRecord = typeof permissions === "object" && permissions !== null
    ? permissions as Record<string, unknown>
    : {};
  const permits = Object.entries(permissionRecord)
    .filter(([, enabled]) => enabled === true)
    .map(([name]) => name)
    .join(", ");
  const forbids = Object.entries(permissionRecord)
    .filter(([, enabled]) => enabled === false)
    .map(([name]) => name)
    .join(", ");
  return (
    <dl className="compact-fields commit-approval-preview">
      <div><dt>Remote</dt><dd>{String(preview?.remote ?? "unavailable")}</dd></div>
      <div><dt>Upstream</dt><dd>{String(preview?.upstream ?? "new")}</dd></div>
      <div><dt>Target</dt><dd>{String(preview?.target_branch ?? "unavailable")}</dd></div>
      <div><dt>HEAD</dt><dd><code>{String(preview?.head ?? "unavailable")}</code></dd></div>
      <div><dt>Remote HEAD</dt><dd><code>{String(preview?.remote_head ?? "new branch")}</code></dd></div>
      <div><dt>Permits</dt><dd>{permits || "none"}</dd></div>
      <div><dt>Forbids</dt><dd>{forbids || "none"}</dd></div>
    </dl>
  );
}
