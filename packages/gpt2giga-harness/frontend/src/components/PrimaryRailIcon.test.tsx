import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { primarySurfaces } from "../navigation";
import { PrimaryRailBrand, PrimaryRailIcon } from "./PrimaryRailIcon";

describe("PrimaryRailIcon", () => {
  it("uses the existing multi-resolution favicon without a text fallback", () => {
    const markup = renderToStaticMarkup(<PrimaryRailBrand />);

    expect(markup).toContain('src="/assets/favicon.ico"');
    expect(markup).toContain('width="30"');
    expect(markup).toContain('height="30"');
    expect(markup).not.toContain("g2");
  });

  it("renders the accepted five pictorial metaphors without letter placeholders", () => {
    const markup = primarySurfaces.map(({ id }) => renderToStaticMarkup(
      <PrimaryRailIcon surface={id} />,
    ));

    expect(markup).toHaveLength(5);
    expect(markup.join(" ")).not.toMatch(/>\s*[WRAEI]\s*</u);
    expect(markup.map((icon) => icon.match(/data-icon="([^"]+)"/u)?.[1])).toEqual([
      "workbench",
      "runs",
      "automation",
      "evaluation",
      "integrations",
    ]);
  });

  it("keeps every icon decorative, scalable, and color-token driven", () => {
    for (const { id } of primarySurfaces) {
      const markup = renderToStaticMarkup(<PrimaryRailIcon surface={id} />);
      expect(markup).toContain('aria-hidden="true"');
      expect(markup).toContain('focusable="false"');
      expect(markup).toContain('viewBox="0 0 24 24"');
      expect(markup).toContain('class="rail-icon"');
      expect(markup).not.toMatch(/(?:fill|stroke)="#[\da-f]+"/iu);
    }
  });
});
