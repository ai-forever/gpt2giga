import { useEffect, useState } from "react";

import { renderTextIncrementally } from "../bounded-rendering";
import { InspectorFrame } from "./InspectorFrame";
import { message } from "../messages";
import type { LocalePreference } from "../preferences";

export function MarkdownInspector({ locale }: { locale: LocalePreference }) {
  const source = message(locale, "markdownDescription");
  const [rendered, setRendered] = useState("");
  useEffect(() => {
    setRendered("");
    return renderTextIncrementally(source, (chunk) => {
      setRendered((current) => current + chunk);
    });
  }, [source]);
  return (
    <InspectorFrame locale={locale} title={message(locale, "markdown")}>
      {rendered || message(locale, "loadingInspector")}
    </InspectorFrame>
  );
}
