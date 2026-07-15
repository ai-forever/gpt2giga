import { InspectorFrame } from "./InspectorFrame";
import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function EditorInspector({ locale }: { locale: LocalePreference }) {
  return <InspectorFrame locale={locale} title={message(locale, "editor")}>{message(locale, "editorDescription")}</InspectorFrame>;
}
