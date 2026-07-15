import { lazy, Suspense } from "react";

import { message } from "../messages";
import type { LocalePreference } from "../preferences";

const inspectorModules = {
  markdown: lazy(async () => {
    const module = await import("./markdown");
    return { default: module.MarkdownInspector };
  }),
  diff: lazy(async () => {
    const module = await import("./diff");
    return { default: module.DiffInspector };
  }),
  terminal: lazy(async () => {
    const module = await import("./terminal");
    return { default: module.TerminalInspector };
  }),
  editor: lazy(async () => {
    const module = await import("./editor");
    return { default: module.EditorInspector };
  }),
  evidence: lazy(async () => {
    const module = await import("./raw-evidence");
    return { default: module.RawEvidenceInspector };
  }),
} as const;

export type InspectorKind = keyof typeof inspectorModules;

export function LazyInspector({
  kind,
  locale,
}: {
  kind: InspectorKind;
  locale: LocalePreference;
}) {
  const Inspector = inspectorModules[kind];
  return (
    <Suspense fallback={<div className="inspector-loading">{message(locale, "loadingInspector")}</div>}>
      <Inspector locale={locale} />
    </Suspense>
  );
}
