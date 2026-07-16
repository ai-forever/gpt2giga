import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MarkdownRenderer, normalizeModelMarkdown, tokenizeCode } from "./markdown-renderer";

function render(source: string) {
  return renderToStaticMarkup(createElement(MarkdownRenderer, { source }));
}

describe("MarkdownRenderer", () => {
  it.each([
    ["python", "def answer():\n    return 42", "def"],
    ["go", "func main() { return }", "func"],
    ["bash", "if true; then echo ok; fi", "if"],
  ])("highlights %s fenced code", (language, code, keyword) => {
    expect(tokenizeCode(code, language)).toContainEqual({ content: keyword, kind: "keyword" });
  });

  it("renders GFM tables, tasks and multi-backtick code", () => {
    const html = render([
      "| Path | Purpose |",
      "| :--- | ---: |",
      "| `src/` | **Code** |",
      "",
      "- [x] ~~Done~~",
      "- [ ] Review",
      "",
      "Use ``Ctrl + ` + Shift`` now",
    ].join("\n"));
    expect(html).toContain('class="markdown-table-wrap"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain("<del>Done</del>");
    expect(html).toContain("<code>Ctrl + ` + Shift</code>");
  });

  it("preserves nested unordered and ordered list structure", () => {
    const html = render([
      "- First",
      "- Second",
      "  - Nested 2.1",
      "  - Nested 2.2",
      "    1. Deep one",
      "    2. Deep two",
      "- Third",
    ].join("\n"));
    expect(html).toMatch(/<li>Second\s*<ul>/);
    expect(html).toMatch(/<li>Nested 2\.2\s*<ol>/);
    expect(html).toContain("<li>Deep one</li>");
  });

  it("renders inline and block LaTeX with KaTeX", () => {
    const html = render("Energy: $E = mc^2$.\n\n\\[\n\\int_a^b f(x)\\,dx\n\\]");
    expect(html).toContain('class="katex"');
    expect(html).toContain('class="katex-display"');
    expect(html).not.toContain("$E = mc^2$");
  });

  it("allows selected semantic HTML and removes unsafe HTML", () => {
    const html = render([
      "<ins>Underlined</ins> and <u>also underlined</u>.",
      "",
      "<mark>Highlighted</mark>.",
      "",
      "<cite>— Author</cite>",
      "",
      "<!-- hidden -->",
      "",
      "<script>alert('no')</script>",
    ].join("\n"));
    expect(html).toContain("<ins>Underlined</ins>");
    expect(html).toContain("<ins>also underlined</ins>");
    expect(html).toContain("<mark>Highlighted</mark>");
    expect(html).toContain("<cite>— Author</cite>");
    expect(html).not.toContain("hidden");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("alert('no')");
  });

  it("resolves reference links once and blocks unsafe protocols", () => {
    const html = render([
      "Read [the guide][docs] and [bad][unsafe].",
      "[docs]: https://example.com/guide \\\"Guide\\\"",
      "[unsafe]: javascript:alert(1)",
    ].join("\n"));
    expect(html).toContain('href="https://example.com/guide"');
    expect(html).toContain(">the guide</a>");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("[docs]:");
  });

  it("does not normalize model-specific syntax inside fenced code", () => {
    const source = "```text\n\\[\n[id]: https://example.com\n\\]\n```";
    expect(normalizeModelMarkdown(source)).toBe(source);
  });

  it("renders nested quotes without flattening their hierarchy", () => {
    const html = render("> First level\n>\n> > Second level\n> >\n> > > Third level");
    expect(html.match(/<blockquote>/g)).toHaveLength(3);
  });
});
