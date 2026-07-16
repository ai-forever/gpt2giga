import { lazy, Suspense } from "react";

const MarkdownRenderer = lazy(async () => {
  const module = await import("./markdown-renderer");
  return { default: module.MarkdownRenderer };
});

export function MessageMarkdown({ source }: { source: string }) {
  if (!source.trim()) return null;
  return (
    <Suspense fallback={<div className="message-markdown markdown-loading">{source}</div>}>
      <MarkdownRenderer source={source} />
    </Suspense>
  );
}
