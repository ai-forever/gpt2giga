import { Fragment, useState, type ReactNode } from "react";

export type MarkdownBlock =
  | { kind: "code"; language: string; content: string }
  | { kind: "heading"; level: number; content: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; content: string }
  | { kind: "quote"; content: string }
  | {
      kind: "table";
      alignments: Array<"center" | "left" | "right" | null>;
      headers: string[];
      rows: string[][];
    }
  | { kind: "thematic-break" };

type InlineToken =
  | {
      kind: "cite" | "code" | "emphasis" | "strikethrough" | "strong" | "text";
      content: string;
    }
  | { kind: "link"; content: string; href: string };

export type CodeToken = {
  kind: "comment" | "keyword" | "number" | "plain" | "string";
  content: string;
};

const languageKeywords: Record<string, Set<string>> = {
  bash: new Set([
    "case", "do", "done", "elif", "else", "esac", "fi", "for", "function",
    "if", "in", "select", "then", "until", "while",
  ]),
  go: new Set([
    "break", "case", "chan", "const", "continue", "default", "defer", "else",
    "fallthrough", "for", "func", "go", "goto", "if", "import", "interface",
    "map", "package", "range", "return", "select", "struct", "switch", "type", "var",
  ]),
  javascript: new Set([
    "async", "await", "break", "case", "catch", "class", "const", "continue",
    "debugger", "default", "delete", "do", "else", "export", "extends", "finally",
    "for", "from", "function", "if", "import", "in", "instanceof", "let", "new",
    "of", "return", "static", "super", "switch", "throw", "try", "typeof", "var",
    "void", "while", "with", "yield",
  ]),
  python: new Set([
    "and", "as", "assert", "async", "await", "break", "case", "class", "continue",
    "def", "del", "elif", "else", "except", "False", "finally", "for", "from",
    "global", "if", "import", "in", "is", "lambda", "match", "None", "nonlocal",
    "not", "or", "pass", "raise", "return", "True", "try", "while", "with", "yield",
  ]),
};

const languageAliases: Record<string, string> = {
  js: "javascript",
  jsx: "javascript",
  py: "python",
  shell: "bash",
  sh: "bash",
  ts: "javascript",
  tsx: "javascript",
  golang: "go",
  zsh: "bash",
};

function normalizeLanguage(language: string) {
  const normalized = language.trim().toLowerCase();
  return languageAliases[normalized] ?? normalized;
}

function backtickRunLength(value: string, start: number) {
  let end = start;
  while (value[end] === "`") end += 1;
  return end - start;
}

function splitTableRow(value: string) {
  let row = value.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);

  const cells: string[] = [];
  let cell = "";
  let codeDelimiter = 0;
  let index = 0;
  while (index < row.length) {
    if (row[index] === "\\" && index + 1 < row.length) {
      cell += row.slice(index, index + 2);
      index += 2;
      continue;
    }
    if (row[index] === "`") {
      const runLength = backtickRunLength(row, index);
      if (codeDelimiter === 0) codeDelimiter = runLength;
      else if (codeDelimiter === runLength) codeDelimiter = 0;
      cell += row.slice(index, index + runLength);
      index += runLength;
      continue;
    }
    if (row[index] === "|" && codeDelimiter === 0) {
      cells.push(cell.trim());
      cell = "";
      index += 1;
      continue;
    }
    cell += row[index];
    index += 1;
  }
  cells.push(cell.trim());
  return cells;
}

function tableAlignment(value: string): "center" | "left" | "right" | null | undefined {
  const delimiter = value.trim();
  if (!/^:?-{3,}:?$/.test(delimiter)) return undefined;
  if (delimiter.startsWith(":") && delimiter.endsWith(":")) return "center";
  if (delimiter.endsWith(":")) return "right";
  if (delimiter.startsWith(":")) return "left";
  return null;
}

