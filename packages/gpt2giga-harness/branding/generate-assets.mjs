import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const brandingRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(brandingRoot, "..", "..", "..");
const sourcePath = join(brandingRoot, "gigaloom-mark.svg");

const frontendTarget = join(
  repositoryRoot,
  "packages",
  "gpt2giga-harness",
  "frontend",
  "public",
  "brand",
);
const targets = [
  frontendTarget,
  join(repositoryRoot, "docs-site", "static", "brand"),
];
const selectedTargets = process.argv.includes("--frontend-only")
  ? [frontendTarget]
  : targets;

function replaceColors(source, palette) {
  return source.replace(
    /#[0-9A-F]{6}/gu,
    (color) => palette[color.toUpperCase()] ?? color,
  );
}

function monochrome(source) {
  return source
    .replace(/\s*<rect data-part="field"[^>]+\/>\n/u, "\n")
    .replace(/\s+opacity="[^"]+"/gu, "")
    .replace(/#[0-9A-F]{6}/gu, "#000000");
}

function digest(content) {
  return createHash("sha256").update(content).digest("hex");
}

const source = await readFile(sourcePath, "utf8");
const light = source;
const dark = replaceColors(source, {
  "#111827": "#F8FAFC",
  "#F8FAFC": "#172033",
  "#5EEAD4": "#0F766E",
  "#A78BFA": "#6D28D9",
});
const mask = monochrome(source);
const webManifest = `${JSON.stringify({
  name: "GigaLoom",
  short_name: "GigaLoom",
  description: "Local agent workbench for gpt2giga",
  start_url: "/cockpit-v2/work",
  scope: "/cockpit-v2/",
  display: "standalone",
  background_color: "#111827",
  theme_color: "#111827",
  icons: [
    {
      src: "gigaloom-mark.svg",
      sizes: "any",
      type: "image/svg+xml",
      purpose: "any maskable",
    },
    {
      src: "gigaloom-mask.svg",
      sizes: "any",
      type: "image/svg+xml",
      purpose: "monochrome",
    },
  ],
}, null, 2)}\n`;

for (const target of selectedTargets) {
  await mkdir(target, { recursive: true });
  await Promise.all([
    writeFile(join(target, "gigaloom-mark.svg"), light),
    writeFile(join(target, "gigaloom-mark-dark.svg"), dark),
    writeFile(join(target, "gigaloom-mask.svg"), mask),
  ]);
}

const applicationTargets = selectedTargets.filter((target) => target === frontendTarget);
await Promise.all(
  applicationTargets.map((target) => writeFile(
    join(target, "gigaloom.webmanifest"),
    webManifest,
  )),
);

process.stdout.write(
  `generated GigaLoom brand assets ${digest(source).slice(0, 16)}\n`,
);
