import { InspectorFrame } from "./InspectorFrame";
import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function TerminalInspector({ locale }: { locale: LocalePreference }) {
  return <InspectorFrame locale={locale} title={message(locale, "terminal")}>{message(locale, "terminalDescription")}</InspectorFrame>;
}
