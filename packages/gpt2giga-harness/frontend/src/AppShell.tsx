import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

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
import { approvalsOptions, attentionOptions, requestKeys } from "./request-graph";
import { observeRunsCenterUpdates } from "./runs-center-update-stream";

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

function SettingsIcon() {
  return (
    <svg className="action-icon" aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.86 2.86-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.1A1.7 1.7 0 0 0 8.5 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.86-2.86.06-.06A1.7 1.7 0 0 0 4.1 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H2V9.6h.4A1.7 1.7 0 0 0 4.1 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06L6.56 3.7l.06.06A1.7 1.7 0 0 0 8.5 4.1a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V2h4v.4A1.7 1.7 0 0 0 15 4.1a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.86 2.86-.06.06A1.7 1.7 0 0 0 19.4 8.5a1.7 1.7 0 0 0 .6 1 1.7 1.7 0 0 0 1.1.4h.9v4h-.9a1.7 1.7 0 0 0-1.7 1.1Z" />
    </svg>
  );
}

export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const activeSurface = surfaceForPath(pathname);
  const [preferences, setPreferences] = useState(loadPreferences);
  const [inbox, setInbox] = useState<InboxKind | null>(null);
  const queryClient = useQueryClient();
  const approvals = useQuery(approvalsOptions());
  const attention = useQuery(attentionOptions());
  const migratedSurface = activeSurface !== null && activeSurface !== "settings";

  useEffect(() => {
    applyTheme(preferences.theme);
    savePreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    if (typeof globalThis.EventSource !== "function") return;
    return observeRunsCenterUpdates(() => {
      void queryClient.invalidateQueries({ queryKey: requestKeys.runsCenter() });
    });
  }, [queryClient]);

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
        <div className="rail-utility-actions" aria-label={message(preferences.locale, "workspaceUtilities")}>
          <button
            aria-label={message(preferences.locale, "approvals")}
            className="rail-utility-control"
            type="button"
            onClick={() => setInbox("approvals")}
          >
            <span className="rail-utility-symbol">
              <ApprovalIcon />
              {(approvals.data?.pending_count ?? 0) > 0 ? (
                <span className="count-badge">{approvals.data?.pending_count}</span>
              ) : null}
            </span>
            <span className="rail-utility-label">{message(preferences.locale, "approvals")}</span>
          </button>
          <button
            aria-label={message(preferences.locale, "attention")}
            className="rail-utility-control"
            type="button"
            onClick={() => setInbox("attention")}
          >
            <span className="rail-utility-symbol">
              <AttentionIcon />
              {(attention.data?.unread ?? 0) > 0 ? (
                <span className="count-badge attention">{attention.data?.unread}</span>
              ) : null}
            </span>
            <span className="rail-utility-label">{message(preferences.locale, "attention")}</span>
          </button>
          <Link
            activeOptions={{ exact: true }}
            aria-label={message(preferences.locale, "settings")}
            className="rail-utility-control"
            to="/cockpit-v2/settings"
          >
            <span className="rail-utility-symbol"><SettingsIcon /></span>
            <span className="rail-utility-label">{message(preferences.locale, "settings")}</span>
          </Link>
        </div>
      </aside>
      <div className="cockpit-main">
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
      </div>
    </PreferencesContext.Provider>
  );
}
