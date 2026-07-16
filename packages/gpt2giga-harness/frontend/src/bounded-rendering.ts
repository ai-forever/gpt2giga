export interface VirtualWindowInput {
  itemCount: number;
  scrollTop: number;
  viewportHeight: number;
  estimatedItemHeight: number;
  overscan?: number;
}

export interface VirtualWindow {
  start: number;
  end: number;
  offsetTop: number;
  totalHeight: number;
}

export function computeVirtualWindow({
  itemCount,
  scrollTop,
  viewportHeight,
  estimatedItemHeight,
  overscan = 4,
}: VirtualWindowInput): VirtualWindow {
  const count = Math.max(0, Math.floor(itemCount));
  const height = Math.max(1, estimatedItemHeight);
  const buffer = Math.max(0, Math.floor(overscan));
  const visibleStart = Math.floor(Math.max(scrollTop, 0) / height);
  const visibleCount = Math.ceil(Math.max(viewportHeight, 0) / height);
  const start = Math.max(0, visibleStart - buffer);
  const end = Math.min(count, visibleStart + visibleCount + buffer);
  return {
    start,
    end,
    offsetTop: start * height,
    totalHeight: count * height,
  };
}

export function preserveScrollAnchor({
  scrollTop,
  insertedHeight,
  pinnedToEnd,
}: {
  scrollTop: number;
  insertedHeight: number;
  pinnedToEnd: boolean;
}): number {
  return pinnedToEnd
    ? Math.max(scrollTop, 0)
    : Math.max(scrollTop + insertedHeight, 0);
}

export function markdownChunks(source: string, maxCharacters = 4096): string[] {
  const limit = Math.max(256, Math.floor(maxCharacters));
  const chunks: string[] = [];
  let remaining = source;
  while (remaining.length > limit) {
    const newline = remaining.lastIndexOf("\n", limit);
    const boundary = newline >= Math.floor(limit / 2) ? newline + 1 : limit;
    chunks.push(remaining.slice(0, boundary));
    remaining = remaining.slice(boundary);
  }
  if (remaining.length > 0 || chunks.length === 0) chunks.push(remaining);
  return chunks;
}

type IncrementalScheduler = (callback: () => void) => () => void;

const defaultScheduler: IncrementalScheduler = (callback) => {
  const handle = globalThis.setTimeout(callback, 0);
  return () => globalThis.clearTimeout(handle);
};

export function renderTextIncrementally(
  source: string,
  onChunk: (chunk: string) => void,
  options: {
    maxCharacters?: number;
    schedule?: IncrementalScheduler;
  } = {},
): () => void {
  const chunks = markdownChunks(source, options.maxCharacters);
  const schedule = options.schedule ?? defaultScheduler;
  let cancelled = false;
  let cancelScheduled: () => void = () => undefined;
  const emitNext = () => {
    if (cancelled) return;
    const chunk = chunks.shift();
    if (chunk === undefined) return;
    onChunk(chunk);
    if (chunks.length > 0) cancelScheduled = schedule(emitNext);
  };
  cancelScheduled = schedule(emitNext);
  return () => {
    cancelled = true;
    cancelScheduled();
  };
}