function parseTableAt(lines: string[], start: number) {
  const headerLine = lines[start] ?? "";
  const delimiterLine = lines[start + 1] ?? "";
  if (!headerLine.includes("|") || !delimiterLine.includes("|")) return null;
  const headers = splitTableRow(headerLine);
  const alignments = splitTableRow(delimiterLine).map(tableAlignment);
  if (
    headers.length < 2 ||
    alignments.length !== headers.length ||
    alignments.some((alignment) => alignment === undefined)
  ) return null;

  const rows: string[][] = [];
  let index = start + 2;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (!line.trim() || !line.includes("|")) break;
    const cells = splitTableRow(line);
    rows.push(headers.map((_, cellIndex) => cells[cellIndex] ?? ""));
    index += 1;
  }
  return {
    block: {
      alignments: alignments as Array<"center" | "left" | "right" | null>,
      headers,
      kind: "table" as const,
      rows,
    },
    nextIndex: index,
  };
}

function isThematicBreak(value: string) {
  return /^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/.test(value);
}

export function parseMarkdownBlocks(value: string): MarkdownBlock[] {
  const lines = value.replace(/\r\n?/g, "\n").split("\n");
  const lineAt = (position: number) => lines[position] ?? "";
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lineAt(index);
    if (line.trim() === "") {
      index += 1;
      continue;
    }

    if (isThematicBreak(line)) {
      blocks.push({ kind: "thematic-break" });
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```\s*([\w.+-]*)\s*$/);
    if (fence) {
      const content: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lineAt(index))) {
        content.push(lineAt(index));
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({
        content: content.join("\n"),
        kind: "code",
        language: normalizeLanguage(fence[1] || "text"),
      });
      continue;
    }

    const table = parseTableAt(lines, index);
    if (table) {
      blocks.push(table.block);
      index = table.nextIndex;
      continue;
    }

    const heading = line.match(/^\s*(#{1,6})\s+(.+)$/);
    if (heading) {
      blocks.push({
        content: heading[2] ?? "",
        kind: "heading",
        level: (heading[1] ?? "#").length,
      });
      index += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lineAt(index))) {
        quote.push(lineAt(index).replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push({ content: quote.join("\n"), kind: "quote" });
      continue;
    }

    const listItem = line.match(/^\s*(?:(\d+)[.)]|[-*+])\s+(.+)$/);
    if (listItem) {
      const ordered = listItem[1] !== undefined;
      const items: string[] = [];
      while (index < lines.length) {
        const candidate = lineAt(index).match(/^\s*(?:(\d+)[.)]|[-*+])\s+(.+)$/);
        if (!candidate || (candidate[1] !== undefined) !== ordered) break;
        items.push(candidate[2] ?? "");
        index += 1;
      }
      blocks.push({ items, kind: "list", ordered });
      continue;
    }

    const paragraph = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lineAt(index).trim() !== "" &&
      !/^\s*```/.test(lineAt(index)) &&
      !isThematicBreak(lineAt(index)) &&
      parseTableAt(lines, index) === null &&
      !/^\s*(?:#{1,6}\s+|>\s?|(?:(?:\d+)[.)]|[-*+])\s+)/.test(lineAt(index))
    ) {
      paragraph.push(lineAt(index).trim());
      index += 1;
    }
    blocks.push({ content: paragraph.join("\n"), kind: "paragraph" });
  }

  return blocks;
}

function codeSpanAt(value: string, start: number) {
  const delimiterLength = backtickRunLength(value, start);
  let search = start + delimiterLength;
  while (search < value.length) {
    const candidate = value.indexOf("`", search);
    if (candidate === -1) return null;
    const candidateLength = backtickRunLength(value, candidate);
    if (candidateLength === delimiterLength) {
      let content = value.slice(start + delimiterLength, candidate).replace(/\n/g, " ");
      if (
        content.startsWith(" ") &&
        content.endsWith(" ") &&
        content.trim().length > 0
      ) content = content.slice(1, -1);
      return { content, end: candidate + delimiterLength };
    }
    search = candidate + candidateLength;
  }
  return null;
}

