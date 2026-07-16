import { InspectorFrame } from "./InspectorFrame";
import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function RawEvidenceInspector({ locale }: { locale: LocalePreference }) {
  return <InspectorFrame locale={locale} title={message(locale, "rawEvidence")}>{message(locale, "rawEvidenceDescription")}</InspectorFrame>;
}
