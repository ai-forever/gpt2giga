import { useState } from "react";

import { LazyInspector, type InspectorKind } from "../inspectors/LazyInspector";
import { message, type MessageKey } from "../messages";
import { usePreferences } from "../preferences-context";

const inspectorLabels: ReadonlyArray<[InspectorKind, MessageKey]> = [
  ["markdown", "markdown"],
  ["diff", "diff"],
  ["terminal", "terminal"],
  ["editor", "editor"],
  ["evidence", "rawEvidence"],
];

export function SurfaceScaffold({
  detailKey,
  eyebrowKey,
  titleKey,
}: {
  detailKey: MessageKey;
  eyebrowKey: MessageKey;
  titleKey: MessageKey;
}) {
  const [inspector, setInspector] = useState<InspectorKind | null>(null);
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  return (
    <div className="surface-grid">
      <section className="surface-intro">
        <p className="eyebrow">{message(locale, eyebrowKey)}</p>
        <h1>{message(locale, titleKey)}</h1>
        <p className="surface-detail">{message(locale, detailKey)}</p>
        <div className="migration-note" role="status">
          {message(locale, "migrationNote")}
        </div>
      </section>
      <section className="boundary-panel" aria-label="Lazy module boundaries">
        <div>
          <p className="eyebrow">{message(locale, "boundaryEyebrow")}</p>
          <h2>{message(locale, "boundaryTitle")}</h2>
          <p>{message(locale, "boundaryDescription")}</p>
        </div>
        <div className="inspector-actions">
          {inspectorLabels.map(([kind, labelKey]) => (
            <button
              className={inspector === kind ? "selected" : ""}
              key={kind}
              onClick={() => setInspector(kind)}
              type="button"
            >
              {message(locale, labelKey)}
            </button>
          ))}
        </div>
        {inspector === null ? (
          <div className="inspector-empty">{message(locale, "boundaryEmpty")}</div>
        ) : (
          <LazyInspector kind={inspector} locale={locale} />
        )}
      </section>
    </div>
  );
}
