import { describe, expect, it } from "vitest";

import { parseMarkdownBlocks, tokenizeCode } from "./message-markdown";

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
});
