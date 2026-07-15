import { InspectorFrame } from "./InspectorFrame";
import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function MarkdownInspector({ locale }: { locale: LocalePreference }) {
  return <InspectorFrame locale={locale} title={message(locale, "markdown")}>{message(locale, "markdownDescription")}</InspectorFrame>;
}
