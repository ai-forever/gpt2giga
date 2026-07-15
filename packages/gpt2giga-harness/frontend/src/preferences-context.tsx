import { createContext, useContext } from "react";

import type {
  LocalePreference,
  PresentationPreferences,
  ThemePreference,
} from "./preferences";

export interface PreferencesContextValue {
  preferences: PresentationPreferences;
  setLocale: (locale: LocalePreference) => void;
  setTheme: (theme: ThemePreference) => void;
}

export const PreferencesContext = createContext<PreferencesContextValue | null>(null);

export function usePreferences(): PreferencesContextValue {
  const value = useContext(PreferencesContext);
  if (value === null) {
    throw new Error("Cockpit V2 preferences context is unavailable");
  }
  return value;
}
