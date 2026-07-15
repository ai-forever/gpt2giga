import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

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
  const [inbox, setInbox] = useState<"approvals" | "attention" | null>(null);

  useEffect(() => {
    applyTheme(preferences.theme);
    savePreferences(preferences);
  }, [preferences]);

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
        <a className="brand-mark" href="/cockpit-v2/work" aria-label="gpt2giga Cockpit V2">
          <span>g2</span>
        </a>
        <nav aria-label="Primary navigation">
          {primarySurfaces.map((surface) => (
            <Link
              activeOptions={{ exact: false }}
              className={activeSurface === surface.id ? "rail-link active" : "rail-link"}
              key={surface.id}
              to={surface.path}
            >
              <span className="rail-symbol" aria-hidden="true">{surface.label.slice(0, 1)}</span>
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
            </button>
            <button
              aria-label={message(preferences.locale, "attention")}
              type="button"
              onClick={() => setInbox("attention")}
            >
              <AttentionIcon />
              <span className="action-label">{message(preferences.locale, "attention")}</span>
            </button>
            <Link className="settings-link" to="/cockpit-v2/settings">{message(preferences.locale, "settings")}</Link>
          </div>
        </header>
        <div className="shell-notice">
          <span>{message(preferences.locale, "shellNotice")}</span>
          <a href="/legacy">{message(preferences.locale, "legacy")}</a>
        </div>
        <main className="surface-shell">
          <Outlet />
        </main>
      </div>
      {inbox === null ? null : (
        <div className="drawer-backdrop" role="presentation" onClick={() => setInbox(null)}>
          <aside className="inbox-drawer" role="dialog" aria-modal="true" aria-label={message(preferences.locale, inbox)} onClick={(event) => event.stopPropagation()}>
            <div className="drawer-heading">
              <div>
                <p className="eyebrow">Global inbox</p>
                <h2>{message(preferences.locale, inbox)}</h2>
              </div>
              <button type="button" onClick={() => setInbox(null)}>{message(preferences.locale, "close")}</button>
            </div>
            <div className="inbox-empty">{message(preferences.locale, "noItems")}</div>
          </aside>
        </div>
      )}
      <span className="sr-only" aria-live="polite">{message(preferences.locale, "connection")}</span>
      </div>
    </PreferencesContext.Provider>
  );
}
