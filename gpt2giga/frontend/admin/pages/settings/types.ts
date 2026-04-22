export type SettingsSection =
  | "application"
  | "observability"
  | "gigachat"
  | "security"
  | "history";

export type SettingsPage =
  | "settings"
  | "settings-application"
  | "settings-observability"
  | "settings-gigachat"
  | "settings-security"
  | "settings-history";

export const SETTINGS_LABELS: Record<SettingsSection, string> = {
  application: "Application",
  observability: "Observability",
  gigachat: "GigaChat",
  security: "Security",
  history: "History",
};
