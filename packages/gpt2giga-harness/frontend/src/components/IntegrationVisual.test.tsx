import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IntegrationVisual, integrationMonogram } from "./IntegrationVisual";

describe("IntegrationVisual", () => {
  it("uses curated local pictograms for governed built-ins and MCP", () => {
    const skill = renderToStaticMarkup(
      <IntegrationVisual
        category="skills"
        label="Find Skills skill"
        packageId="gpt2giga.builtin.find-skills"
        title="Find Skills"
      />,
    );
    const mcp = renderToStaticMarkup(
      <IntegrationVisual category="mcp" label="Repository Search MCP" packageId="repo-search" title="Repository Search" />,
    );

    expect(skill).toContain('data-visual="find"');
    expect(mcp).toContain('data-visual="mcp"');
    expect(skill).toContain('aria-label="Find Skills skill"');
    expect(skill).not.toContain("http");
  });

  it("uses a deterministic accessible monogram for unknown integrations", () => {
    const markup = renderToStaticMarkup(
      <IntegrationVisual
        category="plugins"
        label="Acme review tools plugin"
        packageId="acme.review-tools"
        title="Acme Review Tools"
      />,
    );

    expect(markup).toContain('data-visual="monogram"');
    expect(markup).toContain('aria-label="Acme review tools plugin"');
    expect(markup).toContain(">AT</span>");
    expect(integrationMonogram("  neuraldeep/skill.sh  ")).toBe("NS");
    expect(integrationMonogram("")).toBe("?");
  });

  it("keeps category placeholders decorative", () => {
    const markup = renderToStaticMarkup(<IntegrationVisual category="skills" />);

    expect(markup).toContain('aria-hidden="true"');
    expect(markup).not.toContain("role=");
  });
});
