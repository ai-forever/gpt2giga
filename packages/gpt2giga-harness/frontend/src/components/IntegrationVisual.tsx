export type IntegrationVisualCategory = "skills" | "plugins" | "mcp";

type CuratedVisual = "find" | "create" | "install" | "mcp" | "plugin";

const curatedVisuals: Readonly<Record<string, CuratedVisual>> = {
  "gpt2giga.builtin.find-skills": "find",
  "gpt2giga.builtin.skill-creator": "create",
  "gpt2giga.builtin.skill-installer": "install",
};

export function integrationMonogram(value: string) {
  const tokens = value
    .normalize("NFKC")
    .split(/[\s/._-]+/u)
    .map((token) => Array.from(token).filter((character) => /[\p{L}\p{N}]/u.test(character)).join(""))
    .filter(Boolean);
  if (tokens.length === 0) return "?";
  const firstToken = tokens[0] ?? "";
  const lastToken = tokens.at(-1) ?? "";
  const monogram = tokens.length === 1
    ? Array.from(firstToken).slice(0, 2).join("")
    : `${Array.from(firstToken)[0]}${Array.from(lastToken)[0] ?? ""}`;
  return monogram.toLocaleUpperCase().slice(0, 2);
}

export function IntegrationVisual({
  category,
  label,
  packageId,
  title,
}: {
  category: IntegrationVisualCategory;
  label?: string;
  packageId?: string;
  title?: string;
}) {
  const curated = packageId ? curatedVisuals[packageId] : undefined;
  const visual = curated
    ?? (category === "mcp" ? "mcp" : packageId?.startsWith("gpt2giga.builtin.") ? "plugin" : undefined);
  const accessibility = label
    ? { "aria-label": label, role: "img" as const }
    : { "aria-hidden": true as const };

  return (
    <span
      {...accessibility}
      className={`plugin-item-icon ${category} ${visual ? `curated-${visual}` : "monogram"}`}
      data-visual={visual ?? "monogram"}
    >
      {visual ? <CuratedIcon visual={visual} /> : integrationMonogram(title ?? packageId ?? category)}
    </span>
  );
}

function CuratedIcon({ visual }: { visual: CuratedVisual }) {
  const common = {
    "aria-hidden": true,
    focusable: "false",
    viewBox: "0 0 24 24",
  } as const;
  if (visual === "find") {
    return <svg {...common}><circle cx="10.5" cy="10.5" r="5.5" /><path d="m14.5 14.5 5 5M4 4l2 2" /></svg>;
  }
  if (visual === "create") {
    return <svg {...common}><path d="m4 20 3.5-1 10-10-2.5-2.5-10 10L4 20Z" /><path d="m13 5 2-2 3 3-2 2M7 5l.8 2.2L10 8l-2.2.8L7 11l-.8-2.2L4 8l2.2-.8L7 5Z" /></svg>;
  }
  if (visual === "install") {
    return <svg {...common}><path d="M12 3v11m0 0 4-4m-4 4-4-4" /><path d="M5 16v4h14v-4" /></svg>;
  }
  if (visual === "mcp") {
    return <svg {...common}><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></svg>;
  }
  return <svg {...common}><path d="M8.5 4v4.5H4v7h4.5V20h7v-4.5H20v-7h-4.5V4h-7Z" /><path d="M11 4v3M13 17v3M4 12h3M17 12h3" /></svg>;
}