function parseInline(value: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let plain = "";
  let index = 0;
  const flush = () => {
    if (plain) tokens.push({ content: plain, kind: "text" });
    plain = "";
  };

  while (index < value.length) {
    if (value[index] === "\\" && index + 1 < value.length) {
      plain += value[index + 1];
      index += 2;
      continue;
    }

    if (value[index] === "`") {
      const code = codeSpanAt(value, index);
      if (code) {
        flush();
        tokens.push({ content: code.content, kind: "code" });
        index = code.end;
        continue;
      }
    }

    const cite = value.slice(index).match(/^<cite>([\s\S]*?)<\/cite>/i);
    if (cite) {
      flush();
      tokens.push({ content: cite[1] ?? "", kind: "cite" });
      index += cite[0].length;
      continue;
    }

    const link = value.slice(index).match(/^\[([^\]]+)]\(([^\s)]+)(?:\s+"[^"]*")?\)/);
    if (link) {
      flush();
      tokens.push({ content: link[1] ?? "", href: link[2] ?? "", kind: "link" });
      index += link[0].length;
      continue;
    }

    const marker = value.startsWith("~~", index)
      ? "~~"
      : value.startsWith("**", index)
        ? "**"
      : value.startsWith("__", index)
        ? "__"
        : value[index] === "*" || value[index] === "_"
          ? value[index]
          : null;
    if (marker) {
      const end = value.indexOf(marker, index + marker.length);
      if (end > index + marker.length) {
        flush();
        tokens.push({
          content: value.slice(index + marker.length, end),
          kind: marker === "~~" ? "strikethrough" : marker.length === 2 ? "strong" : "emphasis",
        });
        index = end + marker.length;
        continue;
      }
    }

    plain += value[index];
    index += 1;
  }
  flush();
  return tokens;
}

function safeHref(href: string) {
  return /^(?:https?:\/\/|mailto:|\/|#)/i.test(href) ? href : null;
}

function InlineMarkdown({ value }: { value: string }) {
  return parseInline(value).map((token, index) => {
    const key = `${token.kind}-${index}`;
    if (token.kind === "code") return <code key={key}>{token.content}</code>;
    if (token.kind === "cite") return <cite key={key}><InlineMarkdown value={token.content} /></cite>;
    if (token.kind === "emphasis") return <em key={key}><InlineMarkdown value={token.content} /></em>;
    if (token.kind === "strikethrough") return <del key={key}><InlineMarkdown value={token.content} /></del>;
    if (token.kind === "strong") return <strong key={key}><InlineMarkdown value={token.content} /></strong>;
    if (token.kind === "link") {
      const href = safeHref(token.href);
      return href ? (
        <a href={href} key={key} rel="noreferrer" target={href.startsWith("#") ? undefined : "_blank"}>
          <InlineMarkdown value={token.content} />
        </a>
      ) : <Fragment key={key}>{token.content}</Fragment>;
    }
    return <Fragment key={key}>{token.content}</Fragment>;
  });
}

export function tokenizeCode(code: string, language: string): CodeToken[] {
  const normalized = normalizeLanguage(language);
  const keywords = languageKeywords[normalized] ?? new Set<string>();
  const tokens: CodeToken[] = [];
  const push = (kind: CodeToken["kind"], content: string) => {
    const previous = tokens.at(-1);
    if (previous?.kind === kind) previous.content += content;
    else tokens.push({ content, kind });
  };
  let index = 0;

  while (index < code.length) {
    const char = code[index] ?? "";
    const isHashComment = (normalized === "python" || normalized === "bash") && char === "#";
    const isSlashComment = ["go", "javascript"].includes(normalized) && code.startsWith("//", index);
    if (isHashComment || isSlashComment) {
      const end = code.indexOf("\n", index);
      const next = end === -1 ? code.length : end;
      push("comment", code.slice(index, next));
      index = next;
      continue;
    }
    if (char === "\"" || char === "'" || char === "`") {
      let end = index + 1;
      while (end < code.length) {
        if (code[end] === "\\") end += 2;
        else if (code[end] === char) {
          end += 1;
          break;
        } else end += 1;
      }
      push("string", code.slice(index, end));
      index = end;
      continue;
    }
    const number = code.slice(index).match(/^\b(?:0x[\da-f]+|\d+(?:\.\d+)?)\b/i);
    if (number) {
      push("number", number[0]);
      index += number[0].length;
      continue;
    }
    const identifier = code.slice(index).match(/^[A-Za-z_$][\w$]*/);
    if (identifier) {
      push(keywords.has(identifier[0]) ? "keyword" : "plain", identifier[0]);
      index += identifier[0].length;
      continue;
    }
    push("plain", char);
    index += 1;
  }
  return tokens;
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };
  return (
    <div className="markdown-code-block">
      <div className="markdown-code-toolbar">
        <span>{language || "text"}</span>
        <button onClick={() => void copy()} type="button">{copied ? "Copied" : "Copy"}</button>
      </div>
      <pre><code>{tokenizeCode(code, language).map((token, index) => (
        <span className={`syntax-${token.kind}`} key={`${token.kind}-${index}`}>{token.content}</span>
      ))}</code></pre>
    </div>
  );
}

