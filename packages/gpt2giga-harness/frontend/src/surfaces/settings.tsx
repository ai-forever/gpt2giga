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
    </section>
  );
}
