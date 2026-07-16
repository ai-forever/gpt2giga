import { useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema, type Options as SanitizeSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

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
  golang: "go",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  sh: "bash",
  shell: "bash",
  ts: "javascript",
  tsx: "javascript",
  zsh: "bash",
};

function normalizeLanguage(language: string) {
  const normalized = language.trim().toLowerCase();
  return languageAliases[normalized] ?? normalized;
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
    const character = code[index] ?? "";
    const isHashComment = (normalized === "python" || normalized === "bash") && character === "#";
    const isSlashComment = ["go", "javascript"].includes(normalized) && code.startsWith("//", index);
    if (isHashComment || isSlashComment) {
      const end = code.indexOf("\n", index);
      const next = end === -1 ? code.length : end;
      push("comment", code.slice(index, next));
      index = next;
      continue;
    }
    if (character === "\"" || character === "'" || character === "`") {
      let end = index + 1;
      while (end < code.length) {
        if (code[end] === "\\") end += 2;
        else if (code[end] === character) {
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
    push("plain", character);
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

const markdownSchema: SanitizeSchema = {
  ...defaultSchema,
  allowComments: false,
  attributes: {
    ...defaultSchema.attributes,
    code: [
      ...(defaultSchema.attributes?.code ?? []),
      ["className", "language-math", "math-display", "math-inline", /^language-[\w-]+$/],
    ],
  },
  tagNames: [...new Set([...(defaultSchema.tagNames ?? []), "cite", "ins", "mark", "u"])],
};

function childrenText(children: ReactNode) {
  return String(children).replace(/\n$/, "");
}

const components: Components = {
  a({ children, href, node, ...properties }) {
    void node;
    if (!href) return <>{children}</>;
    const external = Boolean(href && /^(?:https?:|mailto:)/i.test(href));
    return (
      <a {...properties} href={href} rel={external ? "noreferrer" : undefined} target={external ? "_blank" : undefined}>
        {children}
      </a>
    );
  },
  code({ children, className, node, ...properties }) {
    void node;
    const language = /(?:^|\s)language-([\w.+-]+)/.exec(className ?? "")?.[1];
    const block = Boolean(language) || String(children).endsWith("\n");
    const content = childrenText(children);
    if (block) {
      return <CodeBlock code={content} language={normalizeLanguage(language ?? "text")} />;
    }
    return <code {...properties} className={className}>{children}</code>;
  },
  img({ alt, node, ...properties }) {
    void node;
    return <img {...properties} alt={alt ?? ""} loading="lazy" referrerPolicy="no-referrer" />;
  },
  input({ checked, node, type, ...properties }) {
    void node;
    if (type === "checkbox") {
      return (
        <span
          aria-checked={Boolean(checked)}
          aria-label={checked ? "Completed task" : "Incomplete task"}
          className="markdown-task-checkbox"
          role="checkbox"
        >
          {checked ? "✓" : ""}
        </span>
      );
    }
    return <input {...properties} disabled type={type} />;
  },
  pre({ children }) {
    return <>{children}</>;
  },
  table({ children, node, ...properties }) {
    void node;
    return <div className="markdown-table-wrap"><table {...properties}>{children}</table></div>;
  },
  u({ children }) {
    return <ins>{children}</ins>;
  },
};

export function normalizeModelMarkdown(source: string) {
  const output: string[] = [];
  let fence: "```" | "~~~" | null = null;
  for (const originalLine of source.replace(/\r\n?/g, "\n").split("\n")) {
    const fenceMarker = originalLine.match(/^\s*(```|~~~)/)?.[1] as "```" | "~~~" | undefined;
    if (fenceMarker) {
      fence = fence === fenceMarker ? null : fence ?? fenceMarker;
      output.push(originalLine);
      continue;
    }
    if (fence) {
      output.push(originalLine);
      continue;
    }
    const trimmed = originalLine.trim();
    if (trimmed === "\\[" || trimmed === "\\]") {
      output.push("$$");
      continue;
    }
    const referenceDefinition = /^\s{0,3}\[[^\]\n]+]:\s*\S/.test(originalLine);
    if (referenceDefinition && output.length > 0 && output.at(-1)?.trim()) output.push("");
    output.push(
      referenceDefinition
        ? originalLine.replace(/\s+\\"([^"\n]*)\\"\s*$/, ' "$1"')
        : originalLine,
    );
  }
  return output.join("\n");
}

export function MarkdownRenderer({ source }: { source: string }) {
  return (
    <div className="message-markdown">
      <ReactMarkdown
        components={components}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSchema], rehypeKatex]}
        remarkPlugins={[remarkGfm, remarkMath]}
      >
        {normalizeModelMarkdown(source)}
      </ReactMarkdown>
    </div>
  );
}