function blockContent(block: Extract<MarkdownBlock, { content: string }>): ReactNode {
  return <InlineMarkdown value={block.content} />;
}

function MarkdownHeading({ children, level }: { children: ReactNode; level: number }) {
  if (level === 1) return <h1>{children}</h1>;
  if (level === 2) return <h2>{children}</h2>;
  if (level === 3) return <h3>{children}</h3>;
  if (level === 4) return <h4>{children}</h4>;
  if (level === 5) return <h5>{children}</h5>;
  return <h6>{children}</h6>;
}

function taskItem(value: string) {
  const match = value.match(/^\[([ xX])]\s+(.+)$/);
  if (!match) return null;
  return { checked: (match[1] ?? "").toLowerCase() === "x", content: match[2] ?? "" };
}

function MarkdownList({ block, blockKey }: {
  block: Extract<MarkdownBlock, { kind: "list" }>;
  blockKey: string;
}) {
  const tasks = block.items.map(taskItem);
  const isTaskList = tasks.every((task) => task !== null);
  const List = block.ordered ? "ol" : "ul";
  return (
    <List className={isTaskList ? "markdown-task-list" : undefined} key={blockKey}>
      {block.items.map((item, itemIndex) => {
        const task = isTaskList ? tasks[itemIndex] : null;
        return (
          <li className={task ? "markdown-task-item" : undefined} key={`${blockKey}-${itemIndex}`}>
            {task ? (
              <span
                aria-checked={task.checked}
                aria-label={task.checked ? "Completed task" : "Incomplete task"}
                className="markdown-task-checkbox"
                role="checkbox"
              >
                {task.checked ? "✓" : ""}
              </span>
            ) : null}
            <span><InlineMarkdown value={task?.content ?? item} /></span>
          </li>
        );
      })}
    </List>
  );
}

function MarkdownTable({ block }: { block: Extract<MarkdownBlock, { kind: "table" }> }) {
  return (
    <div className="markdown-table-wrap">
      <table>
        <thead>
          <tr>{block.headers.map((header, index) => (
            <th
              key={`header-${index}`}
              scope="col"
              style={block.alignments[index] ? { textAlign: block.alignments[index] } : undefined}
            >
              <InlineMarkdown value={header} />
            </th>
          ))}</tr>
        </thead>
        <tbody>{block.rows.map((row, rowIndex) => (
          <tr key={`row-${rowIndex}`}>{row.map((cell, cellIndex) => (
            <td
              key={`cell-${rowIndex}-${cellIndex}`}
              style={block.alignments[cellIndex] ? { textAlign: block.alignments[cellIndex] } : undefined}
            >
              <InlineMarkdown value={cell} />
            </td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function MessageMarkdown({ source }: { source: string }) {
  const blocks = parseMarkdownBlocks(source);
  if (blocks.length === 0) return null;
  return (
    <div className="message-markdown">
      {blocks.map((block, index) => {
        const key = `${block.kind}-${index}`;
        if (block.kind === "code") return <CodeBlock code={block.content} key={key} language={block.language} />;
        if (block.kind === "thematic-break") return <hr key={key} />;
        if (block.kind === "quote") return <blockquote key={key}><MessageMarkdown source={block.content} /></blockquote>;
        if (block.kind === "list") return <MarkdownList block={block} blockKey={key} />;
        if (block.kind === "table") return <MarkdownTable block={block} key={key} />;
        if (block.kind === "heading") {
          return <MarkdownHeading key={key} level={block.level}>{blockContent(block)}</MarkdownHeading>;
        }
        return <p key={key}>{blockContent(block)}</p>;
      })}
    </div>
  );
}
