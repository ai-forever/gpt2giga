import { brotliCompressSync, constants } from "node:zlib";
import { createHash } from "node:crypto";
import { readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, extname, join, relative, sep } from "node:path";
import { gzipSync } from "fflate";

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const outputRoot = join(frontendRoot, "..", "src", "gpt2giga_harness", "ui", "cockpit_v2", "assets");
const viteManifestPath = join(outputRoot, ".vite", "manifest.json");
const formatVersion = "gpt2giga-cockpit-v2-assets-v1";

const mediaTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".woff2", "font/woff2"],
]);

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    if (entry.name === ".vite" || entry.name === "manifest.json" || entry.name.endsWith(".br") || entry.name.endsWith(".gz")) {
      continue;
    }
    const absolute = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(absolute)));
    } else if (entry.isFile()) {
      files.push(absolute);
    }
  }
  return files;
}

function normalizePath(path) {
  return path.split(sep).join("/");
}

const viteManifest = JSON.parse(await readFile(viteManifestPath, "utf8"));
const entry = viteManifest["index.html"];
if (entry?.isEntry !== true || typeof entry.file !== "string") {
  throw new Error("Vite manifest has no deterministic index entry");
}

const initial = new Set(["index.html", entry.file, ...(entry.css ?? [])]);
const assets = {};
for (const absolute of await walk(outputRoot)) {
  const name = normalizePath(relative(outputRoot, absolute));
  const content = await readFile(absolute);
  const extension = extname(name);
  const mediaType = mediaTypes.get(extension) ?? "application/octet-stream";
  const record = {
    bytes: content.byteLength,
    media_type: mediaType,
    sha256: sha256(content),
  };
  if ([".css", ".html", ".js", ".json", ".svg"].includes(extension)) {
    const gzip = gzipSync(new Uint8Array(content), { level: 9, mtime: 0 });
    const brotli = brotliCompressSync(content, {
      params: {
        [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
        [constants.BROTLI_PARAM_QUALITY]: 11,
        [constants.BROTLI_PARAM_SIZE_HINT]: content.byteLength,
      },
    });
    await writeFile(`${absolute}.gz`, gzip);
    await writeFile(`${absolute}.br`, brotli);
    record.gzip = `${name}.gz`;
    record.gzip_bytes = gzip.byteLength;
    record.gzip_sha256 = sha256(gzip);
    record.brotli = `${name}.br`;
    record.brotli_bytes = brotli.byteLength;
    record.brotli_sha256 = sha256(brotli);
  }
  assets[name] = record;
}

const manifest = {
  assets,
  entry: "index.html",
  format_version: formatVersion,
  initial: [...initial].sort(),
};
await writeFile(join(outputRoot, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
await rm(join(outputRoot, ".vite"), { recursive: true, force: true });

const manifestStat = await stat(join(outputRoot, "manifest.json"));
if (!manifestStat.isFile()) {
  throw new Error("Cockpit V2 manifest was not written");
}
