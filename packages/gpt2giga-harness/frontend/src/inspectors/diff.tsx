import { InspectorFrame } from "./InspectorFrame";
import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function DiffInspector({ locale }: { locale: LocalePreference }) {
  return <InspectorFrame locale={locale} title={message(locale, "diff")}>{message(locale, "diffDescription")}</InspectorFrame>;
}
