import { Fragment, useState, type ReactNode } from "react";

export type MarkdownBlock =
  | { kind: "code"; language: string; content: string }
  | { kind: "heading"; level: number; content: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; content: string }
  | { kind: "quote"; content: string };

type InlineToken =
  | { kind: "code" | "emphasis" | "strong" | "text"; content: string }
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
      !/^\s*(?:#{1,6}\s+|>\s?|(?:(?:\d+)[.)]|[-*+])\s+)/.test(lineAt(index))
    ) {
      paragraph.push(lineAt(index).trim());
      index += 1;
    }
    blocks.push({ content: paragraph.join("\n"), kind: "paragraph" });
  }

  return blocks;
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
      const end = value.indexOf("`", index + 1);
      if (end > index + 1) {
        flush();
        tokens.push({ content: value.slice(index + 1, end), kind: "code" });
        index = end + 1;
        continue;
      }
    }

    const link = value.slice(index).match(/^\[([^\]]+)]\(([^\s)]+)(?:\s+"[^"]*")?\)/);
    if (link) {
      flush();
      tokens.push({ content: link[1] ?? "", href: link[2] ?? "", kind: "link" });
      index += link[0].length;
      continue;
    }

    const marker = value.startsWith("**", index)
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
          kind: marker.length === 2 ? "strong" : "emphasis",
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
    if (token.kind === "emphasis") return <em key={key}>{token.content}</em>;
    if (token.kind === "strong") return <strong key={key}>{token.content}</strong>;
    if (token.kind === "link") {
      const href = safeHref(token.href);
      return href ? (
        <a href={href} key={key} rel="noreferrer" target={href.startsWith("#") ? undefined : "_blank"}>
          {token.content}
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

export function MessageMarkdown({ source }: { source: string }) {
  const blocks = parseMarkdownBlocks(source);
  if (blocks.length === 0) return null;
  return (
    <div className="message-markdown">
      {blocks.map((block, index) => {
        const key = `${block.kind}-${index}`;
        if (block.kind === "code") return <CodeBlock code={block.content} key={key} language={block.language} />;
        if (block.kind === "quote") return <blockquote key={key}><MessageMarkdown source={block.content} /></blockquote>;
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return <List key={key}>{block.items.map((item, itemIndex) => (
            <li key={`${key}-${itemIndex}`}><InlineMarkdown value={item} /></li>
          ))}</List>;
        }
        if (block.kind === "heading") {
          return <MarkdownHeading key={key} level={block.level}>{blockContent(block)}</MarkdownHeading>;
        }
        return <p key={key}>{blockContent(block)}</p>;
      })}
    </div>
  );
}
