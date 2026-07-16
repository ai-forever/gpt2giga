export type ThemePreference = "light" | "dark" | "system";
export type LocalePreference = "en" | "ru";

const preferenceKey = "gpt2giga.cockpit-v2.preferences.v1";

export interface PresentationPreferences {
  locale: LocalePreference;
  theme: ThemePreference;
}

const defaults: PresentationPreferences = { locale: "en", theme: "system" };

export function loadPreferences(): PresentationPreferences {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(preferenceKey) ?? "null");
    if (typeof value !== "object" || value === null) {
      return defaults;
    }
    const record = value as Record<string, unknown>;
    return {
      locale: record.locale === "ru" ? "ru" : "en",
      theme:
        record.theme === "light" || record.theme === "dark"
          ? record.theme
          : "system",
    };
  } catch {
    return defaults;
  }
}

export function savePreferences(preferences: PresentationPreferences): void {
  localStorage.setItem(preferenceKey, JSON.stringify(preferences));
}

export function applyTheme(theme: ThemePreference): void {
  document.documentElement.dataset.theme = theme;
}
