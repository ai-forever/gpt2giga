import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { InboxDrawer, type InboxKind } from "./components/InboxDrawer";
import { PrimaryRailBrand, PrimaryRailIcon } from "./components/PrimaryRailIcon";
import { message } from "./messages";
import { primarySurfaces, surfaceForPath } from "./navigation";
import { PreferencesContext } from "./preferences-context";
import {
  applyTheme,
  loadPreferences,
  savePreferences,
  type LocalePreference,
  type ThemePreference,
} from "./preferences";
import { approvalsOptions, attentionOptions } from "./request-graph";

function ApprovalIcon() {
  return (
    <svg className="action-icon" aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.5 12 2.2 2.2 4.8-5" />
    </svg>
  );
}

function AttentionIcon() {
  return (
    <svg className="action-icon" aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 4 21 20H3L12 4Z" />
      <path d="M12 9v5M12 17.2v.1" />
    </svg>
  );
}

export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const activeSurface = surfaceForPath(pathname);
  const [preferences, setPreferences] = useState(loadPreferences);
  const [inbox, setInbox] = useState<InboxKind | null>(null);
  const approvals = useQuery(approvalsOptions());
  const attention = useQuery(attentionOptions());
  const migratedSurface = activeSurface !== null && activeSurface !== "settings";

  useEffect(() => {
    applyTheme(preferences.theme);
    savePreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    const openInbox = (event: Event) => {
      const kind = (event as CustomEvent<InboxKind>).detail;
      if (kind === "approvals" || kind === "attention") setInbox(kind);
    };
    globalThis.addEventListener("cockpit:open-inbox", openInbox);
    return () => globalThis.removeEventListener("cockpit:open-inbox", openInbox);
  }, []);

  const setLocale = (locale: LocalePreference) => {
    setPreferences((current) => ({ ...current, locale }));
  };
  const setTheme = (theme: ThemePreference) => {
    setPreferences((current) => ({ ...current, theme }));
  };

  return (
    <PreferencesContext.Provider value={{ preferences, setLocale, setTheme }}>
      <div className="cockpit-shell">
      <aside className="primary-rail">
        <Link className="brand-mark" to="/cockpit-v2/work" aria-label="gpt2giga Cockpit V2">
          <PrimaryRailBrand />
        </Link>
        <nav aria-label="Primary navigation">
          {primarySurfaces.map((surface) => (
            <Link
              activeOptions={{ exact: false }}
              className="rail-link"
              key={surface.id}
              to={surface.path}
            >
              <span className="rail-symbol" aria-hidden="true">
                <PrimaryRailIcon surface={surface.id} />
              </span>
              <span>{message(preferences.locale, surface.messageKey)}</span>
            </Link>
          ))}
        </nav>
        <div className="rail-footer">
          <span className="connection-dot" aria-hidden="true" />
          <span>{message(preferences.locale, "connected")}</span>
        </div>
      </aside>
      <div className="cockpit-main">
        <header className="cockpit-header">
          <div>
            <p className="project-label">{message(preferences.locale, "project")}</p>
            <strong>gpt2giga</strong>
          </div>
          <div className="header-actions">
            <button
              aria-label={message(preferences.locale, "approvals")}
              type="button"
              onClick={() => setInbox("approvals")}
            >
              <ApprovalIcon />
              <span className="action-label">{message(preferences.locale, "approvals")}</span>
              {(approvals.data?.pending_count ?? 0) > 0 ? (
                <span className="count-badge">{approvals.data?.pending_count}</span>
              ) : null}
            </button>
            <button
              aria-label={message(preferences.locale, "attention")}
              type="button"
              onClick={() => setInbox("attention")}
            >
              <AttentionIcon />
              <span className="action-label">{message(preferences.locale, "attention")}</span>
              {(attention.data?.unread ?? 0) > 0 ? (
                <span className="count-badge attention">{attention.data?.unread}</span>
              ) : null}
            </button>
            <Link className="settings-link" to="/cockpit-v2/settings">{message(preferences.locale, "settings")}</Link>
          </div>
        </header>
        {migratedSurface ? null : (
          <div className="shell-notice">
            <span>{message(preferences.locale, "shellNotice")}</span>
            <a href="/legacy">{message(preferences.locale, "legacy")}</a>
          </div>
        )}
        <main className={migratedSurface ? "surface-shell migrated" : "surface-shell"}>
          <Outlet />
        </main>
      </div>
      {inbox === null ? null : <InboxDrawer kind={inbox} onClose={() => setInbox(null)} />}
      <span className="sr-only" aria-live="polite">{message(preferences.locale, "connection")}</span>
      </div>
    </PreferencesContext.Provider>
  );
}
