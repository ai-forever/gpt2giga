import { useState } from "react";

import { LazyInspector, type InspectorKind } from "../inspectors/LazyInspector";
import type { LocalePreference, ThemePreference } from "../preferences";
import { usePreferences } from "../preferences-context";
import { message } from "../messages";

export function SettingsSurface() {
  const { preferences, setLocale, setTheme } = usePreferences();
  const locale = preferences.locale;
  return (
    <section className="settings-surface">
      <p className="eyebrow">{message(locale, "presentationOnly")}</p>
      <h1>{message(locale, "settings")}</h1>
      <p>{message(locale, "settingsDescription")}</p>
      <div className="settings-grid">
        <label>
          {message(locale, "language")}
          <select value={preferences.locale} onChange={(event) => setLocale(event.target.value as LocalePreference)}>
            <option value="en">English</option>
            <option value="ru">Русский</option>
          </select>
        </label>
        <label>
          {message(locale, "theme")}
          <select value={preferences.theme} onChange={(event) => setTheme(event.target.value as ThemePreference)}>
            <option value="light">{message(locale, "light")}</option>
            <option value="dark">{message(locale, "dark")}</option>
            <option value="system">{message(locale, "system")}</option>
          </select>
        </label>
      </div>
      <SettingsInspectorBoundary />
    </section>
  );
}

const inspectorKinds: readonly InspectorKind[] = [
  "markdown",
  "diff",
  "terminal",
  "editor",
  "evidence",
];

function SettingsInspectorBoundary() {
  const { preferences } = usePreferences();
  const [kind, setKind] = useState<InspectorKind | null>(null);
  return (
    <details className="operational-inspectors">
      <summary>{message(preferences.locale, "lazyBoundary")}</summary>
      <div className="inspector-actions">
        {inspectorKinds.map((item) => (
          <button key={item} onClick={() => setKind(item)} type="button">
            {message(preferences.locale, item === "evidence" ? "rawEvidence" : item)}
          </button>
        ))}
      </div>
      {kind === null ? null : <LazyInspector kind={kind} locale={preferences.locale} />}
    </details>
  );
}
