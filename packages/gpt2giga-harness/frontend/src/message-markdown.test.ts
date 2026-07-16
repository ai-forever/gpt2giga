import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MessageMarkdown, parseMarkdownBlocks, tokenizeCode } from "./message-markdown";

describe("MessageMarkdown", () => {
  it("parses prose, lists and fenced code without treating code as HTML", () => {
    expect(parseMarkdownBlocks("# Result\n\n- one\n- two\n\n```python\nprint('<ok>')\n```"))
      .toEqual([
        { content: "Result", kind: "heading", level: 1 },
        { items: ["one", "two"], kind: "list", ordered: false },
        { content: "print('<ok>')", kind: "code", language: "python" },
      ]);
  });

  it.each([
    ["python", "def answer():\n    return 42", "def"],
    ["go", "func main() { return }", "func"],
    ["bash", "if true; then echo ok; fi", "if"],
  ])("highlights %s fenced code", (language, code, keyword) => {
    expect(tokenizeCode(code, language)).toContainEqual({ content: keyword, kind: "keyword" });
  });

  it("normalizes common language aliases", () => {
    expect(parseMarkdownBlocks("```sh\necho ok\n```"))
      .toEqual([{ content: "echo ok", kind: "code", language: "bash" }]);
  });

  it("parses GFM tables with column alignment and inline Markdown", () => {
    expect(parseMarkdownBlocks(
      "| Path | Purpose |\n| :--- | ---: |\n| `src/` | **Code** |",
    )).toEqual([{
      alignments: ["left", "right"],
      headers: ["Path", "Purpose"],
      kind: "table",
      rows: [["`src/`", "**Code**"]],
    }]);
  });

  it("renders thematic breaks, task lists, strikethrough and safe cite markup", () => {
    const html = renderToStaticMarkup(createElement(MessageMarkdown, {
      source: "---\n\n- [x] ~~Done~~\n- [ ] Review\n\n<cite>— Author</cite>",
    }));
    expect(html).toContain("<hr/>");
    expect(html).toContain('class="markdown-task-list"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain("<del>Done</del>");
    expect(html).toContain("<cite>— Author</cite>");
  });

  it("supports multi-backtick inline code spans without leaking delimiters", () => {
    const html = renderToStaticMarkup(createElement(MessageMarkdown, {
      source: "Use ``Ctrl + ` + Shift`` now",
    }));
    expect(html).toContain("<code>Ctrl + ` + Shift</code>");
    expect(html).not.toContain("``Ctrl");
  });

  it("keeps arbitrary inline HTML escaped", () => {
    const html = renderToStaticMarkup(createElement(MessageMarkdown, {
      source: "<script>alert('no')</script>",
    }));
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });
});
