import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { message, type MessageKey } from "../messages";
import { usePreferences } from "../preferences-context";

export type OperationalPath =
  | "/cockpit-v2/automation/agents"
  | "/cockpit-v2/automation/workflows"
  | "/cockpit-v2/automation/schedules"
  | "/cockpit-v2/evaluation/arena"
  | "/cockpit-v2/evaluation/evals"
  | "/cockpit-v2/evaluation/baselines"
  | "/cockpit-v2/integrations/harnesses"
  | "/cockpit-v2/integrations/models"
  | "/cockpit-v2/integrations/mcp"
  | "/cockpit-v2/integrations/doctor";

export interface OperationalTab {
  href: OperationalPath;
  id: string;
  labelKey: MessageKey;
}

export function OperationalSurface({
  activeTab,
  aside,
  children,
  detailKey,
  eyebrowKey,
  tabs,
  titleKey,
}: {
  activeTab: string;
  aside: ReactNode;
  children: ReactNode;
  detailKey: MessageKey;
  eyebrowKey: MessageKey;
  tabs: readonly OperationalTab[];
  titleKey: MessageKey;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  return (
    <div className="operations-surface">
      <header className="operations-header">
        <div>
          <span className="section-kicker">{message(locale, eyebrowKey)}</span>
          <h1>{message(locale, titleKey)}</h1>
          <p>{message(locale, detailKey)}</p>
        </div>
        <span className="content-free-badge">{message(locale, "contentFreeProjection")}</span>
      </header>
      <nav className="secondary-tabs" aria-label={message(locale, titleKey)}>
        {tabs.map((tab) => (
          <Link
            aria-current={activeTab === tab.id ? "page" : undefined}
            className={activeTab === tab.id ? "active" : ""}
            key={tab.id}
            to={tab.href}
          >
            {message(locale, tab.labelKey)}
          </Link>
        ))}
      </nav>
      <div className="operations-layout">
        <section className="operations-list-pane">{children}</section>
        <aside className="operations-detail-pane">{aside}</aside>
      </div>
    </div>
  );
}

export function LoadingRows() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <div className="skeleton-row" />
      <div className="skeleton-row" />
      <div className="skeleton-row" />
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const tone = ["passed", "ready", "healthy", "enabled", "success", "completed"].includes(normalized)
    ? "success"
    : ["failed", "blocked", "error", "unavailable"].includes(normalized)
      ? "danger"
      : ["degraded", "running", "queued", "needs_attention", "warning"].includes(normalized)
        ? "warning"
        : "";
  return <span className={`status-label ${tone}`}>{status || "unknown"}</span>;
}
