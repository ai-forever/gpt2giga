import type { ReactNode } from "react";

import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function InspectorFrame({
  children,
  locale,
  title,
}: {
  children: ReactNode;
  locale: LocalePreference;
  title: string;
}) {
  return (
    <section className="lazy-inspector" aria-label={title}>
      <div className="eyebrow">{message(locale, "lazyBoundary")}</div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}
